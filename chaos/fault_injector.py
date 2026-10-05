"""
Fault Injector Framework
-------------------------
Automates chaos fault injection into the Kubernetes environment:
  1. Service Latency Injection (HTTP delay via dynamic endpoint)
  2. Service Error Injection (HTTP 500 responses via dynamic endpoint)
  3. Pod Deletion / Restart (kubectl pod kill)
  4. ConfigMap Corruption / Mutate
  5. Cluster-wide Chaos Reset
"""

import os
import json
import subprocess
import httpx
from typing import Dict, Any
from kubernetes import client, config
from kubernetes.client.rest import ApiException

def _load_kube_config():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

def _is_in_cluster() -> bool:
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

class FaultInjector:
    def __init__(self, namespace: str = "prod"):
        self.namespace = namespace
        _load_kube_config()
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.http_client = httpx.Client(timeout=10.0)
        self.in_cluster = _is_in_cluster()

    def _send_chaos_request(self, service_name: str, port: int, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends HTTP request directly if in pod, or via kubectl exec curl if on host."""
        if self.in_cluster:
            url = f"http://{service_name}.{self.namespace}.svc.cluster.local:{port}{endpoint}"
            try:
                resp = self.http_client.post(url, json=payload)
                resp.raise_for_status()
                return {"status": "success", "service": service_name, "details": resp.json()}
            except Exception as e:
                return {"status": "error", "service": service_name, "message": str(e)}
        else:
            # Running on host machine -> Execute curl via frontend pod inside cluster
            payload_str = json.dumps(payload).replace('"', '\\"')
            cmd = (
                f'kubectl exec -n {self.namespace} deploy/frontend -- '
                f'curl -s -X POST http://{service_name}:{port}{endpoint} '
                f'-H "Content-Type: application/json" -d "{payload_str}"'
            )
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
                output = res.stdout.strip()
                parsed = json.loads(output) if output else {}
                return {"status": "success", "service": service_name, "details": parsed}
            except Exception as e:
                return {"status": "error", "service": service_name, "message": str(e)}

    def inject_latency(self, service_name: str, port: int, latency_ms: int) -> Dict[str, Any]:
        """Inject HTTP latency into a target microservice."""
        payload = {"latency_ms": latency_ms, "error_rate": 0.0, "enabled": True}
        return self._send_chaos_request(service_name, port, "/chaos/inject", payload)

    def inject_errors(self, service_name: str, port: int, error_rate: float) -> Dict[str, Any]:
        """Inject HTTP 500 errors into a target microservice."""
        payload = {"latency_ms": 0, "error_rate": error_rate, "enabled": True}
        return self._send_chaos_request(service_name, port, "/chaos/inject", payload)

    def reset_service_chaos(self, service_name: str, port: int) -> Dict[str, Any]:
        """Reset chaos state on a specific microservice."""
        return self._send_chaos_request(service_name, port, "/chaos/reset", {})

    def kill_pod(self, service_name: str) -> Dict[str, Any]:
        """Force delete a random running pod of a microservice to trigger rescheduling."""
        try:
            pods = self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"app={service_name}"
            )
            if not pods.items:
                return {"status": "error", "message": f"No pods found for app={service_name}"}
            
            target_pod = pods.items[0].metadata.name
            self.v1.delete_namespaced_pod(name=target_pod, namespace=self.namespace)
            return {"status": "success", "deleted_pod": target_pod, "service": service_name}
        except ApiException as e:
            return {"status": "error", "message": f"ApiException: {e.status} {e.reason}"}

    def corrupt_configmap(self, configmap_name: str, key: str, invalid_value: str) -> Dict[str, Any]:
        """Mutate a ConfigMap key to simulate a misconfiguration error."""
        try:
            cm = self.v1.read_namespaced_config_map(name=configmap_name, namespace=self.namespace)
            if cm.data is None:
                cm.data = {}
            original_value = cm.data.get(key, "")
            cm.data[key] = invalid_value
            self.v1.patch_namespaced_config_map(name=configmap_name, namespace=self.namespace, body=cm)
            return {
                "status": "success",
                "configmap": configmap_name,
                "key": key,
                "original_value": original_value,
                "corrupted_value": invalid_value
            }
        except ApiException as e:
            return {"status": "error", "message": f"ApiException: {e.status} {e.reason}"}

    def reset_all_microservices(self) -> Dict[str, Any]:
        """Reset chaos settings on all standard microservices in the stack."""
        services = [
            ("user-service", 8001),
            ("product-service", 8002),
            ("payment-service", 8003),
            ("order-service", 8004),
            ("api-gateway", 8000)
        ]
        results = {}
        for svc_name, port in services:
            results[svc_name] = self.reset_service_chaos(svc_name, port)
        return results

if __name__ == "__main__":
    print("Testing FaultInjector initialization...")
    injector = FaultInjector(namespace="prod")
    print("FaultInjector ready for chaos testing.")
