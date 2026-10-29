import json
import os
from typing import Annotated

from fastapi import HTTPException, Path

import common as c

app = c.make_app(use_cache=True)
CartID = Annotated[str, Path(pattern=r"^[a-zA-Z0-9-]{1,80}$")]


@app.post("/carts/{cart_id}")
def save(cart_id: CartID, item: c.Item):
    # One line item per demo cart; replacement is explicit and atomic.
    c.remote("catalog", f"/products/{item.sku}")
    c.cache.setex(
        f"cart:{cart_id}",
        int(os.getenv("CART_TTL_SECONDS", "3600")),
        item.model_dump_json(),
    )
    return {"cart_id": cart_id, **item.model_dump()}


@app.get("/carts/{cart_id}")
def get(cart_id: CartID):
    raw = c.cache.get(f"cart:{cart_id}")
    if not raw:
        raise HTTPException(404, "Cart missing or expired")
    return {"cart_id": cart_id, **json.loads(raw)}
