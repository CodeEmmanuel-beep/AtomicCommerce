# 🚀 High-Performance E-Commerce Engine
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)


A modular, service-oriented FastAPI backend architected for global scale, platform stability, and sub-100ms Fresh Data latency. 

---

## 🛠️ Engineering Highlights
*   **Atomic State Management**: Implements **PostgreSQL Advisory Locks** and Row-Level Locking (`FOR UPDATE`) to prevent "Lost Updates" in high-concurrency environments.
*   **Elite Performance**: Optimized via **Redis Cache-Aside** patterns and **Async Connection Pooling**. Fresh DB hits average **72ms**; Cache hits average **0.1ms (internal)**.
*   **Security & Privacy**: Field-level PII encryption using **Fernet** and custom **Pydantic Validation Contexts** for secure, on-the-fly decryption.
*   **Resilient Storage**: Distributed transaction logic for **Supabase/S3** uploads with automated **Orphaned-File Cleanup** on database rollbacks.
*   **Advanced Orchestration**: Strategic use of **FastAPI BackgroundTasks** for lightweight I/O and **Celery** for heavy architectural processing.
// Example Structured Log
{"level": "INFO", "service": "order-v1", "event": "atomic_transaction_success", "latency_ms": 72.4}
---

## 📁 Modular Service Architecture (SOA)
The system is divided into **12+ Domain-Specific Services**, ensuring zero circular dependencies and high maintainability for a 6,200+ line codebase.

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
