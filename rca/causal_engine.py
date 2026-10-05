"""
Causal Root Cause Analysis (RCA) Engine
---------------------------------------
Executes Reverse Depth-First Causal Graph Traversal:
  1. Identifies entry-point symptom services (services with high error rates).
  2. Follows outbound call edges (downstream callees) down the dependency tree.
  3. Finds the deepest node v in the dependency chain with significant anomaly score S(v).
  4. Classifies failure type (LATENCY_SPIKE, HTTP_5XX_ERRORS, POD_CRASH_LOOP, BAD_DEPLOYMENT_ROLLOUT).
  5. Computes overall RCA Diagnosis Confidence Score (0.0 to 1.0).
"""

import sys
import os
import networkx as nx
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from topology.graph_builder import TopologyGraphBuilder
from rca.evidence_fusion import EvidenceFusion, ServiceEvidence

def _is_in_cluster() -> bool:
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

class RCADiagnosis(BaseModel):
    root_cause_service: str
    failure_type: str
    confidence_score: float
    symptom_services: List[str]
    causal_chain: List[str]
    summary: str
    evidence_breakdown: Dict[str, Any]

class CausalRCAEngine:
    """Core deterministic Causal Root Cause Analyzer."""

    def __init__(
        self,
        namespace: str = "prod",
        jaeger_url: str = None,
        prom_url: str = None,
        loki_url: str = None
    ):
        self.namespace = namespace
        in_cluster = _is_in_cluster()

        jaeger_default = "http://jaeger.monitoring.svc.cluster.local:16686" if in_cluster else "http://localhost:16686"
        prom_default = "http://prometheus-server.monitoring.svc.cluster.local:80" if in_cluster else "http://localhost:9099"
        loki_default = "http://loki.monitoring.svc.cluster.local:3100" if in_cluster else "http://localhost:3100"

        j_url = jaeger_url or jaeger_default
        p_url = prom_url or prom_default
        l_url = loki_url or loki_default

        self.topo_builder = TopologyGraphBuilder(jaeger_url=j_url, prometheus_url=p_url)
        self.evidence_fusion = EvidenceFusion(
            namespace=namespace, prom_url=p_url, loki_url=l_url, jaeger_url=j_url
        )

    def diagnose(self) -> RCADiagnosis:
        """Executes full multi-signal causal diagnosis."""
        # 1. Build live dependency graph
        G = self.topo_builder.build_graph()

        # 2. Collect multi-signal evidence map
        evidence_map = self.evidence_fusion.collect_all_evidence()

        # 3. Identify all anomalous candidate services (composite score >= 0.08)
        anomalous_nodes = {
            node: ev for node, ev in evidence_map.items() if ev.composite_score >= 0.08
        }

        # Filter out background noise if k8s warning is the only signal
        active_anomalies = {}
        for node, ev in anomalous_nodes.items():
            if ev.score_metrics > 0 or ev.score_logs > 0 or ev.score_traces > 0:
                active_anomalies[node] = ev

        if not active_anomalies:
            return RCADiagnosis(
                root_cause_service="NONE",
                failure_type="HEALTHY",
                confidence_score=1.0,
                symptom_services=[],
                causal_chain=[],
                summary="All microservices are operating normally within parameters.",
                evidence_breakdown={}
            )

        # 4. Perform Causal Path Traversal
        sorted_candidates = sorted(
            active_anomalies.items(), key=lambda item: item[1].composite_score, reverse=True
        )

        entry_symptom = None
        for edge_svc in ["frontend", "api-gateway", "order-service"]:
            if edge_svc in active_anomalies:
                entry_symptom = edge_svc
                break
        
        if not entry_symptom:
            entry_symptom = sorted_candidates[0][0]

        causal_chain = [entry_symptom]
        current_node = entry_symptom

        while True:
            callees = self.topo_builder.get_direct_callees(current_node)
            anomalous_callees = [c for c in callees if c in active_anomalies]

            if not anomalous_callees:
                break

            next_node = max(anomalous_callees, key=lambda c: active_anomalies[c].composite_score)
            causal_chain.append(next_node)
            current_node = next_node

        root_cause_svc = current_node
        root_ev = evidence_map[root_cause_svc]

        symptoms = [node for node in active_anomalies if node != root_cause_svc]

        # 5. Classify Failure Type
        failure_type = "UNKNOWN_FAILURE"
        if root_ev.score_k8s > 0.5 and root_ev.k8s_warning_count > 0:
            failure_type = "POD_CRASH_LOOP"
        elif root_ev.metric_error_rate > 0.05 or root_ev.metric_error_count > 0 or root_ev.score_logs > 0.05 or root_ev.score_traces > 0.05:
            failure_type = "HTTP_5XX_ERRORS"
        elif root_ev.metric_latency_ms > 1000:
            failure_type = "LATENCY_SPIKE"
        elif root_ev.recent_rollout:
            failure_type = "BAD_DEPLOYMENT_ROLLOUT"
        else:
            failure_type = "DEPENDENCY_DOWNSTREAM_FAILURE"

        # 6. Calculate Confidence Score
        signals_present = sum([
            1 if root_ev.score_metrics > 0.05 else 0,
            1 if root_ev.score_logs > 0.05 else 0,
            1 if root_ev.score_traces > 0.05 else 0,
            1 if root_ev.score_k8s > 0.05 else 0
        ])
        confidence = min(0.99, max(0.60, 0.40 + (signals_present * 0.15)))

        summary_msg = (
            f"Root cause isolated to '{root_cause_svc}' ({failure_type}) with "
            f"{confidence*100:.1f}% confidence. Causal propagation path: {' -> '.join(causal_chain)}."
        )

        evidence_breakdown = {
            svc: {
                "composite_score": ev.composite_score,
                "error_rate": ev.metric_error_rate,
                "error_count": ev.metric_error_count,
                "log_errors": ev.log_error_count,
                "trace_errors": ev.trace_error_count,
                "k8s_warnings": ev.k8s_warning_count
            }
            for svc, ev in active_anomalies.items()
        }

        return RCADiagnosis(
            root_cause_service=root_cause_svc,
            failure_type=failure_type,
            confidence_score=round(confidence, 2),
            symptom_services=symptoms,
            causal_chain=causal_chain,
            summary=summary_msg,
            evidence_breakdown=evidence_breakdown
        )

if __name__ == "__main__":
    print("Testing Causal RCA Engine...")
    engine = CausalRCAEngine()
    diagnosis = engine.diagnose()
    print("\n--- RCA Diagnosis Output ---")
    if hasattr(diagnosis, "model_dump_json"):
        print(diagnosis.model_dump_json(indent=2))
    else:
        print(diagnosis.json(indent=2))
