# 🔔 In-App Push Notifications Module

Governs user alerts, real-time Server-Sent Events (SSE) stream delivery, automated read-receipt synchronization, and context-aware messaging for active or soft-deleted stakeholders.

## 🗄️ Database Event Generation
Database trigger functions are set with raw SQL, executing automatically upon table operations to emit notifications.

**Trigger Function**

```sql
CREATE OR REPLACE FUNCTION notify_event()
RETURNS TRIGGER AS $$
DECLARE 
    target_user_id INT; 
    product INT; 
    subscriber INT; 
    event_time TIMESTAMPTZ; 
    v_store_id INT; 
    review_object INT; 
    v_customer_id INT;
BEGIN 
    IF TG_TABLE_NAME = 'reply' THEN 
        SELECT user_id INTO target_user_id 
        FROM review 
        WHERE id = NEW.review_id;

        IF NEW.product_id IS NOT NULL THEN 
            review_object := NEW.product_id; 
        ELSE 
            review_object := NEW.store_id; 
        END IF;

        IF target_user_id IS NOT NULL THEN 
            PERFORM pg_notify(
                'app_events', 
                json_build_object(
                    'inserter', NEW.user_id, 
                    'notification', 'reply to your review', 
                    'obj', review_object, 
                    'user_id', target_user_id, 
                    'action', TG_OP, 
                    'product_id', NEW.product_id, 
                    'store_id', NEW.store_id,  
                    'time', NEW.time_of_post
                )::text
            ); 
        END IF;

    ELSIF TG_TABLE_NAME IN ('cart', 'review', 'order') THEN 
        IF TG_TABLE_NAME = 'review' THEN 
            event_time := NEW.time_of_post;  
            product := NEW.product_id; 
        ELSE 
            event_time := NEW.created_at; 
            product := NULL; 
        END IF; 

        FOR subscriber IN 
            SELECT users_id FROM store_staffs WHERE stores_id = NEW.store_id 
            UNION ALL 
            SELECT users_id FROM store_owners WHERE stores_id = NEW.store_id 
        LOOP
            PERFORM pg_notify(
                'app_events', 
                json_build_object(
                    'inserter', NEW.user_id, 
                    'product_id', product, 
                    'store_id', NEW.store_id, 
                    'user_id', subscriber, 
                    'notification', 'New ' || TG_TABLE_NAME, 
                    'action', TG_OP, 
                    'time', event_time
                )::text
            ); 
        END LOOP;

    ELSIF TG_TABLE_NAME = 'payment' THEN 
        SELECT store_id INTO v_store_id 
        FROM "order" 
        WHERE id = NEW.order_id; 

        IF v_store_id IS NOT NULL THEN
            FOR subscriber IN 
                SELECT users_id FROM store_owners WHERE stores_id = v_store_id
            LOOP
                PERFORM pg_notify(
                    'app_events', 
                    json_build_object(
                        'inserter', NEW.user_id, 
                        'notification', 'New payment for order ' || NEW.order_id,
                        'status', NEW.payment_status, 
                        'user_id', subscriber, 
                        'store_id', v_store_id, 
                        'action', TG_OP, 
                        'time', NEW.payment_date
                    )::text
                ); 
            END LOOP; 
        END IF;

    ELSIF TG_TABLE_NAME = 'membership' THEN 
        FOR subscriber IN 
            SELECT users_id FROM store_staffs WHERE stores_id = NEW.store_id 
            UNION ALL 
            SELECT users_id FROM store_owners WHERE stores_id = NEW.store_id 
        LOOP 
            PERFORM pg_notify(
                'app_events',
                json_build_object(
                    'inserter', NEW.user_id, 
                    'is_active', NEW.is_active, 
                    'is_deleted', NEW.is_deleted, 
                    'store_id', NEW.store_id,  
                    'notification', 'New membership', 
                    'type', NEW.membership_type, 
                    'time', NEW.start_date, 
                    'user_id', subscriber,
                    'action', TG_OP
                )::text
            );
        END LOOP;

    ELSIF TG_TABLE_NAME = 'subscription' THEN 
        SELECT store_id, user_id INTO v_store_id, v_customer_id 
        FROM membership 
        WHERE id = NEW.membership_id; 

        FOR subscriber IN 
            SELECT users_id FROM store_owners WHERE stores_id = v_store_id 
            UNION ALL 
            SELECT users_id FROM store_staffs WHERE stores_id = v_store_id 
        LOOP 
            PERFORM pg_notify(
                'app_events', 
                json_build_object(
                    'inserter', v_customer_id, 
                    'notification', 'New subscription', 
                    'status', NEW.status, 
                    'store_id', v_store_id, 
                    'time', NEW.time_of_subscription,
                    'action', TG_OP,
                    'user_id', subscriber
                )::text
            ); 
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

```

**Table Triggers**

```sql
CREATE TRIGGER trigger_replies AFTER INSERT ON reply FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_review AFTER INSERT ON review FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_cart AFTER INSERT ON cart FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_order AFTER INSERT ON "order" FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_payment AFTER INSERT ON payment FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_update_payment AFTER UPDATE ON payment FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_member AFTER INSERT ON membership FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_update_member AFTER UPDATE ON membership FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_sub AFTER INSERT ON subscription FOR EACH ROW EXECUTE FUNCTION notify_event();
CREATE TRIGGER trigger_update_sub AFTER UPDATE ON subscription FOR EACH ROW EXECUTE FUNCTION notify_event();
```

## 📡 LISTEN / NOTIFY & Redis Fan-Out

* **Database Event Capture (Listen)**: When a transaction triggers an event, the application processes the database-level message over an asynchronous connection pool listening on the configured system channel:
```python
async with aiopg.connect(dsn) as conn:
    async with conn.cursor() as cur:
        await cur.execute("LISTEN app_events;")
````

* **Persistence & Batched Writes**: Events received from the engine are passed to an internal processing queue (`await queue.get()`). To prevent downstream consumer saturation, backpressure limits are enforced and notifications are flushed to the primary datastore using buffered writes in batches of up to 100 entries.

* **Redis Fan-Out**: Live messages are mapped to a dedicated channel schema matching the target user key, protecting multi-tenant isolation boundaries. The active Server-Sent Events (SSE) server node subscribes to this local channel and streams the payload immediately down to the client.

* **Fault Tolerance & Automatic Reconnection**: To protect the active event-loop from driver drops or network disruptions, the background routing workers operate inside an automated reconnection supervisor block, restoring the DB listener channel automatically upon crashes.

---

## 📡 Server-Client Interface

* **Real-Time Reactive Streaming**: Establishes live HTTP event streaming connections utilizing an async event mechanism (`EventSourceResponse`) bound to an underlying key-value pub/sub structure (`notifications_stream(user_id)`). To clear communication lines before connection tracking mounts, it performs an immediate out-of-band invalidation loop (`await notification_invalidation(user_id)`).

* **Polymorphic State Labeling**: Evaluates sender account flags during relational query processing (`select(Notification, User)`) to adjust text outputs dynamically. If the actor's profile is active (`sender.is_active`), it interpolates the complete entity signature; otherwise, it appends a structural fallback marker (`"deleted user"`).

* **Atomic Read-State Synchronization**: Pairs read-heavy retrievals with bulk state mutations by updating data properties in a single transaction lifecycle. Upon gathering message payloads, the engine executes an atomic criteria update (`update(Notification).where(...)`) to shift target unread statuses (`is_read=True`) across the data model.


📐 **Architectural Decisions & Safeguards**:

* **Volatile Query Slicing**: Implements strict horizontal pagination limits (`.limit(30)`) on simple index looks, paired with calculated row offsets (`(page - 1) * limit`) inside full ledger lists. This isolates high-volume notification entries, ensuring fast response times while running on short caching lifespans (`ttl=60`).

* **Implicit Commit Recovery**: Isolates relational joins and state-flag updates within protected execution blocks. Any unexpected database driver failure or mid-stream disconnection stops transaction processing before executing `await db.commit()`, keeping the primary unread counters accurate and consistent.

* **Cache Invalidation AT SSE Endpoint**: To ensure consistency between persisted notifications and cached retrievals, the system invalidates the user’s cache entry whenever a new notification is created, so that subsequent REST calls and SSE streams always reflect the latest state without serving stale data

### 📋 Business Rule

**Notification Compartmentalization**: While store owners and staff members receive most store operations notifications together (like reviews, carts, and orders), only store owners are notified of financial updates and payments.

---

## Core Endpoint

**Notification List**

`GET api/v1/notifications/notifications_data`

Retrieves a paginated list of notifications for the authenticated session, automatically updating unread status tracking.

**JSON RESPONSE**

```json
{
  "status": "success",
  "message": "notifications",
  "data": {
    "items": [
      {
        "id": 511,
        "notification": "New payment for order 36 by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "status": "SUCCESS",
        "time_of_op": "2026-07-15T18:03:44.740371Z",
        "created_at": "2026-07-15T18:05:55.418389Z"
      },
      {
        "id": 509,
        "notification": "New payment for order 36 by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "status": "PENDING",
        "time_of_op": "2026-07-15T18:03:44.740371Z",
        "created_at": "2026-07-15T18:03:54.539620Z"
      },
      {
        "id": 503,
        "notification": "New subscription by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "status": "past_due",
        "time_of_op": "2026-07-15T17:06:57.457105Z",
        "created_at": "2026-07-15T17:07:03.776979Z"
      },
      {
        "id": 507,
        "notification": "New membership by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "membership_type": "Premium",
        "is_active": true,
        "is_deleted": false,
        "time_of_op": "2026-06-10T14:01:54.207191Z",
        "created_at": "2026-07-15T17:07:03.776979Z"
      },
      {
        "id": 501,
        "notification": "New membership by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "membership_type": "Premium",
        "is_active": true,
        "is_deleted": false,
        "time_of_op": "2026-06-10T14:01:54.207191Z",
        "created_at": "2026-07-15T17:07:02.120240Z"
      },
      {
        "id": 497,
        "notification": "New subscription by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "status": "past_due",
        "time_of_op": "2026-07-15T17:06:57.521501Z",
        "created_at": "2026-07-15T17:07:02.120240Z"
      },
      {
        "id": 494,
        "notification": "New subscription by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "status": "past_due",
        "time_of_op": "2026-07-15T16:37:11.629451Z",
        "created_at": "2026-07-15T16:37:21.332619Z"
      },
      {
        "id": 492,
        "notification": "New membership by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "membership_type": "Premium",
        "is_active": false,
        "is_deleted": false,
        "time_of_op": "2026-06-10T14:01:54.207191Z",
        "created_at": "2026-07-15T16:37:21.332619Z"
      },
      {
        "id": 488,
        "notification": "New order by Jacob Israel",
        "store_name": "Emmanuel Electronics",
        "time_of_op": "2026-07-15T15:32:07.999572Z",
        "created_at": "2026-07-15T15:32:12.474630Z"
      },
      {
        "id": 485,
        "notification": "New review by Jacob Israel",
        "product_name": "HP Laptop",
        "store_name": "Emmanuel Electronics",
        "time_of_op": "2026-07-15T15:30:10.426155Z",
        "created_at": "2026-07-15T15:30:15.026719Z"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 188
    }
  }
}
```

---

### ⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.

* **verify_token**: Validates session signatures and extracts permissions.

---

### Security Guardrail

* **401 Unauthorized**: Dispatched when inbound sessions present malformed, modified, or expired access tokens.

