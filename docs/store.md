# 🏪 Stores Module

Governs the storefront registration lifecycles, configuration editing regimes, owners and staffs onboarding, cross-role staff and owner permissions, and cascading hard/soft-deletion workflows.

---

## 📡 Server-Client Interface

* **Multi-Owner Store Registration Fencing**: Restricts multi-tenant profile instantiation to authorized users, validating requested parameters using clean regex validations (`^[\p{L}\s]+$`). The routine verifies that the target profile does not breach maximum asset thresholds (`store_count >= 10`) and validates existing taxonomy requirements within a synchronized subquery block.

* **Polymorphic Search Engine**: Enables unified catalog searches across products, categories, subcategories, or unique store names via a single polymorphic endpoint (GET api/v1/store/search_stores_global). Queries utilize versioned key-value cache signatures:

$$\text{Key} = \text{"store\_global\_view:v"}\dots$$

* **Immutable Name Modification & Appending**: Regulates configuration update patterns by tracking title-change states (`edited_name = True`). If a storefront profile modifies its commercial name once, future modification attempts are barred. For nested parameters (such as sub-categories), developers pass explicit mutation parameters (`update_type="add"` or `"replace"`), which use mathematical set unions (`current_sub_category.union(...)`) to append fresh metadata without destroying legacy assignments.

* **Personnel Escalation & Roster Ceilings**: Enforces explicit headcount boundaries on organizational rosters via multi-row constraint checks. Staff assignments prevent overlapping roles (blocking staff from acting as store owners and vice versa) and enforce explicit capacity metrics across the enterprise layout:


$$\text{Max Stores Per Owner} \le 10$$


$$\text{Max Employed Stores Per Staff Member} \le 2$$



📐 **Architectural Decisions & Safeguards**:

* **Advisory Locks for Personnel Realignment**: Mitigates concurrent race conditions when rewriting organizational rosters by invoking an explicit database session lock (`SELECT pg_advisory_xact_lock(:id)`). This isolates transaction states during personnel updates, preventing double-assignment flaws or out-of-bounds roster sizes under rapid network loads.

* **Pessimistic Isolation and Lock Bounds**: Isolates store profile mutations using explicit row-level locks (`.with_for_update()`) on the `store` table during concurrent `updates` and `soft-deletes`. This strategy shields store configuration lines from concurrent state conflicts.

* **Asynchronous Lateral Image Promotion**: Optimizes paginated global discovery feeds by combining a deterministic seed-based hashing mechanism (`func.md5(...)`) with a lateral subquery correlation loop. This structure surfaces exactly one prominent product profile alongside its primary storage link directly within the parent query scope, lowering processing overhead during random discovery queries.

* **Cascading Dependency Demolition**: Executes sweeping database invalidation passes during store deletion routines by combining targeted soft-deletes with hard file purges. While parent relationships (Stores, Inventory records, Financial accounts, and Addresses) are safely toggled via soft flags (`is_deleted = True`), associated nested tracking nodes (`ProductImage`) are permanently dropped from relational schemas, triggering an external script to clear out orphan object storage artifacts.

* **Fuzzy In-String Matching**: The core catalog engine uses Postgres case-insensitive pattern matching (`.ilike`) across structural query strings, allowing shoppers to retrieve highly relevant results using minimal character fragments.


### Business Rules

* **Owners Immunity**: Store staff can be removed from a roster; store owners cannot be removed.
* **Third Party Restrictions**: Stores cannot be created on behalf of third parties, the creator must include themselves as an owner for store provisioning to succeed.
* **Platform Approval Requirement**: Only stores explicitly approved by the platform owner or platform administrators are visible in global discovery feeds and eligible for commercial transactions (`approved = True`).
* **Store Deletion Authorization**: Store deletion workflows can only be initiated by verified store owners, platform administrators, or the platform owner.
* **Roster Access Hierarchy**: Store owners possess visibility across both the staff roster and the owner list; store staff can view their own roster but lack permissions to view the store's owner list.

---

## Core Endpoints

**Register Store**

`POST api/v1/store/create`

Provision a new merchant store profile linked to the authenticated user.

**Request Payload**

```python
    store_photo: UploadFile = File(...),
    store_name: str = Form(...),
    owners: str = Form(...),
    category: str = Form(...),
    sub_category: str = Form(...),
    store_email: str = Form(None),
    store_contact: str = Form(None),
```

**JSON Response**

```json
{"status": "success", "message":  "store created"}
```

---

**Fetch Stores**

`GET api/v1/store/search_stores_global`

Retrieves a paginated list of public operational data for active stores matching specified search criteria.

**Request Payload**

```python
  search_value: str
  search: str = Query(
  "category", enum=["category", "sub_category", "store_name", "product_name"]
  )
  seed: float = 0.5  
  page: int = Query(1, ge=1)
  limit: int = Query(10, le=100)
```

**JSON Response**

```json
{
  "status": "success",
  "message": "available 'hp' stores",
  "data": {
    "items": [
      {
        "id": 1,
        "business_logo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/325a35ac-2602-45d1-bed5-eef549ebd9a2_Screenshot_2025-11-14_023914.png",
        "store_photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/634e8496-7149-466e-98e3-d8e4bab86658_Screenshot_2025-11-25_140924.png",
        "store_name": "Emmanuel Electronics",
        "category_name": "Electronics & Technology",
        "sub_category": [
          "Computers & Tablets",
          "Mobile Phones & Accessories"
        ],
        "review_count": 2,
        "avg_rating": "4.50",
        "motto": "Powering Your World, One Innovation at a Time",
        "featured_product": {
          "id": 1,
          "product_name": "HP Laptop",
          "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
          "product_price": "650.00",
          "product_availability": "available",
          "avg_rating": "4.50",
          "inventory": {
            "stock_quantity": 39
          }
        },
        "shipping_fee": "2500.00",
        "store_description": "Welcome to Emmanuel Electronics, your one‑stop destination for premium electronics. We specialize exclusively in computers, laptops, mobile phones, and accessories — delivering the latest technology at unbeatable value.",
        "founded": "2026-05-26T13:23:15.997733Z"
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

**Update Store**

`POST api/v1/store/update`

Modifies branding, operational parameters, or contact options for a merchant store.

**Request Payload**

```python
    store_id: int,
    update_type: str = Query("add", enum=["add", "replace"]),
    store_photo: UploadFile = File(None),
    business_logo: UploadFile = File(None),
    store_name: str = Form(None),
    sub_category: str = Form(None),
    motto: str = Form(None),
    description: str = Form(None),
    store_contact: str = Form(None),
    store_email: str = Form(None),
    tax_rate: Decimal = Form(None),
    shipping_fee: Decimal = Form(None),
```

**JSON Response**

```json
{"status": "success", "message": "store updated"}
```

---

**Delete Store**

`DELETE api/v1/store/delete_store`

Initiates the cascading deletion sequence for a targeted store instance.

**Request Payload**
```python
  store_id: int
```

**JSON Response**

```json
{"status": "success", "message": "store deleted"}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.
* **get_supabase**: Retrieves the persistent Supabase client registered globally on `request.app.state.supabase` during the application lifecycle. This client handles binary streams directly for public storage buckets, avoiding client re-initialization penalties.

---

### Security  Guardrails

* **400 Bad Request**: Dispatched during database integrity failures, malformed form payloads, or invalid parameter inputs.
* **401 Unauthorized**: Dispatched when authentication credentials are missing, malformed, expired, or the supplied JWT fails validation.
* **403 Forbidden**: Dispatched if an unprivileged account attempts unauthorized store mutations, staff member role escalation, or if any caller targets a Platform Owner profile for deactivation.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
