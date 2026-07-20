# 📦 Product Module

Governs the digital marketplace catalog, secure multi-media asset provisioning, cross-tenant inventory boundaries, transactional stock allocation safety controls, structured hierarchical taxonomy enforcement, and conditional inventory suppression engines.

---

## 📡 Server-Client Interface

* **Secure Cloud-Storage Ingestion Hooks**: Pairs multi-tenant product additions with direct cloud bucket integrations (`get_supabase.storage.from_`). The pipeline enforces rigorous content-type screening against explicit image formats (`image/jpeg`, `image/png`, `image/webp`), sanitizes string profiles into universally unique identifiers (`uuid.uuid4`), and maps safe filenames into the database layer.

* **Taxonomy & Sub-Category Subqueries**: Validates matching entries by performing strict matching logic against storefront category constraints. It screens inputs using whitespace trimming and down-casing comparisons (`func.trim(SubCategory.name) == sub_category_name.strip()`), raising a 409 Conflict if a vendor attempts to upload items into unassigned catalog branches.

* **Hierarchical Classification Engines**: Establishes parent-child relationships through an explicit recursive taxonomy map where a SubCategory is bound structurally under a root Category. The validation framework prevents cyclic dependencies by verifying that a new category or sub-category cannot assign an active child record as its parent node, keeping data structures strictly directed and acyclic.

* **Multi-Tenant Catalog Isolation**: Couples structural product definitions with dynamic store domain filters. Products are strictly bound to individual store contexts (store_id), ensuring that inventory, metadata queries, and search index sweeps never cross tenant domains during concurrent executions.

* **Orphaned Asset Invalidation Loops**: Prevents storage resource leakage during execution failures via transactional exception tracking. If a core metadata database modification triggers an `IntegrityError` or an unexpected application halt, a cleanup task (`cleaned_up`) runs to remove orphaned binary files from storage.

* **Polymorphic Evaluation Pipeline**: The catalog lookup endpoint implements a polymorphic search architecture allowing clients to query products via product_name, category, or sub_category. Results are dynamically ordered based on targeted runtime matrices:

    * **"cheap"**: Evaluates by sorting unit values incrementally (Product.product_price.asc()).
    * **"quality"**: Evaluates by consumer satisfaction signals (Product.avg_rating.desc(), Product.review_count.desc()).
    * **"latest"**: Evaluates structural adjustments chronologically (Inventory.last_updated.desc()).


📐 **Architectural Decisions & Safeguards**:

* **Seed-Deterministic Pseudo-Random Sorting**: Implements performant marketplace catalog generation by introducing a consistent randomizing factor (`seed`). Listing pipelines apply low-overhead md5 hashing combinations (`order_by(func.md5(func.concat(cast(Product.id, String), str(seed))))`) to shuffle product visibility predictably across paginated boundaries, avoiding costly index-breaking array sorts.

* **Soft Deletion Suppression Trees**: Transitions records out of consumer view without breaking historical integrity by chaining cascade blocks. Triggering a delete sets an explicit visibility state (`Product.is_deleted = True`) and runs an update query (`update(Inventory)`) to suppress corresponding warehouse slots while simultaneously dropping secondary files (`delete(ProductImage)`).

* **Concurrent Global Invalidation Matrix**: Controls global cache consistency when catalog states change by running parallel non-blocking workers (`asyncio.gather`). Modifications instantly clear dependent caches, evicting stale data fragments simultaneously across three modules: `cart_global_invalidation`, `order_global_invalidation`, and `product_invalidation`.

* **Fuzzy In-String Matching**: The core catalog engine uses Postgres case-insensitive pattern matching (`.ilike`) across structural query strings, allowing shoppers to retrieve highly relevant results using minimal character fragments.

### Business Rules

* **Store Ownership Authorization**: Prior to executing a product creation, modification, or structural deletion, strict store authentication layer checks are performed. Mutating actions are restricted exclusively to authorized store owners and assigned staff members.

* **Primary Media Mandate**: While supplementary media galleries are optional, every single product listing must possess at least one designated image flagged as the `primary_image`.

* **Asymmetric Data Purges**: Supplementary product images can be completely purged and their underlying assets hard-deleted from cloud storage. However, the root product entity and its original `primary_image` entry are strictly restricted to soft-deletion states for downstream auditing and historical ledger integrity.


---

## Core Endpoints

**Create Product**

`POST api/v1/product/add_product`

Creates a unique product entry linked to a specific category and sub-category branch.

**Request Payload**

```python
store_id: int = Form(...)
sub_category_name: str = Form(...)
primary_image: UploadFile = File(...)
product_name: str = Form(...)
product_type: str = Form(...)
product_size: str = Query(
        "small", enum=["small", "medium", "large", "extra_large"]
)
product_price: Decimal = Form(...)
product_description: str = Form(...)
```
**JSON Response**
```json
{"status": "success", "message": "product added to shelve"}
```

**Fetch Product**

`GET api/v1/product/search_products`

Retrieves a filtered collection of discoverable items assigned to a target store domain.

**Request Payload**

```python
seed: float = 0.5
filters: str = Query(None, enum=["cheap", "quality", "latest"])
product_name: str | None = None
category: str | None = None
sub_category: str | None = None
page: int = Query(1, ge=1)
limit: int = Query(10, le=100)
```

**JSON Response**

```json
{
  "status": "success",
  "message": "products data",
  "data": {
    "items": [
      {
        "id": 1,
        "product_name": "HP Laptop",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
        "product_type": "HP EliteBook 840 G6 TOUCHSCREEN intel Core i5-16GB RAM/512GB SSD",
        "product_price": "650.00",
        "avg_rating": "4.50",
        "review_count": 2,
        "product_size": "small",
        "product_description": "The HP EliteBook 840 G6 is a premium 14‑inch business laptop designed for professionals, offering strong performance, advanced security features, and a slim aluminum design. It balances portability with enterprise‑grade reliability, making it ideal for office and mobile work",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 39
        }
      },
      {
        "id": 3,
        "product_name": "iPad",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
        "product_type": "7 inch i Pad",
        "product_price": "1000.00",
        "avg_rating": "5.00",
        "review_count": 1,
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 50
        }
      },
      {
        "id": 6,
        "product_name": "Infinix",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/939580eb-6b49-4c82-9829-b2880fecf540_Screenshot_2026-01-05_203517.png",
        "product_type": "A 38",
        "product_price": "950.00",
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 82
        }
      },
      {
        "id": 2,
        "product_name": "MacBook",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "product_type": "Apple product",
        "product_price": "1200.00",
        "avg_rating": "3.00",
        "review_count": 2,
        "product_size": "small",
        "product_description": "great innovation ",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 261
        }
      },
      {
        "id": 4,
        "product_name": "Power Bank",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/bb87c9fb-bd60-4340-a6e5-ad2e6bfd82df_Screenshot_2026-01-05_203517.png",
        "product_type": "50000 mAH",
        "product_price": "200.00",
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "out_of_stock",
        "inventory": {
          "stock_quantity": 0
        }
      },
      {
        "id": 5,
        "product_name": "Samsung",
        "primary_image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/ae73fe88-8972-4fc0-b68d-784a17a8d484_Screenshot_2026-01-05_203517.png",
        "product_type": "A38",
        "product_price": "950.00",
        "product_size": "small",
        "product_description": "premium product",
        "product_availability": "available",
        "inventory": {
          "stock_quantity": 60
        }
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 6
    }
  }
}
```

---

**Delete Product**

`DELETE api/v1/product/delete`

Flags an active product for soft-deletion and cleanses secondary asset files.

**Request Payload**

```python
store_id: int
product_id: int
```

**JSON Response**

```json
{
  "status": "success",
  "message": "deleted product",
  "data": {
    "id": 5,
    "user_id": 22,
    "deleted": true
          }
}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.
* **get_supabase**: Retrieves the persistent Supabase client registered globally on `request.app.state.supabase` during the application lifecycle. This client handles binary streams directly for public storage buckets, avoiding client re-initialization penalties.

---

### Security  Guardrails

* **400 Bad Request**: Dispatched upon database integrity violations, invalid image content-type filters, executing the search endpoint without providing any query parameters, trying to upload more than 5 product images, or generic transaction failures.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **409 Conflict**: Raised when a product is assigned to a sub-category that is not associated with the target store.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---

---
