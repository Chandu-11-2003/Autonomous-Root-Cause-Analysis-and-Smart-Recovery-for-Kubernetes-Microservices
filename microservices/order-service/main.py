import os
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

from common import setup_telemetry

app = FastAPI(title="Order Service")
logger = setup_telemetry(app, "order-service")

USER_SVC_URL = os.getenv("USER_SVC_URL", "http://user-service:8001")
PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-service:8002")
PAYMENT_SVC_URL = os.getenv("PAYMENT_SVC_URL", "http://payment-service:8003")

DB_HOST = os.getenv("DB_HOST", "database")
DB_NAME = os.getenv("DB_NAME", "micro_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT,
        sslmode="disable",
        connect_timeout=3,
    )


class OrderCreate(BaseModel):
    user_id: int
    product_id: int
    quantity: int


@app.post("/api/orders")
async def create_order(order: OrderCreate):
    logger.info(
        f"Processing new order creation: user={order.user_id}, "
        f"product={order.product_id}, qty={order.quantity}"
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Verify User
        try:
            u_res = await client.get(f"{USER_SVC_URL}/api/users/{order.user_id}")
            if u_res.status_code != 200:
                raise HTTPException(status_code=502, detail="User service returned non-200")
            user_data = u_res.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"User service call failed: {e}")
            raise HTTPException(status_code=502, detail=f"User service error: {str(e)}")

        # 2. Verify Product & Stock
        try:
            p_res = await client.get(f"{PRODUCT_SVC_URL}/api/products/{order.product_id}")
            if p_res.status_code != 200:
                raise HTTPException(status_code=502, detail="Product service returned non-200")
            product_data = p_res.json()
            if product_data.get("stock", 0) < order.quantity:
                raise HTTPException(status_code=400, detail="Insufficient stock")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Product service call failed: {e}")
            raise HTTPException(status_code=502, detail=f"Product service error: {str(e)}")

        # 3. Process Payment
        amount = float(product_data["price"]) * order.quantity
        try:
            pay_payload = {
                "user_id": order.user_id,
                "amount": amount,
                "payment_method": "CREDIT_CARD",
            }
            pay_res = await client.post(
                f"{PAYMENT_SVC_URL}/api/payments/process", json=pay_payload
            )
            if pay_res.status_code != 200:
                logger.error(f"Payment service failed with status {pay_res.status_code}")
                raise HTTPException(status_code=502, detail=f"Payment processing failed: HTTP {pay_res.status_code}")
            payment_data = pay_res.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Payment service call failed: {e}")
            raise HTTPException(
                status_code=502, detail=f"Payment service error: {str(e)}"
            )

        # 4. Save Order to Database
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                INSERT INTO orders (user_id, product_id, quantity, total_price, status, payment_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, status, created_at;
                """,
                (
                    order.user_id,
                    order.product_id,
                    order.quantity,
                    amount,
                    "COMPLETED",
                    payment_data.get("payment_id"),
                ),
            )
            new_order = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            logger.info(f"Order #{new_order['id']} created successfully")
            return {
                "order_id": new_order["id"],
                "status": "COMPLETED",
                "total_price": amount,
                "payment": payment_data,
            }
        except Exception as e:
            logger.error(f"Database insertion failed: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/api/orders/{order_id}")
def get_order(order_id: int):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
        order = cur.fetchone()
        cur.close()
        conn.close()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return dict(order)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
