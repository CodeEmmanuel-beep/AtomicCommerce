# 📦 Inventory Module

Governs warehouse inventory levels, product stock allocation, multi-tenant inventory administration, and product availability synchronization across storefront catalogs.

---

## 📡 Server-Client Interface

* **Multi-Tenant Authorization Isolation**: Executes multi-condition authorization query during creation workflows, validating whether the requesting `user_id` is bound to the target `store_id` via `store_owners` or `store_staffs` relation records, while verifying that the product exists and is active (`~Product.is_deleted`). This prevents cross-tenant spoofing vectors at the query-execution layer.


* **Pessimistic Locking & Volatility Alignment**: Implements database row-level isolation via SQLAlchemy's `.with_for_update()` on target inventory records during updates and structural modifications. It locks matching records to secure high-concurrency writes while utilizing preloaded execution trees (`selectinload(Inventory.product)`).


* **Dual-Entity State Management**: Features transactional state synchronization during quantity adjustments. When stock levels are increased via an update mutation, the module evaluates the nested product metadata; if the linked catalog item is flagged as `"out_of_stock"`, the system resets its marketplace state back to `"available"` inline with the transaction.



📐 **Architectural Decisions & Safeguards**:

* **Volatile Caching Hierarchies**: Deploys a tiered distributed caching architecture using short-lived keys (`inventory:store_id:inventory_id`) holding a hardcoded `ttl=30` (30 seconds) for singular profiles, alongside paginated lists running on a `ttl=60` (1 minute) lifespan. This structure balances immediate public catalog discoverability with minimal stale-data margins.

* **Database Unique Constraint**: Each physical product variant is strictly mapped to one inventory record at the database level to prevent duplicate stock tracking pools.

* **Database Check Constraint** The core database engine strictly blocks stock levels from dipping below zero using a SQL-level constraint:

                   `CheckConstraint("stock_quantity >= 0", name="positive_quantity")`  

* **Audit-Safe Purging Topology**: Enforces strict historical integrity across ledger transactions by overriding destructive SQL commands with a logical soft-delete marker (`inventory.is_deleted = True`). The execution flow wraps all database mutations inside explicit `try...except` contexts that issue immediate `await db.rollback()` invocations on intercepting `IntegrityError` or runtime exceptions to block data pollution.

### 📋 Business Rules

* **Stock Restriction**: Stock quantity is only decreased by the corresponding value ordered. Cart allocations or active shopping bag items (`cart_quantity`) do not hold or deduct stock quantities.
* **Reservation Timeout Policy**: Inventory reservations placed on items inside checkout carts are locked to a strict one-hour expiration window. If the customer does not complete payment within this window, the pending checkout is canceled and the locked stock is dynamically reclaimed.
* **Reclaimed Order**: If a cancelled order is re-ordered, the system reclaims the respective stocks for an interval of 30 minutes, provided the active `stock_quantity` is greater than or equal to `OrderItem.quantity`.
* **Background Reconciliation** Inventory levels and status drifts are programmatically audited and reconciled in the background through scheduled Celery workers as a reliable fallback in case asynchronous HTTP lifecycle events fail.
  
---

## Core Endpoints

**Create Inventory**

`POST api/v1/inventory/create_inventory`

Creates an isolated inventory ledger record for a specified product.

**Request Payload**

```python
store_id: int
product_id: int
stock_quantity: int
```

**JSON Response**

```json
{"status": "success", "message": "inventory created"}
```

---

**Fetch Inventory**

`GET api/v1/inventory/store_inventory_list`

Fetches the paginated inventory levels of an isolated storefront. Results are capped at a maximum of 100 items per query.

**Request Payload**

```python
store_id: int
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```

**JSON Response**

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

**Update Inventory**

`PUT api/v1/inventory/update_inventory`

Increments the available stock quantity for the targeted inventory record.

**Request Payload**

```python
  store_id: int
  inventory_id: int
  stock_quantity: int
```

**JSON Response**

```json
{"status": "success", "message": "inventory updated"}
```

---

**Delete Inventory**

`DELETE api/v1/inventory/delete_inventory`

Executes a logical soft-delete of the targeted inventory record.

**Request Payload**

```python
 store_id: int
 inventory_id: int
```

**JSON Response**

```json
{"status": "success", "message": "inventory deleted"}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.

---

### Security Guardrails

* **400 Bad Request**: Dispatched upon downstream relational integrity violations or transaction failures.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **403 Forbidden**: Dispatched when an operator attempts to access, create inventory for a storefront where they have neither owner nor staff credentials.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.
