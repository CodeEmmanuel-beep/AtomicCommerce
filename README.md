# 🚀 AtomicCommerce: High-Performance Multi-Tenant Engine

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)

A heavy-duty, service-oriented FastAPI backend architected for enterprise-scale multi-tenant commerce, strict data isolation, and exceptional performance under high concurrent load.

---

## 🏗️ Core Architecture & Event Flow

```text
[ Client Requests ]
       │
       ▼
 [ FastAPI / ASGI ] ──(Token Rotation / RBAC)──> [ Domain Services ]
       │                                                 │
       ├─(Async Queue Buffer)─> [ micro-batch task ]     ├─(Postgres Advisory Locks)
       │                              │                  │             │
       ▼                              ▼                  ▼             ▼
[ Redis Cache-Aside ]         [ Time-Series Logs ] ──> [ PostgreSQL Relational DB ]
       ▲                              ▲                        │
       │                              │                 (LISTEN / NOTIFY)
       │                      (Celery Workers)                 │
       │                              ▲                        ▼
       └───────(Pub/Sub Fan-Out)──────┴─────────── [ Shared Event Listener ]
```
---

## ✨ Features

*   **Multi-Tenant Marketplace**: Enforces absolute data isolation boundaries across independent vendor nodes, allowing separate brand networks to operate securely under a single, unified database schema.
*   **Stripe Subscriptions & Billing**: An asynchronous financial ledger core managing B2B/B2C multi-tier subscription states, trial/grace intervals, automated webhook processing, and credit proration.
*   **Warehouse Inventory**: Atomic stock engine enforcing strict concurrency controls to eradicate race conditions, warehouse drops, and product over-allocation.
*   **Real-Time Analytics**: High-signal metrics tracking layer engineered using low-overhead time-series ledger write logs to bypass expensive computational table lookups.
*   **Event-Driven Notifications**: Sub-millisecond data reactivity using native PostgreSQL `LISTEN/NOTIFY` structures combined with async task broadcasting pipelines.
*   **Redis Caching**: Highly efficient Cache-Aside strategy serving intense catalog reads, pricing structures, and storefront snapshots natively out of sub-millisecond memory stores.
*   **Celery Workers**: Offloads long-running application-level computations, metric compilations, transactional reporting, and automated subscription status checks out of the core request-response lifecycle.
*   **Media Uploads**: Chunk-streaming asset gateway that scans, validates MIME-types at the binary byte level, and writes straight to Supabase Storage Buckets to protect server memory.
*   **JWT Authentication**: Stateless verification workflow featuring Multi-Tenant Role-Based Access Control (RBAC) maps backed by a zero-reuse Refresh Token Rotation security policy.
*   **Customer Support Messaging (Ticketing System)**: A durable, multi-tenant ticketing and operational support routing layout. Tracks client issues with strict SLA expiration states, tenant boundary verification, and asynchronous agent assignment queues managed outside the core transaction paths.

---

## 📈 System Metrics & Scale

*   **100+ REST Endpoints**: Fully versioned, clean API paths covering multi-tenant billing portals, vendor marketplaces, real-time analytics dashboards, shopping carts, checkout logic, and advanced stock administration.
*   **20+ Service Modules**: Fully isolated domain modules following Service-Oriented Architecture (SOA) principles to eliminate circular imports and enforce a clear separation of concerns.
*   **20+ Database Tables**: A robust PostgreSQL relational schema complete with optimized composite indexes, write-ahead time-series logging, explicit cascading parameters, and foreign key boundaries.
*   **10+ Strict Enums**: Rigid state-machine tracking via Python/SQLAlchemy Enums (e.g., Subscription Status, Order states, Payment states, Account tiers, Analytics event types) ensuring type-safe processing at every interface.

---

## 💳 Enterprise Billing & Stripe Lifecycle Engine

The platform implements a production-grade, asynchronous financial ledger engine driven by a deeply integrated **Stripe API architecture** handling complex B2B/B2C payment lifecycles:

*   **Idempotent Webhook Processing**: A bulletproof webhook listening architecture protecting against duplicate events. State synchronization is guarded by unique event ledger validation to prevent double-processing.
*   **Comprehensive Subscription Lifecycles**: Fully handles automated provision state updates covering subscription creation, trial periods, grace periods, and clean sync on cancellations.
*   **Mid-Billing Cycle Tier Upgrades/Downgrades**: Formulated accurate proration charging structures, calculating immediate usage shifts and credit adjustments midway through subscription intervals seamlessly.
*   **One-Time Payments & Partial/Full Refunds**: Isolated transactional service endpoints engineered to settle explicit one-time order payments alongside secure refund handling logic that enforces programmatic ledger balance rollbacks.

---

## 📡 Transactional Streaming & Lifecycle Engine

The platform features an event-driven, low-latency infrastructure designed to capture high-signal commerce status updates and broadcast core operational events across multi-container instances:

*   **Reactive Lifecycle Triggers (LISTEN/NOTIFY)**: Millisecond data reactivity built on native PostgreSQL transactional layers. State mutations across critical transactional domains (e.g., successful orders, payment settling, subscription status changes, and membership upgrades) emit immediate async payloads via `NOTIFY`, completely bypassing application-level polling loops.
*   **Horizontal Redis Pub/Sub Fan-Out**: To scale across distributed ASGI container pools, a dedicated worker listener intercepts database notifications and pipes them into a Redis Pub/Sub distribution broker. This ensures multi-node synchronization, distributing lifecycle updates reliably to all connected tenant channels.
*   **Reactive Event Streaming (EventSourceResponse)**: Real-time user notifications, cart warnings, and order status tickers are fueled by a clean Server-Sent Events (SSE) protocol using `EventSourceResponse`. Clients maintain a lightweight, persistent, unidirectional HTTP connection for instantaneous event propagation.
*   **Buffered Event Ledger Persistence**: To protect database connection pools from high-concurrency spikes, transactional events pass through an in-memory micro-batching buffer. Events are held briefly in an execution queue and committed in optimized blocks, striking an ideal balance between low-latency network propagation and database performance.

---

## 🛠️ Engineering Highlights

*   **Asynchronous Architecture**: Built entirely on an ASGI worker pool loop using FastAPI and SQLAlchemy `AsyncSession`, enabling high-concurrency throughput without thread context-switching overhead.
*   **Atomic State Management**: Guarantees zero "Lost Updates" or inventory drift in high-throughput warehouse environments by implementing precise **PostgreSQL Advisory Locks** and row-level locking schemas (`FOR UPDATE`) across critical transaction paths.
*   **Read-Optimized Analytics Modules**: Offloads expensive aggregate queries (`SUM`, `AVG`) from core transaction tables on every API call by leveraging a read-optimized time-series ledger strategy. Efficiently buckets store performance, net revenue, conversion rates, and item sales velocity across customizable hourly, daily, and monthly windows.
*   **Analytics Performance Safeguards**: High-volume analytics lookups utilize explicit composite indexes on `(store_id, created_at DESC)` and are structured to avoid nested loop joins and sequential scans, verified via `EXPLAIN ANALYZE`.
*   **Stateless Deterministic Pagination**: Replaces erratic runtime execution setups like `setseed()` for randomized store and product discoveries. Instead, the layout uses an `md5(id || seed)` cryptographic sorting schema inside raw SQL strings to guarantee predictable, drift-free, page-by-page infinite scrolling across concurrent database lookups.
*   **High-Throughput Micro-Batching Buffer**: Mitigates heavy connection pool strain by routing intense ingestion feeds (e.g., streaming telemetry, notification logs) through an `asyncio.Queue` buffer. A background execution task drains the queue using a sliding-window chunk architecture—committing up to 100 records inside a single transaction or flushing automatically on a 100ms timeout threshold with a robust, structured retry policy.
*   **Redis Caching Framework**: Utilizes a strict **Redis Cache-Aside** strategy. High-demand product catalogs, pricing tiers, and pre-aggregated analytics endpoints return responses instantly, reducing total round-trip times (RTT) dramatically.
*   **Distributed Background Processing**: Offloads heavy out-of-process operations seamlessly. Uses **FastAPI BackgroundTasks** for lightweight, post-response I/O chores, and **Celery** workers for heavy architectural workloads, reporting loops, and automated ledger adjustments.
*   **Hardened Auth & Token Rotation**: Effortlessly isolates and enforces Multi-Tenant Role-Based Access Control (Admin vs. Staff permissions) via stateless JWTs. Implements **Refresh Token Rotation**—revoking and replacing refresh tokens on every single use—to block token-reuse vectors out of the box.
*   **Zero-Crash Media Pipeline & Orphan Cleanup**: Protects server memory under heavy asset workloads. Media uploads bypass container staging via a chunk-streaming pipeline that caps file sizes in real time, validates MIME-types at the binary byte layer, and streams files directly to **Supabase Storage Buckets**. Orphaned files are tracked and cleaned up automatically on database rollbacks.
*   **Ironclad Database Integrity**: Implements strict database-level unique constraints (preventing duplicate SKUs) and check constraints (ensuring quantities can never drop below zero), wrapped inside explicit transaction boundaries within the application logic for atomic rollbacks.

```jsonc
// Example Structured Performance Log
{"level": "INFO", "service": "billing-webhook", "event": "stripe_subscription_proration_success", "latency_ms": 48.2}
```

## 📁 Modular Service Architecture (SOA)
The system is divided into **20+ Domain-Specific Services**, ensuring zero circular dependencies and high maintainability for a 12,000+ line codebase.

```text
.
├── app/                        # Core Engine
│   ├── api/v1/                 # Versioned REST Routes
│   ├── auth/                   # JWT & Security Logic
│   ├── database/               # Async Engine & Session Management
│   ├── services/               # 12+ Business Logic Domains (Cart, Order, etc.)
│   ├── utils/                  # Redis, Fernet Encryption, Supabase Helpers
│   ├── main.py                 # App Entry Point
│   └── models_sql.py           # Centralized SQLAlchemy Models
├── migration/                  # Alembic Database Versioning
│   └── versions/               # Schema Evolution History
├── logs/                       # Per-Service Observability (Auth, Order, etc.)
├── Dockerfile                  # Production Containerization
├── docker-compose.yaml         # Local Environment Orchestration
├── alembic.ini                 # Migration Configuration
└── requirements.txt            # Dependency Management

```

---

🚀 Setup & Deployment
Clone & Environment: Copy .env.example to .env and configure your CIPHER_KEY and DATABASE_URL.
Docker Orchestration: docker-compose up --build to spin up FastAPI, Redis, and PostgreSQL.
Database Migrations: alembic upgrade head to sync the latest hardened schema.
