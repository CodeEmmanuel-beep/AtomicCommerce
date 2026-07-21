# 💳 Store Account & Address Module

Governs multi-tenant vendor onboard banking lifecycles, asymmetric cryptography frameworks for regulatory financial records, strict verification state workflows, and spatial address topologies.

---

## 📡 Server-Client Interface

* **Symmetric Cryptographic Ingestion**: Protects highly sensitive financial identifiers (such as bank account, tax, and personal identity numbers) by running them through a symmetrical block cipher encoder (`cipher.encrypt`). Raw text bytes are scrambled during creation and edit sequences before being serialized into storage, shielding vendor data at rest.

* **Verification-State Update Lockouts**: Enforces data-tampering barriers on validated financial entities by evaluating structural state variables (`AccountVerification.verified`). If a storefront profile has already achieved an active verified state, the application blocks modification requests and throws a 400 Bad Request exception, unless the vendor is exclusively appending a missing tax identification token.

* **Sequential Verification Auditing**: Transitions store banking entries through distinct verification lifecycles (`verify` or `reject`). Approving an entity maps the current system timestamp to the record (`verified_at = datetime.now(timezone.utc)`) and archives any existing rejection logs into cold historical tables; rejecting an entity locks down future payouts and logs the mandatory text justification provided by administrators.



📐 **Architectural Decisions & Safeguards**:

* **Atomic Multi-Condition Ownership Validation**: Employs an explicit multi-clause existence check (`select(exists()..., exists()..., exists()...)`) inside a single database round-trip during entry generation. The query simultaneously validates storefront existence, verifies whether the current profile holds authenticated owner permissions within the `store_owners` junction table, and confirms that the business has not already established a banking profile.

* **Context-Aware Symmetric Decryption**: Masks sensitive structural models from standard network visualization tools by passing external decryption matrices contextually. The viewing route passes an initialized secure block cipher through Pydantic pipeline contexts (`StoreAccountResponse.model_validate(..., context={"cipher": cipher})`), decrypting banking tokens only for verified administrators or matching store owners.

* **Analytical Windows for Paginated Addresses**: Optimizes address lists across store regions by computing total matches within a windowed query execution block (`func.count(Address.id).over().label("total_count")`). This pattern isolates subtotal records directly alongside paginated offset blocks, enabling the caching engine (`ttl=300`) to store complete metadata packets without firing separate count queries.

* **Pessimistic Locking**: Soft-deletion of store locations invokes `.with_for_update(of=Address)` to prevent concurrent updates to active shipping/tax configurations.

* **Explicit Flag for Store Physical Address**: Use a boolean flag `store_address = TRUE` to explicitly identify a store’s physical address, ensuring it is always distinguished from customer delivery addresses linked to that store.

### Business Rules

* **Singular Account**: Each store is strictly limited to one account.
* **Role Immunity**: Payout bank accounts and physical addresses can only be created or modified by verified Store Owners (Staff members are locked out).
* **Immutable Account**: Once an account has been verified, all account fields become immutable. The only permitted modification is the insertion of a previously null tax identification number (TIN). After the TIN has been supplied, no further modifications are allowed.
* **Unlimited Addresses**: The number of physical addresses a store can register has no limit.
* **Payout Flow**: When a customer buys a product, funds route to the platform owner's primary Stripe account. The platform owner manages and executes payouts into individual store accounts.
* **Permissions**: Only store owners, platform administrators, and platform owner can view account details

---

## Core Endpoints

**Create Account**

`POST api/v1/store_account_and_address/store_account`

Sets or updates merchant bank account information for automated payouts.

**Request Payload**

```python
  store_id: int
  bank_name: str = Form(...)
  account_type: str = Query("business", enum=["savings", "current", "business"]),
  account_holder_name: str = Form(...)
  account_number: str = Form(...)
  type_of_id: str = Query(
        "national_id", enum=["voter_id", "national_id", "driver_license", "other_id"]
  )
  identification_number: str = Form(...)
  tax_identification_number: str = Form(None)
```

**JSON Response**

```json
{"status": "success", "message": "finance details added"}
```
---

**Add Address**

`POST api/v1/store_account_and_address/store_address`

Creates a store address using `store_id` for multi-tenancy.

**Request Payload**

```python
  store_id: int
  address_details: AddressDetails
```

***AddressDetails Object***

```python
class AddressDetails(BaseModel):
    street: str
    city: str
    state: str
    country: str
```

**JSON Response**

```json
{"status": "success", "message": "address details added"}
```

---

**Fetch Store Account**

`GET api/v1/store_account_and_address/view_account_details`

Returns the account details of a store to its authorized owners, platform administrators, and the platform owner.

**Request Payload**

```python
  store_id: int
```

**JSON Response**

```json
{
  "status": "success",
  "message": "store account",
  "data": {
    "bank_name": "First Bank",
    "account_type": "savings",
    "account_holder_name": "Emmanuel Chiedu Eke",
    "account_number": "3057163551",
    "type_of_id": "national_id",
    "identification_number": "84516481194",
    "tax_identification_number": "20010002",
    "verification_status": "verified"
  }
}
```

---

**Fetch Store Address**

`GET api/v1/store_account_and_address/view_store_address_details`

Retrieves a paginated list of physical store addresses.

**Request Payload**

```python
  store_id: int
  page: int = Query(1, ge=1)
  limit: int = Query(10, le=100)
```

**JSON Response**

```json
{
  "status": "success",
  "message": "store addresses retrieved",
  "data": {
    "items": [
      {
        "id": 6,
        "street": "Gwarinpa",
        "city": "Abuja",
        "state": "Federal Capital Territory",
        "country": "Nigeria"
      },
      {
        "id": 9,
        "street": "Green Lake",
        "city": "Dallas",
        "state": "Florida",
        "country": "United States of America"
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
* **get_cipher**: For account decryption and encryption functions.

---

### Security  Guardrails

* **400 Bad Request**: Dispatched upon downstream integrity violations, duplicate account creation, or illegal mutations on verified entities.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **403 Forbidden**: Dispatched during failed  authorizations.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
