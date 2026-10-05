#!/usr/bin/env python3
"""Demo: collect K8s events + change evidence for RCA (Step 8)."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observability.k8s.events_client import K8sEventsClient
from observability.k8s.change_tracker import K8sChangeTracker


def main():
    ns = os.getenv("K8S_NAMESPACE", "prod")
    print("=" * 60)
    print(f" STEP 8 — Kubernetes Evidence (namespace={ns})")
    print("=" * 60)

    events = K8sEventsClient(namespace=ns)
    changes = K8sChangeTracker(namespace=ns)

    print("\n[1] Namespace health summary (events)")
    summary = events.summarize_namespace_health()
    print(json.dumps({k: summary[k] for k in summary if k != "recent_failures"}, indent=2))

    print("\n[2] Recent failure/warning events (max 8)")
    for ev in summary.get("recent_failures", [])[:8]:
        obj = ev.get("involved_object") or {}
        print(
            f"  • {ev.get('last_timestamp')} | {ev.get('reason'):20} | "
            f"{obj.get('kind')}/{obj.get('name')}"
        )
        msg = (ev.get("message") or "")[:100]
        if msg:
            print(f"      {msg}")

    print("\n[3] Deployment posture")
    for d in changes.list_deployments():
        if "error" in d:
            print("  ERROR", d)
            continue
        ready_ok = d.get("replicas_ready") == d.get("replicas_desired")
        flag = "OK" if ready_ok else "DEGRADED"
        print(
            f"  [{flag}] {d['name']}: ready={d.get('replicas_ready')}/{d.get('replicas_desired')} "
            f"rev={d.get('revision')}"
        )

    print("\n[4] Recent rollouts (last 180 min) — change correlation")
    recent = changes.detect_recent_rollouts(within_minutes=180)
    if not recent:
        print("  (none in window)")
    else:
        for r in recent[:15]:
            print(
                f"  • {r['deployment']} rev={r.get('revision')} "
                f"age={r.get('age_minutes')}m rs={r.get('replica_set')}"
            )

    print("\n[5] Per-service event slice: order-service")
    svc_events = events.get_events_for_service("order-service", limit=5)
    for ev in svc_events[:5]:
        print(f"  • [{ev.get('type')}] {ev.get('reason')}: {ev.get('message', '')[:90]}")

    print("\n✅ Step 8 evidence collectors are working.")
    print("These feed the multi-signal RCA engine in later steps.")


if __name__ == "__main__":
    main()
