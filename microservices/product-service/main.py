import os
import sqlite3
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sys
sys.path.append("..")
from common import setup_telemetry

app = FastAPI(title="Product Service", version="1.0.0")
logger = setup_telemetry(app, "product-service")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "ecommerce")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
USE_SQLITE = os.getenv("USE_SQLITE", "false").lower() == "true"

def get_db():
    if USE_SQLITE:
        conn = sqlite3.connect("products_local.db")
        conn.row_factory = sqlite3.Row
        return conn
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )

def init_sqlite():
    if USE_SQLITE:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price REAL,
                stock INTEGER
            )
        ''')
        cur.execute("INSERT OR IGNORE INTO products (id, name, description, price, stock) VALUES (1, 'Cloud Native Laptop', 'High perf dev laptop', 999.99, 25)")
        cur.execute("INSERT OR IGNORE INTO products (id, name, description, price, stock) VALUES (2, 'Kubernetes Mug', 'Observability Mug', 14.50, 100)")
        conn.commit()
        conn.close()

init_sqlite()

class ReserveStockRequest(BaseModel):
    quantity: int

@app.get("/api/products")
def list_products():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price, stock FROM products ORDER BY id;")
    rows = cur.fetchall()
    conn.close()
    if USE_SQLITE:
        return {"products": [dict(r) for r in rows]}
    return {
        "products": [
            {"id": r[0], "name": r[1], "description": r[2], "price": float(r[3]), "stock": r[4]}
            for r in rows
        ]
    }

@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price, stock FROM products WHERE id = %s" if not USE_SQLITE else "SELECT id, name, description, price, stock FROM products WHERE id = ?", (product_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    if USE_SQLITE:
        return dict(row)
    return {"id": row[0], "name": row[1], "description": row[2], "price": float(row[3]), "stock": row[4]}

@app.post("/api/products/{product_id}/reserve")
def reserve_stock(product_id: int, req: ReserveStockRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT stock FROM products WHERE id = %s" if not USE_SQLITE else "SELECT stock FROM products WHERE id = ?", (product_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    
    current_stock = row[0] if not USE_SQLITE else row["stock"]
    if current_stock < req.quantity:
        conn.close()
        raise HTTPException(status_code=400, detail="Out of stock")
    
    new_stock = current_stock - req.quantity
    cur.execute(
        "UPDATE products SET stock = %s WHERE id = %s" if not USE_SQLITE else "UPDATE products SET stock = ? WHERE id = ?",
        (new_stock, product_id)
    )
    conn.commit()
    conn.close()
    return {"status": "reserved", "product_id": product_id, "remaining_stock": new_stock}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
