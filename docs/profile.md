# 👤 User Profile Module

Governs identity lifecycle validation, strict role-segregated governance protocols, dynamic field synchronization, and soft-deactivation privacy walls.

---

## 📡 Server-Client Interface

* **Syntax-Enforced Identity Screening**: Protects electronic profile metadata by intercepting email update sequences. It channels string evaluations through specialized external syntax parsers (`validate_email`), throwing an immediate 400 Bad Request if the target payload breaks RFC standard specifications.

* **Hierarchical Self-Deletion Walls**: Controls destructive profile pathways through a rigid multi-tier role authorization structure. Base consumer identities are permitted to self-terminate, but cross-profile administrative commands trigger secondary authorization logic: standard admins cannot drop target accounts if the resource role evaluates as an `Owner`, nor can they delete other peer `Admin` records.

* **Idempotent State-Locked Suppression**: Prevents redundant transactional state writes by pre-checking existing runtime flags before processing deactivations. If a profile's operational state is already disabled (`not data.is_active`), the execution block short-circuits and safely outputs a success response without executing additional database operations.

📐 **Architectural Decisions & Safeguards**:

* **Dual-Query Unique Allocation Checks**: Eliminates identity conflicts during active updates by verifying email exclusivity before committing changes. If an email modification deviates from the authenticated baseline record, the pipeline initiates a fast existence subquery (`select(exists().where(User.email == profile.email, User.id != user_id))`) to check if the identifier is already claimed elsewhere.

* **Audit-Safe Deletion Topology**: Avoids destructive database record purging (`DELETE`) to maintain structural history. The deactivation workflow executes a logical deactivation by setting (`User.is_active = False`), immediately isolating the targeted entry from subsequent retrieval queries while maintaining database relational integrity.

* **Dynamic Nullable Mutation Masking**: Optimizes update patterns by dynamically matching structural updates against explicit field arrays (`fields`). The service separates standard properties from explicitly defined empty parameters (`nullable = ["middle_name", "address"]`), allowing specific text properties to be cleared out while tracking change flags (`has_changed = True`) to minimize unnecessary write cycles.

* **Background Asset Resolvers**: Normalizes public profile outputs by resolving internal storage keys into full URLs. Read sequences route file path tokens through an external cloud asset engine (`get_public_url(profile.profile_picture)`), abstracting underlying asset topologies from client applications.

### Business Rule

* **Nullable Fields**: Only `address`, and `middle_name` are optional; the remaining profile attributes are strictly non-nullable.

* **Profile Delete Logic**: A profile can be self-deactivated by the resource owner or administratively purged by a `SuperAdmin`.

* **Immunity & Administrative Hierarchy**: A Platform Owner possesses complete authority to execute soft-deactivations on any account ledger, including peer Platform Administrators. However, the system enforces a strict runtime immunity lock that completely prevents the Platform Owner's account record from ever being targeted for deactivation.

---

## Core Endpoints

**Update Profile Metadata**

`PUT api/v1/profile/update_profile`

Modifies an active customer's profile attributes, contact options, or settings.

**Request Payload**

```python
profile: ProfileMode
```

***ProfileMode Object***

```python
class ProfileMode(BaseModel):
    first_name: str = Form(None)
    middle_name: str = Form(None)
    surname: str = Form(None)
    email: str = Form(None)
    nationality: str = Form(None)
    phone_number: str = Form(None)
    address: str = Form(None)
```

**JSON Response**

```json
 {"status": "success", "message": "profile successfully edited"}
```

---

**Fetch Profile**

`GET api/v1/profile/personal_profile`

Fetches the active user's profile details using the unique user_id resolved from the validated JWT.

**JSON Response**

```json
{
    "status": "success",
    "message": "profile",
    "data": {
        "id": 8,
        "profile_picture": "https://xpaemtnkeiigcwxcaush.supabase.co/storage/v1/object/public/e_commerce/733d0321-2858-4c36-80a0-dbd9017a0156_payment_terminal_logs.png",
        "first_name": "Jacob",
        "middle_name": "Glory",
        "surname": "Israel",
        "username": "jayeye",
        "phone_number": "+972784983",
        "email": "jayglo@gmail.com",
        "nationality": "Israel",
        "address": "Tel Aviv"
    }
}
```

---

**Delete Profile**

`DELETE api/v1/profile/delete_personal_profile`

Executes a soft-deactivation mutation workflow on a targeted profile record.

**Request Payload**

```python
userId: int | None = None,
```

**JSON Response**

```json
{
 "status": "success",
 "message": "deleted profile",
 "data": {
    "id": 5,
    "user_id": 5,
    "deleted": "Yes",
          }
}
```

---

⚙️ Module Dependencies

The routes within this module inherit the following controller structures:

* **get_db**: Context manager providing asynchronous pool operations to the database tier.

* **verify_token**: Validates session signatures and extracts permissions.

### Security Guardrails

* **400 Bad Request**: Dispatched during database integrity errors, unique schema index collisions, structural evaluation failures, or email syntax validation errors.

* **401 Unauthorized**: Dispatched when authentication credentials are missing, malformed, expired, or the supplied JWT fails validation.

* **403 Forbidden**: Dispatched if a merchant, unprivileged user, or standard administrator attempts unauthorized or out-of-rank administrative account deactivations, or if any entity targets a Platform Owner for deactivation.

* **404 Not Found**: Dispatched if a specified target record or parent identifier does not exist in active storage blocks.

* **500 Internal Server Error**: Dispatched as an unmapped escape route to cleanly catch unhandled thread runtime exceptions.

---
