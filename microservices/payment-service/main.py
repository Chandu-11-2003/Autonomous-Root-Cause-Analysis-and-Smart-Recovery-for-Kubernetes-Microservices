import random
import time
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import sys
sys.path.append("..")
from common import setup_telemetry

app = FastAPI(title="Payment Service", version="1.0.0")
logger = setup_telemetry(app, "payment-service")

class PaymentRequest(BaseModel):
    user_id: int
    amount: float
    payment_method: str = "credit_card"

@app.post("/api/payments/process")
async def process_payment(req: PaymentRequest, request: Request):
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.info(
        f"Processing payment of ${req.amount:.2f} for user {req.user_id}",
        extra={"trace_id": trace_id, "user_id": req.user_id, "amount": req.amount}
    )
    
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payment amount")
    
    # Simulate payment processing delay (30-80ms)
    time.sleep(random.uniform(0.03, 0.08))
    
    # Simulated fraud guard rule (> $5000 requires special clearance)
    if req.amount > 5000:
        logger.warning(f"Payment rejected due to risk limit: ${req.amount}", extra={"trace_id": trace_id})
        raise HTTPException(status_code=422, detail="Transaction flagged by risk management engine")
    
    tx_id = f"tx_{int(time.time()*1000)}_{random.randint(100, 999)}"
    return {
        "status": "COMPLETED",
        "transaction_id": tx_id,
        "user_id": req.user_id,
        "amount": req.amount,
        "timestamp": time.time()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
