# 🔐 Authentication & Authorization Module

The Auth module manages secure user provisioning, multi-tenant authentication lifecycles, and cryptographic authorization mechanics across the application ecosystem.

---

## ⚙️ Environment Variables & Configuration

Configure the following variables in your local `.env` file to initialize the module:

| **Variable** | **Type** | **Description** | **Example** |
| --- | --- | --- | --- |
| ***JWT Secret Key*** | String | High-entropy cryptographic string used to sign stateless tokens. | `your_super_long_secret_key` |
| ***JWT Access Token Expire Minutes*** | Integer | Lifespan profile for short-lived access tokens. | `15` |
| ***JWT Refresh Token Expire Days*** | Integer | Lifespan profile for long-lived, rotating refresh tokens. | `7` |

---

### Server-Client Interface

* **Registration Engine**: Validates emails and enforces a blacklisted registry of reserved terms (root, admin, system) alongside spatial restrictions. Normalizes all incoming username patterns via low-level SQL transformations (func.lower(func.trim())) to avoid duplicate variations.

* **Security & Token Rotations**: Issues short-lived JWT authorization headers alongside isolated HttpOnly, SameSite=Lax, and Secure cookie-based refresh tokens. Implements immediate Refresh Token Rotation on every invocation to block token-reuse vectors out of the box.

* **Access Control Policies**: Implements strict administrative tenancy checks, preventing standard users or foreign node objects from modifying user access flags while restricting structural owners from self-redesignation blocks.

📐 **Architectural Decisions & Safeguards**:

> 💡 **Decoupled Asset Upload Pipeline**
> Profile picture uploading is explicitly isolated from the core user registration transaction path. Because media handling relies on external I/O operations to Supabase Storage Buckets, decoupling this ensures network latencies or third-party cloud failures never cause a fatal drop during a user's initial onboarding block.

* **Memory-Safe Asset Capping**: Profile media uploads leverage an asyncio chunked streaming processor that enforces a hard 5MB size cap in flight and performs strict binary byte-level magic number parsing to restrict files exclusively to jpeg, png, and webp.

* **Transactional Orphan Purging**: If a database transaction fails after a media payload has been written to the bucket, an automated cleanup helper (cleaned_up) intercepts the exception context, rolling back the database state and issuing a delete vector to the storage engine to keep the asset bucket zero-orphan compliant.

### Core Endpoint

**User Registration**
`POST api/v1/auth/registration`

Handles users onboarding
**Request Payload**

```python
class RegistrationModel(BaseModel):
    first_name: str = Form(...)
    surname: str = Form(...)
    username: str = Form(...)
    email: str = Form(...)
    nationality: str = Form(...)
    address: str = Form(None)
    password: str = Form(...)
    confirm_password: str = Form(...)
```

**Registration JSON Response**
```jsonc
{
 "status":"success",
 "message": "Registeration Successful {registration.username}, login to continue",
}
```
---
**Photo Upload**
`Post api/v1/auth/profile_picture`

Streams asset chunks to cloud storage buckets. Protected by bearer token validation.

***Request Payload***
```python
profile_picture: UploadFile = File(...)
```

**Photo Upload JSON Response**

```jsonc
{
 "status":"success",
 "message": "profile picture uploaded successfully",
}
```

---

**Login**
`Post api/v1/auth/login`

Exchanges valid credentials for a bearer token. Sets a rolling refresh token in a secure cookie.

**Request Payload**
```python
class LoginResponse(BaseModel):
    username: str
    password: str
```

**Login JSON Response**
```jsonc
{
  "status": "success",
  "message": "login successful",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJuYW1lIjoiQ2VuYSIsInN1YiI6ImpheWNlZSIsInVzZXJfaWQiOjMsIm5hdGlvbmFsaXR5IjoiQW1lcmljYSIsInJvbGUiOiJ1c2VyIiwidHlwZSI6ImFjY2Vzc190b2tlbiIsImV4cCI6MTc4Mzc3NTQzN30.FdL6UEg5WqkcE-P6IrUsE_bq0_xv0eE8gqax2PK3Meo",
    "token_type": "Bearer"
  }
}
```
---

**Create Role**
`POST api/v1/auth/make_role`

Assigns privileges to an existing account node. Restricted to Admin/Owner tiers.

**Request Payload**

```python
    username: str,
    role: str = Query("user", enum=["Admin", "customer_care", "user"])
```

**Create Role JSON Response**

```jsonc
{
"status":"success",
 "message":"{username} assigned role {role}"
}
```
---

### Security Guardrails

* **401 Unauthorized**: Returned when a client fails authentication challenges, presents an expired/malformed JWT, or attempts access without a valid token.
* **403 Forbidden**: Returned when an authenticated client successfully establishes identity but fails explicit RBAC/tenancy validation checkpoints.

