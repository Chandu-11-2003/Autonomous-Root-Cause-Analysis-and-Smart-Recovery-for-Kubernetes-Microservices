"""
Topology Visualizer Utility
---------------------------
Formats NetworkX dependency graph into human-readable ASCII trees and JSON topologies.
"""

import sys
import os
import networkx as nx

# Ensure project root is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def render_ascii_tree(G: nx.DiGraph, root_node: str = "frontend", level: int = 0, visited: set = None) -> str:
    """Renders a hierarchical ASCII tree starting from root_node."""
    if visited is None:
        visited = set()
        
    indent = "  " * level
    icon = "🌐" if level == 0 else ("📦" if root_node != "database" else "🗄️")
    output = f"{indent}└── {icon} {root_node}\n"
    
    visited.add(root_node)
    
    if G.has_node(root_node):
        for successor in G.successors(root_node):
            if successor not in visited:
                output += render_ascii_tree(G, successor, level + 1, visited.copy())
            else:
                output += f"{indent}  └── 🔄 {successor} (shared dependency)\n"
                
    return output

if __name__ == "__main__":
    from topology.graph_builder import TopologyGraphBuilder
    builder = TopologyGraphBuilder()
    G = builder.build_graph()
    print("\n--- System Topology Call Hierarchy ---")
    print(render_ascii_tree(G, "frontend"))
