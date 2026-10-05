import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import sys
sys.path.append("..")
from common import setup_telemetry

app = FastAPI(title="User Service", version="1.0.0")
logger = setup_telemetry(app, "user-service")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "ecommerce")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
USE_SQLITE = os.getenv("USE_SQLITE", "false").lower() == "true"

def get_db():
    if USE_SQLITE:
        conn = sqlite3.connect("users_local.db")
        conn.row_factory = sqlite3.Row
        return conn
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        sslmode="disable",
        connect_timeout=3
    )

def init_sqlite():
    if USE_SQLITE:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                balance REAL DEFAULT 1000.0
            )
        ''')
        cur.execute("INSERT OR IGNORE INTO users (id, username, email, balance) VALUES (1, 'alice', 'alice@example.com', 500.00)")
        cur.execute("INSERT OR IGNORE INTO users (id, username, email, balance) VALUES (2, 'bob', 'bob@example.com', 1200.00)")
        conn.commit()
        conn.close()

init_sqlite()

class DeductBalanceRequest(BaseModel):
    amount: float

@app.get("/api/users")
def list_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, balance FROM users ORDER BY id;")
    users = [dict(row) for row in cur.fetchall()] if USE_SQLITE else [
        {"id": r[0], "username": r[1], "email": r[2], "balance": float(r[3])} for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return {"users": users}

@app.get("/api/users/{user_id}")
def get_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, balance FROM users WHERE id = %s" if not USE_SQLITE else "SELECT id, username, email, balance FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if USE_SQLITE:
        return dict(row)
    return {"id": row[0], "username": row[1], "email": row[2], "balance": float(row[3])}

@app.post("/api/users/{user_id}/deduct")
def deduct_balance(user_id: int, req: DeductBalanceRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE id = %s" if not USE_SQLITE else "SELECT balance FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    
    current_balance = float(row[0] if not USE_SQLITE else row["balance"])
    if current_balance < req.amount:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Insufficient funds")
    
    new_balance = current_balance - req.amount
    cur.execute(
        "UPDATE users SET balance = %s WHERE id = %s" if not USE_SQLITE else "UPDATE users SET balance = ? WHERE id = ?",
        (new_balance, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "user_id": user_id, "new_balance": new_balance}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
