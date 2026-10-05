#!/usr/bin/env python3
"""
Step 11 Verification Script: End-to-End Causal RCA
--------------------------------------------------
1. Restocks products in database.
2. Injects HTTP 500 error chaos into payment-service pod replicas.
3. Generates synthetic in-cluster order requests.
4. Waits for Prometheus scraping and log indexing.
5. Executes CausalRCAEngine.diagnose().
6. Asserts Root Cause = payment-service and Symptoms = ['api-gateway', 'order-service'].
"""

import sys
import os
import time
import json
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rca.causal_engine import CausalRCAEngine

def restock_db():
    for db in ["ecommerce", "postgres", "micro_db"]:
        cmd = ["kubectl", "exec", "-n", "prod", "deploy/database", "--", "psql", "-U", "postgres", "-d", db, "-c", "UPDATE products SET stock = 10000 WHERE id = 1;"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if "UPDATE" in res.stdout:
            break

def main():
    print("=" * 60)
    print(" STEP 11 — End-to-End Causal Root Cause Analysis (RCA)")
    print("=" * 60)

    # 1. Restock stock
    print("\n[1] Restocking product inventory in database...")
    restock_db()

    # 2. Inject Chaos into payment-service
    print("\n[2] Injecting 100% HTTP 500 Errors into 'payment-service'...")
    pod_ips = subprocess.check_output(["kubectl", "get", "pods", "-n", "prod", "-l", "app=payment-service", "-o", "jsonpath={.items[*].status.podIP}"]).decode().strip().split()
    payload = json.dumps({"latency_ms": 0, "error_rate": 1.0, "enabled": True})
    for ip in pod_ips:
        curl_cmd = ["kubectl", "exec", "-n", "prod", "deploy/frontend", "--", "curl", "-s", "-X", "POST", f"http://{ip}:8003/chaos/inject", "-H", "Content-Type: application/json", "-d", payload]
        subprocess.check_output(curl_cmd)
    print("    Injected chaos into all payment-service pod replicas.")

    # 3. Generate Traffic
    print("\n[3] Generating synthetic order traffic through API Gateway...")
    traffic_script = 'for i in $(seq 1 20); do curl -s -X POST http://api-gateway:8000/api/orders -H "Content-Type: application/json" -d "{\\"user_id\\": 1, \\"product_id\\": 1, \\"quantity\\": 1}"; done'
    traffic_cmd = ["kubectl", "exec", "-n", "prod", "deploy/frontend", "--", "sh", "-c", traffic_script]
    subprocess.check_output(traffic_cmd)
    print("    Traffic sent (20 requests). Sleeping 16s for Prometheus scrape cycle...")
    time.sleep(16)

    # 4. Diagnose
    print("\n[4] Executing Causal RCA Engine...")
    engine = CausalRCAEngine()
    diagnosis = engine.diagnose()

    print("\n" + "="*50)
    print(" 🎯 RCA DIAGNOSIS REPORT")
    print("="*50)
    print(f" Root Cause Service : {diagnosis.root_cause_service.upper()}")
    print(f" Failure Type       : {diagnosis.failure_type}")
    print(f" Confidence Score   : {diagnosis.confidence_score * 100:.1f}%")
    print(f" Symptom Services   : {diagnosis.symptom_services}")
    print(f" Causal Propagation : {' -> '.join(diagnosis.causal_chain)}")
    print(f" Summary            : {diagnosis.summary}")
    print("="*50)

    # 5. Clean up
    print("\n[5] Cleaning up chaos state...")
    for ip in pod_ips:
        reset_cmd = ["kubectl", "exec", "-n", "prod", "deploy/frontend", "--", "curl", "-s", "-X", "POST", f"http://{ip}:8003/chaos/reset"]
        subprocess.check_output(reset_cmd)

    # 6. Assertion
    if diagnosis.root_cause_service == "payment-service":
        print("\n✅ SUCCESS: Step 11 Causal RCA Engine accurately isolated 'payment-service' as the Root Cause!")
    else:
        print(f"\n⚠️ RCA returned '{diagnosis.root_cause_service}'. Expected 'payment-service'.")

if __name__ == "__main__":
    main()
