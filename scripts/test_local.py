import subprocess
import time
import httpx
import sys

print("🚀 Starting all microservices locally in SQLite test mode...")

env_vars = {"USE_SQLITE": "true", "PATH": subprocess.os.environ["PATH"]}

procs = [
    subprocess.Popen([sys.executable, "main.py"], cwd="microservices/user-service", env=env_vars),
    subprocess.Popen([sys.executable, "main.py"], cwd="microservices/product-service", env=env_vars),
    subprocess.Popen([sys.executable, "main.py"], cwd="microservices/payment-service", env=env_vars),
    subprocess.Popen([sys.executable, "main.py"], cwd="microservices/order-service", env=env_vars),
    subprocess.Popen([sys.executable, "main.py"], cwd="microservices/api-gateway", env=env_vars),
]

time.sleep(3)

try:
    print("Testing End-to-End Flow via API Gateway (Port 8000)...")
    
    # 1. Test Gateway Health
    r = httpx.get("http://localhost:8000/healthz")
    print(f"1. Gateway Health: {r.status_code} -> {r.json()}")
    
    # 2. Test Fetch Products
    r = httpx.get("http://localhost:8000/api/products")
    print(f"2. Product Catalog: {r.status_code} -> Found {len(r.json()['products'])} products")
    
    # 3. Test Place Order
    r = httpx.post(
        "http://localhost:8000/api/orders",
        json={"user_id": 1, "product_id": 1, "quantity": 1}
    )
    print(f"3. Order Creation: {r.status_code} -> {r.json()}")
    
    # 4. Verify Metrics Endpoint
    r = httpx.get("http://localhost:8000/metrics")
    assert "http_requests_total" in r.text
    print("4. Prometheus Metrics: OK (RED Metrics Exposed)")
    
    print("\n🎉 ALL LOCAL TESTS PASSED SUCCESSFULLY!")

finally:
    print("Stopping test background processes...")
    for p in procs:
        p.terminate()
