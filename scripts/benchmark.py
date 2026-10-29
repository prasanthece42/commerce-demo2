"""Bounded closed-loop HTTP benchmark; one process, loopback gateway only."""

import argparse
import asyncio
import json
import math
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18180"


def percentile(values, fraction):
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] * 1000, 2)
        if values
        else None
    )


async def stage(concurrency, seconds, workload):
    samples, failures, replicas, operations = [], Counter(), Counter(), Counter()
    run_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    deadline = started + seconds
    cpu_start = time.process_time()
    async with httpx.AsyncClient(
        base_url=BASE,
        timeout=20,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    ) as client:

        async def worker(number):
            iteration = 0
            while time.perf_counter() < deadline:
                operation_start = time.perf_counter()
                action = "browse"
                try:
                    # Mixed: 60% catalog, 20% stock, 20% complete checkout (two gateway requests).
                    if workload == "mixed" and iteration % 5 == number % 5:
                        action = "checkout"
                        key = f"load-{run_id}-{number}-{iteration}"
                        response = await client.post(
                            f"/api/cart/carts/{key}",
                            json={"sku": "sku-1", "quantity": 1},
                        )
                        response.raise_for_status()
                        response = await client.post(
                            "/api/orders/checkout",
                            json={"order_id": key, "cart_id": key},
                        )
                        response.raise_for_status()
                        data = response.json()
                        assert data["status"] == "confirmed" and data["amount_cents"] == 4900
                        replicas[data["served_by"]] += 1
                    elif workload == "mixed" and iteration % 5 == (number + 1) % 5:
                        action = "stock"
                        response = await client.get("/api/inventory/stock/sku-1")
                        response.raise_for_status()
                        assert response.json()["quantity"] >= 0
                    else:
                        response = await client.get("/api/catalog/products")
                        response.raise_for_status()
                        assert len(response.json()["products"]) == 3
                    operations[action] += 1
                except (
                    httpx.HTTPError,
                    AssertionError,
                    KeyError,
                    ValueError,
                    TypeError,
                ) as exc:
                    label = (
                        f"HTTP {exc.response.status_code}"
                        if isinstance(exc, httpx.HTTPStatusError)
                        else type(exc).__name__
                    )
                    failures[label] += 1
                finally:
                    samples.append(time.perf_counter() - operation_start)
                iteration += 1

        await asyncio.gather(*(worker(i) for i in range(concurrency)))
    elapsed = time.perf_counter() - started
    return {
        "workload": workload,
        "concurrency": concurrency,
        "target_seconds": seconds,
        "elapsed_seconds": round(elapsed, 3),
        "operations": len(samples),
        "successful": dict(operations),
        "operations_per_second": round(len(samples) / elapsed, 2),
        "p50_ms": percentile(samples, 0.5),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
        "errors": sum(failures.values()),
        "error_details": dict(failures),
        "order_replicas": dict(replicas),
        "load_generator_cpu_seconds": round(time.process_time() - cpu_start, 3),
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10, 30, 60])
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30 or any(not 1 <= c <= 100 for c in args.concurrency):
        raise SystemExit("Bounds: 1–30 seconds per stage, 1–100 concurrent clients")
    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "base_url": BASE,
        "kind": "closed-loop local synthetic benchmark",
        "results": [],
    }
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    for workload in ("browse", "mixed"):
        for concurrency in args.concurrency:
            result = await stage(concurrency, args.seconds, workload)
            report["results"].append(result)
            (local / "benchmark.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
