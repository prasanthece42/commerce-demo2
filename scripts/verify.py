"""Real integration checks through the load balancer, including concurrent retries."""

import asyncio
import json
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:18180"


async def verify():
    key = "verify-" + uuid.uuid4().hex
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        for service in [
            "catalog",
            "inventory",
            "cart",
            "orders",
            "payments",
            "notifications",
        ]:
            response = await client.get(f"/api/{service}/ready")
            assert response.status_code == 200, (service, response.text)
        products = (await client.get("/api/catalog/products")).json()["products"]
        assert len(products) == 3
        assert (await client.get("/api/inventory/stock/missing")).status_code == 404
        assert (await client.get("/api/cart/carts/missing")).status_code == 404
        assert (
            await client.post(f"/api/cart/carts/{key}", json={"sku": "sku-1", "quantity": 0})
        ).status_code == 422
        response = await client.post(f"/api/cart/carts/{key}", json={"sku": "sku-1", "quantity": 2})
        assert response.status_code == 200, response.text
        before = (await client.get("/api/inventory/stock/sku-1")).json()["quantity"]
        responses = await asyncio.gather(
            *(
                client.post("/api/orders/checkout", json={"order_id": key, "cart_id": key})
                for _ in range(16)
            )
        )
        for response in responses:
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "confirmed"
            assert response.json()["amount_cents"] == 9800
        after = (await client.get("/api/inventory/stock/sku-1")).json()["quantity"]
        assert before - after == 2, (before, after)
        assert sum(not r.json()["replayed"] for r in responses) == 1
        replicas = sorted({r.json()["served_by"] for r in responses})
        assert len(replicas) == 2, replicas
        # A changed cart must not change an already committed checkout.
        await client.post(f"/api/cart/carts/{key}", json={"sku": "sku-2", "quantity": 3})
        replay = await client.post("/api/orders/checkout", json={"order_id": key, "cart_id": key})
        assert replay.json()["amount_cents"] == 9800
        conflict = await client.post(
            "/api/orders/checkout", json={"order_id": key, "cart_id": key + "-other"}
        )
        assert conflict.status_code == 409, conflict.text
    result = {
        "status": "passed",
        "order_id": key,
        "concurrent_retries": 16,
        "stock_deducted": 2,
        "order_replicas": replicas,
        "checks": [
            "six ready services",
            "validation",
            "missing data",
            "checkout",
            "single stock deduction",
            "idempotent concurrency",
            "two order replicas",
            "cart snapshot",
            "conflicting idempotency key",
        ],
    }
    local = Path(__file__).resolve().parents[1] / ".local"
    local.mkdir(exist_ok=True)
    (local / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(verify())
