"""
Kubernetes Events Client
------------------------
Queries cluster events for RCA evidence:
  - Pod failures (OOMKilled, CrashLoopBackOff, Failed)
  - Scheduling / image pull / probe failures
  - Warning vs Normal event classification
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException


def _load_kube_config() -> None:
    """Load in-cluster config if present, else local kubeconfig."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _parse_ts(event: client.CoreV1Event) -> Optional[str]:
    """Best-effort event timestamp in ISO format."""
    ts = event.last_timestamp or event.first_timestamp or event.event_time
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _event_to_dict(event: client.CoreV1Event) -> Dict[str, Any]:
    involved = event.involved_object
    return {
        "namespace": event.metadata.namespace if event.metadata else None,
        "name": event.metadata.name if event.metadata else None,
        "type": event.type,  # Normal | Warning
        "reason": event.reason,
        "message": event.message,
        "count": event.count,
        "first_timestamp": (
            event.first_timestamp.isoformat()
            if event.first_timestamp and hasattr(event.first_timestamp, "isoformat")
            else str(event.first_timestamp) if event.first_timestamp else None
        ),
        "last_timestamp": _parse_ts(event),
        "involved_object": {
            "kind": involved.kind if involved else None,
            "name": involved.name if involved else None,
            "namespace": involved.namespace if involved else None,
            "field_path": involved.field_path if involved else None,
        },
        "source": {
            "component": event.source.component if event.source else None,
            "host": event.source.host if event.source else None,
        },
    }


class K8sEventsClient:
    """
    Read Kubernetes events for a namespace (or all namespaces)
    and filter them for RCA-relevant failure signals.
    """

    # Reasons that strongly indicate failure / instability
    FAILURE_REASONS = {
        "BackOff",
        "CrashLoopBackOff",
        "Failed",
        "FailedScheduling",
        "FailedMount",
        "FailedAttachVolume",
        "FailedCreatePodSandBox",
        "ImagePullBackOff",
        "ErrImagePull",
        "InvalidImageName",
        "OOMKilling",
        "OOMKilled",
        "Unhealthy",
        "ProbeWarning",
        "NetworkNotReady",
        "NodeNotReady",
        "Evicted",
        "ExceededGracePeriod",
        "FailedKillPod",
        "FailedPostStartHook",
        "FailedPreStopHook",
        "FailedSync",
        "FailedValidation",
        "ReplicaSetCreateError",
        "SuccessfulCreate",  # kept for change correlation; filtered in warnings-only helpers
        "Killing",
        "Preempting",
    }

    def __init__(self, namespace: str = "prod"):
        _load_kube_config()
        self.namespace = namespace
        self.v1 = client.CoreV1Api()

    def list_events(
        self,
        namespace: Optional[str] = None,
        field_selector: Optional[str] = None,
        label_selector: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """List raw events (most recent first after sort)."""
        ns = namespace if namespace is not None else self.namespace
        try:
            if ns == "" or ns == "*":
                result = self.v1.list_event_for_all_namespaces(
                    field_selector=field_selector,
                    label_selector=label_selector,
                    limit=limit,
                )
            else:
                result = self.v1.list_namespaced_event(
                    namespace=ns,
                    field_selector=field_selector,
                    label_selector=label_selector,
                    limit=limit,
                )
        except ApiException as e:
            return [{"error": f"ApiException: {e.status} {e.reason}", "body": e.body}]

        events = [_event_to_dict(ev) for ev in result.items]
        # Sort by last_timestamp descending (None last)
        events.sort(key=lambda e: e.get("last_timestamp") or "", reverse=True)
        return events

    def get_warning_events(
        self,
        namespace: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Only Warning-type events."""
        events = self.list_events(namespace=namespace, limit=limit)
        return [e for e in events if e.get("type") == "Warning" and "error" not in e]

    def get_events_for_object(
        self,
        kind: str,
        name: str,
        namespace: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Events for a specific object, e.g. Pod/order-service-xxx or Deployment/order-service."""
        ns = namespace if namespace is not None else self.namespace
        # field selector on involvedObject
        fs = f"involvedObject.kind={kind},involvedObject.name={name}"
        return self.list_events(namespace=ns, field_selector=fs, limit=limit)

    def get_events_for_service(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Collect events related to a logical microservice name.
        Matches involved object names that start with the service name
        (Deployment, ReplicaSet, Pod, Service, etc.).
        """
        events = self.list_events(namespace=namespace, limit=limit * 2)
        matched = []
        for e in events:
            if "error" in e:
                continue
            obj_name = (e.get("involved_object") or {}).get("name") or ""
            if obj_name == service_name or obj_name.startswith(service_name + "-"):
                matched.append(e)
            if len(matched) >= limit:
                break
        return matched

    def get_failure_events(
        self,
        namespace: Optional[str] = None,
        since_minutes: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Warning events whose reason looks like a failure.
        Optional time window filter using last_timestamp.
        """
        warnings = self.get_warning_events(namespace=namespace, limit=limit * 2)
        failures = []
        cutoff = None
        if since_minutes is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - (since_minutes * 60)

        for e in warnings:
            reason = e.get("reason") or ""
            # Match exact or substring (e.g. BackOff covers CrashLoopBackOff-style messages)
            if reason not in self.FAILURE_REASONS and not any(
                r.lower() in reason.lower() for r in ("fail", "backoff", "oom", "unhealthy", "evict")
            ):
                continue
            if cutoff is not None:
                ts = e.get("last_timestamp")
                if not ts:
                    continue
                try:
                    # Handle Z vs +00:00
                    ts_norm = ts.replace("Z", "+00:00")
                    ev_ts = datetime.fromisoformat(ts_norm).timestamp()
                    if ev_ts < cutoff:
                        continue
                except Exception:
                    pass
            failures.append(e)
            if len(failures) >= limit:
                break
        return failures

    def summarize_namespace_health(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Compact summary for RCA dashboards / decision engine."""
        ns = namespace if namespace is not None else self.namespace
        warnings = self.get_warning_events(namespace=ns, limit=200)
        failures = self.get_failure_events(namespace=ns, limit=200)

        by_reason: Dict[str, int] = {}
        by_object: Dict[str, int] = {}
        for e in failures:
            r = e.get("reason") or "Unknown"
            by_reason[r] = by_reason.get(r, 0) + 1
            obj = e.get("involved_object") or {}
            key = f"{obj.get('kind')}/{obj.get('name')}"
            by_object[key] = by_object.get(key, 0) + 1

        top_objects = sorted(by_object.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "namespace": ns,
            "warning_count": len(warnings),
            "failure_event_count": len(failures),
            "by_reason": dict(sorted(by_reason.items(), key=lambda x: x[1], reverse=True)),
            "top_involved_objects": [{"object": k, "count": v} for k, v in top_objects],
            "recent_failures": failures[:10],
        }


if __name__ == "__main__":
    import json

    print("Testing K8s Events Client...")
    kc = K8sEventsClient(namespace="prod")
    summary = kc.summarize_namespace_health()
    print(json.dumps({k: v for k, v in summary.items() if k != "recent_failures"}, indent=2))
    print("\nRecent failure events (up to 5):")
    for ev in summary.get("recent_failures", [])[:5]:
        print(
            f"  [{ev.get('type')}] {ev.get('reason')}: "
            f"{(ev.get('involved_object') or {}).get('kind')}/"
            f"{(ev.get('involved_object') or {}).get('name')} — {ev.get('message', '')[:80]}"
        )
