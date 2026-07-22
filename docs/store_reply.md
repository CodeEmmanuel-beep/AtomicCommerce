# 💬 Store Reply Module

Governs the interactive lifecycle of storefront review responses, validating structural role authorization, compiling multi-dimensional reaction counts, and executing transactional counter corrections.

---

## 📡 Server-Client Interface

* **Role-Bounded Cross-Examination Hook**: Evaluates structural privileges during comment processing to isolate authorized merchant personnel from regular customers. By deploying inline table evaluation layers (`exists()`) wrapped around the core identity schema, the verification engine simultaneously determines ownership flags (`store_owners`) and staff clearances (`store_staffs`). It matches them against the underlying review record to ensure only the original reviewer or verified store operators can publish remarks.

* **Asynchronous Cache Eviction Pipelines**: Minimizes API thread blockage by offloading Redis entry footprint invalidations to secondary background tasks (`background_task.add_task`) immediately following database mutations. The service purges cached visibility trees for both nested responses and parent evaluation structures synchronously upon every successful insertion, rewrite, or deletion cycle:


```math
Cache\_Version\_Scope = f"store\_reply\_key:\{store\_id\}"
```



* **Transactional Counter Invalidation Safeguards**: Protects cumulative analytical metrics from drift during destructive deletion passes by wrapping updates within explicit lock blocks (`with_for_update`). When a comment is purged from the database, the system queries the associated parent row and decrements its total feedback metric safely, bounding the metric to prevent negative value flaws:


```math
store\_reply\_count = \max(0, store\_reply\_count_{current} - 1)
```

* **Multi-Tenant Reply Isolation**: Guarantees that response actions and queries strictly enforce tenant boundaries (`WHERE store_id = :store_id AND is_deleted = FALSE`). Cross-store response mutations are blocked at the ORM/Query builder level.


📐 **Architectural Decisions & Safeguards**:

* **Idempotent Content Mutation Controls**: Suppresses unnecessary transaction overhead at edit endpoints by cross-referencing inbound text parameters against existing row metrics before executing database commits. If the revised text completely matches the current persistent state, the database commit is bypassed entirely and a lightweight code status (`HTTP_204_NO_CONTENT`) is returned to the client.

* **Aggregated Batch Reaction Summaries**: Lowers communication costs across high-traffic message boards by evaluating reaction records in batches. Instead of issuing individual subqueries for each response row, the engine maps primary array keys (`reply_ids`) into a collective aggregation utility (`react_summary`), returning pre-compiled reaction counts within paginated collection feeds.

* **Dynamic State Mutation Triggers**: Enforces accountability across message boards by monitoring content alterations. When an author modifies an existing entry, the operational routine alters the tracking flag (`edited = True`), signaling to consumers that the message has been modified from its original post state.


### Business Rules

* **Tenancy Inheritance**: A store reply must inherit the exact `store_id` boundaries of its parent review block. Cross-tenant posting is completely blocked.

* **Reply Restriction**: Only the store owners, staffs, and original reviewer can reply.

---

## Core Endpoints

**Post Store Reply**

`POST api/v1/store_replies/create_store_reply`

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

`GET api/v1/store_replies/view_store_replies`

Retrieves all replies associated with a specific store review.

**Request Payload**

```python
store_id: int
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
        "id": 6,
        "edited": true,
        "user": {
          "id": 5,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/82c8ca02-96a4-47a1-92ac-58df63d559b8_passport_image.png",
          "first_name": "Sandra",
          "surname": "Eke"
        },
        "reply_text": "Thank you for your patronage, Mr. James, hope to serve you again. Peace and Love.",
"store_reply_reaction_count": 1,
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

**Delete Store Reply**

`DELETE api/v1/store_replies/store_reply_delete`

Erases a targeted reply directly. Restricted to the author of the reply.

**Request Payload**

```python
reply_id: int
review_id: int
```

**JSON Response**

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
