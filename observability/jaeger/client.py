import httpx
from typing import List, Dict, Any, Tuple

class JaegerClient:
    """Client for querying Jaeger Tracing API to build call graphs and detect bottleneck spans."""
    
    def __init__(self, base_url: str = "http://jaeger.monitoring.svc.cluster.local:16686"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=10.0)

    def get_services(self) -> List[str]:
        """Fetch list of all instrumented services in Jaeger."""
        try:
            resp = self.client.get(f"{self.base_url}/api/services")
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            return []

    def get_traces_for_service(self, service: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch latest traces for a specific microservice."""
        try:
            resp = self.client.get(f"{self.base_url}/api/traces", params={"service": service, "limit": limit})
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            return []

    def get_trace_by_id(self, trace_id: str) -> Dict[str, Any]:
        """Fetch full trace details including all child spans across all microservices."""
        try:
            resp = self.client.get(f"{self.base_url}/api/traces/{trace_id}")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return data[0] if data else {}
        except Exception as e:
            return {}

    def extract_dependency_edges(self, limit: int = 50) -> List[Tuple[str, str]]:
        """Extract parent -> child caller relationships across all traces to dynamically build dependency graph."""
        services = self.get_services()
        edges = set()
        
        for svc in services:
            traces = self.get_traces_for_service(svc, limit=10)
            for trace in traces:
                processes = trace.get("processes", {})
                span_service_map = {}
                
                for p_id, p_info in processes.items():
                    span_service_map[p_id] = p_info.get("serviceName")
                
                span_id_to_svc = {}
                for span in trace.get("spans", []):
                    s_id = span.get("spanID")
                    p_id = span.get("processID")
                    svc_name = span_service_map.get(p_id)
                    if s_id and svc_name:
                        span_id_to_svc[s_id] = svc_name
                
                for span in trace.get("spans", []):
                    child_svc = span_service_map.get(span.get("processID"))
                    for ref in span.get("references", []):
                        if ref.get("refType") == "CHILD_OF":
                            parent_span_id = ref.get("spanID")
                            parent_svc = span_id_to_svc.get(parent_span_id)
                            if parent_svc and child_svc and parent_svc != child_svc:
                                edges.add((parent_svc, child_svc))
                                
        return list(edges)

if __name__ == "__main__":
    print("Testing Jaeger Client...")
    jc = JaegerClient()
    services = jc.get_services()
    print("Services in Jaeger:", services)
    edges = jc.extract_dependency_edges()
    print("Discovered Call Dependencies:", edges)
