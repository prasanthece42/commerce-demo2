import json
import os

from fastapi import HTTPException

import common as c

app = c.make_app(
    """
CREATE TABLE IF NOT EXISTS catalog_products(
  sku text PRIMARY KEY, name text NOT NULL, price_cents int NOT NULL
);
INSERT INTO catalog_products VALUES
  ('sku-1','Keyboard',4900),
  ('sku-2','Mouse',2500),
  ('sku-3','Headset',7900)
ON CONFLICT DO NOTHING;
""",
    use_cache=True,
)


@app.get("/products")
def products():
    cached = c.cache.get("catalog:products")
    if cached:
        return {"products": json.loads(cached), "cache": "hit"}
    with c.db.connection() as conn:
        rows = conn.execute("SELECT * FROM catalog_products ORDER BY sku").fetchall()
    c.cache.setex("catalog:products", int(os.getenv("CACHE_TTL_SECONDS", "30")), json.dumps(rows))
    return {"products": rows, "cache": "miss"}


@app.get("/products/{sku}")
def product(sku: str):
    for item in products()["products"]:
        if item["sku"] == sku:
            return item
    raise HTTPException(404, "Unknown product")
