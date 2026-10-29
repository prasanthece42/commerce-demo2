from fastapi import HTTPException

import common as c

app = c.make_app("""
CREATE TABLE IF NOT EXISTS inventory_stock(
  sku text PRIMARY KEY, quantity int NOT NULL CHECK(quantity >= 0)
);
CREATE TABLE IF NOT EXISTS inventory_reservations(
  order_id text PRIMARY KEY, sku text NOT NULL, quantity int NOT NULL
);
INSERT INTO inventory_stock VALUES
  ('sku-1',1000000),('sku-2',1000000),('sku-3',1000000) ON CONFLICT DO NOTHING;
""")


@app.get("/stock/{sku}")
def stock(sku: str):
    with c.db.connection() as conn:
        row = conn.execute("SELECT * FROM inventory_stock WHERE sku=%s", (sku,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown product")
    return row


@app.post("/reservations")
def reserve(item: c.Reservation):
    with c.db.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (item.order_id,))
        existing = conn.execute(
            "SELECT * FROM inventory_reservations WHERE order_id=%s", (item.order_id,)
        ).fetchone()
        if existing:
            if (existing["sku"], existing["quantity"]) != (item.sku, item.quantity):
                raise HTTPException(409, "Order ID reused with different items")
            return existing
        changed = conn.execute(
            "UPDATE inventory_stock SET quantity=quantity-%s "
            "WHERE sku=%s AND quantity >= %s RETURNING sku",
            (item.quantity, item.sku, item.quantity),
        ).fetchone()
        if not changed:
            raise HTTPException(409, "Insufficient stock")
        conn.execute(
            "INSERT INTO inventory_reservations VALUES (%s,%s,%s)",
            (item.order_id, item.sku, item.quantity),
        )
    return item.model_dump()
