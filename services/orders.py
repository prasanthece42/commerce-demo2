import json

from fastapi import HTTPException
from pydantic import BaseModel, Field

import common as c

app = c.make_app("""
CREATE TABLE IF NOT EXISTS orders_records(
  order_id text PRIMARY KEY, cart_id text NOT NULL, result jsonb
);
CREATE TABLE IF NOT EXISTS orders_intents(order_id text PRIMARY KEY, result jsonb NOT NULL);
""")


class Checkout(BaseModel):
    order_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")
    cart_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")


@app.post("/checkout")
def checkout(item: Checkout):
    # Persist intent before downstream calls. Retrying the same ID resumes safely.
    with c.db.connection() as conn:
        conn.execute(
            "INSERT INTO orders_records(order_id,cart_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (item.order_id, item.cart_id),
        )
    with c.db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM orders_records WHERE order_id=%s FOR UPDATE",
            (item.order_id,),
        ).fetchone()
        if row["cart_id"] != item.cart_id:
            raise HTTPException(409, "Order ID reused with a different cart")
        if row["result"]:
            return {**row["result"], "served_by": c.INSTANCE, "replayed": True}
        # Snapshot cart + price once, before side effects, so retries cannot change them.
        stored = conn.execute(
            "SELECT result FROM orders_intents WHERE order_id=%s", (item.order_id,)
        ).fetchone()
        if stored:
            intent = stored["result"]
        else:
            cart = c.remote("cart", f"/carts/{item.cart_id}")
            product = c.remote("catalog", f"/products/{cart['sku']}")
            intent = {
                "order_id": item.order_id,
                "sku": cart["sku"],
                "quantity": cart["quantity"],
                "amount_cents": cart["quantity"] * product["price_cents"],
            }
            conn.execute(
                "INSERT INTO orders_intents VALUES (%s,%s)",
                (item.order_id, json.dumps(intent)),
            )
        # Commit durable intent while keeping subsequent processing serialized by row lock below.
    with c.db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM orders_records WHERE order_id=%s FOR UPDATE",
            (item.order_id,),
        ).fetchone()
        if row["result"]:
            return {**row["result"], "served_by": c.INSTANCE, "replayed": True}
        c.remote(
            "inventory",
            "/reservations",
            {k: intent[k] for k in ("order_id", "sku", "quantity")},
        )
        payment = c.remote(
            "payments",
            "/charges",
            {"order_id": item.order_id, "amount_cents": intent["amount_cents"]},
        )
        c.remote("notifications", "/events", {"order_id": item.order_id})
        result = {**intent, "status": "confirmed", "payment": payment["status"]}
        conn.execute(
            "UPDATE orders_records SET result=%s WHERE order_id=%s",
            (json.dumps(result), item.order_id),
        )
    return {**result, "served_by": c.INSTANCE, "replayed": False}


@app.get("/orders/{order_id}")
def order(order_id: str):
    with c.db.connection() as conn:
        row = conn.execute("SELECT * FROM orders_records WHERE order_id=%s", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown order")
    return (
        {"order_id": order_id, "status": "pending", "served_by": c.INSTANCE}
        if not row["result"]
        else {**row["result"], "served_by": c.INSTANCE}
    )
