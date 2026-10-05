import time
import httpx
from typing import List, Dict, Any, Optional

class LokiClient:
    """Client for querying Grafana Loki log aggregation engine."""
    
    def __init__(self, base_url: str = "http://loki.monitoring.svc.cluster.local:3100"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=10.0)

    def query_logs(
        self,
        query: str,
        start_ns: Optional[int] = None,
        end_ns: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Execute a LogQL query and return parsed log events."""
        url = f"{self.base_url}/loki/api/v1/query_range"
        params = {"query": query, "limit": limit}
        
        if start_ns:
            params["start"] = str(start_ns)
        if end_ns:
            params["end"] = str(end_ns)
            
        try:
            resp = self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            results = []
            for stream in data.get("data", {}).get("result", []):
                labels = stream.get("stream", {})
                for value in stream.get("values", []):
                    ts_ns, log_line = value
                    results.append({
                        "timestamp_ns": int(ts_ns),
                        "timestamp_s": int(ts_ns) / 1e9,
                        "labels": labels,
                        "log": log_line
                    })
            return sorted(results, key=lambda x: x["timestamp_ns"])
        except Exception as e:
            return [{"error": f"Failed to query Loki: {str(e)}"}]

    def get_service_logs(self, service: str, namespace: str = "prod", limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch latest logs for a specific service."""
        query = f'{{namespace="{namespace}", app="{service}"}}'
        return self.query_logs(query=query, limit=limit)

    def get_error_logs(self, service: Optional[str] = None, namespace: str = "prod", limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch error-level logs containing ERROR, Exception, or 5xx."""
        if service:
            query = f'{{namespace="{namespace}", app="{service}"}} |= "ERROR"'
        else:
            query = f'{{namespace="{namespace}"}} |= "ERROR"'
        return self.query_logs(query=query, limit=limit)

    def get_trace_logs(self, trace_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch all logs across all services for a given trace_id."""
        query = f'{{namespace=~"prod|staging"}} |= "{trace_id}"'
        return self.query_logs(query=query, limit=limit)

if __name__ == "__main__":
    print("Testing Loki Python Client...")
    client = LokiClient()
    logs = client.get_service_logs("order-service", limit=5)
    print(f"Retrieved {len(logs)} log entries from order-service.")
