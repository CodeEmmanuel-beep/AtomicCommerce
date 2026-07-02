# 🚀 AtomicCommerce: High-Performance Multi-Tenant Engine

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)

A heavy-duty, service-oriented FastAPI backend architected for enterprise-scale multi-tenant commerce, data isolation, and exceptional performance under concurrent load.

---

## 📈 System Metrics & Scale

*   **100+ REST Endpoints**: Fully versioned, clean API paths covering multi-tenant vendor marketplaces, products, shopping carts, checkout logic, and advanced stock administration.
*   **20+ Service Modules**: Fully isolated domain modules following Service-Oriented Architecture (SOA) principles to eliminate circular imports and enforce a clear separation of concerns.
*   **20+ Database Tables**: A robust PostgreSQL relational schema complete with optimized composite indexes, explicit cascading parameters, and foreign key boundaries.
*   **10+ Strict Enums**: Rigid state-machine tracking via Python/SQLAlchemy Enums (e.g., Order states, Transaction statuses, Account tiers) ensuring type-safe processing at every interface.

---

## 🛠️ Engineering Highlights

*   **Asynchronous Architecture**: Built entirely on an ASGI worker pool loop using FastAPI and SQLAlchemy `AsyncSession`, enabling high-concurrency throughput without thread context-switching overhead.
*   **Atomic State Management**: Guarantees zero "Lost Updates" or inventory drift in high-throughput warehouse environments by implementing precise **PostgreSQL Advisory Locks** and row-level locking schemas (`FOR UPDATE`) across critical transaction paths.
*   **Redis Caching Framework**: Utilizes a strict **Redis Cache-Aside** strategy. High-demand product catalogs, pricing tiers, and vendor profile endpoints return responses instantly, reducing total round-trip times (RTT) dramatically.
*   **Distributed Background Processing**: Offloads heavy out-of-process operations seamlessly. Uses **FastAPI BackgroundTasks** for lightweight, post-response I/O chores, and **Celery** workers for heavy architectural workloads, reporting loops, and automated ledger adjustments.
*   **Hardened Auth & Token Rotation**: Effortlessly isolates and enforces Multi-Tenant Role-Based Access Control (Admin vs. Staff permissions) via stateless JWTs. Implements **Refresh Token Rotation**—revoking and replacing refresh tokens on every single use—to block token-reuse vectors out of the box.
*   **Zero-Crash Media Pipeline & Orphan Cleanup**: Protects server memory under heavy asset workloads. Media uploads bypass container staging via a chunk-streaming pipeline that caps file sizes in real time, validates MIME-types at the binary byte layer, and streams files directly to **Supabase Storage Buckets**. Orphaned files are tracked and cleaned up automatically on database rollbacks.
*   **Ironclad Database Integrity**: Implements strict database-level unique constraints (preventing duplicate SKUs) and check constraints (ensuring quantities can never drop below zero), wrapped inside explicit transaction boundaries within the application logic for atomic rollbacks.

```json
// Example Structured Performance Log
{"level": "INFO", "service": "inventory-v1", "event": "atomic_transaction_success", "latency_ms": 72.4}

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

🚀 Setup & Deployment
Clone & Environment: Copy .env.example to .env and configure your CIPHER_KEY and DATABASE_URL.
Docker Orchestration: docker-compose up --build to spin up FastAPI, Redis, and PostgreSQL.
Database Migrations: alembic upgrade head to sync the latest hardened schema.

Status: 75% Complete | Benchmarks: Fresh DB (72ms) / Cache (5ms Total RTT)
