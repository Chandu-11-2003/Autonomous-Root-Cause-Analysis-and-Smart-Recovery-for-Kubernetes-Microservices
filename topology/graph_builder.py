"""
Dynamic Topology Graph Builder
------------------------------
Fuses telemetry signals to construct a live microservice dependency graph:
  1. Jaeger OpenTelemetry Traces (Parent -> Child span relationships)
  2. Prometheus Metrics (http_requests_total caller/callee labels)
  3. Static Fallback Rules (declared system architecture)

Uses NetworkX for directed graph analysis (downstream call chain, upstream blast radius).
"""

import sys
import os
import networkx as nx
from typing import Dict, List, Set, Tuple, Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from observability.jaeger.client import JaegerClient
from observability.prometheus.client import PrometheusClient

def _is_in_cluster() -> bool:
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

class TopologyGraphBuilder:
    """Constructs and maintains live Directed Graph (DiGraph) of the microservices ecosystem."""

    STATIC_DEPENDENCY_FALLBACK = [
        ("frontend", "api-gateway"),
        ("api-gateway", "user-service"),
        ("api-gateway", "product-service"),
        ("api-gateway", "order-service"),
        ("order-service", "user-service"),
        ("order-service", "product-service"),
        ("order-service", "payment-service"),
        ("order-service", "database"),
        ("user-service", "database"),
        ("product-service", "database"),
    ]

    KNOWN_NODES = [
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
        jaeger_url: str = None,
        prometheus_url: str = None
    ):
        in_cluster = _is_in_cluster()
        j_url = jaeger_url or ("http://jaeger.monitoring.svc.cluster.local:16686" if in_cluster else "http://localhost:16686")
        p_url = prometheus_url or ("http://prometheus-server.monitoring.svc.cluster.local:80" if in_cluster else "http://localhost:9090")

        self.jaeger_client = JaegerClient(base_url=j_url)
        self.prometheus_client = PrometheusClient(base_url=p_url)
        self.graph = nx.DiGraph()

    def discover_jaeger_edges(self) -> List[Tuple[str, str]]:
        """Extract caller -> callee edges from active Jaeger distributed traces."""
        try:
            return self.jaeger_client.extract_dependency_edges(limit=20)
        except Exception:
            return []

    def discover_prometheus_edges(self) -> List[Tuple[str, str]]:
        """Infer active edges from Prometheus http_requests_total metrics."""
        edges = set()
        query = 'sum by (service) (rate(http_requests_total[5m])) > 0'
        try:
            metrics = self.prometheus_client.query_instant(query)
            active_services = [m["metric"].get("service") for m in metrics if "service" in m["metric"]]
            
            for svc in active_services:
                if svc == "api-gateway":
                    edges.add(("frontend", "api-gateway"))
                elif svc in ["user-service", "product-service", "order-service"]:
                    edges.add(("api-gateway", svc))
                elif svc == "payment-service":
                    edges.add(("order-service", "payment-service"))
        except Exception:
            pass
            
        return list(edges)

    def build_graph(self) -> nx.DiGraph:
        """Constructs the unified live DiGraph."""
        G = nx.DiGraph()

        for node in self.KNOWN_NODES:
            G.add_node(node, type="microservice" if node != "database" else "database")

        discovered_edges: Set[Tuple[str, str]] = set()

        jaeger_edges = self.discover_jaeger_edges()
        for u, v in jaeger_edges:
            discovered_edges.add((u, v))

        prom_edges = self.discover_prometheus_edges()
        for u, v in prom_edges:
            discovered_edges.add((u, v))

        if len(discovered_edges) < 3:
            for u, v in self.STATIC_DEPENDENCY_FALLBACK:
                discovered_edges.add((u, v))

        for u, v in discovered_edges:
            source_tag = "dynamic_jaeger" if (u, v) in jaeger_edges else ("dynamic_prometheus" if (u, v) in prom_edges else "static_fallback")
            G.add_edge(u, v, discovery=source_tag)

        self.graph = G
        return G

    def get_downstream_dependencies(self, service: str) -> List[str]:
        if not self.graph.has_node(service):
            return []
        return list(nx.descendants(self.graph, service))

    def get_upstream_dependents(self, service: str) -> List[str]:
        if not self.graph.has_node(service):
            return []
        return list(nx.ancestors(self.graph, service))

    def get_direct_callees(self, service: str) -> List[str]:
        if not self.graph.has_node(service):
            return []
        return list(self.graph.successors(service))

    def get_direct_callers(self, service: str) -> List[str]:
        if not self.graph.has_node(service):
            return []
        return list(self.graph.predecessors(service))

    def export_topology_dict(self) -> Dict[str, Any]:
        if len(self.graph.nodes) == 0:
            self.build_graph()
            
        nodes = [{"id": n, "type": self.graph.nodes[n].get("type", "microservice")} for n in self.graph.nodes]
        edges = [{"source": u, "target": v, "discovery": self.graph.edges[u, v].get("discovery", "unknown")} for u, v in self.graph.edges]
        
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges
        }

if __name__ == "__main__":
    print("Testing Topology Graph Builder...")
    builder = TopologyGraphBuilder()
    G = builder.build_graph()
    print(f"Graph constructed successfully with {len(G.nodes)} nodes and {len(G.edges)} edges.")
