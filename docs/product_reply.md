# 💬 Product Reply Module

Governs the interactive consumer feedback threaded discussion layer, store hierarchy-prioritized thread sorting, social engagement metrics, and atomic response metadata tracking.

---

## 📡 Server-Client Interface

* **Verified Buyer Reply Gatekeeper**: Validates responding profiles against a transactional ledger pattern (`select(exists(...))`). It matches checking logic down to individual order line items (`OrderItem`) linked with active fulfillment loops (`OrderStatus.processing` or `OrderStatus.delivered`), ensuring only verified buyers of that specific product can interact with its review threads.

* **Decoupled Async Cache Eviction**: Offloads transactional execution delays from the main server thread by passing cache invalidations (`product_reply_invalidation`, `product_review_invalidation`) to an asynchronous background task queue (`background_task.add_task`). This guarantees that cache purges run completely out-of-band only after an engine transaction commit successfully clears.

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

* **Foreign Key Cascade Bounds**: Employs strong relational persistence design using database-level constraints:

$$\text{ForeignKeyConstraint}(\text{reply}.\text{review\\_id} \rightarrow \text{review}.\text{id}) \quad [\text{ON DELETE CASCADE}]$$
  
  If a consumer or platform operator wipes out a parent review entity, the underlying transaction execution automatically discards all linked text replies from active storage layout zones.


### Business Rules

* **Tenancy Inheritance**: A product reply must inherit the exact `store_id` boundaries of its parent review block. Cross-tenant posting is completely blocked.

* **Reply Restriction**: One reply per review thread per individual user profile.

---

## Core Endpoints

**Post Product Reply**

` POST api/v1/product_replies/create_product_reply`

Appends a threaded reply string to an active target review structure.

**Request Payload**

```python
reply: Reply
```

***Reply Object***

```python
class Reply(BaseModel):
    id: int | None = None
    store_id: int
    product_id: int | None = None
    review_id: int | None = None
    reply_text: str
```

**JSON Response**

```json
{"status": "success", "message": "reply successfully posted"}
```

---

**Fetch Replies**

`GET api/v1/product_replies/view_product_replies`

Retrieves all replies associated with a specific product review.

**Request Payload**

```python
product_id: int
review_id: int
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```

**JSON Response**

```json
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

**Delete Reply**

`DELETE api/v1/product_replies/product_reply_delete`

Erases a targeted reply directly. Restricted to the author of the reply.

**Request Payload**

```python
reply_id: int
review_id: int
```

```json
{"status": "success", "message": "deleted reply"}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.
* **verify_token**:  Decorator layer executing JWT decryption and validation checkpoints.

---


### Security Guardrails

* **400 Bad Request**: Dispatched during database integrity errors, unique compound key check violations, structural evaluation failures, or attempts to publish feedback from an unverified buyer account.
* **401 Unauthorized**: Dispatched when authentication credentials are missing, malformed, expired, or the supplied JWT fails validation.
* **404 Not Found**:  Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
