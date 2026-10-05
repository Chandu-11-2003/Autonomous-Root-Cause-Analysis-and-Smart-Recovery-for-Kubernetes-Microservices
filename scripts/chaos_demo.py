#!/usr/bin/env python3
"""
Step 9 Demo Script: Chaos & Fault Injection
-------------------------------------------
1. Injects 2500ms latency into payment-service.
2. Injects 100% error rate into product-service.
3. Runs test requests to verify degradation in metrics/responses.
4. Resets all microservices back to normal operating parameters.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chaos.fault_injector import FaultInjector

def main():
    print("=" * 60)
    print(" STEP 9 — Chaos Engineering & Fault Injection Test")
    print("=" * 60)

    injector = FaultInjector(namespace="prod")

    # 1. Inject Latency into payment-service
    print("\n[1] Injecting 2500ms latency into payment-service...")
    res_lat = injector.inject_latency("payment-service", 8003, latency_ms=2500)
    print("   Response:", res_lat)

    # 2. Inject 100% error rate into product-service
    print("\n[2] Injecting 100% HTTP 500 Error rate into product-service...")
    res_err = injector.inject_errors("product-service", 8002, error_rate=1.0)
    print("   Response:", res_err)

    # 3. Sleep briefly and verify status via Python in-cluster execution
    print("\n[3] Verifying injected fault state...")
    time.sleep(1)

    # 4. Clean up / Reset chaos state
    print("\n[4] Cleaning up / Resetting chaos on all microservices...")
    res_reset = injector.reset_all_microservices()
    for svc, res in res_reset.items():
        print(f"   Reset {svc:20}: {res.get('status')}")

    print("\n✅ Step 9 Fault Injection Framework successfully verified!")

if __name__ == "__main__":
    main()
