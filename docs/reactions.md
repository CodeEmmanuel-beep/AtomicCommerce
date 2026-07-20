# 🎭 Reactions Module

Governs the user engagement loop, polymorphic social reaction tracking, dynamic telemetry count management, and multi-tenant cache eviction across product and store review threads.

---

## 📡 Server-Client Interface

* **Polymorphic Target Isolation Guard**: Restricts inputs to ensure a reaction applies to exactly one entity type by validating incoming parameters. The route throws a 409 Conflict exception if a user passes both `reply_id` and `review_id` simultaneously, or if it receives an empty structural payload (`reply_id is None and review_id is None`).

* **Dynamic Telemetry Field Mapping**: Determines target contexts by checking relationship attributes (`target.product`). It dynamically constructs model fields using text composition (`f"{prefix}_{suffix}"`) to map interactions across four explicit counters: `product_review_reaction_count`, `store_review_reaction_count`, `product_reply_reaction_count`, or `store_reply_reaction_count`.

* **Three-Way Toggle State Machine**: Modifies database rows sequentially based on existing record presence and input matching. If an entry matches both user and target, providing the same type triggers a soft removal (`db.delete`) while decrementing counters; providing a new type updates the interaction type inline, whereas an empty state generates a new transaction record (`React`).

📐 **Architectural Decisions & Safeguards**:

* **Volatile Caching Hierarchies**: Deploys a tiered distributed caching architecture for `reactions_list` endpoint using short-lived keys (`reactions_list:{user_id}:{review_id}:{reply_id}:{page}:{limit}`) holding a hardcoded `ttl=30` (30 seconds) for paginated lists. This structure balances immediate public catalog discoverability with minimal stale-data margins.

* **Enumerated Value Enforcement**: Safeguards data models against invalid inputs by routing incoming strings through standard verification types (`ReactionType(reaction_type)`). Any parsing failure triggers an execution catch block that yields a 400 Bad Request error, isolating the relational engine from corrupted inputs.

* **Pessimistic Isolation and Lock Bounds**: Isolates state modifications using explicit row-level locks (`.with_for_update()`) across `review`, `reply`, and `react` tables. This strategy shields active metadata lines from concurrent race conditions during high-volume reaction toggles.

* **Targeted Cache Eviction Worker Routing**: Orchestrates worker tasks based on mapped field outputs to clear relevant caches dynamically (`background_task.add_task`). Depending on the context, it invalidates cache engines across product reviews, store reviews, product replies, or store replies to keep consumer dashboards accurate and synchronous.

### Business Rules

* **Target Exclusivity**: A reaction payload must target either a `review_id` or a `reply_id`, never both simultaneously and never neither.
* **Allowed Reaction Types**: The reaction_type attribute must strictly match pre-approved domain keys (e.g., `like`, `love`, `angry`, `laugh`, `wow`, `sad`).
* **Self-Interaction Policy**: Authenticated users are permitted to react to their own reviews or replies.

---

## Core Endpoints

**Toggle Reaction**

`POST api/v1/reactions/react`

Creates, updates, or removes a social reaction on a target review or reply.

**Request Payload**

```python
 reaction_type: ReactionType
 reply_id: int | None = None
 review_id: int | None = None
```

***ReactionType Enum***

```python
class ReactionType(str, Enum):
    like = "like"
    love = "love"
    laugh = "laugh"
    wow = "wow"
    sad = "sad"
    angry = "angry"
```

**JSON Response**

```json
{"status": "success", "message": "Reaction added", "data": "like"}
```

***Note***: If a user re-submits the exact same reaction on an already reacted item, the engine toggles it off, returning `"message": "Reaction deleted"`. 

---

**Fetch Reactions**

`GET api/v1/reactions/reactions_list`

Retrieves a paginated collection of reactions associated with a target review or reply, including profile metadata for users who reacted.

**Request Payload**

```python
 review_id: int | None = None
 reply_id: int | None = None
 page: int = Query(1, ge=1)
 limit: int = Query(10, le=100)
```

**JSON Response**

```json
{
  "status": "success",
  "message": "reactions",
  "data": {
    "items": [
      {
        "id": 16,
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "reaction_type": "wow",
        "time_of_reaction": "2026-06-29T12:09:47.531526Z"
      },
      {
        "id": 3,
        "user": {
          "id": 10,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/ee7ef925-93cb-47c3-9790-2f6579b07f63_payment_json_response.png",
          "first_name": "Great",
          "middle_name": "juan",
          "surname": "God"
        },
        "reaction_type": "love",
        "time_of_reaction": "2026-06-27T15:32:54.618447Z"
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

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.

---

### Security Guardrails

* **400 Bad Request**: Dispatched upon relational integrity violations, supplying an invalid reaction type, or database operation failures.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **409 Conflict**: Dispatched when both `review_id` and `reply_id` are populated or when neither is populated.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
