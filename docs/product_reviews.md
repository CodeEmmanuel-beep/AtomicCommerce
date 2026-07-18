# 💬 Product Review Module

Governs verified-purchase consumer feedback loops, real-time multi-tenant rolling product metric aggregation engines, social reaction summaries, and automated cache eviction trees.

---

## 📡 Server-Client Interface

* **Verified-Purchase Gatekeeping Filter**: Restricts feedback submissions by assessing transactional history using an analytical subquery pattern (`select(exists(...))`). It verifies that the customer has a recorded item entry (`OrderItem`) mapped to a finalized transaction status (`OrderStatus.processing` or `OrderStatus.delivered`) before allowing a review to be generated.

* **Row-Locked Aggregation Rolling Math**: Isolates catalog updates during review submissions by applying row-level table locks via `.with_for_update(of=Product)`. The engine calculates rolling average ratings and feedback counts in memory to prevent mathematical race conditions across parallel threads:


```math
new\_avg = \frac{(current\_avg \times current\_count) + ratings}{current\_count + 1}
```

* **Dynamic Correction Recalculation Loops**: Re-evaluates rolling statistics dynamically when a review is edited or removed. If a review's score changes, the system applies an adjustment formula to correct the product's average score without recalculating the entire table; if a review is deleted, it scales back the metrics using an update block (`update(Product)`) while clamping minimum boundaries to `0.0`:


```math
adjusted\_avg = \frac{(current\_avg \times current\_count) - former\_rating + ratings}{current\_count}
```

* **Multi-Tenant Sentiment Isolation**: Validates that both the reviewer, the target product, and the parent store share matching structural ecosystem domains. Reviews are explicitly tagged with `store_id` and `product_id`, guaranteeing that concurrent search engine queries or dashboard statistics never bleed cross-tenant review metrics.


📐 **Architectural Decisions & Safeguards**:

* **Transactional Anti-Duplication Boundary**: Restricts submissions to a single entry per item per user profile by scanning lookups for existing matches (`exists().where(Review.user_id == user_id)`) inside its locking clause. If an existing record matches, the thread throws a 400 Bad Request exception, preventing data duplication or artificial metric inflating across storefront paths.

* **Dual-Egress Background Eviction Tree**: Maximizes API read performance by serving requests from short-lived paginated cache keys (`ttl=30`) that are isolated by schema version numbers (`cache_version`). When a review is created, modified, or deleted, the service offloads cache clearing to separate worker threads (`background_task.add_task`), running both `product_review_invalidation` and `product_invalidation` to guarantee data consistency across dependent modules.

* **Idempotent Single-Review Enforcement**: Prevents rating manipulation by establishing a unique compound key constraint in the database layer:

                        $$\text{UniqueConstraint}(\text{user\_id}, \text{product\_id})$$

  A consumer is restricted to exactly one active review per product. Subsequent mutation requests update the existing record rather than generating a new entity.

* **Cascade Suppression Trees**: Implements relational data integrity through clean hard-deletion sweeps. If a parent review entity is removed from the active catalog ledger, child dependencies such as text replies are cascade deleted automatically from the database layer.


###  Business Rules

* **Purchase Verification**: A customer may only review a product after purchasing it through a completed order.

* **Review Constraint**: Each customer may maintain only one active review per product.

* **Ratings Recalculation**: Updating a review recalculates aggregate product metrics.

---

## Core Endpoints

**Submit Product Review**

`POST api/v1/product_reviews/post_product_review`

Creates or updates a verified buyer review entry linked to a specific item.

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

**Fetch Product Reviews**

`GET api/v1/product_reviews/view_product_reviews`

Retrieves a paginated collection of public, visible reviews for a target product.

**Request Payload**

```python
product_id: int
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```

**JSON Response**

```json
{
  "status": "success",
  "message": "reviews",
  "data": {
    "items": [
      {
        "id": 4,
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "review_text": "This HP laptop is excellent. It boots up within seconds and handles multi-tasking effortlessly. The keyboard is very comfortable to type on, the battery life holds up well throughout the day, and it doesn't get hot or loud. If you're looking for a reliable, fast machine for work or everyday use, this is a great choice.",
        "ratings": 4,
        "product_review_reaction_count": 2,
        "reactions": {
          "love": 1,
          "wow": 1
        },
        "time_of_post": "2026-06-27T14:18:13.748646Z"
      },
      {
        "id": 3,
        "user": {
          "id": 8,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
          "first_name": "Jacob",
          "middle_name": "Glory",
          "surname": "Israel"
        },
        "review_text": "I am really impressed with this HP product. It boots up incredibly fast, runs smoothly, and handles all my daily tasks without any lag. The screen is clear and the design feels solid. Great value for money and highly recommended!",
        "ratings": 5,
        "product_reply_count": 1,
        "product_review_reaction_count": 2,
        "reactions": {
          "like": 1,
          "love": 1
        },
        "time_of_post": "2026-06-27T13:11:38.901985Z"
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

**Delete Review**

`DELETE api/v1/product_reviews/product_review_delete`

Deletes a targeted review and cascade-purges all child replies from the system.

**Request Payload**

```python
store_id: int
product_id: int
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
