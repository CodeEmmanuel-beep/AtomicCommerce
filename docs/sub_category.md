# 🏷️ Sub-Category Module

Governs secondary product classification taxonomies, nesting rules within parent nodes, and elevated administrative access blocks across the directory engine.

---

## 📡 Server-Client Interface

* **Role-Based Access Enforcement**: Restricts access rights at the entry point of the module, rejecting execution unless the validated `user_id` resolves to a database `User` account holding administrative privileges of either `["Admin", "Owner"]`. Unprivileged accounts are blocked with 403 Forbidden exceptions prior to processing any schema logic.

* **Normalized Pattern Deduplication**: Prevents naming variations and duplicate item injections by normalizing input strings (`" ".join(name.split())`). Checks text variations against existing database sub-categories using low-level SQL regex and formatting transformations:

$$func.lower(func.trim(func.regexp_replace(SubCategory.name, r"\s+", "", "g")))$$


This collapses all inner whitespace sequences into zero-space blocks, neutralizing character-spacing bypass attacks at the database engine layer.

* **Paginated Selection Engine**: Surfaces active records (`~SubCategory.is_deleted`) by compiling an isolated row-count aggregate query from a standalone database subquery statement (`select(func.count()).select_from(stmt.subquery())`). This separates metric counts from page slicing offsets to output correct pagination totals.


📐 **Architectural Decisions & Safeguards**:

* **Audit-Safe Deletion Topology**: Disables destructive database record purging (`DELETE`) to preserve relational mapping trees across product portfolios. The module executes structural state modifications by setting a soft-delete flag (`SubCategory.is_deleted = True`), instantly hiding the targeted entry from subsequent consumer retrieval pipelines while maintaining database integrity.

* **Encapsulated Unit-of-Work Fail-Safes**: Encapsulates write actions and state updates inside isolated `try...except` contexts that intercept `IntegrityError` and global exceptions. Any database block breakdown triggers an immediate `await db.rollback()`, ensuring uncommitted mutations unwind instantly to shield directory metadata from fragmentation.


### Business Rules

* **Parent Requirement**: Every sub-category must be associated with a valid, non-deleted parent category.
* **Name Uniqueness**: Sub-category names must be unique within their assigned parent category.

---

## Core Endpoints

**Create Sub-Category**

`POST api/v1/sub_category/create_sub_category`

Creates a new sub-category linked to an active parent category.

**Request Payload**

```python
  category_id: int
  name: str
```

**JSON Response**

```json
{"status": "success", "message": "sub_category created"}
```

---

**Fetch Sub-Categories**

`GET api/v1/sub_category/get_sub_categories`

Retrieves either:
 * all active sub-categories, or
 * only those belonging to a specified parent category.

**Request Payload**

```python
  category_id: int | None = None
  page: int = Query(1, ge=1)
  limit: int = Query(10, le=100)
```

**JSON Response**

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

**Delete Sub-Category**

`DELETE api/v1/sub_category/delete`

Soft-deletes a sub-category.

**Request Payload**

```python
sub_category_id: int
```

**JSON Response**

```json
{
  "status": "success",
        "message": "deleted sub_category",
        "data": {
            "id": 5,
            "user_id": 22,
            "deleted": "Yes"
        }
}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.
* **verify_token**: Validates session signatures and extracts permissions.

---

### Security Guardrails

* **400 Bad Request**: Dispatched during integrity errors, naming validation failure, unique value structural collisions, or foreign key constraint Violations.
* **403 Forbidden**: Dispatched if a merchant or user who is not a platform owner or platform admin attempts structural creation or deletion sweeps on the global taxonomy tree.
* **404 Not Found**: Dispatched if a specified parent_id target does not exist in the active records.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---

---
