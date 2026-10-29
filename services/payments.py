from fastapi import HTTPException

import common as c

app = c.make_app("""
CREATE TABLE IF NOT EXISTS payments_charges(order_id text PRIMARY KEY, amount_cents int NOT NULL);
""")


@app.post("/charges")
def charge(item: c.Charge):
    with c.db.connection() as conn:
        conn.execute(
            "INSERT INTO payments_charges VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (item.order_id, item.amount_cents),
        )
        row = conn.execute(
            "SELECT * FROM payments_charges WHERE order_id=%s", (item.order_id,)
        ).fetchone()
        if row["amount_cents"] != item.amount_cents:
            raise HTTPException(409, "Order ID reused with different amount")
    return {**row, "status": "simulated", "real_money": False}
