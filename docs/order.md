# 📦 Order Module: Architectural Blueprint

Governs multi-tenant consumer checkout lifecycles, precision tax and discount computations, distributed transactional inventory reservation fencing, and session-expiration gatekeeping loops.

---

## 📡 Server-Client Interface

* **Pessimistic Stock Reservation & Inventory Fencing**: Isolates transactional order items against high-concurrency races by locking target records inside explicit database blocks using `.with_for_update()`. It validates matching catalog entries (`Inventory.product_id.in_(product_ids)`) and rejects checkout requests with a 400 Bad Request exception if a cart item violates availability thresholds, exhibits a cross-tenant store mismatch, or runs into insufficient warehouse quantities.

* **Precision Fixed-Point Financial Math**: Calculates pricing properties, loyalty discounts, shipping variables, and tax liabilities utilizing precise fixed-point decimal arithmetic (`Decimal`). Totals are normalized using standard financial rounding rules (`.quantize(Decimal("0.01"))`) to prevent precision drift across tax tiers and membership matrix rules:


```math
total\_amount = (subtotal + shipping\_fee + tax\_amount) - discount\_amount
```

* **State-Driven Multi-Tier Expiration Gates**: Evaluates transactional session windows using dynamic temporal thresholds (`created_at` or `re_order_time` checkpoints). If a buyer navigates to the payment portal after a transaction boundary lapses (e.g., more than 1 hour post-creation or 30 minutes post-reactivation), the engine triggers an automatic cleanup phase—marking the checkout status as `OrderStatus.cancelled`, executing inventory restock hooks (`restore_inventory`), and soft-deleting the expired session record.


📐 **Architectural Decisions & Safeguards**:

* **Atomic Cart Invalidation Isolation**: Couples order creation tracking with atomic, non-blocking checkouts by implementing conditional backend modifications (`update(Cart).values(check_out=True).returning(Cart.id)`). If the database query yields an empty row pattern, the system short-circuits the pipeline with a 409 Conflict exception to block double-checkout exploits across concurrent request paths.

* **Dual-Perspective Cache Eviction Trees**: Protects data freshness by running explicit, out-of-band invalidation clusters (`order_invalidation`, `cart_invalidation`) inside concurrent event threads (`asyncio.gather`). It pairs these background steps with shared version tags (`cache_version("order_key")`) to render entire storefront cache fragments invalid instantly across global cluster profiles when structural changes occur.

* **Pessimistic Concurrency Control**: Implements database row-level isolation via SQLAlchemy's `.with_for_update()` on targeted order and cart rows during order creation and structural modifications. It locks matching records to secure high-concurrency writes while utilizing preloaded execution trees (selectinload or joinedload) to prevent database deadlock conditions.

* **Fail-Safe Reconciliation**: On-demand HTTP cancellation endpoints paired with automated Celery sweep workers. Ensures immediate inventory release when requested, while guaranteeing abandoned orders are systematically cleaned up even without client interaction.



### 📋 Business Rules

* **Re-Order Constraint**: Allowed exactly once per invalidated order. It requires absolute confirmation of active stock availability.

* **Order Cancel Constraint**: Only pending orders can be cancelled.

* **Process Order Constraint**: Only orders with a valid, fully completed delivery address can transition to processing/shipped.

* **Discount Boundaries**: Loyalty discounts are strictly calculated on the subtotal. Tax and shipping values are calculated independently and appended at face value.


---

### Core Endpoints

**Create Order**

`POST api/v1/order/create_order`

Verifies if the required quantities are available in stock, atomically creates the order and order items, marks the cart as checked out, reserves warehouse stock, and computes the subtotal and total values.

**Request Payload**

```python
store_id: int
cart_id: int
```

**JSON Response**

```json
{
"status": "success",
"message": "order item successfully created",
"data": "you have one hour to check out the order, order_id: 56"
}
```

---

**Fetch Orders**

`GET api/v1/order/view_orders`

Retrieves paginated order histories. This endpoint is accessible only by consumers, strictly restricted to their own orders and authorized tenant stores.

**Request Payload**

```payload
store_id: int
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```

**JSON Response**

```json
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

**Cancel Order**

`POST api/v1/order/cancel_order`

Transitions order state to canceled and releases reserved inventory back to the active store warehouse pools.

**Request Payload**

```python
store_id: int
order_id: int
```

```json
{"status": "success", message": "order cancelled"}
```

---

**Delete Order**

`POST api/v1/order/delete_order`

Executes a soft-delete on the selected order in the selected store context.

```python
store_id: int
order_id: int
```

**JSON Response**

```json
{"status": "success":, "message": "order deleted"}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.

---

### Security  Guardrails

* **400 Bad Request**: Dispatched upon downstream relational integrity violations or transaction failures.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **409 Conflict**: Dispatched when a cart is about to be checked out twice or when an invalidated order is being processed.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
