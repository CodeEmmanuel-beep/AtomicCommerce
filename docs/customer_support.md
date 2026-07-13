# 🎧 Customer Support Module

The Customer Support Module handles store-level issue remediation, user-to-merchant message routing, and support thread management. It enables store owners and their designated staff to manage, track, and resolve inquiries initiated by their specific storefront users. It also manages multi-tenant customer care lifecycles, load-balanced ticket allocation routing, asynchronous storage engine integration, and message-state indicators

---

### 📡 Server-Client Interface

* **Load-Balanced Support Allocation**: Employs an automated, aggregate load-routing query to detect and assign incoming help requests to active, qualified store personnel or operators. The engine groups unresolved entries via an inner subquery (`TicketStatus.open`, `TicketStatus.in_progress`), matching them against parent structures via an outer join that filters for active states (`User.is_active.is_(True)`). It then routes the ticket to the least-burdened operator using a dynamic ascending null-coalesced ordering sequence:

$$func.coalesce(subq.c.cnt, 0).asc()$$


* **Dual-Perspective Message Slicing & Indicators**: Manages role-filtered lookups (`customer_view` vs. `support_view`) using programmatic message-state synchronizations. Queries compile unified conversation strings (`func.concat(func.least(...), ":", func.greatest(...))`) while tracking unread volumes via subquery aggregations. When lists are pulled, the endpoint triggers selective bulk update records (`update(Messaging).where(...)`) to switch unseen flags (`seen=True, delivered=True`) for incoming messages natively at the database level.
* **Logical Partitioned Thread Erasures**: Restricts entry removal workflows by support until the parent status field resolves to `TicketStatus.closed`. Bulk messaging erasures employ conditional expressions (`case`) inside atomic sql updates (`update(Messaging)`) to switch delete vectors (`sender_deleted`, `receiver_deleted`) based on the active agent perspective, completely separating the thread viewpoints without breaking compliance logging balances.

📐 **Architectural Decisions & Safeguards**:

* **Decoupled Multi-State Orphan Purging**: Media attachments handle multi-tier file asset additions using async external storage uploads (`upload_photo_helper`) backed by Supabase buckets before database entries are written. If a subsequent transaction block drops due to database errors or runtime interruptions, an exception handler overrides execution, calls a cleanup block (`cleaned_up`) to target and purge the newly uploaded storage file path, and executes an `await db.rollback()` to prevent orphaned file assets.
* **Strict Concurrency Thread Fencing**: Intercepts ticket update threads by applying row-level locks (`with_for_update()`) on targeted parent rows. This layer blocks cross-concurrency edits, protects resolution status changes (`TicketStatus.closed`), maintains structural integrity across temporal updates (`ticket.updated_at`), and handles inactivity locks (blocking closures until 2 days post-interaction) securely.


---

### 📋 Business Rules

* **Ticket Cap**: Users are restricted to a maximum of one active ticket (`Open` or `In_Progress` state) at any given time to prevent channel flooding.
* **Delete Restriction**: Support personnel can only execute deletion sweeps on threads where the parent ticket status is explicitly set to `Closed`.
* **Ticket Closure Restriction**: Support agents can only manually close tickets that have been completely inactive (no messages sent) for a minimum of 2 days.
* **Unattended Ticket Protection**: An agent is only allowed to resolve/close a ticket that they have actively replied to.
* **Automatic Closure**: If a storefront user completely clears/deletes their conversation history on a ticket, the ticket status is automatically transitioned to `Closed`.
* **Last Message Rendering**: The conversation list endpoint is optimized to query and display the single most recent message payload in each conversation block.

---

### Core Endpoints

**Message Support**

`POST api/v1/customer_service/message_support`

Couples outgoing message with ticket creation to provide a seamless user experience.

**Request Payload**

```python
store_id: int
subject: str
message: str | None = None
picture: UploadFile = File(None)
```

**JSON Response**

```json
{"status": "success", "message": "successfully sent to customer support"}
```

---

**Fetch Messages**

`GET api/v1/customer_service/view_ticket_messages`

Retrieves a paginated list of messages attached to a ticket. Can only be viewed by the assigned support operator (`Ticket.assigned_to == user_id`) or the initiating customer (`Ticket.user_id == user_id`).

**Request Payload**

```python
 store_id: int,
 ticket_id: int,
view: str = Query("customer_view", enum=["support_view", "customer_view"]),
 page: int = Query(1, ge=1),
 limit: int = Query(10, le=100),
```

**JSON Response**

```json
{
  "status": "success",
  "message": "your messages",
  "data": {
    "conversations": [
      {
        "conversation_id": "3:11",
        "store_photo": "634e8496-7149-466e-98e3-d8e4bab86658_Screenshot_2025-11-25_140924.png",
        "customer_photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/c7b4f5cd-11d4-45ae-b1f0-5159d1f4286d_passport_white_background.jpeg",
        "customer_support": "John Cena",
        "customer": "Calvin Klein",
        "ticket_id": 1,
        "ticket_status": "closed",
        "messages": [
          {
            "id": 10,
            "sender": "customer_support",
            "message": "we await your patronage sir",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-08T17:36:07.062920Z"
          },
          {
            "id": 9,
            "sender": "customer",
            "message": "okay, when I am ready, I will come ",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-08T17:28:35.411178Z"
          },
          {
            "id": 7,
            "sender": "customer_support",
            "message": "sorry sir for the late reply, yes we do sell HP of the best quality! We await your patronage",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-07T14:01:30.750281Z"
          },
          {
            "id": 6,
            "sender": "customer",
            "photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/sign/customer_support/b4400e0a-bc62-40e6-b1ab-c64fcca74a67_Screenshot_2026-07-07_143856.png?token=eyJraWQiOiJzdG9yYWdlLXVybC1zaWduaW5nLWtleV8xMjQ2ODE4MC0zMjBmLTQ1M2EtOWNmZS1kYjZkMDg4MTJiY2EiLCJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJjdXN0b21lcl9zdXBwb3J0L2I0NDAwZTBhLWJjNjItNDBlNi1iMWFiLWM2NGZjY2E3NGE2N19TY3JlZW5zaG90XzIwMjYtMDctMDdfMTQzODU2LnBuZyIsInNjb3BlIjoiZG93bmxvYWQiLCJpYXQiOjE3ODM3NzE4OTksImV4cCI6MTc4Mzc3OTA5OX0.wiLtO4kBLQvv2Kp36ABHs3lOn4HLmMd4MfsWAHxc5Ao",
            "message": "I have sent you a message for hours now and no reply, do well to reply me!",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-07T13:50:15.390699Z"
          },
          {
            "id": 1,
            "sender": "customer",
            "photo": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/sign/customer_support/07cf2168-cabe-4546-bbb4-231dfb36c09c_project1.jpg?token=eyJraWQiOiJzdG9yYWdlLXVybC1zaWduaW5nLWtleV8xMjQ2ODE4MC0zMjBmLTQ1M2EtOWNmZS1kYjZkMDg4MTJiY2EiLCJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJjdXN0b21lcl9zdXBwb3J0LzA3Y2YyMTY4LWNhYmUtNDU0Ni1iYmI0LTIzMWRmYjM2YzA5Y19wcm9qZWN0MS5qcGciLCJzY29wZSI6ImRvd25sb2FkIiwiaWF0IjoxNzgzNzcxODk5LCJleHAiOjE3ODM3NzkwOTl9.MpWacrFZHO0AVyI42hyZKPCVLu5FBO57TONNhb-Gaeg",
            "message": "Please is your HP reliable, I dont want to purchase something I would later regret",
            "delivered": true,
            "seen": true,
            "time_of_chat": "2026-07-06T15:27:03.803069Z"
          }
        ]
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 5
    }
  }
}
```

---

**Support Resolve Ticket**

`PUT api/v1/customer_service/support_resolve_ticket`

Invoked by store operators to transition a ticket state to closed when validation checks are satisfied.


**Request Payload**
```python
 store_id: int
 ticket_id: int
```

**JSON Response**

```json
{"status": "success", "message": "ticket closed due to inactivity"}
```

---

**Delete Conversation**

`DELETE api/v1/customer_service/delete_conversation`

Performs a logical deletion of all messages associated with the specified ticket from the caller's perspective. The underlying conversation history is preserved until both participants clear the thread or retention policies apply.

**Request Payload**

```python
 store_id: int
 ticket_id: int
 agent: str = Query("customer", enum=["support", "customer"])
```

**JSON Response**

```json
{"status": "success", "message": "conversation successfully cleared"}
```

---

⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.

* **verify_token**: Validates session signatures, parses permissions, and returns both the individual user_id and the linked merchant store_id.

* **get_supabase**: Retrieve the persistent Supabase client registered globally on `request.app.state.supabase` during the application lifespan. This client is used to upload files to your private storage buckets and generate time-bound, secure signed URLs without the overhead of client re-initialization.

---

### Security Guardrails

400 Bad Request: Dispatched during out-of-order state transitions, database integrity errors, or attempts to post to a frozen thread.

403 Forbidden: Dispatched during validation failures, or when invalid auth session tokens are provide

404 Not Found: Dispatched if a specified ticket_id or targeted resource index does not exist within the active workspace records
