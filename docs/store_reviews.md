# 💬 Store Review Module

Governs verified-purchase consumer feedback loops, real-time rolling store metric aggregation engines, social reaction summaries, and automated cache eviction trees.

---

## 📡 Server-Client Interface

* **Verified-Purchase Gatekeeping Filter**: Restricts feedback submissions by assessing transactional history using an analytical subquery pattern (`select(exists(...))`). It verifies that the customer has a recorded order entry mapped to a finalized transaction status (`OrderStatus.processing` or `OrderStatus.delivered`) under the target storefront before allowing a review to be generated.

* **Row-Locked Aggregation Rolling Math**: Isolates catalog updates during review submissions by applying row-level table locks via `.with_for_update(of=Store)`. The engine calculates rolling average ratings and feedback counts in memory to prevent mathematical race conditions across parallel threads:



```math
new\_avg = \frac{(current\_avg \times current\_count) + ratings}{current\_count + 1}
```



* **Dynamic Correction Recalculation Loops**: Re-evaluates rolling statistics dynamically when a review is edited or removed. If a review's score changes, the system applies an adjustment formula to correct the store's average score without recalculating the entire table; if a review is deleted, it scales back the metrics using an update block (`update(Store)`) while clamping minimum boundaries to `0.0`:


```math
adjusted\_avg = \frac{(current\_avg \times current\_count) - former\_rating + ratings}{current\_count}
```

* **Multi-Tenant Review Isolation**: Guarantees that review analytics queries strictly enforce tenant boundaries (`WHERE store_id = :store_id`). Cross-store data leaks are blocked at the ORM/Query builder level.



📐 **Architectural Decisions & Safeguards**:

* **Transactional Anti-Duplication Boundary**: Restricts submissions to a single entry per storefront per user profile by scanning lookups for existing matches (`exists().where(Review.user_id == user_id), Review.store_id == review.store_id`) inside its locking clause. If an existing record matches, the thread throws a 400 Bad Request exception, preventing data duplication or artificial metric inflating across storefront paths.

* **Dual-Egress Background Eviction Tree**: Maximizes API read performance by serving requests from short-lived paginated cache keys (`ttl=30`) that are isolated by schema version numbers (`cache_version`). When a store review is created, modified, or deleted, the service offloads cache clearing to separate worker threads (`background_task.add_task`), running both `store_review_invalidation` and `store_invalidation` to guarantee data consistency across dependent modules.

### Business Rules

* **Purchase Verification**: A customer may only review a storefront after purchasing from it through a completed order.
* **Review Constraint**: Each customer may maintain only one active review per storefront.
* **Ratings Recalculation**: Updating a review recalculates aggregate store ratings metrics if ratings is altered.

---

## Core Endpoints

**Submit Store Review**

`POST api/v1/store_reviews/post_store_review`

Creates a verified buyer review entry linked to a specific store.

**Request Payload**

```python
review: Review
ratings: int = Query(0, le=5)
```

***Review Object***

```python
class Review(BaseModel):
    id: int | None = None
    product_id: int | None = None
    store_id: int
    review_text: str
```

**JSON Response**

```json
{"status": "success", "message": "review generated successfully"}
```

---

**Fetch Store Reviews**

`GET api/v1/store_reviews/view_store_reviews`

Retrieves a paginated collection of public, visible reviews for a target store.

**Request Payload**

```python
store_id: int
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```
### JSON Response

```json
{
  "status": "success",
  "message": "reviews",
  "data": {
    "items": [
      {
        "id": 10,
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "ratings": 4,
        "review_text": "Emmanuel Electronics is one of the most reliable sellers I’ve bought from on AtomicCommerce. My order was processed quickly, the product matched the description perfectly, and delivery was right on schedule. The packaging was secure, and customer service was polite and helpful when I reached out. It’s clear they value their customers, and I’ll continue shopping with Emmanuel Electronics for future electronics needs.",
        "store_review_reaction_count": 1,
        "reactions": {
          "like": 1
        },
        "time_of_post": "2026-07-01T20:51:05.424142Z"
      },
      {
        "id": 8,
        "user": {
          "id": 8,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
          "first_name": "Jacob",
          "middle_name": "Glory",
          "surname": "Israel"
        },
        "edited": true,
        "ratings": 5,
        "review_text": "I bought from Emmanuel Electronics through AtomicCommerce and had an excellent experience. The item was exactly as described, packaged securely, and delivered on time. Communication from the seller was clear and professional, and they responded quickly to my questions. It’s reassuring to know there are trustworthy vendors like Emmanuel Electronics on the platform. I’ll definitely shop with them again.",
        "store_reply_count": 2,
        "time_of_post": "2026-07-01T13:22:40.508280Z"
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

**Delete Store Review**

`DELETE api/v1/store_reviews/store_review_delete`

Deletes a targeted store review and cascade-purges all child replies from the system.

**Request Payload**

```python
store_id: int
```

**JSON Response**

```json
{"status": "success", "message": "review deleted"}
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
