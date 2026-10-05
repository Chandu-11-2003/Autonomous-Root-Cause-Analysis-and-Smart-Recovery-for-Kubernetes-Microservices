import time
import random
import httpx

GATEWAY_URL = "http://localhost:30080/api"

print("🔥 Continuous Microservices Traffic Generator Started...")
print("Press CTRL+C to stop.\n")

products = [1, 2, 3, 4]
users = [1, 2, 3]

client = httpx.Client(timeout=10.0)

success_count = 0
fail_count = 0

try:
    while True:
        action = random.choices(["browse", "view_user", "buy"], weights=[50, 20, 30])[0]
        
        try:
            if action == "browse":
                res = client.get(f"{GATEWAY_URL}/products")
                print(f"[BROWSE] GET /api/products -> {res.status_code}")
            elif action == "view_user":
                u = random.choice(users)
                res = client.get(f"{GATEWAY_URL}/users/{u}")
                print(f"[USER] GET /api/users/{u} -> {res.status_code}")
            elif action == "buy":
                p = random.choice(products)
                u = random.choice(users)
                res = client.post(
                    f"{GATEWAY_URL}/orders",
                    json={"user_id": u, "product_id": p, "quantity": 1}
                )
                print(f"[BUY] POST /api/orders (user={u}, prod={p}) -> {res.status_code}")
            
            if res.status_code < 400:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            print(f"[ERROR] Request failed: {e}")
            
        time.sleep(random.uniform(0.2, 0.8))

except KeyboardInterrupt:
    print(f"\nStopped traffic generator. Successes: {success_count}, Failures: {fail_count}")
