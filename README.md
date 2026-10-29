# Commerce demo — source package

Six independently containerized Python/FastAPI services, an Nginx gateway/load
balancer, PostgreSQL and Redis. This package contains the multi-service source contract for
portal-driven registration/deployment after platform activation. It does not register an application, create
a repository or deploy anything merely by being extracted.

## Portal registration

The new Aegis 0.5.0 source candidate supports this package through the
`python312-multiservice` profile. The configured live portal must first be upgraded
with reviewed stack workflow/chart pins and the updated GitOps worker/observer.
Until that activation, the installed single-service portal cannot deploy this ZIP.
The platform activation runbook is `aegis-platform/docs/multiservice.md`.

After activation, upload this ZIP through **Register application → Upload a new
app**. Detection reads `aegis-stack.json`, lists all six services and selects the
multi-service application type. Review public environment defaults and the
`commerce-demo-runtime` Secret reference. The gateway settings are port `8080`
and health path `/health`. The resource profile is `small` per container.

Review/install the proposed pinned stack CI/release callers using the authorized
maintainer workflow. Submit registration, complete catalog/target review and have
the operator provision runtime credentials. Once a validated complete release is
available, select it and confirm DEV deployment in the portal. Uploading alone
never registers or deploys the application.

The stack manifest is the platform contract. Compose is an optional local
reference; the portal does not execute Compose or source-owned lifecycle commands.

## Services

| Service | Responsibility | State |
| --- | --- | --- |
| catalog | Seeded product list and prices | PostgreSQL + Redis cache |
| inventory | Atomic stock reservations, idempotent by order ID | PostgreSQL |
| cart | One line item per cart, explicit replacement and expiry | Redis |
| orders | Checkout orchestration and immutable checkout intent | PostgreSQL |
| payments | Idempotent simulated charge ledger | PostgreSQL |
| notifications | Idempotent notification event ledger | PostgreSQL |

`gateway/nginx.conf` routes `/api/{service}/...`. The Compose definition specifies
two order replicas; service DNS distributes gateway connections between them.
Each runtime Python image contains `common.py` and only its selected business service.
Build it with `docker build --build-arg SERVICE=catalog -t commerce-catalog .`,
substituting each service name. No common database tables are read directly by a
different business service; communication uses HTTP. For this small lab the
PostgreSQL instance and database credential are shared across the service tables.

The root endpoint returns topology information; this is an API demo, without a
shopping storefront. Interactive API docs are at `/api/{service}/docs`.

## Environment configuration

| Variable | Purpose |
| --- | --- |
| SERVICE_NAME | Identity of the service in each image/runtime |
| DATABASE_URL | PostgreSQL DSN; inject as a secret |
| REDIS_URL | Authenticated Redis URL; inject as a secret |
| CATALOG_URL, INVENTORY_URL, CART_URL | Internal service addresses |
| ORDERS_URL, PAYMENTS_URL, NOTIFICATIONS_URL | Internal service addresses |
| DB_POOL_SIZE | Connections per process, default 8 |
| HTTP_TIMEOUT_SECONDS | Downstream request timeout, default 5 |
| CACHE_TTL_SECONDS | Product cache lifetime, default 30 |
| CART_TTL_SECONDS | Cart lifetime, default 3600 |

For Compose, `.env.example` lists `DB_PASSWORD`, `REDIS_PASSWORD` and gateway port
settings. Use newly generated URL-safe hex passwords. Actual values belong only
in an ignored `.env` file or the target secret manager. The Aegis uploader excludes
`.env*` files, so this template is documentation, not runtime secret injection.
PostgreSQL and Redis have persistent volumes and no published host ports. Only
the gateway binds to loopback. There is no application authentication; keep this
development app private. Payments never charge money and notifications never
send email or SMS.

## Behavior and limitations

Create a cart using `POST /api/cart/carts/demo-1` with
`{"sku":"sku-1","quantity":2}`. Submit
`POST /api/orders/checkout` with
`{"order_id":"order-1","cart_id":"demo-1"}`. Retry with the same order ID after
a timeout. Concurrent retries share one reservation, charge and notification.
Reusing an order ID with a different cart returns 409.

Checkout stores the cart and price snapshot before downstream side effects. A
dependency failure returns 503 and leaves a pending order; retrying the same ID
resumes the snapshot. This lab has no automatic saga compensation, pending-order
expiry or background recovery. Tables are created at service startup under a
database lock; a production profile should use explicit migrations and separate
least-privilege database identities.

`scripts/verify.py` checks six services, checkout, validation, concurrent retries
and both order replicas against loopback port 18180. `scripts/benchmark.py` is a
bounded load generator for later use after you deploy; it does not deploy.
Its mixed workload is 60% catalog, 20% stock and 20% checkout by operation count.
Each checkout operation includes cart creation plus checkout, so operations/sec
and HTTP requests/sec are different measurements. No production capacity claim
is made from local checks.

The earlier direct local test deployment was removed after the workflow was
clarified. No portal registration or deployment has been performed for this app.
