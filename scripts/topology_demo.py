#!/usr/bin/env python3
"""
Step 10 Demo Script: Dynamic Topology & Dependency Engine
--------------------------------------------------------
1. Queries Jaeger and Prometheus to construct live dependency graph.
2. Displays node list and caller -> callee edges with discovery source.
3. Performs Blast Radius (Upstream Impact) analysis for all services.
4. Renders ASCII call hierarchy tree.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topology.graph_builder import TopologyGraphBuilder
from topology.visualizer import render_ascii_tree

def main():
    print("=" * 60)
    print(" STEP 10 — Dynamic Topology & Dependency Engine")
    print("=" * 60)

    # In-cluster or host-forwarded URLs
    jaeger_url = os.getenv("JAEGER_URL", "http://jaeger.monitoring.svc.cluster.local:16686")
    prom_url = os.getenv("PROMETHEUS_URL", "http://prometheus-k8s.monitoring.svc.cluster.local:9090")

    builder = TopologyGraphBuilder(jaeger_url=jaeger_url, prometheus_url=prom_url)
    G = builder.build_graph()

    print(f"\n[1] Dynamic Topology Graph Constructed ({len(G.nodes)} Nodes, {len(G.edges)} Edges):")
    for u, v in G.edges:
        source = G.edges[u, v].get("discovery", "unknown")
        print(f"   • {u:20}  ───(calls)───►  {v:20} [{source}]")

    print("\n[2] Blast Radius & Dependency Impact Analysis:")
    for service in builder.KNOWN_NODES:
        direct_callees = builder.get_direct_callees(service)
        upstream_dependents = builder.get_upstream_dependents(service)
        print(f"\n 📦 Service: {service.upper()}")
        print(f"    ├─ Direct Callees (Depends On) : {direct_callees if direct_callees else 'None (Leaf / Infra)'}")
        print(f"    └─ Blast Radius (Affected If It Fails) : {upstream_dependents if upstream_dependents else 'None (User Edge)'}")

    print("\n[3] ASCII Dependency Tree Visualization:")
    print(render_ascii_tree(G, "frontend"))

    print("\n[4] Exported Graph Structure (JSON):")
    topo_dict = builder.export_topology_dict()
    print(json.dumps(topo_dict, indent=2))

    print("\n✅ Step 10 Dynamic Topology Engine successfully verified!")

if __name__ == "__main__":
    main()
