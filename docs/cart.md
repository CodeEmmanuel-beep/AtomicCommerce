# 🛒 Shopping Cart Module

The Cart module manages a user's pre-checkout shopping session by maintaining cart state, validating inventory availability, applying business constraints, and preparing items for the checkout pipeline.

### 📡 Server-Client Interface

* **Pessimistic Concurrency Layout**: Implements explicit row-level locking via SQLAlchemy's `.with_for_update()` when querying active `Cart` or `CartItem` schemas during modifications (`add_item_to_cart`, `edit_quantity`, `update_cart`, `delete_one`). This freezes the target row states directly inside the PostgreSQL engine to prevent race conditions during simultaneous catalog interactions.


* **Availability & Constraint Verification**: Validates storefront existence (`Store.is_deleted.is_(False)`), multi-table joins ensuring item stock capacity (`Inventory.stock_quantity >= quantity`), availability markers (`Product.product_availability == "available"`), and enforces a hard ceiling of **30 unique line items** per cart configuration.


* **Versioned Caching Topology**: Utilizes a split key caching format incorporating a dynamic version string (`cart_key` via `cache_version`) to manage localized user lookups under a hardcoded `ttl=3600` (1 hour). Write operations and state modifications invoke the `cart_invalidation(user_id)` routine to flush stale records synchronously.


📐 **Architectural Decisions & Safeguards**:

> 💡 **All-or-Nothing Mutation Guarantees**
> Encapsulates all data alterations (`db.add`, `db.delete`, quantity deltas) inside explicit `try...except` transaction wrappers capturing `IntegrityError` and global exceptions. Any state mutation block failure invokes an immediate `await db.rollback()` before re-raising errors to completely shield the transactional tracking ledger from partial updates or database drift.


* **Auto-Cleaning Sanitize Routines (`update_cart`)**: Features a localized reconciliation routine that parses an active cart, detects items matching deleted products (`item.product.is_deleted`) or items exceeding current warehouse numbers (`stock_quantity < item.quantity`), and executes atomic bulk deletes (`delete(CartItem).where(CartItem.id.in_(...))`) to reconcile states prior to billing handoffs.

### 📋 Business Rules

* **Capacity Cap**: Strict maximum limit of 30 unique line items per cart.
* **Active Cart Limit**: Exactly one unchecked-out cart permitted per user context.
* **Duplication Logic**: Adding an identical item twice results in an increment of quantity (**addition**), not field substitution.
* **Mutation Logic**: Modifying an existing cart item's size/quantity directly overwrites the previous configuration (**substitution**), not addition.
* **Stock Isolation**: Active cart items do not reserve or affect physical warehouse `stock_quantity` metrics until checkout initialization.


### Core Endpoints

**Add To Cart**

`POST api/v1/cart/add_to_cart`

Couples both cart initialization and the initial line-item addition into a single transaction block for an optimized user experience.

**Request Payload**

```python
 store_id: int
 product_id: int
```

**JSON Response**

```jsonc
{"status": "success", "message": "product added to cart"}
```

---

**Fetch Cart**

`GET api/v1/cart/fetch_cart`

Returns a parent-child JSON structure containing core cart calculations paired with its associated list of paginated items.

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

**Edit Quantity**

`PUT api/v1/cart/edit_quantity`

Substitutes the previous item count configuration with the newly provided quantity value.

**Request Payload**

```python
store_id: int
cart_id: int
cartitem_id: int
new_quantity: int = Query(1, ge=1)
```

**JSON Response**

```jsonc
{"status": "success", "message": "cart item quantity updated"}
```

---

**Delete Cart**

`DELETE api/v1/cart/delete_cart`

Clears out the parent cart entity and cascade-deletes all associated child item relationships from the schema.

**Response Payload**

```python
 store_id: int
 cart_id: int
```

**JSON Response**

```jsonc
{"status": "success", "message": "cart emptied"}
```

---

⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.


---
### Security Guardrails

* **400 Bad Request**: Dispatched upon downstream relational integrity violations, attempts to select deleted catalogs, or requests exceeding warehouse tracking limits.
* **404 Not Found** Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.
