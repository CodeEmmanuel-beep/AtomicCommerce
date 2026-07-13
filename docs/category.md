# 🗂️ Category Module

The Category module manages the platform-wide product taxonomy. It provides hierarchical category management, enforces normalized naming rules, and maintains referential integrity for all product classifications across the marketplace.

---

### 📡 Server-Client Interface

* **Role-Based Access Enforcement**: Implements explicit security checks at the API routing boundary, blocking execution unless the verified `user_id` resolves to a `User` record holding an elevated role context of either `["Admin", "Owner"]`. Standard buyers or unprivileged accounts are rejected with strict 403 Forbidden exceptions prior to executing mutations.

* **Direct Database Evaluation**: Due to the low-frequency use and small footprint of category states, operations read and write directly to the database layer without an intermediate caching layer. This guarantees absolute data freshness across all storefront instances simultaneously.

* **Global Taxonomy Model**: Category definitions are entirely global and shared across the application instance. No store-level multi-tenant partitioning occurs within this module; tenancy isolation is enforced strictly downstream when an individual store references a global category ID via a foreign key relationship within its own product catalogs.

* **Normalized Pattern Deduplication**: Avoids naming variations and duplicate entry injection by normalizing input names (`" ".join(name.split())`). Checks strings against database categories using low-level SQL regex and formatting transformations:


```python
func.lower(
    func.trim(
        func.regexp_replace(Category.name, r"\s+", "", "g")
    )
)
```


This collapses all inner whitespace sequences into zero-space blocks, neutralizing character-spacing bypass attacks at the engine layer.


* **Paginated Selection Engine**: Surfaces non-deleted categories (`~Category.is_deleted`) by compiling a standalone row-count aggregate query from a isolated database subquery statement (`select(func.count()).select_from(stmt.subquery())`). This isolates metric counts from limit-offset slicing variables to output correct total tracking fields.



📐 **Architectural Decisions & Safeguards**:

* **Audit-Safe Deletion Topology**: Avoids destructive database record purging (`DELETE`) to maintain structural history across product line items and historical catalogs. The delete workflow executes a state modification by setting a soft-delete flag (`Category.is_deleted = True`), immediately isolating the targeted entry from subsequent retrieval queries while maintaining database relational integrity.


* **Encapsulated Unit-of-Work Fail-Safes**: Runs write actions (`db.add`) and state modifications inside isolated `try...except` contexts capturing `IntegrityError` and global exception boundaries. Any database block breakdown triggers an immediate, synchronous `await db.rollback()`, ensuring uncommitted modifications unwind to protect the directory metadata from corruption.


### 📋 Business Rules

* **Normalized Categories**: Two categories cannot have identical normalized names.
* **Foreign Key Constraints**: Structural deletions are guarded at the database layer. A global category cannot be removed if its primary key (`id`) is actively referenced by any downstream product or child category foreign key.

---

### Core Endpoints

**Create Category**

`POST api/v1/category/create_category`

Lets Platform Owner or Admins to create normalized categories

**Request Payload**

```python
name: str
```

**JSON Response**

```json
{"status": "success", "message": "category created"}
```

---

**Fetch Category**

`GET api/v1/category/get_category`

Retrieves all categories, paginated with a limit of 100

**Request Payload**

```python
 page: int = Query(1, ge=1)
 limit: int = Query(10, le=100)
```

**JSON Response**

```json
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

**Delete Category**

`DELETE api/v1/category/delete`

Soft deletes a category at a time

**Request Payload**
```python
category_id: int
```

**JSON Response**

```json
{
"status": "success",
"message": "deleted category",
"data": {
"id": 5,
"user_id": 42,
"deleted": "Yes"
 }
}
```

---

⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.

* **verify_token**: Validates session signatures and extracts permissions.

### Security Guardrails

* **400 Bad Request**: Dispatched during integrity errors, naming validation failure, unique value structural collisions, or ForeignKey Constraint Violations.

* **403 Forbidden**: Dispatched if a merchant or user who is not platform owner or platform admin attempts structural creation or deletion sweeps on the global taxonomy tree.

* **404 Not Found**: Dispatched if a specified parent_id target does not exist in the active records.
