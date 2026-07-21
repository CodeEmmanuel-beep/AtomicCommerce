# 📊 Store Analytics Module

Governs merchant visibility dashboards, multi-dimensional gross profit aggregation engines, time-series volume performance filters, and stock tier monitoring arrays.

---

## 📡 Server-Client Interface

* **Multi-Clause Ownership Authorization Hook**: Evaluates profile metadata structures using an inline tuple extraction query (`select(Store, exists(...))`). It simultaneously confirms business clearance flags (`Store.approved.is_(True)`) and verifies if the profile matches verified credentials within the `store_owners` junction table before serving business intelligence details.

* **Net Revenue Financial Matrix**: Extends standard gross calculation routines by parsing raw operational logs across payment relationships. The arithmetic engine strips operational costs from standard ledger metrics to reveal true merchant gross sales, computing rolling performance tracking averages dynamically:



```math
merchant\_revenue = \sum(total\_amount) - \sum(shipping\_fee)
```



```math
avg\_sales\_per\_day = \frac{gross\_sales}{today - store\_founded\_date}
```



* **Time-Bound Flexible Product Ranking**: Provides rolling visibility insights by evaluating product orders across structured date limits (`relativedelta`). The system sorts items based on volume performance configurations, filtering by sales metrics (`func.sum(OrderItem.quantity)`) or customer satisfaction averages (`func.avg(Review.ratings)`) to isolate top or underperforming products.

* **Multi-Tenant Granular Data Isolation**: Guarantees that analytical queries strictly enforce tenant boundaries (`WHERE store_id = :store_id AND is_deleted = FALSE`). Cross-store data leaks are blocked at the ORM/Query builder level.


📐 **Architectural Decisions & Safeguards**:

* **Onboarding Visibility Fencing**: Protects overall analytical performance reports during initial startup phases by enforcing an absolute one-month maturity constraint. If the runtime check determines that the operational timeline is less than 30 days old (`today < target_store.founded + relativedelta(months=1)`), the system suspends metric delivery to allow meaningful baseline data collection.

* **Multi-Tier Inventory Classification Ranges**: Maps warehouse tracking records into discrete, segmented buckets based on remaining stock quantities. Relational filters isolate distinct ranges (such as `above_fifty`, `ten_below`, `out_of_stock`, or `total`) to construct real-time tracking lists, enabling merchants to monitor supply chain health without executing high-overhead sorting passes.

* **Context-Variant Analytical Key Tree**: Manages cache space efficiently by partitioning Redis entry footprints dynamically using signature string parameters. Tracking routes combine context flags, product IDs, and time boundaries into descriptive keys (`f"{slug}:{context}:{context_1}:{context_2}"`) to separate specific analytics views from general public storefront cache records.

### Business Rules

* **Role Isolation**: Public store statistics are publicly accessible, whereas internal operational metrics (inventory stats, revenue reports, detailed product rankings) are strictly restricted to verified Store Owners and authorized Platform Administrators.

* **Sales Calculation**: Revenue aggregations subtract shipping fees to ensure true merchant revenue metrics:

$$\text{total\\_gross\\_sales} = \text{total\\_amount} - \text{shipping\\_fees}$$


---

**View Public Statistics**

`GET api/v1/store_analytics/store_public_dashboard`

Retrieves public-facing performance metrics for a target storefront.

**Request Payload**

```python
  slug: str
```

**JSON Response**

```json
{
  "status": "success",
  "message": "store data successfully retrieved",
  "data": {
    "store_total_orders": 14,
    "last_order": "2026-07-16T16:12:08.783004Z",
    "top_performing_product": {
      "id": 2,
      "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
      "product_name": "MacBook",
      "product_size": "small",
      "quantity_sold": 150
    }
} 
```

---

**Fetch Inventory**

`GET api/v1/store_analytics/inventory_statistics`

Returns a list of inventory with the chosen `stock_range`.

```python  
  slug: str
  stock_range: str = Query(
        "ten_below",
        enum=[
            "thirty_below",
            "five_below",
            "twenty_below",
            "fifty_below",
            "out_of_stock",
            "above_fifty",
            "ten_below",
        ],
    )
```

**JSON Response**

```json
{
  "status": "success",
  "message": "inventory statistics for above_fifty range",
  "data": {
    "items": [
      {
        "id": 2,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "product_name": "Mac Book",
        "product_size": "small",
        "stock_quantity": 261
      },
      {
        "id": 6,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/939580eb-6b49-4c82-9829-b2880fecf540_Screenshot_2026-01-05_203517.png",
        "product_name": "Infinix",
        "Product_size": "small",
        "stock_quantity": 82
      },
      {
        "id": 5,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/ae73fe88-8972-4fc0-b68d-784a17a8d484_Screenshot_2026-01-05_203517.png",
        "product_name": "Samsung",
        "Product_size": "small",
        "stock_quantity": 60
      }
    ]
  }
}
```

---

**Store Current Performance**

`GET api/v1/store_analytics/store_performance_in_current_month`

Retrieves the current month's performance aggregates for authorized store owners.

**Request Payload**

```python
  slug: str
```

**JSON Response**


```json
{
  "status": "success",
  "message": "current performance",
  "data": {
    "orders_this_month": 2,
    "day_of_last_order": "2026-07-16T16:12:08.783004Z",
    "total_ratings_this_month": 3,
    "average_ratings_this_month": "4.7",
    "gross_sales_this_month": "5248.00",
    "highest_sales": {
      "date": "2026-07-03T17:04:18.793700Z",
      "sales": "4568.75"
    },
    "lowest_sales": {
      "date": "2026-07-15T18:03:44.740371Z",
      "sales": "679.25"
    },
    "daily_average": "249.90"
  }
}
```

---

**Fetch Product Statistics**

`GET api/v1/store_analytics/product_statistics`

Retrieves product performance statistics filtered by ranking criteria and target timeframes.

**Request Payload**

```python
  slug: str
  ranking: str = Query("top_product", enum=["least_product", "top_product"])
  time_frame: str = Query(
  "1 week", enum=["1 month", "3 months", "6 months", "1 year", "total", "1 week"]
  )
```

**JSON Response**

```json
{
  "status": "success",
  "message": "most sold products and most rated products in descending order",
  "data": {
    "product_sales": [
      {
        "id": 2,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "product_name": "MacBook",
        "product_size": "small",
        "quantity_sold": 150
      },
      {
        "id": 3,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
        "product_name": "iPad",
        "product_size": "small",
        "quantity_sold": 59
      },
      {
        "id": 1,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
        "product_name": "HP Laptop",
        "product_size": "small",
        "quantity_sold": 18
      }
    ],
    "product_ratings": [
      {
        "id": 3,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/8b68b937-9d4f-4e56-8e7c-052efad399f3_Screenshot_2025-11-01_184102.png",
        "product_name": "iPad",
        "product_size": "small",
        "ratings": "5.0"
      },
      {
        "id": 1,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/d94e1f63-a9b7-43cf-88a8-1dd6b0a845a6_project1.jpg",
        "product_name": "HP Laptop",
        "product_size": "small",
        "ratings": "4.5"
      },
      {
        "id": 2,
        "image": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/309ee1aa-e2eb-4ed1-b960-74ee276d1ab1_Screenshot_2025-10-25_160322.png",
        "product_name": "MacBook",
        "product_size": "small",
        "ratings": "3.0"
      }
    ]
  }
}
```
---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.

---

### Security Guardrail

* **400 Bad Request**: Dispatched when an invalid time_frame, ranking, or stock_range parameter is provided, or when a requested time_frame exceeds the store's total existence duration.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens via helper module.
* **403 Forbidden**: Dispatched during authorization failures via helper module.
---

