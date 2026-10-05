import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common import setup_telemetry

app = FastAPI(title="API Gateway")
logger = setup_telemetry(app, "api-gateway")

SERVICE_MAP = {
    "/api/users": os.getenv("USER_SVC_URL", "http://user-service:8001"),
    "/api/products": os.getenv("PRODUCT_SVC_URL", "http://product-service:8002"),
    "/api/payments": os.getenv("PAYMENT_SVC_URL", "http://payment-service:8003"),
    "/api/orders": os.getenv("ORDER_SVC_URL", "http://order-service:8004"),
}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway_proxy(request: Request, full_path: str):
    # Allow telemetry/chaos routes registered by setup_telemetry to win;
    # this catch-all only handles unmatched API proxy paths.
    target_base = None
    path_with_slash = "/" + full_path

    for prefix, url in SERVICE_MAP.items():
        if path_with_slash.startswith(prefix):
            target_base = url
            break

    if not target_base:
        return JSONResponse(
            status_code=404,
            content={"error": f"Path /{full_path} not found in gateway router"},
        )

    target_url = f"{target_base}{path_with_slash}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)

    trace_id = getattr(request.state, "trace_id", None)
    if trace_id:
        headers["x-trace-id"] = trace_id

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"raw": resp.text}
            else:
                payload = {"raw": resp.text}
            return JSONResponse(status_code=resp.status_code, content=payload)
        except Exception as e:
            logger.error(f"Gateway proxy error target={target_url}: {str(e)}")
            return JSONResponse(
                status_code=502,
                content={"error": f"Bad Gateway: {str(e)}"},
            )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
