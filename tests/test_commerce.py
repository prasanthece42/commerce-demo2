"""Model checks plus dependency-backed checkout when the CI gateway is supplied."""

import asyncio
import importlib
import os
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError


def test_invalid_quantity_and_unknown_sku(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "test")
    common = importlib.import_module("common")
    for payload in (
        {"sku": "sku-1", "quantity": 0},
        {"sku": "sku-1", "quantity": 11},
        {"sku": "unknown", "quantity": 1},
    ):
        with pytest.raises(ValidationError):
            common.Item.model_validate(payload)
    assert common.Item(sku="sku-1", quantity=2).quantity == 2


@pytest.mark.skipif(
    not os.getenv("AEGIS_STACK_URL"), reason="Full-stack CI supplies the gateway URL"
)
def test_real_checkout_is_idempotent_and_keeps_its_cart_snapshot():
    async def exercise():
        key = "ci-" + uuid4().hex
        async with httpx.AsyncClient(base_url=os.environ["AEGIS_STACK_URL"], timeout=30) as client:
            products = await client.get("/api/catalog/products")
            assert len(products.json()["products"]) == 3
            before = (await client.get("/api/inventory/stock/sku-1")).json()["quantity"]
            cart = await client.post(f"/api/cart/carts/{key}", json={"sku": "sku-1", "quantity": 2})
            cart.raise_for_status()
            payload = {"order_id": key, "cart_id": key}
            responses = await asyncio.gather(
                *(client.post("/api/orders/checkout", json=payload) for _ in range(8))
            )
            for response in responses:
                response.raise_for_status()
                assert response.json()["status"] == "confirmed"
                assert response.json()["payment"] == "simulated"
                assert response.json()["amount_cents"] == 9800
            assert sum(not r.json()["replayed"] for r in responses) == 1
            after = (await client.get("/api/inventory/stock/sku-1")).json()["quantity"]
            assert before - after == 2
            await client.post(f"/api/cart/carts/{key}", json={"sku": "sku-2", "quantity": 3})
            replay = await client.post("/api/orders/checkout", json=payload)
            assert replay.json()["amount_cents"] == 9800
            conflict = await client.post(
                "/api/orders/checkout", json={**payload, "cart_id": key + "other"}
            )
            assert conflict.status_code == 409

    asyncio.run(exercise())
