# 📍 Delivery Address Module

The Delivery Address Module handles multi-tenant customer shipping profiles, order-address bindings, strict active fulfillment constraints, and multi-tenant read-through cache topologies. It ensures that storefront users can seamlessly manage multiple shipping destinations while maintaining strict logical isolation between different merchant store scopes.

---

## 📡 Server-Client Interface

* **Pessimistic Concurrency Boundings**: Enforces row-level isolation using explicit database locks (`.with_for_update()`) when allocating or altering address targets against active, non-deleted merchant orders (`Order.id == order_id`, `~Order.order_delete`). This prevents underlying fulfillment criteria from drifting over concurrent mutation workflows.

* **Logical Ownership Boundaries**: Prevents cross-tenant access. Every database operation on a shipping profile enforces a strict composite filter mapping both `Order.user_id` (from the authenticated session) and the active `store_id`. This prevents malicious users from querying, modifying, or deleting shipping destinations belonging to another client or storefront.

* **Distinct Deduplicated Aggregations**: Queries stored addresses using explicit `.distinct()` constraints and calculates total volume records by executing a matching distinct-count modifier inside the SQL aggregate function:



$$func.count(func.distinct(Address.id))$$



This prevents duplicate joins from inflating pagination counts.


* **Order Lifecycle Validation**: Protects active supply chains by blocking address removal calls if any linked order record deviates from completed or terminated transaction boundaries. The module iterates through preloaded tracking properties and drops the deletion attempt with a 400 Bad Request error if a linked checkout falls outside of `[OrderStatus.cancelled, OrderStatus.delivered]`.



📐 **Architectural Decisions & Safeguards**:

* **Decoupled Async Cache Eviction**: Offloads transactional execution delays from the main server thread by passing cache invalidations (`order_invalidation`, `order_address_invalidation`) to an asynchronous background task queue (`background_task.add_task`). This guarantees that cache purges run completely out-of-band only after an engine transaction commit successfully clears.

* **Dual-Layer Mutation Rollbacks**: Encapsulates all transactional changes—such as setting logical delete indicators (`address.is_deleted = True`) or updating array fields (`order.delivery_address`)—inside explicit, error-trapped database blocks. Any constraint collision or backend driver failure triggers an immediate `await db.rollback()` to protect the underlying order tracking parameters from partial execution fragments.


### 📋 Business Rules

* **Active Order Lock**: Any address currently linked to an order in `processing`, `shipped`, or `pending` state cannot be edited or soft-deleted until the order lifecycle transitions to `delivered` or `cancelled`.

* **Address Reuse Constraint**: Customers can only select and reuse addresses that have been previously linked to at least one completed or historic order. If an address was created but never successfully bound to an order, it is treated as an ephemeral draft and cannot be recalled or reused.

* **Address Change Restriction**: Shipping and delivery addresses can only be modified or reassigned while the target order remains in a pending state.

---

## Core Endpoints

**Add Delivery Address**

`POST api/v1/delivery_address/add_delivery_address`

Creates a new delivery address and links it to the intended parent order using a foreign key relationship via `order_id`.

**Request Payload**

```python
store_id: int
order_id: int
delivery_address: AddressDetails
```

***AddressDetails Object***

```python
class AddressDetails(BaseModel):
    street: str
    city: str
    state: str
    country: str
```


**JSON Response**

```json
{"status": "success", "message": "delivery address added successfully"}
```

---

**Fetch Delivery Address**

`GET api/v1/delivery_address/delivery_address_list`

Retrieves a paginated collection of delivery addresses linked to at least one existing order for an isolated storefront. Results are restricted to a maximum of 10 items per page with an upper ceiling limit of 100.

**Request Payload**

```python
store_id: int
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```

**JSON Response**

```json
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

**Delete Delivery Address**

`DELETE api/v1/delivery_address/delete_delivery_address`

Performs a logical soft-delete of target addresses, provided all associated orders are in `cancelled` or `delivered` states.

**Request Payload**

```python
 store_id: int
 address_id: int
```

**JSON Response**

```json
{"status": "success", "message": "delivery address deleted successfully"}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.
* **verify_token**:  Decorator layer executing JWT decryption and validation checkpoints.

---

### Security Guardrails

* **400 Bad Request**: Dispatched during integrity constraint violations, or when trying to delete or alter an address locked inside an active, non-finalized shipment lifecycle.
* **401 Unauthorized**:  Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **404 Not Found**: Dispatched if the requested `address_id` does not exist or has already been flagged as soft-deleted (`is_deleted=True`).
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.
