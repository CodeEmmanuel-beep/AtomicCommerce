# 💳 Membership Module

Governs store loyalty memberships, payment plan tiers, cascading subscription updates, multi-tenant administrative lookups, and lifecycle state transitions.

---

## 📡 Server-Client Interface

* **Dual-Entity Intent Architecture**: Coordinates nested tables during onboarding workflows by validating structural configurations (`membership_type`, `activation_type`) prior to persistence. It flushes a new parent record (`Membership`) to generate an automated unique key, maps it instantly into a child reference (`Subscription`), and evaluates configuration flags to conditionally apply pricing tiers:

    * **One-Time Transitions**: Maps flat costs from configuration values (`settings.Standard_Price`, `settings.Regular_Price`, `settings.Premium_Price`) while explicitly setting the remote payment processor marker to `None`.
    * **Recurring Subscriptions**: Injects dedicated subscription tokens (`settings.Standard`, `settings.Regular`, `settings.Premium`) while leaving flat prices blank to delegate variable capture to external billing layers.

* **Pessimistic Isolation and Lock Bounds**: Isolates membership modifications using explicit table constraints (`.with_for_update(of=Membership)`) across cross-cutting outer joins. This strategy shields active metadata lines from concurrent state conflicts while allowing un-indexed tracking tables to safely receive incoming edits.

* **Common Table Expression (CTE) Security Gateways**: Validates merchant system updates using conditional inline queries (`.cte("portal_access")`). The framework cross-references incoming identities using multi-tenant permission gates (`store_owners` or `store_staffs`) within a separate query execution step, preventing horizontal escalation before applying the main transaction update.



📐 **Architectural Decisions & Safeguards**:

* **Version-Keyed Key Invalidation**: Integrates a versioned distributed-caching design (`cache_version("member_key")`) to manage multi-tenant paginated view pipelines. Modifying an active account updates the central tracking version, rendering cached lists stale across the entire storefront application space without necessitating targeted scans of arbitrary user arrays.

* **Decoupled Async Cache Eviction**: Offloads transactional execution delays from the main server thread by passing cache invalidations (`member_global_invalidation`, `member_invalidation`) to an asynchronous background task queue (`background_task.add_task`). This guarantees that cache purges run completely out-of-band only after an engine transaction commit successfully clears.

* **Dual-Perspective Deletion Strategy**: Implements two separate logical erasure modes within a single endpoint. If executed with an administrative key, the filter targets explicit membership row records (`Membership.id == membership_id`); if called via a consumer context, it falls back to a tenant user match (`Membership.user_id == user_id`), updating historical markers (`delete_date`), clearing visibility properties, and queuing asynchronous out-of-band cache flushes securely.


### 📋 Business Rules

* **Coupled Logic**: Membership and Subscription data creation are tightly coupled and transactionally linked.
*  **Membership Update Restriction**: The `membership_type` can only be upgraded or downgraded in-app when there is no active subscription. If an active subscription exists, the user will be redirected to the Stripe checkout dashboard to manage changes.
*  **Single Membership Constraint**: Each user is restricted to a single membership per store via user constraint, if the user membership details are deleted and they want to create another membership,  they would be asked to contact support for reactivation or further assistance.
*  **Reactivation Restriction**: Only store owners or staff members can restore or reactivate a soft-deleted membership.
*  **Membership Deletion**: Both the consumer and store administrators (owners and staff) have permission to soft-delete a membership, allowing the store flexible control over access.
*  **Background Reconciliation**: Both membership and subscription activation statuses are reconciled using Celery workers to buffer asynchronous HTTP inconsistencies and mitigate logic drift from Stripe webhook payloads.

---

## Core Endpoint

**Create Membership**

`POST api/v1/member/create_membership`

Creates both membership and subscription records atomically.

**Request Payload**

```python
store_id: int
membership_type: str = Query("Regular", enum=["Standard", "Premium", "Regular"])
activation_type: str = Query("subscription", enum=["one_time", "subscription"])
```

**JSON Response**

```json
{"status": "success", "message": "membership created"}
```
---

**Fetch Membership**

`GET api/v1/member/selected_profiles`

Retrieves selected profiles filtered by status (`active_members`, `inactive_members`, or `deleted_members`) in a paginated format. This endpoint is strictly restricted to store owners and staff.

**Request Payload**

```python
 store_id: int
 member_status: str = Query(
        "active_members",
        enum=[
            "inactive_members",
            "deleted_members",
            "active_members",
        ],
    )
 page: int = Query(1, ge=1)
 limit: int = Query(10, le=100)
```

**JSON Response**

```json
{
  "status": "success",
  "message": "active_members",
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
        "membership_type": "Premium",
        "start_date": "2026-06-10T14:01:54.207191Z"
      },
      {
        "user": {
          "id": 7,
          "first_name": "James",
          "surname": "John"
        },
        "membership_type": "Premium",
        "start_date": "2026-06-11T13:05:12.233872Z"
      },
      {
        "user": {
          "id": 9,
          "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/31e443bd-07d8-419f-95c0-555a692ffdef_WIN_20250922_05_39_57_Pro.jpg",
          "first_name": "Ben",
          "surname": "Ek"
        },
        "membership_type": "Regular",
        "start_date": "2026-06-19T16:51:51.122821Z"
      }
     ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 3
    }
  }
}
```

---

**Membership Restoration**

`PUT api/v1/member/restore_profiles`

Allows store owners or staff to restore a previously soft-deleted membership.

**Request Payload**

```python
store_id: int
membership_id: int
```

**JSON Response**

```json
{"status": "success", "message": "membership restored"}
```

---

**Delete Membership**

`DELETE api/v1/member/delete_membership`

Executes a soft-delete on a membership. This action can be initiated by either the user or authorized store staff/owners.

**Request Payload**

```python
store_id: int
membership_id: int | None = None
```

**JSON Response**

```json
{"status": "success", "message": "membership deleted"}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.
* **verify_token**:  Decorator layer executing JWT decryption and validation checkpoints.

---

### Security Guardrails

* **400 Bad Request**: Dispatched during integrity constraint violations, database conflicts, or when schema/enum rules are violated.
* **401 Unauthorized**:  Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **404 Not Found**: Dispatched if the requested membership or subscription does not exist or has already been flagged as soft-deleted (`is_deleted=True`).
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.
