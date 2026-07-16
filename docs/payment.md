# 💳 Payment Module

Governs global electronic transaction lifecycles, real-time external processor integrations, state-locked refund accounting, and role-segregated financial ledger validation.

---

## 📡 Server-Client Interface

* **Asynchronous Stripe Engine Integration**: Couples local database checkouts with external payment routing through an asynchronous integration client (`stripe_client.v1.checkout.sessions.create_async`, `stripe_client.v1.checkout.refunds.create_async` and `stripe_client.v1.checkout.billing_portal.sessions.create_async`). It handles both physical order payments (converting floating total amounts into fixed integer pennies: `int(round(order.total_amount * 100))`) and subscription pricing configurations, mapping specific billing plan tokens (`sub.price_id`).

* **Dual-State Mutual Exclusion Guards**: Restricts checkout routes by checking input parameters to ensure only one item type is processed per intent creation sequence. The validation framework throws a 400 Bad Request exception if a user passes both `order_id` and `membership_id` simultaneously, or if it catches an empty structural payload (`order_id is None and membership_id is None`).

* **Transactional Ledger Rollback Defenses**: Shields financial entries against transaction discrepancies by tracking partial balances through an explicit log step (`Refund`). If an external transaction succeeds but the database write fails, the execution block traps the exception and outputs a critical error message detailing the tracking drift, alerting administrators that manual reconciliation is required:


> 🚨 **FATAL STATE MISMATCH**: Stripe refund succeeded but database tracking write failed! Manual reconcile required.
> 
> 


📐 **Architectural Decisions & Safeguards**:

* **Strict Balance Fencing**: Controls outbound refunds by comparing requested adjustments against original payment records via a lock filter (`.with_for_update()`). The pipeline prevents over-refunding by summing all matching entries (`func.coalesce(func.sum(Refund.refund_amount), 0)`), calculating the remaining balance, and throwing a 400 Bad Request error if a user requests more than the refundable remainder.

* **Multi-Tenant Time-Slice Queries (Used by payment reporting endpoints.)**: Optimizes lookups across store domains by matching requested filter strings against relative temporal maps (`1 year`, `6 months`, `3 months`, `1 month`, `1 week`). If a store's founding date is newer than the requested query window (`store.founded > time_period`), the search short-circuits with an error response, keeping data lookups efficient and within valid operational bounds.

> Fail-Safe Reconciliation (Three-Tier Redundancy)

   * **Primary Webhook Sync Path**: Upon receiving a successful payment event from Stripe, the webhook handler immediately attempts an asynchronous, atomic database update to activate the membership.

   * **FastAPI Native Background Task (Immediate Fail-Safe)**:

      * A native FastAPI BackgroundTask is always triggered alongside the webhook response.
      * If the primary asynchronous atomic update logic is skipped or bypassed for any reason, this background task catches the state and performs the activation out-of-band.
      * If the primary asynchronous update succeeded, the background task—which is fully idempotent—checks the status, logs that the member is already active, and gracefully skips execution.

  *  **Celery Backup Worker (The Ultimate Safety Net)**: If both the webhook's asynchronous logic and the in-memory FastAPI background task fail (such as during a sudden server crash or restart), a scheduled Celery worker periodically sweeps the database. It automatically activates any inactive accounts that have a valid subscription expiration date in the future (expire_at > current_time).


### Business Rules

* **Order Payment Validation**: Orders lacking a valid delivery address are blocked at checkout and cannot be processed.

* **Payment & Subscription State Constraints (1:1 Mapping)**: To maintain ledger integrity, each order checkout or membership activation is restricted to a single, mutable database row. Status transitions (e.g., FAILED $\rightarrow$ SUCCESS $\rightarrow$ REFUNDED) and metadata updates (such as updating the last_event_id) mutate this single record in place.

* **Refund Cardinality (1:N Mapping)**: To support partial or incremental refunds, each refund event is appended as a new row in the Refund table linked to the parent `payment_id`. The total refunded balance is calculated by aggregating these rows.

---

## Core Endpoints 

**Create Payment**

`POST api/v1/payment/make_payment`

To pay for an order or make a membership subscription.

**Request Payload**

```python
 membership_id: int | None = None
 order_id: int | None = None
 currency: str = "usd"
 one_time_subscription: str = Query("one_time", enum=["one_time", "subscription"])
```

**JSON Response (Payment)**

```json
{
  "status": "success",
  "message": "follow the link below to complete your payment",
  "data": {
    "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_a1J9lQ7dG2zSajnhrKZ7Yde8ZNGESpGSP4MySRoH99rE8Z4RctsOnJc1Qz#fidnandhYHdWcXxpYCc%2FJ2FgY2RwaXEnKSdicGRmZGhqaWBTZHdsZGtxJz8nZmprcXdqaScpJ2R1bE5gfCc%2FJ3VuWnFgdnFaMDRRTk9kbzwxblJERzQ0X0I2dG1oUjEzVmROaVBVcHw0N3F0f25fNlI1QVcyaldcbWZ0ckxEPEtfcTJnVn9rYmlOU119UXZxVXB3fzU1U3dWZ2I9UU1nQkY1NU5iTmExMVJhJyknY3dqaFZgd3Ngdyc%2FcXdwYCknZ2RmbmJ3anBrYUZqaWp3Jz8nJmNjY2NjYycpJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl",
    "payment details": {
      "id": 30,
      "order_id": 38,
      "payment_method": "card",
      "currency": "usd",
      "payment_status": "pending",
      "subtotal": "5000.00",
      "shipping_fee": "0.00",
      "tax_amount": "375.00",
      "discount_amount": "150.00",
      "total_amount": "5225.00",
      "total_refund": "0",
      "reference_id": "cs_test_a1J9lQ7dG2zSajnhrKZ7Yde8ZNGESpGSP4MySRoH99rE8Z4RctsOnJc1Qz",
      "payment_date": "2026-07-16T16:25:45.838048Z"
    }
  }
}
```

**JSON Response (Subscription)**

```json
{
  "status": "success",
  "message": "subscription payment initiated, complete payment to activate membership",
  "data": {
    "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_a1eaGHheIQXFhF2aPZgPMX0Eqr4uWkrgEqJTtQW6Ew42lUPFGkPd1Za9M5#fidnandhYHdWcXxpYCc%2FJ2FgY2RwaXEnKSdicGRmZGhqaWBTZHdsZGtxJz8nZmprcXdqaScpJ2R1bE5gfCc%2FJ3VuWnFgdnFaMDRRTk9kbzwxblJERzQ0X0I2dG1oUjEzVmROaVBVcHw0N3F0f25fNlI1QVcyaldcbWZ0ckxEPEtfcTJnVn9rYmlOU119UXZxVXB3fzU1U3dWZ2I9UU1nQkY1NU5iTmExMVJhJyknY3dqaFZgd3Ngdyc%2FcXdwYCknZ2RmbmJ3anBrYUZqaWp3Jz8nJmNjY2NjYycpJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl",
    "subscription details": {
      "id": 9,
      "membership_id": 10,
      "plan_name": "Regular",
      "price_id": "price_1TKfUW94kWAB11ZGM0ec5S5J",
      "status": "active",
      "expire_at": "2026-07-19T17:23:17Z",
      "time_of_subscription": "2026-07-16T16:32:23.543603Z"
    }
  }
}
```

---

**Refund Client**

Processes partial or full refunds against completed payment transactions.

**Request Payload**

```python
payment_id: int
amount: Decimal
reason: str
```

**JSON Response**

```json
{
  "status": "success",
  "message": "refund logged",
  "data": {
    "refund_id": "re_3TigCc94kWAB11ZG1ys1qXnO"
  }
}
```

---

**Retrieve Receipt**

`GET api/v1/payment/personal_payment`

Retrieves personal receipt for a particular order.

**Request Payload**

```python
store_id: int
order_id: int
```

**JSON Response**

```json
{
    "status": "success",
    "message": "payment for order: '32",
    "data": {
        "id": 25,
        "order_id": 32,
        "payment_method": "card",
        "currency": "usd",
        "payment_status": "success",
        "subtotal": 88750.00,
        "shipping_fee": "2500.00",
        "discount_amount": "887.50",
        "tax_amount": "6656.25",
        "total_amount": "97018.75",
        "reference_id": "cs_test_a1bIDEDh84cPymy8Rz1xM1JqoSW4PpOhVHkXB23dGjoClCooHhr5kbJLsA",
        "transaction_id": "pi_3TigCc94kWAB11ZG1795DuQR",
        "payment_date": "2026-06-15T19:00:39.997909Z"
    }
}
```

**

---


### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Initializes the context manager for asynchronous handling of transactional scopes.
* **verify_token**: Decorator layer executing JWT decryption and validation checkpoints.

---

### Security Guardrails

* **400 Bad Request**: Dispatched upon Stripe error, refund attempt for failed or pending payments, integrity violations or transaction failures.
* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.
* **404 Not Found**: Dispatched if requests target entities missing from active records or configurations sequestered by tenancy bounds.
* **409 Conflict**: Dispatched at double payment attempt or subscription attempt for a member already subscribed.
* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
