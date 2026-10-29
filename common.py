"""Shared transport and instrumentation; each image has one business service."""

import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager
from threading import Lock

import httpx
import redis
from fastapi import FastAPI, HTTPException, Request
from psycopg import Error as DatabaseError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from pydantic import BaseModel, Field

INSTANCE = socket.gethostname()
SERVICE = os.environ["SERVICE_NAME"]
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
http = httpx.Client(
    timeout=float(os.getenv("HTTP_TIMEOUT_SECONDS", "5")),
    limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
)
db = None
cache = None


class Item(BaseModel):
    sku: str = Field(pattern=r"^sku-[123]$")
    quantity: int = Field(ge=1, le=10)


class Reservation(Item):
    order_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")


class Charge(BaseModel):
    order_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")
    amount_cents: int = Field(ge=1, le=10000000)


def make_app(schema_sql="", use_cache=False):
    @asynccontextmanager
    async def lifespan(app):
        global db, cache
        if schema_sql:
            db = ConnectionPool(
                os.environ["DATABASE_URL"],
                min_size=1,
                max_size=int(os.getenv("DB_POOL_SIZE", "8")),
                timeout=5,
                kwargs={"row_factory": dict_row},
            )
            db.wait(timeout=30)
            with db.connection() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SERVICE,))
                conn.execute(schema_sql)
        if use_cache:
            cache = redis.Redis.from_url(
                os.environ["REDIS_URL"],
                decode_responses=True,
                socket_timeout=3,
                socket_connect_timeout=3,
            )
            cache.ping()
        yield
        http.close()
        if db:
            db.close()
        if cache:
            cache.close()

    app = FastAPI(title=f"Commerce {SERVICE}", root_path=f"/api/{SERVICE}", lifespan=lifespan)
    counters = {"requests": 0, "errors": 0, "duration_seconds": 0.0}
    lock = Lock()

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Service-Instance"] = INSTANCE
            return response
        finally:
            if request.url.path not in {"/health", "/ready", "/metrics"}:
                elapsed = time.perf_counter() - start
                with lock:
                    counters["requests"] += 1
                    counters["errors"] += int(status >= 500)
                    counters["duration_seconds"] += elapsed
                logger.info(
                    json.dumps(
                        {
                            "service": SERVICE,
                            "instance": INSTANCE,
                            "method": request.method,
                            "path": request.url.path,
                            "status": status,
                            "duration_ms": round(elapsed * 1000, 2),
                        }
                    )
                )

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE, "instance": INSTANCE}

    @app.get("/ready")
    def ready():
        try:
            if db:
                with db.connection() as conn:
                    conn.execute("SELECT 1")
            if cache:
                cache.ping()
        except (DatabaseError, PoolTimeout, redis.RedisError):
            raise HTTPException(503, "Dependency unavailable") from None
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():
        with lock:
            return {"service": SERVICE, "instance": INSTANCE, **counters}

    return app


def remote(service, path, payload=None):
    url = os.environ[f"{service.upper()}_URL"] + path
    try:
        response = http.get(url) if payload is None else http.post(url, json=payload)
        if response.status_code >= 400:
            raise HTTPException(503, f"{service} rejected the operation")
        return response.json()
    except httpx.HTTPError:
        raise HTTPException(503, f"{service} unavailable; retry with the same order ID") from None
