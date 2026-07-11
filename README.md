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

### Domain Services

### 1. auth_service

Handles user provisioning, tenant authentication lifecycles, and cryptographic authorization mechanics.

* **Registration Engine**: Validates emails and enforces a blacklisted registry of reserved terms (root, admin, system) alongside spatial restrictions. Normalizes all incoming username patterns via low-level SQL transformations (func.lower(func.trim())) to avoid duplicate variations.

* **Security & Token Rotations**: Provisions stateless asymmetric JWT authorization headers alongside isolated HttpOnly, SameSite=Lax, and Secure cookie-based refresh tokens. Implements immediate Refresh Token Rotation on every invocation to block token-reuse vectors out of the box.

* **Access Control Policies**: Implements strict administrative tenancy checks, preventing standard users or foreign node objects from modifying user access flags while restricting structural owners from self-redesignation blocks.

📐 **Architectural Decisions & Safeguards**:
Decoupled Asset Upload Pipeline: Profile picture uploading is explicitly separated from the core user registration transaction path. Because media handling relies on external I/O operations to Supabase Storage Buckets, decoupling this ensures network latencies or third-party cloud failures never cause a fatal drop during a user's initial onboarding block.

* **Memory-Safe Asset Capping**: Profile media uploads leverage an asyncio chunked streaming processor that enforces a hard 5MB size cap in flight and performs strict binary byte-level magic number parsing to restrict files exclusively to jpeg, png, and webp.

* **Transactional Orphan Purging**: If a database transaction fails after a media payload has been written to the bucket, an automated cleanup helper (cleaned_up) intercepts the exception context, rolling back the database state and issuing a delete vector to the storage engine to keep the asset bucket zero-orphan compliant.

### JSON Response

```jsonc
{
  "status": "success",
  "message": "login successful",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJuYW1lIjoiQ2VuYSIsInN1YiI6ImpheWNlZSIsInVzZXJfaWQiOjMsIm5hdGlvbmFsaXR5IjoiQW1lcmljYSIsInJvbGUiOiJ1c2VyIiwidHlwZSI6ImFjY2Vzc190b2tlbiIsImV4cCI6MTc4Mzc3NTQzN30.FdL6UEg5WqkcE-P6IrUsE_bq0_xv0eE8gqax2PK3Meo",
    "token_type": "Bearer"
  }
}
```


---

### 2. Cart Service

Manages active shopping cart lifecycles, item allocations, state synchronizations, and volatile cache invalidations across individual store boundaries.

* **Pessimistic Concurrency Layout**: Implements explicit row-level locking via SQLAlchemy's `.with_for_update()` when querying active `Cart` or `CartItem` schemas during modifications (`add_item_to_cart`, `edit_quantity`, `update_cart`, `delete_one`). This freezes the target row states directly inside the PostgreSQL engine to prevent race conditions during simultaneous catalog interactions.


* **Availability & Constraint Verification**: Validates storefront existence (`Store.is_deleted.is_(False)`), multi-table joins ensuring item stock capacity (`Inventory.stock_quantity >= quantity`), availability markers (`Product.product_availability == "available"`), and enforces a hard ceiling of **30 unique line items** per cart configuration.


* **Versioned Caching Topology**: Utilizes a split key caching format incorporating a dynamic version string (`cart_key` via `cache_version`) to manage localized user lookups under a hardcoded `ttl=3600` (1 hour). Write operations and state modifications invoke the `cart_invalidation(user_id)` routine to flush stale records synchronously.



📐 **Architectural Decisions & Safeguards**:

* **All-or-Nothing Mutation Guarantees**: Encapsulates all data alterations (`db.add`, `db.delete`, quantity deltas) inside explicit `try...except` transaction wrappers capturing `IntegrityError` and global exceptions. Any state mutation block failure invokes an immediate `await db.rollback()` before re-raising errors to completely shield the transactional tracking ledger from partial updates or database drift.


* **Auto-Cleaning Sanitize Routines (`update_cart`)**: Features a localized self-healing pipeline that parses an active cart, detects items matching deleted products (`item.product.is_deleted`) or items exceeding current warehouse numbers (`stock_quantity < item.quantity`), and executes atomic bulk deletes (`delete(CartItem).where(CartItem.id.in_(...))`) to reconcile states prior to billing handoffs.

### JSON Response


```jsonc
{
    "status": "success",
    "message": "cart",
    "data": {
        "cart": {
            "id": 13,
            "total_quantity": 74.0,
            "created_at": "2026-05-31T15:12:51.117996+00:00"
        },
        "cart_item": {
            "items": [
                {
                    "id": 22,
                    "product": {
                        "id": 6,
                        "product_name": "Infinix",
                        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/939580eb-6b49-4c82-9829-b2880fecf540_Screenshot_2026-01-05_203517.png",
                        "product_price": 950.0
                    },
                    "quantity": 7
                },
                {
                    "id": 23,
                    "product": {
                        "id": 5,
                        "product_name": "Samsung",
                        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/ae73fe88-8972-4fc0-b68d-784a17a8d484_Screenshot_2026-01-05_203517.png",
                        "product_price": 950.0
                    },
                    "quantity": 9
                },
                {
                    "id": 24,
                    "product": {
                        "id": 4,
                        "product_name": "Power Bank",
                        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/bb87c9fb-bd60-4340-a6e5-ad2e6bfd82df_Screenshot_2026-01-05_203517.png",
                        "product_price": 200.0
                    },
                    "quantity": 3
                },
                {
                    "id": 25,
                    "product": {
                        "id": 3,
                        "product_name": "i Pad",
                        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
                        "product_price": 1000.0
                    },
                    "quantity": 25
                },
                {
                    "id": 26,
                    "product": {
                        "id": 2,
                        "product_name": "Mac Book",
                        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
                        "product_price": 1200.0
                    },
                    "quantity": 25
                },
                {
                    "id": 27,
                    "product": {
                        "id": 1,
                        "product_name": "HP Laptop",
                        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
                        "product_price": 650.0
                    },
                    "quantity": 5
                }
            ],
            "pagination": {
                "page": 1,
                "limit": 10,
                "total": 6
            }
        }
    }
}
```


---

### 3. Category Service

Governs the product classification taxonomies, structural naming constraints, and administrative access controls of the global platform directory.

* **Role-Based Access Enforcement**: Implements explicit security checks at the API routing boundary, blocking execution unless the verified `user_id` resolves to a `User` record holding an elevated role context of either `["Admin", "Owner"]`. Standard buyers or unprivileged accounts are rejected with strict 403 Forbidden exceptions prior to executing mutations.


* **Normalized Pattern Deduplication**: Avoids naming variations and duplicate entry injection by normalizing input names (`" ".join(name.split())`). Checks strings against database categories using low-level SQL regex and formatting transformations:



$$func.lower(func.trim(func.regexp_replace(Category.name, r"\s+", "", "g")))$$



This collapses all inner whitespace sequences into zero-space blocks, neutralizing character-spacing bypass attacks at the engine layer.


* **Paginated Selection Engine**: Surfaces non-deleted categories (`~Category.is_deleted`) by compiling a standalone row-count aggregate query from a isolated database subquery statement (`select(func.count()).select_from(stmt.subquery())`). This isolates metric counts from limit-offset slicing variables to output correct total tracking fields.



📐 **Architectural Decisions & Safeguards**:

* **Audit-Safe Deletion Topology**: Avoids destructive database record purging (`DELETE`) to maintain structural history across product line items and historical catalogs. The delete workflow executes a state modification by setting a soft-delete flag (`Category.is_deleted = True`), immediately isolating the targeted entry from subsequent retrieval queries while maintaining database relational integrity.


* **Encapsulated Unit-of-Work Fail-Safes**: Runs write actions (`db.add`) and state modifications inside isolated `try...except` contexts capturing `IntegrityError` and global exception boundaries. Any database block breakdown triggers an immediate, synchronous `await db.rollback()`, ensuring uncommitted modifications unwind to protect the directory metadata from corruption.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "categories",
  "data": {
    "items": [
      {
        "id": 1,
        "name": "Toys & Baby Products"
      },
      {
        "id": 2,
        "name": "Books & Stationery"
      },
      {
        "id": 3,
        "name": "Sports & Outdoors"
      },
      {
        "id": 4,
        "name": "Electronics & Technology"
      },
      {
        "id": 5,
        "name": "Fashion"
      },
      {
        "id": 6,
        "name": "Home & Living"
      },
      {
        "id": 7,
        "name": "Groceries"
      },
      {
        "id": 8,
        "name": "Automotive"
      },
      {
        "id": 9,
        "name": "Health & Wellness"
      },
      {
        "id": 14,
        "name": "Beauty & Personal Care"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 10
    }
  }
}
```

---

### 4. Customer Support Service

Governs multi-tenant customer care lifecycles, load-balanced ticket allocation routing, asynchronous storage engine integration, and message-state indicators.

* **Load-Balanced Support Allocation**: Employs an automated, aggregate load-routing query to detect and assign incoming help requests to active, qualified store personnel or `["Owner", "customer_care"]` operators. The engine groups unresolved entries via an inner subquery (`TicketStatus.open`, `TicketStatus.in_progress`), matching them against parent structures via an outer join that filters for active states (`User.is_active.is_(True)`). It then routes the ticket to the least-burdened operator using a dynamic ascending null-coalesced ordering sequence:

$$func.coalesce(subq.c.cnt, 0).asc()$$


* **Dual-Perspective Message Slicing & Indicators**: Manages role-filtered lookups (`customer_view` vs. `support_view`) using programmatic message-state synchronizations. Queries compile unified conversation strings (`func.concat(func.least(...), ":", func.greatest(...))`) while tracking unread volumes via subquery aggregations. When lists are pulled, the endpoint triggers selective bulk update records (`update(Messaging).where(...)`) to switch unseen flags (`seen=True, delivered=True`) for incoming messages natively at the database level.
* **Logical Partitioned Thread Erasures**: Restricts entry removal workflows until the parent status field resolves to `TicketStatus.closed`. Bulk messaging erasures employ conditional expressions (`case`) inside atomic sql updates (`update(Messaging)`) to switch delete vectors (`sender_deleted`, `receiver_deleted`) based on the active agent perspective, completely separating the thread viewpoints without breaking compliance logging balances.

📐 **Architectural Decisions & Safeguards**:

* **Decoupled Multi-State Orphan Purging**: Media attachments handle multi-tier file asset additions using async external storage uploads (`upload_photo_helper`) backed by Supabase buckets before database entries are written. If a subsequent transaction block drops due to database errors or runtime interruptions, an exception handler overrides execution, calls a cleanup block (`cleaned_up`) to target and purge the newly uploaded storage file path, and executes an `await db.rollback()` to prevent orphaned file assets.
* **Strict Concurrency Thread Fencing**: Intercepts ticket update threads by applying row-level locks (`with_for_update()`) on targeted parent rows. This layer blocks cross-concurrency edits, protects resolution status changes (`TicketStatus.closed`), maintains structural integrity across temporal updates (`ticket.updated_at`), and handles inactivity locks (blocking closures until 2 days post-interaction) securely.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "your messages",
  "data": {
    "conversations": [
      {
        "conversation_id": "3:11",
        "store_photo": "634e8496-7149-466e-98e3-d8e4bab86658_Screenshot_2025-11-25_140924.png",
        "customer_photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/c7b4f5cd-11d4-45ae-b1f0-5159d1f4286d_passport_white_background.jpeg",
        "customer_support": "John Cena",
        "customer": "Calvin Klein",
        "ticket_id": 1,
        "ticket_status": "closed",
        "messages": [
          {
            "id": 10,
            "sender": "customer_support",
            "message": "we await your patronage sir",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-08T17:36:07.062920Z"
          },
          {
            "id": 9,
            "sender": "customer",
            "message": "okay, when I am ready, I will come ",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-08T17:28:35.411178Z"
          },
          {
            "id": 7,
            "sender": "customer_support",
            "message": "sorry sir for the late reply, yes we do sell HP of the best quality! We await your patronage",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-07T14:01:30.750281Z"
          },
          {
            "id": 6,
            "sender": "customer",
            "photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/sign/customer_support/b4400e0a-bc62-40e6-b1ab-c64fcca74a67_Screenshot_2026-07-07_143856.png?token=eyJraWQiOiJzdG9yYWdlLXVybC1zaWduaW5nLWtleV8xMjQ2ODE4MC0zMjBmLTQ1M2EtOWNmZS1kYjZkMDg4MTJiY2EiLCJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJjdXN0b21lcl9zdXBwb3J0L2I0NDAwZTBhLWJjNjItNDBlNi1iMWFiLWM2NGZjY2E3NGE2N19TY3JlZW5zaG90XzIwMjYtMDctMDdfMTQzODU2LnBuZyIsInNjb3BlIjoiZG93bmxvYWQiLCJpYXQiOjE3ODM3NzE4OTksImV4cCI6MTc4Mzc3OTA5OX0.wiLtO4kBLQvv2Kp36ABHs3lOn4HLmMd4MfsWAHxc5Ao",
            "message": "I have sent you a message for hours now and no reply, do well to reply me!",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-07T13:50:15.390699Z"
          },
          {
            "id": 1,
            "sender": "customer",
            "photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/sign/customer_support/07cf2168-cabe-4546-bbb4-231dfb36c09c_project1.jpg?token=eyJraWQiOiJzdG9yYWdlLXVybC1zaWduaW5nLWtleV8xMjQ2ODE4MC0zMjBmLTQ1M2EtOWNmZS1kYjZkMDg4MTJiY2EiLCJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJjdXN0b21lcl9zdXBwb3J0LzA3Y2YyMTY4LWNhYmUtNDU0Ni1iYmI0LTIzMWRmYjM2YzA5Y19wcm9qZWN0MS5qcGciLCJzY29wZSI6ImRvd25sb2FkIiwiaWF0IjoxNzgzNzcxODk5LCJleHAiOjE3ODM3NzkwOTl9.MpWacrFZHO0AVyI42hyZKPCVLu5FBO57TONNhb-Gaeg",
            "message": "Please is your HP reliable, I dont want to purchase something I would later regret",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-06T15:27:03.803069Z"
          }
        ]
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 5
    }
  }
}
```

---

### 5. Delivery Address Service

Governs customer shipping coordinates, order-address bindings, strict active fulfillment constraints, and multi-tenant read-through cache topologies.

* **Pessimistic Concurrency Boundings**: Enforces row-level isolation using explicit database locks (`.with_for_update()`) when allocating or altering address targets against active, non-deleted merchant orders (`Order.id == order_id`, `~Order.order_delete`). This prevents underlying fulfillment criteria from drifting over concurrent mutation workflows.


* **Distinct Deduplicated Aggregations**: Queries stored addresses using explicit `.distinct()` constraints and calculates total volume records by executing a matching distinct-count modifier inside the SQL aggregate function:



$$func.count(func.distinct(Address.id))$$



This decouples page offset slicing from structural matching rows to calculate exact pagination properties.


* **Fulfillment Guardrail Enforcements**: Protects active supply chains by blocking address removal calls if any linked order record deviates from completed or terminated transaction boundaries. The module iterates through preloaded tracking properties and drops the deletion attempt with a 400 Bad Request error if a linked checkout falls outside of `[OrderStatus.cancelled, OrderStatus.delivered, OrderStatus.shipped]`.



📐 **Architectural Decisions & Safeguards**:

* **Decoupled Async Cache Eviction**: Offloads transactional execution delays from the main server thread by passing cache invalidations (`order_invalidation`, `order_address_invalidation`) to an asynchronous background task queue (`background_task.add_task`). This guarantees that cache purges run completely out-of-band only after an engine transaction commit successfully clears.


* **Dual-Layer Mutation Rollbacks**: Encapsulates all transactional changes—such as setting logical delete indicators (`address.is_deleted = True`) or updating array fields (`order.delivery_address`)—inside explicit, error-trapped database blocks. Any constraint collision or backend driver failure triggers an immediate `await db.rollback()` to protect the underlying order tracking parameters from partial execution fragments.


### JSON Response

```jsonc
{
    "status": "success",
    "message": "delivery addresses",
    "data": {
        "items": [
            {
                "id": 4,
                "street": "zone 2, Wuse",
                "city": "Abuja",
                "state": "FCT",
                "country": "Nigeria"
            },
            {
                "id": 6,
                "street": "Gwarinpa",
                "city": "Abuja",
                "state": "Federal Capital Territory",
                "country": "Nigeria"
            }
        ],
        "pagination": {
            "page": 1,
            "limit": 10,
            "total": 2
        }
    }
}
```

---

### 6. Inventory Service

Governs warehouse stock counts, catalog item allocations, multi-tenant administrative permission checks, and product availability synchronizations.

* **Multi-Tenant Authorization Isolation**: Executes triple-boolean expression lookups during creation workflows, validating whether the requesting `user_id` is bound to the target `store_id` via `store_owners` or `store_staffs` relation records, while verifying that the product exists and is active (`~Product.is_deleted`). This prevents cross-tenant spoofing vectors at the query-execution layer.


* **Pessimistic Locking & Volatility Alignment**: Implements database row-level isolation via SQLAlchemy's `.with_for_update()` on target inventory records during updates and structural modifications. It locks matching records to secure high-concurrency writes while utilizing preloaded execution trees (`selectinload(Inventory.product)`).


* **Dual-Entity State Management**: Features automatic status modification hooks during quantity adjustments. When stock levels are increased via an update mutation, the module evaluates the nested product metadata; if the linked catalog item is flagged as `"out_of_stock"`, the system resets its marketplace state back to `"available"` inline with the transaction.



📐 **Architectural Decisions & Safeguards**:

* **Volatile Caching Hierarchies**: Deploys a tiered distributed caching architecture using short-lived keys (`inventory:store_id:inventory_id`) holding a hardcoded `ttl=30` (30 seconds) for singular profiles, alongside paginated lists running on a `ttl=60` (1 minute) lifespan. This structure balances immediate public catalog discoverability with minimal stale-data margins.


* **Audit-Safe Purging Topology**: Enforces strict historical integrity across ledger transactions by overriding destructive SQL commands with a logical soft-delete marker (`inventory.is_deleted = True`). The execution flow wraps all database mutations inside explicit `try...except` contexts that issue immediate `await db.rollback()` invocations on intercepting `IntegrityError` or runtime exceptions to block data pollution.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "store inventory",
  "data": {
    "items": [
      {
        "id": 1,
        "product": {
          "id": 1,
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
          "product_name": "HP Laptop"
        },
        "stock_quantity": 39,
        "last_updated": "2026-07-03T16:59:18.004687Z"
      },
      {
        "id": 2,
        "product": {
          "id": 2,
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
          "product_name": "Mac Book"
        },
        "stock_quantity": 261,
        "last_updated": "2026-07-03T16:59:18.004687Z"
      },
      {
        "id": 3,
        "product": {
          "id": 3,
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
          "product_name": "i Pad"
        },
        "stock_quantity": 50,
        "last_updated": "2026-06-27T14:02:03.431488Z"
      },
      {
        "id": 4,
        "product": {
          "id": 4,
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/bb87c9fb-bd60-4340-a6e5-ad2e6bfd82df_Screenshot_2026-01-05_203517.png",
          "product_name": "Power Bank"
        },
        "stock_quantity": 0,
        "last_updated": "2026-06-15T18:42:49.032282Z"
      },
      {
        "id": 6,
        "product": {
          "id": 6,
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/939580eb-6b49-4c82-9829-b2880fecf540_Screenshot_2026-01-05_203517.png",
          "product_name": "Infinix"
        },
        "stock_quantity": 82,
        "last_updated": "2026-06-15T18:42:49.032282Z"
      },
      {
        "id": 5,
        "product": {
          "id": 5,
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/ae73fe88-8972-4fc0-b68d-784a17a8d484_Screenshot_2026-01-05_203517.png",
          "product_name": "Samsung"
        },
        "stock_quantity": 60,
        "last_updated": "2026-06-07T20:49:05.250295Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 6
    }
  }
}
```

---

### 7. Membership Service

Governs store loyalty memberships, payment plan tiers, cascading subscription updates, multi-tenant administrative lookups, and lifecycle state transitions.

* **Dual-Entity Intent Architecture**: Coordinates nested tables during onboarding workflows by validating structural configurations (`membership_type`, `activation_type`) prior to persistence. It flushes a new parent record (`Membership`) to generate an automated unique key, maps it instantly into a child reference (`Subscription`), and evaluates configuration flags to conditionally apply pricing tiers:


* **One-Time Transitions**: Maps flat costs from configuration values (`settings.Standard_Price`, `settings.Regular_Price`, `settings.Premium_Price`) while explicitly setting the remote payment processor marker to `None`.


* **Recurring Subscriptions**: Injects dedicated subscription tokens (`settings.Standard`, `settings.Regular`, `settings.Premium`) while leaving flat prices blank to delegate variable capture to external billing layers.


* **Pessimistic Isolation and Lock Bounds**: Isolates membership modifications using explicit table constraints (`.with_for_update(of=Membership)`) across cross-cutting outer joins. This strategy shields active metadata lines from concurrent state conflicts while allowing un-indexed tracking tables to safely receive incoming edits.


* **Common Table Expression (CTE) Security Gateways**: Validates merchant system updates using conditional inline queries (`.cte("portal_access")`). The framework cross-references incoming identities using multi-tenant permission gates (`store_owners` or `store_staffs`) within a separate query execution step, preventing horizontal escalation before applying the main transaction update.



📐 **Architectural Decisions & Safeguards**:

* **Version-Keyed Key Invalidation**: Integrates a versioned distributed-caching design (`cache_version("member_key")`) to manage multi-tenant paginated view pipelines. Modifying an active account updates the central tracking version, rendering cached lists stale across the entire storefront application space without necessitating targeted scans of arbitrary user arrays.


* **Polymorphic Purging Inversions**: Implements two separate logical erasure modes within a single endpoint. If executed with an administrative key, the filter targets explicit membership row records (`Membership.id == membership_id`); if called via a consumer context, it falls back to a tenant user match (`Membership.user_id == user_id`), updating historical markers (`delete_date`), clearing visibility properties, and queuing asynchronous out-of-band cache flushes securely.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "active_members",
  "data": {
    "items": [
      {
        "user": {
          "id": 8,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
          "first_name": "Jacob",
          "middle_name": "Glory",
          "surname": "Israel"
        },
        "membership_type": "Premium",
        "start_date": "2026-06-10T14:01:54.207191Z"
      },
      {
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "membership_type": "Premium",
        "start_date": "2026-06-11T13:05:12.233872Z"
      },
      {
        "user": {
          "id": 9,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/31e443bd-07d8-419f-95c0-555a692ffdef_WIN_20250922_05_39_57_Pro.jpg",
          "first_name": "Ben",
          "surname": "Ek"
        },
        "membership_type": "Regular",
        "start_date": "2026-06-19T16:51:51.122821Z"
      }
     ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 3
    }
  }
}
```

---

### 8. Notification Service

Governs user alerts, real-time Server-Sent Events (SSE) stream delivery, automated read-receipt synchronization, and context-aware messaging for active or soft-deleted stakeholders.

* **Real-Time Reactive Streaming**: Establishes live HTTP event streaming connections utilizing an async event mechanism (`EventSourceResponse`) bound to an underlying key-value pub/sub structure (`notifications_stream(user_id)`). To clear communication lines before connection tracking mounts, it performs an immediate out-of-band invalidation loop (`await notification_invalidation(user_id)`).


* **Polymorphic State Labeling**: Evaluates sender account flags during relational query processing (`select(Notification, User)`) to adjust text outputs dynamically. If the actor's profile is active (`sender.is_active`), it interpolates the complete entity signature; otherwise, it appends a structural fallback marker (`"deleted user"`).


* **Atomic State Mutators**: Pairs read-heavy retrievals with bulk state mutations by updating data properties in a single transaction lifecycle. Upon gathering message payloads, the engine executes an atomic criteria update (`update(Notification).where(...)`) to shift target unread statuses (`is_read=True`) across the data model.



📐 **Architectural Decisions & Safeguards**:

* **Volatile Query Slicing**: Implements strict horizontal pagination limits (`.limit(30)`) on simple index looks, paired with calculated row offsets (`(page - 1) * limit`) inside full ledger lists. This isolates high-volume notification entries, ensuring fast response times while running on short caching lifespans (`ttl=60`).


* **Implicit Commit Recovery**: Isolates relational joins and state-flag updates within protected execution blocks. Any unexpected database driver failure or mid-stream disconnection stops transaction processing before executing `await db.commit()`, keeping the primary unread counters accurate and consistent.


### JSON RESPONSE

```jsonc
{
  "status": "success",
  "message": "notifications",
  "data": [
    {
      "id": 473,
      "notification": "New payment for order 27 by Jacob Israel",
      "status": "REFUNDED",
      "time_of_op": "2026-06-07T15:32:15.799288Z",
      "created_at": "2026-07-10T13:00:37.823782Z"
    },
    {
      "id": 471,
      "notification": "New payment for order 27 by Jacob Israel",
      "status": "REFUNDED",
      "time_of_op": "2026-06-07T15:32:15.799288Z",
      "created_at": "2026-07-10T12:31:27.405041Z"
    },
    {
      "id": 469,
      "notification": "New payment for order 27 by Jacob Israel",
      "status": "REFUNDED",
      "time_of_op": "2026-06-07T15:32:15.799288Z",
      "created_at": "2026-07-10T12:27:47.301080Z"
    },
    {
      "id": 467,
      "notification": "New payment for order 27 by Jacob Israel",
      "status": "REFUNDED",
      "time_of_op": "2026-06-07T15:32:15.799288Z",
      "created_at": "2026-07-10T12:24:40.880928Z"
    },
    {
      "id": 465,
      "notification": "New payment for order 35 by Sandra Eke",
      "status": "SUCCESS",
      "time_of_op": "2026-07-03T17:04:18.793700Z",
      "created_at": "2026-07-03T17:08:44.806081Z"
    },
    {
      "id": 463,
      "notification": "New payment for order 35 by Sandra Eke",
      "status": "PENDING",
      "time_of_op": "2026-07-03T17:04:18.793700Z",
      "created_at": "2026-07-03T17:04:25.292070Z"
    },
    {
      "id": 461,
      "notification": "New order by Sandra Eke",
      "time_of_op": "2026-07-03T16:59:19.581017Z",
      "created_at": "2026-07-03T16:59:24.332649Z"
    },
    {
      "id": 458,
      "notification": "New cart by Sandra Eke",
      "time_of_op": "2026-07-03T16:58:15.940680Z",
      "created_at": "2026-07-03T16:58:20.388747Z"
    },
    {
      "id": 452,
      "notification": "New review by James John",
      "time_of_op": "2026-07-01T20:51:05.424142Z",
      "created_at": "2026-07-01T20:51:06.936314Z"
    },
    {
      "id": 449,
      "notification": "New review by James John",
      "time_of_op": "2026-07-01T20:41:56.194904Z",
      "created_at": "2026-07-01T20:41:59.315063Z"
    },
    {
      "id": 446,
      "notification": "New review by Jacob Israel",
      "time_of_op": "2026-07-01T13:22:40.508280Z",
      "created_at": "2026-07-01T13:22:42.773756Z"
    },
    {
      "id": 438,
      "notification": "New payment for order 34 by James John",
      "status": "SUCCESS",
      "time_of_op": "2026-06-27T14:07:19.915800Z",
      "created_at": "2026-06-27T14:09:47.248934Z"
    },
    {
      "id": 436,
      "notification": "New payment for order 34 by James John",
      "status": "PENDING",
      "time_of_op": "2026-06-27T14:07:19.915800Z",
      "created_at": "2026-06-27T14:07:27.509337Z"
    },
    {
      "id": 434,
      "notification": "New order by James John",
      "time_of_op": "2026-06-27T13:39:35.793526Z",
      "created_at": "2026-06-27T13:39:41.009724Z"
    },
    {
      "id": 431,
      "notification": "New cart by James John",
      "time_of_op": "2026-06-27T13:30:09.870785Z",
      "created_at": "2026-06-27T13:30:14.071347Z"
    },
    {
      "id": 428,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": true,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T18:25:02.277476Z"
    },
    {
      "id": 425,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T18:14:08.184561Z"
    },
    {
      "id": 422,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T18:13:42.936710Z"
    },
    {
      "id": 419,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T18:04:09.681682Z"
    },
    {
      "id": 416,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T18:01:40.030678Z"
    },
    {
      "id": 413,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:45:46.961475Z"
    },
    {
      "id": 410,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:45:19.563524Z"
    },
    {
      "id": 407,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:42:15.867443Z"
    },
    {
      "id": 404,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": true,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:41:43.411335Z"
    },
    {
      "id": 401,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": true,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:25:00.848939Z"
    },
    {
      "id": 398,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:19:28.276230Z"
    },
    {
      "id": 395,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T17:14:29.385717Z"
    },
    {
      "id": 392,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": true,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T16:59:01.366514Z"
    },
    {
      "id": 389,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": true,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T16:25:00.652814Z"
    },
    {
      "id": 386,
      "notification": "New membership by Ngozi Eke",
      "membership_type": "Premium",
      "is_active": false,
      "is_deleted": false,
      "time_of_op": "2026-06-16T11:37:40.137671Z",
      "created_at": "2026-06-25T16:24:50.564789Z"
    }
  ]
}
```

---


### 9. Order Service

Governs multi-tenant consumer checkout lifecycles, precision tax and discount computations, distributed transactional inventory reservation fencing, and session-expiration gatekeeping loops.

* **Pessimistic Stock Reservation & Inventory Fencing**: Isolates transactional order items against high-concurrency races by locking target records inside explicit database blocks using `.with_for_update()`. It validates matching catalog entries (`Inventory.product_id.in_(product_ids)`) and rejects checkout requests with a 400 Bad Request exception if a cart item violates availability thresholds, exhibits a cross-tenant store mismatch, or runs into insufficient warehouse quantities.


* **Precision Fixed-Point Financial Math**: Calculates pricing properties, loyalty discounts, shipping variables, and tax liabilities utilizing precise fixed-point decimal arithmetic (`Decimal`). Totals are normalized using standard financial rounding rules (`.quantize(Decimal("0.01"))`) to prevent precision drift across tax tiers and membership matrix rules:



```math
total\_amount = (subtotal + shipping\_fee + tax\_amount) - discount\_amount
```



* **State-Driven Multi-Tier Expiration Gates**: Evaluates transactional session windows using dynamic temporal thresholds (`created_at` or `re_order_time` checkpoints). If a buyer navigates to the payment portal after a transaction boundary lapses (e.g., more than 1 hour post-creation or 30 minutes post-reactivation), the engine triggers an automatic cleanup phase—marking the checkout status as `OrderStatus.cancelled`, executing inventory restock hooks (`restore_inventory`), and soft-deleting the expired session record.



📐 **Architectural Decisions & Safeguards**:

* **Atomic Cart Invalidation Isolation**: Couples order creation tracking with atomic, non-blocking checkouts by implementing conditional backend modifications (`update(Cart).values(check_out=True).returning(Cart.id)`). If the database query yields an empty row pattern, the system short-circuits the pipeline with a 409 Conflict exception to block double-checkout exploits across concurrent request paths.


* **Dual-Perspective Cache Eviction Trees**: Protects data freshness by running explicit, out-of-band invalidation clusters (`order_invalidation`, `cart_invalidation`) inside concurrent event threads (`asyncio.gather`). It pairs these background steps with shared version tags (`cache_version("order_key")`) to render entire storefront cache fragments invalid instantly across global cluster profiles when structural changes occur.


### JSON Response

```jsonc
{
    "status": "success",
    "message": "orders",
    "data": {
        "items": [
            {
                "user": {
                    "id": 8,
                    "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
                    "first_name": "Jacob",
                    "middle_name": "Glory",
                    "surname": "Israel"
                },
                "id": 29,
                "tax_rate": 7.5,
                "tax_amount": "6506.25",
                "shipping_fee": "2500.00",
                "discount_amount": "0.00",
                "total_quantity": 85.0,
                "subtotal": "86750.00",
                "total_amount": "95756.25",
                "status": "processing",
                "delivery_address": [
                    "zone 2, Wuse",
                    "Abuja",
                    "FCT",
                    "Nigeria"
                ],
                "created_at": "2026-06-05T14:00:53.281590Z"
            },
            {
                "user": {
                    "id": 8,
                    "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
                    "first_name": "Jacob",
                    "middle_name": "Glory",
                    "surname": "Israel"
                },
                "id": 30,
                "tax_rate": 7.5,
                "tax_amount": "3438.75",
                "shipping_fee": "2500.00",
                "discount_amount": "0.00",
                "total_quantity": 68.0,
                "subtotal": "45850.00",
                "total_amount": "51788.75",
                "status": "processing",
                "delivery_address": [
                    "Gwarinpa",
                    "Abuja",
                    "Federal Capital Territory",
                    "Nigeria"
                ],
                "created_at": "2026-06-05T14:02:52.761004Z"
            },
            {
                "user": {
                    "id": 8,
                    "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
                    "first_name": "Jacob",
                    "middle_name": "Glory",
                    "surname": "Israel"
                },
                "id": 31,
                "tax_rate": 7.5,
                "tax_amount": "9750.00",
                "shipping_fee": "2500.00",
                "discount_amount": "0.00",
                "total_quantity": 110.0,
                "subtotal": "130000.00",
                "total_amount": "142250.00",
                "status": "processing",
                "delivery_address": [
                    "Gwarinpa",
                    "Abuja",
                    "Federal Capital Territory",
                    "Nigeria"
                ],
                "created_at": "2026-06-06T16:02:37.429118Z"
            },
            {
                "user": {
                    "id": 8,
                    "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
                    "first_name": "Jacob",
                    "middle_name": "Glory",
                    "surname": "Israel"
                },
                "id": 27,
                "tax_rate": 7.5,
                "tax_amount": "5553.75",
                "shipping_fee": "2500.00",
                "discount_amount": "0.00",
                "total_quantity": 74.0,
                "subtotal": "74050.00",
                "total_amount": "82103.75",
                "status": "processing",
                "delivery_address": [
                    "zone 2, Wuse",
                    "Abuja",
                    "FCT",
                    "Nigeria"
                ],
                "created_at": "2026-06-01T17:13:44.198419Z"
            },
            {
                "user": {
                    "id": 8,
                    "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
                    "first_name": "Jacob",
                    "middle_name": "Glory",
                    "surname": "Israel"
                },
                "id": 32,
                "tax_rate": 7.5,
                "tax_amount": "6656.25",
                "shipping_fee": "2500.00",
                "discount_amount": "887.50",
                "total_quantity": 107.0,
                "subtotal": "88750.00",
                "total_amount": "97018.75",
                "status": "processing",
                "delivery_address": [
                    "Gwarinpa",
                    "Abuja",
                    "Federal Capital Territory",
                    "Nigeria"
                ],
                "created_at": "2026-06-15T17:26:05.845720Z"
            }
        ],
        "pagination": {
            "page": 1,
            "limit": 10,
            "total": 5
        }
    }
}
```

---

### 10. Payment Service

Governs global electronic transaction lifecycles, real-time external processor integrations, state-locked refund accounting, and role-segregated financial ledger validation.

* **Asynchronous Stripe Engine Integration**: Couples local database checkouts with external payment routing through an asynchronous integration client (`stripe_client.v1.checkout.sessions.create_async`). It handles both physical order payments (converting floating total amounts into fixed integer pennies: `int(round(order.total_amount * 100))`) and subscription pricing configurations, mapping specific billing plan tokens (`sub.price_id`).


* **Dual-State Mutual Exclusion Guards**: Restricts checkout routes by checking input parameters to ensure only one item type is processed per intent creation sequence. The validation framework throws a 400 Bad Request exception if a user passes both `order_id` and `membership_id` simultaneously, or if it catches an empty structural payload (`order_id is None and membership_id is None`).


* **Transactional Ledger Rollback Defenses**: Shields financial entries against transaction discrepancies by tracking partial balances through an explicit log step (`Refund`). If an external transaction succeeds but the database write fails, the execution block traps the exception and outputs a critical error message detailing the tracking drift, alerting administrators that manual reconciliation is required:


> 🚨 **FATAL STATE MISMATCH**: Stripe refund succeeded but database tracking write failed! Manual reconcile required.
> 
> 


📐 **Architectural Decisions & Safeguards**:

* **Strict Balance Fencing**: Controls outbound refunds by comparing requested adjustments against original payment records via a lock filter (`.with_for_update()`). The pipeline prevents over-refunding by summing all matching entries (`func.coalesce(func.sum(Refund.refund_amount), 0)`), calculating the remaining balance, and throwing a 400 Bad Request error if a user requests more than the refundable remainder.


* **Multi-Tenant Time-Slice Queries**: Optimizes lookups across store domains by matching requested filter strings against relative temporal maps (`1 year`, `6 months`, `3 months`, `1 month`, `1 week`). If a store's founding date is newer than the requested query window (`store.founded > time_period`), the search short-circuits with an error response, keeping data lookups efficient and within valid operational bounds.


### JSON Response

```jsonc
{
    "status": "success",
    "message": "payment for order: '32",
    "data": {
        "id": 25,
        "order_id": 32,
        "payment_method": "card",
        "currency": "usd",
        "payment_status": "success",
        "total_amount": "97018.75",
        "shipping_fee": "2500.00",
        "discount_amount": "887.50",
        "tax_amount": "6656.25",
        "reference_id": "cs_test_a1bIDEDh84cPymy8Rz1xM1JqoSW4PpOhVHkXB23dGjoClCooHhr5kbJLsA",
        "transaction_id": "pi_3TigCc94kWAB11ZG1795DuQR",
        "payment_date": "2026-06-15T19:00:39.997909Z"
    }
}
```

---

### 11. Product Reviews Service

Governs verified-purchase consumer feedback loops, real-time rolling product metric aggregation engines, social reaction summaries, and automated cache eviction trees.

* **Verified-Purchase Gatekeeping Filter**: Restricts feedback submissions by assessing transactional history using an analytical subquery pattern (`select(exists(...))`). It verifies that the customer has a recorded item entry (`OrderItem`) mapped to a finalized transaction status (`OrderStatus.processing` or `OrderStatus.delivered`) before allowing a review to be generated.


* **Row-Locked Aggregation Rolling Math**: Isolates catalog updates during review submissions by applying row-level table locks via `.with_for_update(of=Product)`. The engine calculates rolling average ratings and feedback counts in memory to prevent mathematical race conditions across parallel threads:



```math
new\_avg = \frac{(current\_avg \times current\_count) + ratings}{current\_count + 1}
```


* **Dynamic Correction Recalculation Loops**: Re-evaluates rolling statistics dynamically when a review is edited or removed. If a review's score changes, the system applies an adjustment formula to correct the product's average score without recalculating the entire table; if a review is deleted, it scales back the metrics using an update block (`update(Product)`) while clamping minimum boundaries to `0.0`:




```math
adjusted\_avg = \frac{(current\_avg \times current\_count) - former\_rating + ratings}{current\_count}
```



📐 **Architectural Decisions & Safeguards**:

* **Transactional Anti-Duplication Boundary**: Restricts submissions to a single entry per item per user profile by scanning lookups for existing matches (`exists().where(Review.user_id == user_id)`) inside its locking clause. If an existing record matches, the thread throws a 400 Bad Request exception, preventing data duplication or artificial metric inflating across storefront paths.


* **Dual-Egress Background Eviction Tree**: Maximizes API read performance by serving requests from short-lived paginated cache keys (`ttl=30`) that are isolated by schema version numbers (`cache_version`). When a review is created, modified, or deleted, the service offloads cache clearing to separate worker threads (`background_task.add_task`), running both `product_review_invalidation` and `product_invalidation` to guarantee data consistency across dependent modules.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "reviews",
  "data": {
    "items": [
      {
        "id": 4,
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "review_text": "This HP laptop is excellent. It boots up within seconds and handles multi-tasking effortlessly. The keyboard is very comfortable to type on, the battery life holds up well throughout the day, and it doesn't get hot or loud. If you're looking for a reliable, fast machine for work or everyday use, this is a great choice.",
        "ratings": 4,
        "product_review_reaction_count": 2,
        "reactions": {
          "love": 1,
          "wow": 1
        },
        "time_of_post": "2026-06-27T14:18:13.748646Z"
      },
      {
        "id": 3,
        "user": {
          "id": 8,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
          "first_name": "Jacob",
          "middle_name": "Glory",
          "surname": "Israel"
        },
        "review_text": "I am really impressed with this HP product. It boots up incredibly fast, runs smoothly, and handles all my daily tasks without any lag. The screen is clear and the design feels solid. Great value for money and highly recommended!",
        "ratings": 5,
        "product_reply_count": 1,
        "product_review_reaction_count": 2,
        "reactions": {
          "like": 1,
          "love": 1
        },
        "time_of_post": "2026-06-27T13:11:38.901985Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 2
    }
  }
}
```

---


### 12. Product Reply Service

Governs the interactive consumer feedback echo chamber, store hierarchy-prioritized thread sorting, social engagement metrics, and atomic response metadata tracking.

* **Verified Buyer Reply Gatekeeper**: Validates responding profiles against a transactional ledger pattern (`select(exists(...))`). It matches checking logic down to individual order line items (`OrderItem`) linked with active fulfillment loops (`OrderStatus.processing` or `OrderStatus.delivered`), ensuring only verified buyers of that specific product can interact with its review threads.


* **Store-Tiered Priority Sorting Engine**: Re-orders thread responses dynamically using an execution routing rule (`case(...)`). The database evaluates responder permissions relative to the parent entity, giving store owners the highest display priority (`2`), staff members standard priority (`1`), and general consumers baseline priority (`0`) before sorting by submission date:


```sql
CASE 
    WHEN store_owners.user_id = reply.user_id THEN 2
    WHEN store_staffs.user_id = reply.user_id THEN 1
    ELSE 0 
END DESC, reply.time_of_post ASC

```


* **Atomic Interaction Counter Fencing**: Protects cross-table telemetry increments from concurrent race exploits via selective database locking (`.with_for_update()`). When a response is successfully committed, it automatically increases the parent summary variable (`review_obj.product_reply_count += 1`); conversely, deleting a response decrements the count through a boundary-checked correction loop:



```math
reply\_count_{new} = \max(0, reply\_count_{current} - 1)
```



📐 **Architectural Decisions & Safeguards**:

* **Thread Anti-Spam Isolation**: Implements a strict constraint that allows only one reply per user per review thread. By combining database-level checks (`exists().where(Reply.user_id == user_id, Reply.review_id == reply.review_id)`) with row locks, the service short-circuits duplicated inputs with a 400 Bad Request exception.


* **Hierarchical Cache Eviction Pipeline**: Optimizes high-traffic API listing routes through version-tagged Redis keys (`cache_version`). Any state modification (creation, editing, or deletion) immediately offloads cache invalidation requests to background worker threads (`background_task.add_task`), clearing both `product_reply_invalidation` and `product_review_invalidation` keys concurrently.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "replies",
  "data": {
    "items": [
      {
        "id": 1,
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "reply_text": "yea it is a good product, I rated it highly also",
        "product_reply_reaction_count": 1,
        "reactions": {
          "like": 1
        },
        "time_of_post": "2026-06-29T13:58:41.300939Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 1
    }
  }
}
```

---

### 13. Products Service

Governs the digital marketplace catalog, secure multi-media asset provisioning, structured hierarchical taxonomy alignment, and conditional inventory suppression engines.

* **Secure Cloud-Storage Ingestion Hooks**: Pairs multi-tenant product additions with direct cloud bucket integrations (`get_supabase.storage.from_`). The pipeline enforces rigorous content-type screening against explicit image formats (`image/jpeg`, `image/png`, `image/webp`), sanitizes string profiles into universally unique identifiers (`uuid.uuid4`), and maps safe filenames into the database layer.


* **Taxonomy & Sub-Category Subqueries**: Validates matching entries by performing strict matching logic against storefront category constraints. It screens inputs using whitespace trimming and down-casing comparisons (`func.trim(SubCategory.name) == sub_category_name.strip()`), raising a 409 Conflict if a vendor attempts to upload items into unassigned catalog branches.


* **Orphaned Asset Invalidation Loops**: Prevents storage resource leakage during execution failures via transactional exception tracking. If a core metadata database modification triggers an `IntegrityError` or an unexpected application halt, a cleanup task (`cleaned_up`) runs to remove orphaned binary files from storage.



📐 **Architectural Decisions & Safeguards**:

* **Seed-Deterministic Pseudo-Random Sorting**: Implements performant marketplace catalog generation by introducing a consistent randomizing factor (`seed`). Listing pipelines apply low-overhead md5 hashing combinations (`order_by(func.md5(func.concat(cast(Product.id, String), str(seed))))`) to shuffle product visibility predictably across paginated boundaries, avoiding costly index-breaking array sorts.


* **Soft Deletion Suppression Trees**: Transitions records out of consumer view without breaking historical integrity by chaining cascade blocks. Triggering a delete sets an explicit visibility state (`Product.is_deleted = True`) and runs an update query (`update(Inventory)`) to suppress corresponding warehouse slots while simultaneously dropping secondary files (`delete(ProductImage)`).


* **Concurrent Global Invalidation Matrix**: Controls global cache consistency when catalog states change by running parallel non-blocking workers (`asyncio.gather`). Modifications instantly clear dependent caches, evicting stale data fragments simultaneously across three modules: `cart_global_invalidation`, `order_global_invalidation`, and `product_invalidation`.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "products data",
  "data": {
    "items": [
      {
        "id": 1,
        "product_name": "HP Laptop",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
        "product_type": "HP EliteBook 840 G6 TOUCHSCREEN intel Core i5-16GB RAM/512GB SSD",
        "product_price": "650.00",
        "avg_rating": "4.50",
        "review_count": 2,
        "product_size": "small",
        "product_description": "The HP EliteBook 840 G6 is a premium 14‑inch business laptop designed for professionals, offering strong performance, advanced security features, and a slim aluminum design. It balances portability with enterprise‑grade reliability, making it ideal for office and mobile work",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 39
        }
      },
      {
        "id": 3,
        "product_name": "i Pad",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
        "product_type": "7 inch i Pad",
        "product_price": "1000.00",
        "avg_rating": "5.00",
        "review_count": 1,
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 50
        }
      },
      {
        "id": 6,
        "product_name": "Infinix",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/939580eb-6b49-4c82-9829-b2880fecf540_Screenshot_2026-01-05_203517.png",
        "product_type": "A 38",
        "product_price": "950.00",
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 82
        }
      },
      {
        "id": 2,
        "product_name": "Mac Book",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "product_type": "Apple product",
        "product_price": "1200.00",
        "avg_rating": "3.00",
        "review_count": 2,
        "product_size": "small",
        "product_description": "great innovation ",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 261
        }
      },
      {
        "id": 4,
        "product_name": "Power Bank",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/bb87c9fb-bd60-4340-a6e5-ad2e6bfd82df_Screenshot_2026-01-05_203517.png",
        "product_type": "50000 MaH",
        "product_price": "200.00",
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "out_of_stock",
        "inventory": {
          "stock_quantity": 0
        }
      },
      {
        "id": 5,
        "product_name": "Samsung",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/ae73fe88-8972-4fc0-b68d-784a17a8d484_Screenshot_2026-01-05_203517.png",
        "product_type": "A38",
        "product_price": "950.00",
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 60
        }
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 6
    }
  }
}
```

---

### 14. Profile Service

Governs identity lifecycle validation, strict role-segregated governance protocols, dynamic field synchronization, and soft-deactivation privacy walls.

* **Syntax-Enforced Identity Screening**: Protects electronic profile metadata by intercepting email update sequences. It channels string evaluations through specialized external syntax parsers (`validate_email`), throwing an immediate 400 Bad Request if the target payload breaks RFC standard specifications.
* **Hierarchical Self-Deletion Walls**: Controls destructive profile pathways through a rigid multi-tier role authorization structure. Base consumer identities are permitted to self-terminate, but cross-profile administrative commands trigger secondary authorization logic: standard admins cannot drop target accounts if the resource role evaluates as an `Owner`, nor can they delete other peer `Admin` records.
* **Idempotent State-Locked Suppression**: Prevents redundant transactional state writes by pre-checking existing runtime flags before processing deactivations. If a profile's operational state is already disabled (`not data.is_active`), the execution block short-circuits and safely outputs a success response without executing additional database operations.

📐 **Architectural Decisions & Safeguards**:

* **Dual-Query Unique Allocation Checks**: Eliminates identity conflicts during active updates by verifying email exclusivity before committing changes. If an email modification deviates from the authenticated baseline record, the pipeline initiates a fast existence subquery (`select(exists().where(User.email == profile.email, User.id != user_id))`) to check if the identifier is already claimed elsewhere.
* **Dynamic Nullable Mutation Masking**: Optimizes update patterns by dynamically matching structural updates against explicit field arrays (`fields`). The service separates standard properties from explicitly defined empty parameters (`nullable = ["middle_name", "address"]`), allowing specific text properties to be cleared out while tracking change flags (`has_changed = True`) to minimize unnecessary write cycles.
* **Background Asset Resolvers**: Normalizes public profile outputs by resolving internal storage keys into full URLs. Read sequences route file path tokens through an external cloud asset engine (`get_public_url(profile.profile_picture)`), abstracting underlying asset topologies from client applications.


### JSON Response

```jsonc
{
    "status": "success",
    "message": "profile",
    "data": {
        "id": 8,
        "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
        "first_name": "Jacob",
        "middle_name": "Glory",
        "surname": "Israel",
        "username": "jayeye",
        "phone_number": "+972784983",
        "email": "jayglo@gmail.com",
        "nationality": "Israel",
        "address": "Tel Aviv"
    }
}
```

---

### 15. Reactions Service

Governs the user engagement loop, polymorphic social reaction tracking, dynamic telemetry count management, and multi-tenant cache eviction across product and store review threads.

* **Polymorphic Target Isolation Guard**: Restricts inputs to ensure a reaction applies to exactly one entity type by validating incoming parameters. The route throws a 400 Bad Request exception if a user passes both `reply_id` and `review_id` simultaneously, or if it receives an empty structural payload (`reply_id is None and review_id is None`).
* **Dynamic Telemetry Field Mapping**: Determines target contexts by checking relationship attributes (`target.product`). It dynamically constructs model fields using text composition (`f"{prefix}_{suffix}"`) to map interactions across four explicit counters: `product_review_reaction_count`, `store_review_reaction_count`, `product_reply_reaction_count`, or `store_reply_reaction_count`.
* **Three-Way Toggle State Machine**: Modifies database rows sequentially based on existing record presence and input matching. If an entry matches both user and target, providing the same type triggers a soft removal (`db.delete`) while decrementing counters; providing a new type updates the interaction type inline, whereas an empty state generates a new transaction record (`React`).

📐 **Architectural Decisions & Safeguards**:

* **Enumerated Value Enforcement**: Safeguards data models against invalid inputs by routing incoming strings through standard verification types (`ReactionType(reaction_type)`). Any parsing failure triggers an execution catch block that yields a 400 Bad Request error, isolating the relational engine from corrupted inputs.
* **Targeted Cache Eviction Worker Routing**: Orchestrates worker tasks based on mapped field outputs to clear relevant caches dynamically (`background_task.add_task`). Depending on the context, it invalidates cache engines across product reviews, store reviews, product replies, or store replies to keep consumer dashboards accurate and synchronous.

### JSON Response

```jsonc
"reactions": {
          "like": 1,
          "love": 1,
          "wow": 1,
          "angry": 1,
          "laugh": 1
        }
```

---

### 16. Store Account and Address Service

Governs multi-tenant vendor onboard banking lifecycles, asymmetric cryptography frameworks for regulatory financial records, strict verification state workflows, and spatial address topologies.

* **Asymmetric Cryptographic Ingestion**: Protects highly sensitive financial identifiers (such as bank account, tax, and personal identity numbers) by running them through a symmetrical block cipher encoder (`cipher.encrypt`). Raw text bytes are scrambled during creation and edit sequences before being serialized into storage, shielding vendor data at rest.


* **Verification-State Update Lockouts**: Enforces data-tampering barriers on validated financial entities by evaluating structural state variables (`AccountVerification.verified`). If a storefront profile has already achieved an active verified state, the application blocks modification requests and throws a 400 Bad Request exception, unless the vendor is exclusively appending a missing tax identification token.


* **Sequential Verification Auditing**: Transitions store banking entries through distinct verification lifecycles (`verify` or `reject`). Approving an entity maps the current system timestamp to the record (`verified_at = datetime.now(timezone.utc)`) and arches any existing rejection logs into cold historical tables; rejecting an entity locks down future payouts and logs the mandatory text justification provided by administrators.



📐 **Architectural Decisions & Safeguards**:

* **Atomic Multi-Condition Ownership Validation**: Employs an explicit multi-clause existence check (`select(exists()..., exists()..., exists()...)`) inside a single database round-trip during entry generation. The query simultaneously validates storefront existence, verifies whether the current profile holds authenticated owner permissions within the `store_owners` junction table, and confirms that the business has not already established a banking profile.


* **Asymmetric Response Context Decryption**: Masks sensitive structural models from standard network visualization tools by passing external decryption matrices contextually. The viewing route passes an initialized secure block cipher through Pydantic pipeline contexts (`StoreAccountResponse.model_validate(..., context={"cipher": cipher})`), decrypting banking tokens only for verified administrators or matching store owners.


* **Analytical Windows for Paginated Addresses**: Optimizes address lists across store regions by computing total matches within a windowed query execution block (`func.count(Address.id).over().label("total_count")`). This pattern isolates subtotal records directly alongside paginated offset blocks, enabling the caching engine (`ttl=300`) to store complete metadata packets without firing separate count queries.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "store addresses retrieved",
  "data": {
    "items": [
      {
        "id": 1,
        "street": "157B Gidan Mangoro",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria"
      },
      {
        "id": 4,
        "street": "zone 2, Wuse",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria"
      },
      {
        "id": 5,
        "street": "Gwarimpa",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria"
      },
      {
        "id": 6,
        "street": "Gwarinpa",
        "city": "Abuja",
        "state": "Federal Capital Territory",
        "country": "Nigeria"
      },
      {
        "id": 7,
        "street": "Flat 2, CBN Quarters Karu",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria"
      },
      {
        "id": 8,
        "street": "Gidan Mangoro",
        "city": "Abuja",
        "state": "Federal Capital Territory",
        "country": "Nigeria"
      },
      {
        "id": 9,
        "street": "Green Lake",
        "city": "Dallas",
        "state": "Florida",
        "country": "United States of America"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 7
    }
  }
}
```

---

### 17. Store Analytics Service

Governs merchant visibility dashboards, multi-dimensional gross profit aggregation engines, time-series volume performance filters, and stock tier monitoring arrays.

* **Multi-Clause Ownership Authorization Hook**: Evaluates profile metadata structures using an inline tuple extraction query (`select(Store, exists(...))`). It simultaneously confirms business clearance flags (`Store.approved.is_(True)`) and verifies if the profile matches verified credentials within the `store_owners` junction table before serving business intelligence details.
* **Net Revenue Financial Matrix**: Extends standard gross calculation routines by parsing raw operational logs across payment relationships. The arithmetic engine strips operational costs from standard ledger metrics to reveal true merchant gross sales, computing rolling performance tracking averages dynamically:



```math
gross\_sales = \sum(total\_amount) - \sum(shipping\_fee)
```



```math
avg\_sales\_per\_day = \frac{gross\_sales}{today - store\_founded\_date}
```



* **Time-Bound Flexible Product Ranking**: Provides rolling visibility insights by evaluating product orders across structured date limits (`relativedelta`). The system sorts items based on volume performance configurations, filtering by sales metrics (`func.sum(OrderItem.quantity)`) or customer satisfaction averages (`func.avg(Review.ratings)`) to isolate top or underperforming products.

📐 **Architectural Decisions & Safeguards**:

* **Onboarding Visibility Fencing**: Protects analytical performance reports during initial startup phases by enforcing an absolute one-month maturity constraint. If the runtime check determines that the operational timeline is less than 30 days old (`today < target_store.founded + relativedelta(months=1)`), the system suspends metric delivery to allow meaningful baseline data collection.
* **Multi-Tier Inventory Classification Ranges**: Maps warehouse tracking records into discrete, segmented buckets based on remaining stock quantities. Relational filters isolate distinct ranges (such as `above_fifty`, `ten_below`, or `out_of_stock`) to construct real-time tracking lists, enabling merchants to monitor supply chain health without executing high-overhead sorting passes.
* **Context-Variant Analytical Key Tree**: Manages cache space efficiently by partitioning Redis entry footprints dynamically using signature string parameters. Tracking routes combine context flags, product IDs, and time boundaries into descriptive keys (`f"{slug}:{context}:{context_1}:{context_2}"`) to separate specific analytics views from general public storefront cache records.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "most sold products and most rated products in descending order",
  "data": {
    "product_sales": [
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "product_name": "Mac Book",
        "product_size": "small",
        "quantity_sold": 50
      },
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
        "product_name": "i Pad",
        "product_size": "small",
        "quantity_sold": 31
      },
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
        "product_name": "HP Laptop",
        "product_size": "small",
        "quantity_sold": 27
      },
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/bb87c9fb-bd60-4340-a6e5-ad2e6bfd82df_Screenshot_2026-01-05_203517.png",
        "product_name": "Power Bank",
        "product_size": "small",
        "quantity_sold": 20
      },
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/939580eb-6b49-4c82-9829-b2880fecf540_Screenshot_2026-01-05_203517.png",
        "product_name": "Infinix",
        "product_size": "small",
        "quantity_sold": 10
      }
    ],
    "product_ratings": [
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
        "name": "i Pad",
        "product_size": "small",
        "ratings": 5
      },
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
        "name": "HP Laptop",
        "product_size": "small",
        "ratings": 4.5
      },
      {
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "name": "Mac Book",
        "product_size": "small",
        "ratings": 3
      }
    ]
  }
}
```

---


### 18. Core Store Management Service

Governs the storefront registration lifecycles, configuration editing regimes, cross-role staff and owner permissions, and cascading hard/soft-deletion workflows.

* **Multi-Owner Store Registration Fencing**: Restricts multi-tenant profile instantiation to authorized users, validating requested parameters using clean regex validations (`^[\p{L}\s]+$`). The routine verifies that the target profile does not breach maximum asset thresholds (`store_count >= 10`) and validates existing taxonomy requirements within a synchronized subquery block.
* **Immutable Name Modification & Appending**: Regulates configuration update patterns by tracking title-change states (`edited_name = True`). If a storefront profile modifies its commercial name once, future modification attempts are barred. For nested parameters (such as sub-categories), developers pass explicit mutation parameters (`update_type="add"` or `"replace"`), which use mathematical set unions (`current_sub_category.union(...)`) to append fresh metadata without destroying legacy assignments.
* **Personnel Escalation & Roster Ceilings**: Enforces explicit headcount boundaries on organizational rosters via multi-row constraint checks. Staff assignments prevent overlapping roles (blocking staff from acting as store owners and vice versa) and enforce explicit capacity metrics across the enterprise layout:

$$\text{Max Stores Per Owner} \le 10$$


$$\text{Max Employed Stores Per Staff Member} \le 2$$



📐 **Architectural Decisions & Safeguards**:

* **Advisory Locks for Personnel Realignment**: Mitigates concurrent race conditions when rewriting organizational rosters by invoking an explicit database session lock (`SELECT pg_advisory_xact_lock(:id)`). This isolates transaction states during personnel updates, preventing double-assignment flaws or out-of-bounds roster sizes under rapid network loads.
* **Asynchronous Lateral Image Promotion**: Optimizes paginated global discovery feeds by combining a deterministic seed-based hashing mechanism (`func.md5(...)`) with a lateral subquery correlation loop. This structure surfaces exactly one prominent product profile alongside its primary storage link directly within the parent query scope, lowering processing overhead during random discovery queries.
* **Cascading Dependency Demolition**: Executes sweeping database invalidation passes during store deletion routines by combining targeted soft-deletes with hard file purges. While parent relationships (Stores, Inventory records, Financial accounts, and Addresses) are safely toggled via soft flags (`is_deleted = True`), associated nested tracking nodes (`ProductImage`) are permanently dropped from relational schemas, triggering an external script to clear out orphan object storage artifacts.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "available 'hp' stores",
  "data": {
    "items": [
      {
        "id": 1,
        "business_logo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/325a35ac-2602-45d1-bed5-eef549ebd9a2_Screenshot_2025-11-14_023914.png",
        "store_photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/634e8496-7149-466e-98e3-d8e4bab86658_Screenshot_2025-11-25_140924.png",
        "store_name": "Emmanuel Electronics",
        "category_name": "Electronics & Technology",
        "sub_category": [
          "Computers & Tablets",
          "Mobile Phones & Accessories"
        ],
        "review_count": 2,
        "avg_rating": "4.50",
        "motto": "Powering Your World, One Innovation at a Time",
        "featured_product": {
          "id": 1,
          "product_name": "HP Laptop",
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
          "product_price": "650.00",
          "product_availability": "available",
          "avg_rating": "4.50",
          "inventory": {
            "stock_quantity": 39
          }
        },
        "shipping_fee": "2500.00",
        "store_description": "Welcome to TechDirect Online, your one‑stop destination for premium electronics. We specialize exclusively in computers, laptops, mobile phones, and accessories — delivering the latest technology at unbeatable value.",
        "approved": true,
        "founded": "2026-05-26T13:23:15.997733Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 1
    }
  }
}
```

---

### 19. Store Reviews Service

Governs verified-purchase consumer feedback loops, real-time rolling store metric aggregation engines, social reaction summaries, and automated cache eviction trees.

* **Verified-Purchase Gatekeeping Filter**: Restricts feedback submissions by assessing transactional history using an analytical subquery pattern (`select(exists(...))`). It verifies that the customer has a recorded order entry mapped to a finalized transaction status (`OrderStatus.processing` or `OrderStatus.delivered`) under the target storefront before allowing a review to be generated.


* **Row-Locked Aggregation Rolling Math**: Isolates catalog updates during review submissions by applying row-level table locks via `.with_for_update(of=Store)`. The engine calculates rolling average ratings and feedback counts in memory to prevent mathematical race conditions across parallel threads:



```math
new\_avg = \frac{(current\_avg \times current\_count) + ratings}{current\_count + 1}
```



* **Dynamic Correction Recalculation Loops**: Re-evaluates rolling statistics dynamically when a review is edited or removed. If a review's score changes, the system applies an adjustment formula to correct the store's average score without recalculating the entire table; if a review is deleted, it scales back the metrics using an update block (`update(Store)`) while clamping minimum boundaries to `0.0`:



```math
adjusted\_avg = \frac{(current\_avg \times current\_count) - former\_rating + ratings}{current\_count}
```



📐 **Architectural Decisions & Safeguards**:

* **Transactional Anti-Duplication Boundary**: Restricts submissions to a single entry per storefront per user profile by scanning lookups for existing matches (`exists().where(Review.user_id == user_id)`) inside its locking clause. If an existing record matches, the thread throws a 400 Bad Request exception, preventing data duplication or artificial metric inflating across storefront paths.


* **Dual-Egress Background Eviction Tree**: Maximizes API read performance by serving requests from short-lived paginated cache keys (`ttl=30`) that are isolated by schema version numbers (`cache_version`). When a store review is created, modified, or deleted, the service offloads cache clearing to separate worker threads (`background_task.add_task`), running both `store_review_invalidation` and `store_invalidation` to guarantee data consistency across dependent modules.


### JSON Response

```jsonc
{
  "status": "success",
  "message": "reviews",
  "data": {
    "items": [
      {
        "id": 10,
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "ratings": 4,
        "review_text": "Emmanuel Electronics is one of the most reliable sellers I’ve bought from on AtomicCommerce. My order was processed quickly, the product matched the description perfectly, and delivery was right on schedule. The packaging was secure, and customer service was polite and helpful when I reached out. It’s clear they value their customers, and I’ll continue shopping with Emmanuel Electronics for future electronics needs.",
        "store_review_reaction_count": 1,
        "reactions": {
          "like": 1
        },
        "time_of_post": "2026-07-01T20:51:05.424142Z"
      },
      {
        "id": 8,
        "user": {
          "id": 8,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
          "first_name": "Jacob",
          "middle_name": "Glory",
          "surname": "Israel"
        },
        "edited": true,
        "ratings": 5,
        "review_text": "I bought from Emmanuel Electronics through AtomicCommerce and had an excellent experience. The item was exactly as described, packaged securely, and delivered on time. Communication from the seller was clear and professional, and they responded quickly to my questions. It’s reassuring to know there are trustworthy vendors like Emmanuel Electronics on the platform. I’ll definitely shop with them again.",
        "store_reply_count": 2,
        "time_of_post": "2026-07-01T13:22:40.508280Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 2
    }
  }
}
```

---


### 20. Store Reply Service

Governs the interactive lifecycle of storefront review responses, validating structural role authorization, compiling multi-dimensional reaction counts, and executing transactional counter corrections.

* **Role-Bounded Cross-Examination Hook**: Evaluates structural privileges during comment processing to isolate authorized merchant personnel from regular customers. By deploying inline table evaluation layers (`exists()`) wrapped around the core identity schema, the verification engine simultaneously determines ownership flags (`store_owners`) and staff clearances (`store_staffs`). It matches them against the underlying review record to ensure only the original reviewer or verified store operators can publish remarks.


* **Asynchronous Cache Eviction Pipelines**: Minimizes API thread blockage by offloading Redis entry footprint invalidations to secondary background tasks (`background_task.add_task`) immediately following database mutations. The service purges cached visibility trees for both nested responses and parent evaluation structures synchronously upon every successful insertion, rewrite, or deletion cycle:



```math
Cache\_Version\_Scope = f"store\_reply\_key:\{store\_id\}"
```



* **Transactional Counter Invalidation Safeguards**: Protects cumulative analytical metrics from drift during destructive deletion passes by wrapping updates within explicit lock blocks (`with_for_update`). When a comment is purged from the database, the system queries the associated parent row and decrements its total feedback metric safely, bounding the metric to prevent negative value flaws:



```math
store\_reply\_count = \max(0, store\_reply\_count_{current} - 1)
```



📐 **Architectural Decisions & Safeguards**:

* **Idempotent Content Mutation Controls**: Suppresses unnecessary transaction overhead at edit endpoints by cross-referencing inbound text parameters against existing row metrics before executing database commits. If the revised text completely matches the current persistent state, the database commit is bypassed entirely and a lightweight code status (`HTTP_204_NO_CONTENT`) is returned to the client.


* **Aggregated Batch Reaction Summaries**: Lowers communication costs across high-traffic message boards by evaluating reaction records in batches. Instead of issuing individual subqueries for each response row, the engine maps primary array keys (`reply_ids`) into a collective aggregation utility (`react_summary`), returning pre-compiled reaction counts within paginated collection feeds.


* **Dynamic State Mutation Triggers**: Enforces accountability across message boards by monitoring content alterations. When an author modifies an existing entry, the operational routine alters the tracking flag (`edited = True`), signaling to consumers that the message has been modified from its original post state.

### JSON Response

```jsonc
{
  "status": "success",
  "message": "replies",
  "data": {
    "items": [
      {
        "id": 6,
        "edited": true,
        "user": {
          "id": 5,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/82c8ca02-96a4-47a1-92ac-58df63d559b8_passport_image.png",
          "first_name": "Sandra",
          "surname": "Eke"
        },
        "reply_text": "Thank you for your patronage, Mr. James, hope to serve you again. Peace and Love.",
        "reactions": {
          "love": 1
        },
        "time_of_post": "2026-07-02T11:46:46.136024Z"
      },
      {
        "id": 9,
        "user": {
          "id": 8,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
          "first_name": "Jacob",
          "middle_name": "Glory",
          "surname": "Israel"
        },
        "reply_text": "you are welcome",
        "time_of_post": "2026-07-02T19:11:05.971182Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 2
    }
  }
}
```

---

### 21. Financial Gateways & Stripe Webhook Service

Orchestrates asynchronous webhooks from financial providers to safely sync external transactional states with subscription memberships, order processing workflows, and multi-tier refund architectures.

* **Idempotent Multi-Layer Event Fencing**: Employs rigorous state verification to block duplicate processing from out-of-order delivery or re-driven webhooks. By framing updates around explicit event IDs (`last_event_id != event['id']`) and timestamp linear progressions (`last_event_at <= created_timestamp`), the routine safely drops stale notifications and confirms that transactions are modified exactly once per state transition.


* **Polymorphic Metadata Parsing Matrix**: Traverses unstructured inbound JSON blocks to locate internal identifiers across various product profiles. The engine inspects multiple object layers, extracting properties from the core root mapping (`metadata`), specialized billing fields (`subscription_details`), and line-item collections (`lines.data[0].metadata`) to dynamically map events to internal records.


* **Conditional Mathematical State Transitions**: Evaluates external billing statuses via conditional query logic to calculate expiration windows and subscription levels dynamically. For successful membership completions, it shifts access rights safely forward into future windows:




```math
expire\_at = \max(Subscription.expire\_at, now()) + INTERVAL\text{ '30 days'}
```



---

### Stripe Webhook Operational Signals

| Payload Classification | Supported Stripe Signals | Downstream Internal Target Updates |
| :--- | :--- | :--- |
| **Membership & Recurring Billing** | `checkout.session.completed``customer.subscription.updated``customer.subscription.deleted``invoice.payment_succeeded``invoice.payment_failed` | Adjusts core `SubscriptionStatus` variants (`active`, `cancelled`, `past_due`), updates product subscription tiers (`Standard`, `Regular`, `Premium`), and sets the `is_active` flag.
| **Direct Order Checkout** | `checkout.session.completed``payment_intent.succeeded``charge.succeeded``checkout.session.expired``payment_intent.payment_failed``charge.failed` | Maps transaction keys against direct records (`Payment.transaction_id`), alters payment statuses (`SUCCESS`, `FAILED`), and updates parent order processing states.
| **Reversals & Chargebacks** | `charge.refunded``refund.updated` | Validates structural updates across internal ledger schemas (`Refund`); shifts tracking flags to `REFUNDED`, or rolls back parent accounts to `SUCCESS` if rejected.

---

📐 **Architectural Decisions & Safeguards**:

* **Defensive Reversal Restoration Routing**: Protects systems against payment status errors when a credit institution or bank rejects a pending return transaction. When an outbound refund fails, the system catches the failure state and reverts the parent payment record back to `SUCCESS`, protecting financial consistency across the application.


* **Type-Cast Enum Integration**: Eliminates structural schema mapping mismatches by compiling statuses through safe database type casts (`cast(..., target_enum)`). This technique verifies that arbitrary strings from webhooks are parsed into valid database types before submission, preventing runtime schema validation drops.


* **Asynchronous Background Core Activation**: Postpones non-critical business tasks until after the immediate web request-response cycle completes. Once database changes are written and committed, the pipeline registers downstream tasks—such as profile updates—via background worker queues (`background_task.add_task`), ensuring lightning-fast webhook responses.

### Terminal Log

```log
marketplace_api | 2026-06-15 14:41:15,579-INFO-Received webhook for membership subscription event: customer.subscription.created
marketplace_api | { "membership_id": "5", "payment_type": "subscription", "type": "membership", "user_id": "8" }
marketplace_api | 2026-06-15 14:41:15,854-WARNING-Received unhandled event type: payment_intent.succeeded
marketplace_api | 2026-06-15 14:41:15,907-INFO-Received webhook for membership subscription event: checkout.session.completed
marketplace_api | INFO:  172.18.0.1:44814 - "POST /payment/webhook HTTP/1.1" 200 OK
marketplace_api | 2026-06-15 14:41:20,554-INFO-Payment cs_test_a1FmodnSbtlV4Oyp9G6m09F6fwjJhu9lWYKzQi4lLT5c2nfVQBuNh8csKP processed successfully.
```


---

### 22. Sub-Category Service

Governs secondary product classification taxonomies, nesting rules within parent nodes, and elevated administrative access blocks across the directory engine.

* **Role-Based Access Enforcement**: Restricts access rights at the entry point of the module, rejecting execution unless the validated `user_id` resolves to a database `User` account holding administrative privileges of either `["Admin", "Owner"]`. Unprivileged accounts are blocked with 403 Forbidden exceptions prior to processing any schema logic.
* **Normalized Pattern Deduplication**: Prevents naming variations and duplicate item injections by normalizing input strings (`" ".join(name.split())`). Checks text variations against existing database sub-categories using low-level SQL regex and formatting transformations:

$$func.lower(func.trim(func.regexp_replace(SubCategory.name, r"\s+", "", "g")))$$



This collapses all inner whitespace sequences into zero-space blocks, neutralizing character-spacing bypass attacks at the database engine layer.
* **Paginated Selection Engine**: Surfaces active records (`~SubCategory.is_deleted`) by compiling an isolated row-count aggregate query from a standalone database subquery statement (`select(func.count()).select_from(stmt.subquery())`). This separates metric counts from page slicing offsets to output correct pagination totals.

📐 **Architectural Decisions & Safeguards**:

* **Audit-Safe Deletion Topology**: Disables destructive database record purging (`DELETE`) to preserve relational mapping trees across product portfolios. The module executes structural state modifications by setting a soft-delete flag (`SubCategory.is_deleted = True`), instantly hiding the targeted entry from subsequent consumer retrieval pipelines while maintaining database integrity.
* **Encapsulated Unit-of-Work Fail-Safes**: Encapsulates write actions and state updates inside isolated `try...except` contexts that intercept `IntegrityError` and global exceptions. Any database block breakdown triggers an immediate `await db.rollback()`, ensuring uncommitted mutations unwind instantly to shield directory metadata from fragmentation.


### JSON Response

```json
{
  "status": "success",
  "message": "sub_categories",
  "data": {
    "items": [
      {
        "id": 1,
        "category_id": 2,
        "name": "Academic Textbooks"
      },
      {
        "id": 2,
        "category_id": 2,
        "name": "Non‑fiction"
      },
      {
        "id": 3,
        "category_id": 2,
        "name": "Fiction"
      },
      {
        "id": 4,
        "category_id": 2,
        "name": "Children’s Books"
      },
      {
        "id": 5,
        "category_id": 2,
        "name": "Comics & Graphic Novels"
      },
      {
        "id": 6,
        "category_id": 2,
        "name": "Religious & Spiritual"
      },
      {
        "id": 7,
        "category_id": 2,
        "name": "Writing Instruments"
      },
      {
        "id": 8,
        "category_id": 2,
        "name": "Paper Products"
      },
      {
        "id": 9,
        "category_id": 2,
        "name": "Office Supplies"
      },
      {
        "id": 10,
        "category_id": 2,
        "name": "Art Supplies"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 91
    }
  }
}
```


---


🚀 Setup & Deployment
Clone & Environment: Copy .env.example to .env and configure your CIPHER_KEY and DATABASE_URL.
Docker Orchestration: docker-compose up --build to spin up FastAPI, Redis, and PostgreSQL.
Database Migrations: alembic upgrade head to sync the latest hardened schema.
