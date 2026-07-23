# 🗄️ Database Architecture & Entity Specification

High-level specification and reference manual for the platform's multi-tenant e-commerce data model. Built with SQLAlchemy 2.0 (Mapped Declarative) targeting PostgreSQL.

---

## 📐 System Overview & Global Architecture


```text
                                  +-------------------+
                                  |       USER        |
                                  +---------+---------+
                                            |
                         +------------------+------------------+
                         | (1:N)                               | (N:M via store_owners/staffs)
                         v                                     v
                 +---------------+                     +---------------+
                 |    TICKET     |                     |     STORE     |
                 +-------+-------+                     +-------+-------+
                         |                                     |
                         | (1:N)                               | (1:N)
                         v                                     v
                 +---------------+                     +---------------+
                 |    MESSAGE    |                     |    PRODUCT    |
                 +---------------+                     +-------+-------+
                                                               |
                                           +-------------------+-------------------+
                                           | (1:N)                                 | (1:1)
                                           v                                       v
                                   +---------------+                       +---------------+
                                   |    REVIEW     |                       |   INVENTORY   |
                                   +-------+-------+                       +---------------+
                                           |
                                           | (1:N)
                                           v
                                   +---------------+
                                   |     REACT     |
                                   +---------------+
```

---

### Architectural Principles & Guardrails

* **Multi-Tenant Scope**: The Store entity serves as the root domain boundary. Operational models (Product, Inventory, Order, Cart, Membership) bind directly to a store_id.

* **State Preservation via Soft Deletes**: Deletions on critical domain entities (Store, Address, StoreAccount, Product, Inventory, Category, SubCategory, Membership) execute via logical state flags (is_deleted = True) to maintain relational integrity and financial audit trails.

* **Sensitive Data Encryption**: Merchant financial identifiers inside StoreAccount (account_number, tax_identification_number, identification_number) are stored as binary byte streams (LargeBinary), enforcing application-level payload encryption before writing to disk.


## 🔢 Enumeration Types & State Machines

    `TicketStatus`
    
    Defines operational resolution lifecycles for support queries.
    
$$\text{Lifecycle}: \text{open} \longrightarrow \text{in\\_progress} \longrightarrow \text{closed}$$


| Enum Key | Database Value | Description |
| :--- | :--- | :--- |
| `open` | `open` | Initial unassigned/unresolved state. |
| `in_progress` | `in_progress` | Claimed by support agent; active thread. |
| `closed` | `closed` | Resolved ticket; read-only messaging state. |


    `PaymentStatus`
    
    PostgreSQL native Enum (`paymentstatus`) tracking ledger collection.
    
$$\text{Lifecycle}: \text{PENDING} \longrightarrow \{\text{SUCCESS}, \text{FAILED}\} \longrightarrow [\text{REFUNDED}]$$


| Enum Key | Database Value | Description |
| :--- | :--- | :--- |
| `PENDING` | `pending` | Checkout initiated; awaiting gateway webhook. |
| `SUCCESS` | `success` | Settlement confirmed by payment provider. |
| `FAILED` | `failed` | Gateway declined or session expired. |
| `REFUNDED` | `refunded` | Partial or total capital returned to buyer. |


    `AccountVerification`
    
    Merchant payout account onboarding state machine.
    
$$\text{Lifecycle}: \text{pending} \longrightarrow \{\text{verified}, \text{rejected}\}$$

| Enum Key | Database Value | Description |
| :--- | :--- | :--- |
| `pending` | `pending` | Awaiting manual compliance verification. |
| `verified` | `verified` | KYC passed; payout dispatches enabled. |
| `rejected` | `rejected` | KYC failed; re-submission required. |


    `SubscriptionStatus`
    
    Subscription status tracking recurring store/membership tiers.

| Enum Key | Database Value | Description |
| :--- | :--- | :--- |
| `inactive` | `inactive` | No active billing plan attached. |
| `active` | `active` | Billing active and current. |
| `past_due` | `past_due` | Gateway retry active after payment failure. |
| `cancelled` | `cancelled` | Terminated by user or system rule. |


    `OrderStatus`
    
    Order tracking state transition engine.
    
$$\text{Lifecycle}: \text{pending} \longrightarrow \text{processing} \longrightarrow \text{paid} \longrightarrow \text{shipped} \longrightarrow \text{delivered} \quad (\text{or } \text{cancelled})$$


### Other Enums

`ProductSize`: `small`, `medium`, `large`, `extra_large`

`MembershipType`: `Standard`, `Regular`, `Premium`

`SubscriptionPlan`: `Standard`, `Regular`, `Premium`

`ReactionType`: `like`, `love`, `wow`, `laugh`, `sad`, `angry`

`IdType`: `voter_id`, `national_id`, `driver_license`, `other_id`

`AccountType`: `savings`, `current`, `business`

---

## 🗂️ Data Dictionary & Entity Definitions

###  Core & Identity Domain

`User`

Central identity registry containing credentials, global profiles, and relational hooks.


| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `Integer` | `PK, Index` | Primary key identifier. |
| `first_name` | `String` | `Index` | User legal given name. |
| `middle_name` | `String` | `Nullable` | Optional middle name. |
| `surname` | `String` | `Index` | User legal surname. |
| `username` | `String` | `Unique, Index` | Unique platform handle. |
| `password` | `String` | — | Argon2/Bcrypt hash string. |
| `is_active` | `Boolean` | `Default: True` | Account active flag. |
| `role` | `String` | `Default: "user", Index` | Platform RBAC role string. |
| `email` | `String` | — | User contact address. |
| `nationality` | `String` | — | ISO country code/string. |
| `profile_picture` | `String` | `Nullable` | S3 asset URL. |
| `phone_number` | `String` | `Nullable` | E.164 phone string. |
| `address` | `String` | `Nullable` | Default home address string. |


`Store`

Tenant root object controlling branding, tax thresholds, and storefront settings.

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `Integer` | `PK, Index` | Primary key identifier. |
| `business_logo` | `String` | `Nullable` | S3 asset URL. |
| `store_photo` | `String` | — | Banner image URL. |
| `store_name` | `String` | `Unique, Index` | Merchant display title. |
| `motto` | `String` | `Nullable` | Store marketing tagline. |
| `edited_name` | `Boolean` | `Default: False` | Name update track flag. |
| `store_previous_name` | `String` | `Nullable` | Historical store name record. |
| `store_description` | `String` | `Nullable` | Rich text storefront description. |
| `slug` | `String(255)` | `Unique, Index` | Canonical public URL slug. |
| `category_name` | `String` | `Index` | Primary category label cache. |
| `sub_category` | `JSONB` | `Index` | Structured sub-category tree. |
| `category_id` | `Integer` | `FK(category.id), Index` | Foreign key to Category. |
| `avg_rating` | `Numeric(3,2)` | `Default: 0` | Aggregated product rating. |
| `review_count` | `Integer` | `Default: 0` | Rating accumulation tally. |
| `store_email` | `String` | `Nullable` | Public customer contact email. |
| `shipping_fee` | `Numeric(10,2)` | `Default: 0` | Base shipping calculation rate. |
| `tax_rate` | `Float` | `Default: 0` | Tax percentage rate. |
| `store_contact` | `String` | `Nullable` | Direct phone contact. |
| `approved` | `Boolean` | `Default: False, Index` | Platform audit sign-off flag. |
| `is_deleted` | `Boolean` | `Default: False, Index` | Logical deletion state. |
| `founded` | `DateTime` | `Nullable, TZ` | Incorporation date timestamp. |

**Junction Tables**

* `store_owners`: Maps `user.id` (`users_id`) $\leftrightarrow$ `store.id` (`stores_id`). Composite PK on both columns.
* `store_staffs`: Maps `user.id` (`users_id`) $\leftrightarrow$ `store.id` (`stores_id`). Composite PK on both columns.

**Catalog & Taxonomy Domain**

`Category` & `SubCategory`

High-level taxonomy tables with unique naming checks per level.

* `Category`: `id` (`PK`), `name` (`Unique`, `Index`), `is_deleted` (`Boolean`).
* `SubCategory`: `id` (`PK`), `category_id` (`FK(category.id)`), `name` (`Unique`, `Index`), `is_deleted` (`Boolean`).


`Product` & `ProductImage`

Catalog SKU listings and asset mappings.

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `Integer` | `PK, Index` | SKU record identifier. |
| `store_id` | `Integer` | `FK(store.id), Index` | Parent tenant workspace ID. |
| `product_name` | `String` | `Index` | Listing display title. |
| `primary_image` | `String` | — | Thumbnail S3 asset URL. |
| `product_price` | `Numeric(12,2)` | — | Standard unit selling price. |
| `product_type` | `String` | — | Physical / Digital classification. |
| `avg_rating` | `Numeric(3,2)` | `Default: 0` | Computed product rating. |
| `review_count` | `Integer` | `Default: 0` | Total product reviews. |
| `product_description` | `Text` | — | Product specifications body. |
| `product_size` | `ProductSize` | `Enum, Index` | Standardized size footprint. |
| `category_id` | `Integer` | `FK(category.id), Index` | Category link. |
| `sub_category_id` | `Integer` | `FK(subcategory.id), Index` | Sub-category link. |
| `product_availability` | `String` | `Default: "available"` | Inventory availability marker. |
| `is_deleted` | `Boolean` | `Default: False` | Soft deletion status. |


**Inventory & Banking Domaain**

`Inventory`

Tracks physical item stock per store.


```text
+-----------------------------------------------------------------------+
|                              INVENTORY                                |
+-----------------------------------------------------------------------+
| CONSTRAINTS:                                                          |
|  * UniqueConstraint("store_id", "product_id")                         |
|  * CheckConstraint("stock_quantity >= 0")                             |
+-----------------------------------------------------------------------+
```

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `Integer` | `PK, Index` | Inventory row identifier. |
| `product_id` | `Integer` | `FK(product.id), Index` | Targeted SKU reference. |
| `store_id` | `Integer` | `FK(store.id), Index` | Owning store context. |
| `stock_quantity` | `Integer` | `Default: 0` | Available unit count. |
| `is_deleted` | `Boolean` | `Default: False` | Active/Inactive stock line flag. |
| `last_updated` | `DateTime` | `Auto-Update, TZ` | Inventory sync timestamp. |


`StoreAccount`

Encrypted merchant banking registry containing KYC and settlement endpoints.

```text
+-----------------------------------------------------------------------+
|                            STORE_ACCOUNT                              |
+-----------------------------------------------------------------------+
| CONSTRAINTS:                                                          |
|  * UniqueConstraint("store_id")                                       |
|  * CheckConstraint("(rejected_reason IS NULL) OR                      |
|                     (verification_status = 'rejected')")              |
|  * CheckConstraint("(verification_status != 'verified') OR            |
|                     (verified_at IS NOT NULL)")                       |
+-----------------------------------------------------------------------+
```

**Orders & Payment Ledger Domain**

`Order` & `OrderItem`

Header and line-item tables for customer purchases.

$$\text{Total Amount} = (\text{Subtotal} - \text{Discount}) + \text{Tax Amount} + \text{Shipping Fee}$$


```text
+-----------------------------------------------------------------------+
|                                ORDER                                  |
+-----------------------------------------------------------------------+
| delivery_address_id: FK(address.id) ON DELETE SET NULL                |
| delivery_address: JSONB snapshot of full address payload              |
+-----------------------------------------------------------------------+
```

`Payment` & `Refund`

Financial transaction tracking.

```text
+-----------------------------------------------------------------------+
|                                PAYMENT                                |
+-----------------------------------------------------------------------+
| CONSTRAINTS:                                                          |
|  * UniqueConstraint("order_id", name="unique_order_payment")          |
+-----------------------------------------------------------------------+
```

**Engagement & Feedback Domain**

`React`

Polymorphic interaction engine handling user reactions on reviews and replies.

```text
+-----------------------------------------------------------------------+
|                                REACT                                  |
+-----------------------------------------------------------------------+
| CONSTRAINTS:                                                          |
|  * UniqueConstraint("user_id", "reply_id")                            |
|  * UniqueConstraint("user_id", "review_id")                           |
|  * CheckConstraint("(reply_id IS NULL AND review_id IS NOT NULL) OR   |
|                     (reply_id IS NOT NULL AND review_id IS NULL)",    |
|                     name="exactly_one_parent")                        |
+-----------------------------------------------------------------------+
```


### 🔒 Integrity Constraints & Validation Rules Summary


| Constraint Name | Associated Entity | Type | Logic / Structural Rule |
| :--- | :--- | :--- | :--- |
| unique_store_account | StoreAccount | Unique | Enforces a 1:1 mapping between Store and StoreAccount. |
| rejection_reason_check | StoreAccount | Check | Guarantees rejected_reason is only present when status is 'rejected'. |
| verified_account_timestamp_check | StoreAccount | Check | Guarantees verified_at timestamp is set when status is 'verified'. |
| store_product_inventory | Inventory | Unique | Enforces a single inventory tracking row per store/product pair. |
| positive_quantity | Inventory | Check | Enforces stock_quantity >= 0 to prevent negative stock counts. |
| unique_order_payment | Payment | Unique | Enforces a 1:1 relationship between an Order and its Payment. |
| user_store_membership | Membership | Unique | Prevents duplicate user memberships within the same store scope. |
| subscribed_member | Subscription | Unique | Restricts each Membership to a single active Subscription record. |
| user_product_review | Review | Unique | Restricts a user to one review per product. |
| unique_reply_react | React | Unique | Prevents multiple reactions from the same user on a single reply. |
| unique_review_react | React | Unique | Prevents multiple reactions from the same user on a single review. |
| exactly_one_parent | React | Check | Enforces strict single-parent XOR linking to either reply_id or review_id. |

