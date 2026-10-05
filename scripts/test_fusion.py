import sys
import os
import time
import json
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rca.evidence_fusion import EvidenceFusion
from rca.causal_engine import CausalRCAEngine

def main():
    print("--- 1. Restocking DB Product #1 ---")
    for db in ["ecommerce", "postgres", "micro_db"]:
        cmd = ["kubectl", "exec", "-n", "prod", "deploy/database", "--", "psql", "-U", "postgres", "-d", db, "-c", "UPDATE products SET stock = 10000 WHERE id = 1;"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if "UPDATE" in res.stdout:
            print(f"  Successfully restocked product 1 in DB '{db}'!")
            break

    print("\n--- 2. Injecting 100% 500 Chaos into payment-service pods ---")
    pod_ips = subprocess.check_output(["kubectl", "get", "pods", "-n", "prod", "-l", "app=payment-service", "-o", "jsonpath={.items[*].status.podIP}"]).decode().strip().split()
    payload = json.dumps({"latency_ms": 0, "error_rate": 1.0, "enabled": True})
    for ip in pod_ips:
        curl_cmd = ["kubectl", "exec", "-n", "prod", "deploy/frontend", "--", "curl", "-s", "-X", "POST", f"http://{ip}:8003/chaos/inject", "-H", "Content-Type: application/json", "-d", payload]
        out = subprocess.check_output(curl_cmd).decode().strip()
        print(f"  Pod IP {ip}: {out}")

    print("\n--- 3. Sending 20 Order Creation Requests ---")
    traffic_script = 'for i in $(seq 1 20); do curl -s -w "\\nHTTP: %{http_code}\\n" -X POST http://api-gateway:8000/api/orders -H "Content-Type: application/json" -d "{\\"user_id\\": 1, \\"product_id\\": 1, \\"quantity\\": 1}"; done'
    traffic_cmd = ["kubectl", "exec", "-n", "prod", "deploy/frontend", "--", "sh", "-c", traffic_script]
    out = subprocess.check_output(traffic_cmd).decode().strip()
    responses = [line for line in out.split("\n") if line.strip()]
    print("  Sample gateway response:")
    print(" ", "\n ".join(responses[:4]))

    print("\n--- 4. Sleeping 16s for Prometheus scrape cycle ---")
    time.sleep(16)

    print("\n--- 5. Evaluating Evidence Fusion Scores ---")
    fusion = EvidenceFusion()
    evidence_dict = fusion.collect_all_evidence()
    for svc, ev in evidence_dict.items():
        print(f"  Service: {svc:18s} | Composite: {ev.composite_score:.3f} | Metrics: {ev.score_metrics:.3f} | Logs: {ev.score_logs:.3f} | Traces: {ev.score_traces:.3f} | K8s: {ev.score_k8s:.3f}")

    print("\n--- 6. Running Causal Engine Diagnosis ---")
    engine = CausalRCAEngine()
    diagnosis = engine.diagnose()
    print(f"  Root Cause: {diagnosis.root_cause_service.upper()}")
    print(f"  Failure Type: {diagnosis.failure_type}")
    print(f"  Confidence: {diagnosis.confidence_score * 100:.1f}%")
    print(f"  Symptoms: {diagnosis.symptom_services}")
    print(f"  Causal Chain: {' -> '.join(diagnosis.causal_chain)}")

    print("\n--- 7. Resetting Chaos ---")
    for ip in pod_ips:
        reset_cmd = ["kubectl", "exec", "-n", "prod", "deploy/frontend", "--", "curl", "-s", "-X", "POST", f"http://{ip}:8003/chaos/reset"]
        subprocess.check_output(reset_cmd)

if __name__ == "__main__":
    main()
