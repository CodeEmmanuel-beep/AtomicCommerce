# 💳 Financial Gateways & Stripe Webhook Service

Orchestrates asynchronous webhooks from financial providers to safely sync external transactional states with subscription memberships, order processing workflows, and multi-tier refund architectures.

---

## 📡 Server-Client Interface

* **Idempotent Multi-Layer Event Fencing**: Employs rigorous state verification to block duplicate processing from out-of-order delivery or re-driven webhooks. By framing updates around explicit event IDs (`last_event_id != event['id']`) and timestamp linear progressions (`last_event_at <= created_timestamp`), the routine safely drops stale notifications and confirms that transactions are modified exactly once per state transition.

* **Polymorphic Metadata Parsing Matrix**: Traverses unstructured inbound JSON blocks to locate internal identifiers across various product profiles. The engine inspects multiple object layers, extracting properties from the core root mapping (`metadata`), specialized billing fields (`subscription_details`), and line-item collections (`lines.data[0].metadata`) to dynamically map events to internal records.

* **Conditional Mathematical State Transitions**: Evaluates external billing statuses via conditional query logic to calculate expiration windows and subscription levels dynamically. For successful membership completions, it shifts access rights safely forward into future windows:



```math
expire\_at = \max(Subscription.expire\_at, now()) + INTERVAL\text{ '30 days'}
```


---

### Stripe Webhook Operational Signals

| Payload Classification | Supported Stripe Signals | Downstream Internal Target Updates |
| :--- | :--- | :--- |
| **Membership & Recurring Billing** | `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed` | Adjusts core `SubscriptionStatus` variants (`active`, `cancelled`, `past_due`), updates product subscription tiers (`Standard`, `Regular`, `Premium`), and sets the `is_active` flag.
| **Direct Order Checkout** | `checkout.session.completed`, `payment_intent.succeeded`, `checkout.session.expired`, `payment_intent.payment_failed` | Maps transaction keys against direct records (`Payment.transaction_id`), alters payment statuses (`SUCCESS`, `FAILED`), and updates parent order processing states.
| **Reversals & Chargebacks** | `charge.refunded`, `refund.updated` | Validates structural updates across internal ledger schemas (`Refund`); shifts tracking flags to `REFUNDED`, or rolls back parent accounts to `SUCCESS` if rejected.

---

📐 **Architectural Decisions & Safeguards**:

* **Defensive Reversal Restoration Routing**: Protects systems against payment status errors when a credit institution or bank rejects a pending return transaction. When an outbound refund fails, the system catches the failure state and reverts the parent payment record back to `SUCCESS`, protecting financial consistency across the application.

* **Type-Cast Enum Integration**: Eliminates structural schema mapping mismatches by compiling statuses through safe database type casts (`cast(..., target_enum)`). This technique verifies that arbitrary strings from webhooks are parsed into valid database types before submission, preventing runtime schema validation drops.

* **Asynchronous Background Core Activation**: Postpones non-critical business tasks until after the immediate web request-response cycle completes. Once database changes are written and committed, the pipeline registers downstream tasks—such as profile updates—via background worker queues (`background_task.add_task`), ensuring lightning-fast webhook responses.


### Business Rules

* **Signature Enforcement**: Unsigned or signature-mismatched webhook requests are immediately dropped with an HTTP 400 Bad Request.
* **Idempotency Management**: Processed Stripe events are idempotent. Events whose identifiers have already been recorded are ignored without performing additional state mutations.

---

### Terminal Logs

#### Payment Event Log

```log
marketplace_api | 2026-06-15 19:30:12,950-INFO-Received webhook for order payment event: checkout.session.completed
marketplace_api | { "order_id": "32", "type": "order_payment", "user_id": "8" }
marketplace_api | INFO: 172.18.0.1:45624 - "POST /payment/webhook HTTP/1.1" 200 OK
marketplace_api | INFO: 172.18.0.1:45625 - "GET /docs/?session_id=cs_test_albIDEDh84cPymy8Rz1xM1JqoSW4PpOhVHkXB23dGjoClCoohHhr5KbJLsA HTTP/1.1" 307 Temporary Redirect
marketplace_api | INFO: 172.18.0.1:45626 - "GET /docs/?session_id=cs_test_albIDEDh84cPymy8Rz1xM1JqoSW4PpOhVHkXB23dGjoClCoohHhr5KbJLsA HTTP/1.1" 200 OK
marketplace_api | INFO: 172.18.0.1:45656 - "GET /openapi.json HTTP/1.1" 200 OK
marketplace_api | 2026-06-15 19:37:17,131-WARNING-Received unhandled event type: charge.updated
marketplace_api | INFO: 172.18.0.1:45660 - "POST /payment/webhook HTTP/1.1" 200 OK
marketplace_api | 2026-06-15 19:30:17,357-INFO-Payment cs_test_albIDEDh84cPymy8Rz1xM1JqoSW4PpOhVHkXB23dGjoClCoohHhr5KbJLsA processed successfully.
marketplace_api | 2026-06-15 19:30:17,402-INFO-Routed event for op UPDATE to notifications_3
marketplace_api | 2026-06-15 19:30:17,405-INFO-Routed event for op UPDATE to notifications_5
marketplace_api | 2026-06-15 19:32:10,314-INFO-Heartbeat sent: Router is healthy.
```

#### Subscription Event Log

```log
marketplace_api | 2026-06-19 18:43:21,049-INFO-Received webhook for membership subscription event: invoice.payment_succeeded
marketplace_api | { "membership_id": "10", "payment_type": "subscription", "type": "membership", "user_id": "9" }
marketplace_api | INFO: 172.18.0.1:53972 - "POST /payment/webhook HTTP/1.1" 200 OK
marketplace_api | 2026-06-19 18:43:21,128-WARNING-Received unhandled payload category. Event: invoiceitem.created
marketplace_api | INFO: 172.18.0.1:57818 - "POST /payment/webhook HTTP/1.1" 200 OK
marketplace_api | 2026-06-19 18:43:22,942-INFO-Payment sub_1Tk68R9L4kWAB1l1GTfsfLhhg processed successfully.
marketplace_api | INFO: 172.18.0.1:53998 - "POST /payment/webhook HTTP/1.1" 200 OK
marketplace_api | 2026-06-19 18:43:22,721-INFO-Routed event for op UPDATE to notifications_3
marketplace_api | 2026-06-19 18:43:22,555-INFO-Routed event for op UPDATE to notifications_5
marketplace_api | 2026-06-19 18:43:22,559-INFO-Routed event for op UPDATE to notifications_6
marketplace_api | 2026-06-19 18:43:22,562-INFO-Routed event for op UPDATE to notifications_3
marketplace_api | 2026-06-19 18:43:22,570-INFO-Routed event for op UPDATE to notifications_5
marketplace_api | 2026-06-19 18:43:23,703-INFO-Membership status for membership_id: 10 is already up to date. No changes made.
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **stripe_sdk**: Configured asynchronous Stripe SDK client initialized with secret keys.
* **BackgroundTasks**: Used to trigger the Membership Activation function asynchronously, ensuring it runs after the response is sent without blocking the request cycle.
* **Request**: Provides access to the incoming webhook event, allowing the webhook handler to inspect Stripe headers.

---

### Security Guardrails

* **400 Bad Request**: Dispatched on Stripe signature verification failures and database error at order refund reconciliation.
* **500 Internal Server Error**: Dispatched when downstream Stripe API calls fail due to network outages or unhandled driver exceptions.

---
