"""
Multi-Signal Evidence Fusion Module
-----------------------------------
Fuses evidence across 4 distinct telemetry channels:
  1. Prometheus RED Metrics (HTTP Error Rate, Latency Spikes)
  2. Loki Centralized Logs (Error Log Volume, Exception Traces)
  3. Jaeger Distributed Traces (Span Errors, Duration Bottlenecks)
  4. Kubernetes Cluster Events & Change Tracker (Pod Restarts, ConfigMap Hash Changes)

Outputs a normalized per-service Anomaly Score S(v) in [0.0, 1.0].
"""

import sys
import os
import time
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from observability.prometheus.client import PrometheusClient
from observability.loki.client import LokiClient
from observability.jaeger.client import JaegerClient
from observability.k8s.events_client import K8sEventsClient
from observability.k8s.change_tracker import K8sChangeTracker

def _is_in_cluster() -> bool:
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

class ServiceEvidence:
    """Holds accumulated telemetry evidence for a single microservice."""
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.metric_error_rate: float = 0.0
        self.metric_error_count: float = 0.0
        self.metric_latency_ms: float = 0.0
        self.log_error_count: int = 0
        self.trace_error_count: int = 0
        self.k8s_warning_count: int = 0
        self.recent_rollout: bool = False
        self.config_change: bool = False
        
        # Sub-scores (0.0 to 1.0)
        self.score_metrics: float = 0.0
        self.score_logs: float = 0.0
        self.score_traces: float = 0.0
        self.score_k8s: float = 0.0
        self.composite_score: float = 0.0

class EvidenceFusion:
    """Aggregates telemetry from all 4 channels to score anomaly severity."""

    KNOWN_SERVICES = [
        "frontend",
        "api-gateway",
        "user-service",
        "product-service",
        "payment-service",
        "order-service",
        "database"
    ]

    def __init__(
        self,
        namespace: str = "prod",
        prom_url: str = None,
        loki_url: str = None,
        jaeger_url: str = None
    ):
        self.namespace = namespace
        in_cluster = _is_in_cluster()
        
        prom_default = "http://prometheus-server.monitoring.svc.cluster.local:80" if in_cluster else "http://localhost:9099"
        loki_default = "http://loki.monitoring.svc.cluster.local:3100" if in_cluster else "http://localhost:3100"
        jaeger_default = "http://jaeger.monitoring.svc.cluster.local:16686" if in_cluster else "http://localhost:16686"

        self.prom_client = PrometheusClient(base_url=prom_url or prom_default)
        self.loki_client = LokiClient(base_url=loki_url or loki_default)
        self.jaeger_client = JaegerClient(base_url=jaeger_url or jaeger_default)
        self.k8s_events = K8sEventsClient(namespace=namespace)
        self.k8s_changes = K8sChangeTracker(namespace=namespace)

    def collect_all_evidence(self) -> Dict[str, ServiceEvidence]:
        """Queries all 4 telemetry sources and computes composite anomaly scores."""
        evidence_map: Dict[str, ServiceEvidence] = {
            svc: ServiceEvidence(svc) for svc in self.KNOWN_SERVICES
        }

        # 1. Prometheus Metrics Evidence
        try:
            error_rates = self.prom_client.get_service_error_rates()
            error_counts = self.prom_client.get_service_error_counts()

            for svc, rate in error_rates.items():
                if svc in evidence_map:
                    evidence_map[svc].metric_error_rate = rate

            for svc, cnt in error_counts.items():
                if svc in evidence_map:
                    evidence_map[svc].metric_error_count = cnt

            for svc, ev in evidence_map.items():
                rate_score = min(1.0, ev.metric_error_rate / 0.20)
                cnt_score = min(1.0, ev.metric_error_count / 5.0)
                ev.score_metrics = max(rate_score, cnt_score)
        except Exception:
            pass

        # 2. Loki Log Evidence
        for svc in self.KNOWN_SERVICES:
            if svc == "database":
                continue
            try:
                logs = self.loki_client.get_error_logs(service_name=svc, limit=20)
                err_cnt = len(logs)
                evidence_map[svc].log_error_count = err_cnt
                evidence_map[svc].score_logs = min(1.0, err_cnt / 5.0)
            except Exception:
                pass

        # 3. Jaeger Distributed Trace Evidence
        for svc in self.KNOWN_SERVICES:
            if svc == "database":
                continue
            try:
                traces = self.jaeger_client.get_traces_for_service(service=svc, limit=10)
                error_spans = 0
                for tr in traces:
                    for span in tr.get("spans", []):
                        tags = {t.get("key"): t.get("value") for t in span.get("tags", [])}
                        if tags.get("error") is True or tags.get("http.status_code", 200) >= 500:
                            error_spans += 1
                evidence_map[svc].trace_error_count = error_spans
                evidence_map[svc].score_traces = min(1.0, error_spans / 3.0)
            except Exception:
                pass

        # 4. Kubernetes Events & Change Tracker
        try:
            recent_rollouts = self.k8s_changes.detect_recent_rollouts(within_minutes=30)
            rolled_out_apps = {r.get("deployment") for r in recent_rollouts if r.get("deployment")}
            
            for svc in self.KNOWN_SERVICES:
                events = self.k8s_events.get_events_for_service(service_name=svc, limit=20)
                warning_cnt = len([e for e in events if e.get("type") == "Warning"])
                
                evidence_map[svc].k8s_warning_count = warning_cnt
                evidence_map[svc].recent_rollout = svc in rolled_out_apps
                
                k8s_score = min(0.7, warning_cnt / 5.0)
                if evidence_map[svc].recent_rollout:
                    k8s_score += 0.3
                evidence_map[svc].score_k8s = min(1.0, k8s_score)
        except Exception:
            pass

        # 5. Compute Composite Score S(v)
        for svc, ev in evidence_map.items():
            ev.composite_score = round(
                (0.40 * ev.score_metrics) +
                (0.25 * ev.score_logs) +
                (0.25 * ev.score_traces) +
                (0.10 * ev.score_k8s), 3
            )

        return evidence_map

if __name__ == "__main__":
    print("Testing Evidence Fusion Module...")
    fusion = EvidenceFusion()
    evidence = fusion.collect_all_evidence()
    print("\nService Composite Anomaly Scores:")
    for svc, ev in evidence.items():
        print(f"  • {svc:20}: S(v) = {ev.composite_score:.3f} (Metrics={ev.score_metrics:.2f}, Logs={ev.score_logs:.2f}, Traces={ev.score_traces:.2f}, K8s={ev.score_k8s:.2f})")
