"""
Prometheus API Client
---------------------
Queries Prometheus HTTP API for RED metrics, error rates, latencies, and service metrics.
"""

import os
import httpx
import math
from typing import List, Dict, Any, Optional

def _is_in_cluster() -> bool:
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

class PrometheusClient:
    def __init__(self, base_url: str = None):
        if base_url is None:
            base_url = "http://prometheus-server.monitoring.svc.cluster.local:80" if _is_in_cluster() else "http://localhost:9099"
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=10.0)

    def query_instant(self, query: str) -> List[Dict[str, Any]]:
        """Query instant metric values for a PromQL expression."""
        try:
            resp = self.client.get(f"{self.base_url}/api/v1/query", params={"query": query})
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
            return []
        except Exception:
            return []

    def query_range(self, query: str, start: float, end: float, step: str = "15s") -> List[Dict[str, Any]]:
        """Query range metric values for time-series analysis."""
        try:
            resp = self.client.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
            return []
        except Exception:
            return []

    def get_service_error_rates(self) -> Dict[str, float]:
        """Fetch error percentage per microservice over recent 2-minute window."""
        query = 'sum(increase(http_requests_total{status_code=~"5.."}[2m])) by (service) / sum(increase(http_requests_total[2m])) by (service)'
        results = self.query_instant(query)
        rates = {}
        for r in results:
            svc = r.get("metric", {}).get("service")
            val = r.get("value", [0, "0"])[1]
            if svc:
                try:
                    v = float(val)
                    if not math.isnan(v):
                        rates[svc] = v
                except (ValueError, TypeError):
                    pass
        return rates

    def get_service_error_counts(self) -> Dict[str, float]:
        """Fetch total HTTP 5xx error count over recent 2-minute window."""
        query = 'sum(increase(http_requests_total{status_code=~"5.."}[2m])) by (service)'
        results = self.query_instant(query)
        counts = {}
        for r in results:
            svc = r.get("metric", {}).get("service")
            val = r.get("value", [0, "0"])[1]
            if svc:
                try:
                    v = float(val)
                    if not math.isnan(v):
                        counts[svc] = v
                except (ValueError, TypeError):
                    pass
        return counts

if __name__ == "__main__":
    print("Testing Prometheus Client...")
    pc = PrometheusClient()
    res = pc.query_instant("up")
    print("Prometheus Active Targets:", len(res))
