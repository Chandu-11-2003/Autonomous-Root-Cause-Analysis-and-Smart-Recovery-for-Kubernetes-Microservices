import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
import sys
sys.path.append("..")
from common import setup_telemetry

app = FastAPI(title="Frontend Service", version="1.0.0")
logger = setup_telemetry(app, "frontend")

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous Cloud E-Commerce</title>
    <style>
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }
        .container { max-width: 1200px; margin: 0 auto; }
        header { border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }
        h1 { margin: 0; font-size: 24px; color: #38bdf8; }
        .badge { background: #0284c7; padding: 4px 10px; border-radius: 9999px; font-size: 12px; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }
        .card { background: #1e293b; border-radius: 10px; padding: 20px; border: 1px solid #334155; margin-bottom: 20px; }
        h2 { font-size: 18px; margin-top: 0; color: #94a3b8; }
        .product-item { display: flex; justify-content: space-between; align-items: center; padding: 12px; border-bottom: 1px solid #334155; }
        .product-item:last-child { border-bottom: none; }
        .btn { background: #0ea5e9; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; }
        .btn:hover { background: #0284c7; }
        .btn-danger { background: #ef4444; }
        .log-box { background: #020617; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 13px; height: 260px; overflow-y: auto; color: #a3e635; border: 1px solid #1e293b; }
        .status-pill { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #22c55e; margin-right: 6px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Cloud-Native Microservices Store</h1>
                <p style="color:#94a3b8; margin: 4px 0 0 0; font-size:14px;">Autonomous RCA & Smart Healing Target Application</p>
            </div>
            <div>
                <span class="status-pill"></span><span class="badge">Cluster Active</span>
            </div>
        </header>

        <div class="grid">
            <div>
                <div class="card">
                    <h2>Product Catalog & Order Placement</h2>
                    <div id="product-list">Loading products...</div>
                </div>
                <div class="card">
                    <h2>Recent Orders</h2>
                    <div id="order-list">Loading orders...</div>
                </div>
            </div>

            <div>
                <div class="card">
                    <h2>User Profiles</h2>
                    <div id="user-list">Loading users...</div>
                </div>
                <div class="card">
                    <h2>Live Activity Stream</h2>
                    <div class="log-box" id="activity-log">System ready.<br></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = '/api';

        function log(msg) {
            const box = document.getElementById('activity-log');
            const time = new Date().toLocaleTimeString();
            box.innerHTML = `[${time}] ${msg}<br>` + box.innerHTML;
        }

        async function loadProducts() {
            try {
                const res = await fetch(`${API_BASE}/products`);
                const data = await res.json();
                const container = document.getElementById('product-list');
                container.innerHTML = data.products.map(p => `
                    <div class="product-item">
                        <div>
                            <strong>${p.name}</strong><br>
                            <span style="color:#94a3b8; font-size:13px;">${p.description}</span><br>
                            <span style="color:#38bdf8; font-weight:bold;">₹${p.price.toFixed(2)}</span>
                            <span style="color:#64748b; font-size:12px;"> | Stock: ${p.stock}</span>
                        </div>
                        <button class="btn" onclick="buyProduct(${p.id})">Buy Now</button>
                    </div>
                `).join('');
            } catch (err) {
                log('Error loading products: ' + err);
            }
        }

        async function loadUsers() {
            try {
                const res = await fetch(`${API_BASE}/users`);
                const data = await res.json();
                const container = document.getElementById('user-list');
                container.innerHTML = data.users.map(u => `
                    <div class="product-item">
                        <div>
                            <strong>${u.username}</strong> (${u.email})<br>
                            <span style="color:#22c55e;">Balance: ₹${u.balance.toFixed(2)}</span>
                        </div>
                    </div>
                `).join('');
            } catch(e) {
                log('Error loading users: ' + e);
            }
        }

        async function loadOrders() {
            try {
                const res = await fetch(`${API_BASE}/orders`);
                const data = await res.json();
                const container = document.getElementById('order-list');
                container.innerHTML = data.orders.slice(0, 5).map(o => `
                    <div class="product-item">
                        <div>
                            <strong>Order #${o.id}</strong> - Status: <span style="color:#38bdf8">${o.status}</span><br>
                            <span style="color:#94a3b8; font-size:12px;">Trace ID: ${o.trace_id}</span>
                        </div>
                        <span style="font-weight:bold; color:#a3e635;">₹${o.total_amount.toFixed(2)}</span>
                    </div>
                `).join('');
            } catch(e) {
                log('Error loading orders: ' + e);
            }
        }

        async function buyProduct(productId) {
            log(`Placing order for Product ID ${productId}...`);
            try {
                const res = await fetch(`${API_BASE}/orders`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ user_id: 1, product_id: productId, quantity: 1 })
                });
                const data = await res.json();
                if (res.ok) {
                    log(`✅ Order #${data.order_id} Confirmed! Trace ID: ${data.trace_id}`);
                } else {
                    log(`❌ Order Failed: ${data.detail || JSON.stringify(data)}`);
                }
                loadProducts();
                loadUsers();
                loadOrders();
            } catch(err) {
                log('❌ Network error: ' + err);
            }
        }

        // Initial Load
        loadProducts();
        loadUsers();
        loadOrders();
        setInterval(loadOrders, 5000);
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_TEMPLATE

# Proxy requests from UI to Gateway
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_gateway(path: str, request: Request):
    headers = dict(request.headers)
    headers.pop("host", None)
    body = await request.body()
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(
            method=request.method,
            url=f"{GATEWAY_URL}/api/{path}",
            params=request.query_params,
            headers=headers,
            content=body
        )
        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
