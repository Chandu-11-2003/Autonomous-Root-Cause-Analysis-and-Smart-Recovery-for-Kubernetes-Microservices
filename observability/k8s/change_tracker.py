"""
Kubernetes Change Tracker
-------------------------
Tracks configuration and workload changes for RCA time-correlation:
  - Deployment revisions / rollouts / image changes
  - Replica counts and conditions
  - ConfigMap and Secret data-hash changes (not secret values)
  - Recent ReplicaSet creations (rollout markers)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException


def _load_kube_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _dt_iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _stable_hash(data: Dict[str, str]) -> str:
    """Hash ConfigMap/Secret keys+values without logging secret values elsewhere."""
    payload = json.dumps(data or {}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class K8sChangeTracker:
    """Detect recent workload and configuration changes in a namespace."""

    def __init__(self, namespace: str = "prod"):
        _load_kube_config()
        self.namespace = namespace
        self.apps = client.AppsV1Api()
        self.core = client.CoreV1Api()

    def list_deployments(self, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        ns = namespace or self.namespace
        try:
            result = self.apps.list_namespaced_deployment(namespace=ns)
        except ApiException as e:
            return [{"error": f"ApiException: {e.status} {e.reason}"}]

        out = []
        for d in result.items:
            containers = []
            template = d.spec.template if d.spec else None
            pod_spec = template.spec if template else None
            for c in (pod_spec.containers if pod_spec else []) or []:
                containers.append({"name": c.name, "image": c.image})

            conditions = []
            if d.status and d.status.conditions:
                for cond in d.status.conditions:
                    conditions.append(
                        {
                            "type": cond.type,
                            "status": cond.status,
                            "reason": cond.reason,
                            "message": cond.message,
                            "last_update_time": _dt_iso(cond.last_update_time),
                        }
                    )

            labels = (
                d.spec.template.metadata.labels
                if d.spec and d.spec.template and d.spec.template.metadata
                else {}
            ) or {}
            ann = d.metadata.annotations or {}
            out.append(
                {
                    "name": d.metadata.name,
                    "namespace": d.metadata.namespace,
                    "replicas_desired": d.spec.replicas if d.spec else None,
                    "replicas_ready": d.status.ready_replicas if d.status else None,
                    "replicas_available": d.status.available_replicas if d.status else None,
                    "replicas_updated": d.status.updated_replicas if d.status else None,
                    "observed_generation": d.status.observed_generation if d.status else None,
                    "generation": d.metadata.generation,
                    "creation_timestamp": _dt_iso(d.metadata.creation_timestamp),
                    "containers": containers,
                    "conditions": conditions,
                    "revision": ann.get("deployment.kubernetes.io/revision"),
                    "change_cause": ann.get("kubernetes.io/change-cause"),
                    "selector_labels": labels,
                }
            )
        return out

    def get_deployment(self, name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        ns = namespace or self.namespace
        d_list = self.list_deployments(namespace=ns)
        for d in d_list:
            if d.get("name") == name:
                return d
        return {"error": f"Deployment/{name} not found in {ns}"}

    def get_rollout_history(
        self, deployment_name: str, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Infer rollout history from ReplicaSets owned by the Deployment."""
        ns = namespace or self.namespace
        try:
            rs_list = self.apps.list_namespaced_replica_set(namespace=ns)
        except ApiException as e:
            return [{"error": f"ApiException: {e.status} {e.reason}"}]

        history = []
        for rs in rs_list.items:
            owner_refs = rs.metadata.owner_references or []
            owned = any(
                o.kind == "Deployment" and o.name == deployment_name for o in owner_refs
            )
            if not owned:
                continue
            ann = rs.metadata.annotations or {}
            containers = []
            if rs.spec and rs.spec.template and rs.spec.template.spec:
                for c in rs.spec.template.spec.containers or []:
                    containers.append({"name": c.name, "image": c.image})
            history.append(
                {
                    "replica_set": rs.metadata.name,
                    "revision": ann.get("deployment.kubernetes.io/revision"),
                    "change_cause": ann.get("kubernetes.io/change-cause"),
                    "replicas": rs.spec.replicas if rs.spec else None,
                    "ready_replicas": rs.status.ready_replicas if rs.status else None,
                    "creation_timestamp": _dt_iso(rs.metadata.creation_timestamp),
                    "containers": containers,
                }
            )

        def rev_key(h):
            try:
                return int(h.get("revision") or 0)
            except Exception:
                return 0

        history.sort(key=rev_key, reverse=True)
        return history

    def list_configmap_fingerprints(
        self, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ns = namespace or self.namespace
        try:
            result = self.core.list_namespaced_config_map(namespace=ns)
        except ApiException as e:
            return [{"error": f"ApiException: {e.status} {e.reason}"}]

        out = []
        for cm in result.items:
            data = cm.data or {}
            out.append(
                {
                    "kind": "ConfigMap",
                    "name": cm.metadata.name,
                    "namespace": cm.metadata.namespace,
                    "keys": sorted(list(data.keys())),
                    "data_hash": _stable_hash(data),
                    "resource_version": cm.metadata.resource_version,
                    "generation": cm.metadata.generation,
                    "creation_timestamp": _dt_iso(cm.metadata.creation_timestamp),
                }
            )
        return out

    def list_secret_fingerprints(
        self, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fingerprint secrets by key names + hash. Never prints secret payloads."""
        ns = namespace or self.namespace
        try:
            result = self.core.list_namespaced_secret(namespace=ns)
        except ApiException as e:
            return [{"error": f"ApiException: {e.status} {e.reason}"}]

        out = []
        for sec in result.items:
            data = sec.data or {}
            string_data = sec.string_data or {}
            combined = {k: str(v) for k, v in {**data, **string_data}.items()}
            out.append(
                {
                    "kind": "Secret",
                    "name": sec.metadata.name,
                    "namespace": sec.metadata.namespace,
                    "type": sec.type,
                    "keys": sorted(list(combined.keys())),
                    "data_hash": _stable_hash(combined),
                    "resource_version": sec.metadata.resource_version,
                    "creation_timestamp": _dt_iso(sec.metadata.creation_timestamp),
                }
            )
        return out

    def snapshot(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Full change-awareness snapshot for a namespace."""
        ns = namespace or self.namespace
        deployments = self.list_deployments(namespace=ns)
        rollouts = {}
        for d in deployments:
            name = d.get("name")
            if name and "error" not in d:
                rollouts[name] = self.get_rollout_history(name, namespace=ns)

        return {
            "namespace": ns,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "deployments": deployments,
            "rollout_history": rollouts,
            "configmaps": self.list_configmap_fingerprints(namespace=ns),
            "secrets": self.list_secret_fingerprints(namespace=ns),
        }

    def detect_recent_rollouts(
        self,
        namespace: Optional[str] = None,
        within_minutes: int = 60,
    ) -> List[Dict[str, Any]]:
        """ReplicaSets created in the last N minutes → likely recent deploys/restarts."""
        ns = namespace or self.namespace
        cutoff = datetime.now(timezone.utc).timestamp() - (within_minutes * 60)
        recent = []
        deployments = self.list_deployments(namespace=ns)
        for d in deployments:
            name = d.get("name")
            if not name or "error" in d:
                continue
            for rs in self.get_rollout_history(name, namespace=ns):
                ts = rs.get("creation_timestamp")
                if not ts:
                    continue
                try:
                    ts_norm = ts.replace("Z", "+00:00")
                    created = datetime.fromisoformat(ts_norm).timestamp()
                except Exception:
                    continue
                if created >= cutoff:
                    recent.append(
                        {
                            "deployment": name,
                            "replica_set": rs.get("replica_set"),
                            "revision": rs.get("revision"),
                            "change_cause": rs.get("change_cause"),
                            "creation_timestamp": ts,
                            "containers": rs.get("containers"),
                            "age_minutes": round(
                                (datetime.now(timezone.utc).timestamp() - created) / 60, 1
                            ),
                        }
                    )
        recent.sort(key=lambda x: x.get("creation_timestamp") or "", reverse=True)
        return recent


if __name__ == "__main__":
    import json

    print("Testing K8s Change Tracker...")
    tracker = K8sChangeTracker(namespace="prod")
    deps = tracker.list_deployments()
    print(f"Deployments in prod: {len(deps)}")
    for d in deps:
        if "error" in d:
            print("  ERROR:", d)
            continue
        print(
            f"  - {d['name']}: ready={d.get('replicas_ready')}/{d.get('replicas_desired')} "
            f"rev={d.get('revision')} images={[c['image'] for c in d.get('containers', [])]}"
        )

    print("\nRecent rollouts (last 120 minutes):")
    recent = tracker.detect_recent_rollouts(within_minutes=120)
    print(json.dumps(recent[:10], indent=2))

    print("\nConfigMap fingerprints:")
    for cm in tracker.list_configmap_fingerprints():
        if "error" in cm:
            print("  ERROR:", cm)
        else:
            print(f"  - {cm['name']}: hash={cm['data_hash']} keys={cm['keys']}")
