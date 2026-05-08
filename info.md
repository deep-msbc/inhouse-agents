# DWERP Backend — Project Information

## Project Overview
**DWERP** is a multi-tenant B2B SaaS platform for managing enquiries, products, quotations, and customer relationships. Built with Django 5.2 + Django REST Framework (DRF), PostgreSQL, and Supabase JWT authentication. Implements row-level security (RLS), multi-tenancy, and role-based access control (RBAC).

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| **Framework** | Django 5.2 + Django REST Framework |
| **Database** | PostgreSQL 13+ (psycopg3) |
| **Authentication** | JWT (JSON Web Tokens) |
| **RBAC** | msbc-rbac v0.0.29 |
| **API Documentation** | drf-spectacular (OpenAPI 3.0) |
| **Testing** | pytest + pytest-django |
| **Linting** | ruff |
| **Production** | gunicorn + Nginx (Dockerfile included) |
| **Env Management** | uv (preferred), python-dotenv |

---

## Project Structure

```
DWERP_BE/
├── auth_app/                          # Authentication, users, tenants, RBAC
│   ├── models/
│   │   ├── __init__.py               # Exports TenantModel, UserModel
│   │   ├── tenant_model.py           # Multi-tenancy root model
│   │   └── user_model.py             # AbstractUser-based user model
│   ├── utils/
│   │   ├── guard_utils.py            # Permission classes (require_role, IsWriteAllowed)
│   │   ├── jwt_utils.py              # JWT decode/encode utilities
│   │   └── validators.py             # Custom validators for auth
│   ├── serializers/
│   │   ├── auth_serializer.py        # Signup, login, password reset
│   │   └── user_serializer.py        # User CRUD
│   ├── services/
│   │   └── auth_service.py           # Business logic (signup, login, invite)
│   ├── middleware.py                 # JWTAuthMiddleware (token decode, role load, RLS context)
│   ├── management/
│   │   └── commands/
│   │       └── setup_rbac.py         # Seed static roles to all tenants
│   └── urls.py
│
├── enquiry_app/                       # Enquiries, products, follow-ups, documents
│   ├── models/
│   │   ├── enquiry_model.py          # Main enquiry model (soft-deleted)
│   │   ├── product_model.py          # Line items for enquiries
│   │   ├── document_model.py         # Attached files
│   │   └── __init__.py
│   ├── services/
│   │   └── enquiry_service.py        # CRUD, status transitions, role-based filtering
│   ├── serializers/
│   │   ├── enquiry_serializer.py
│   │   ├── product_serializer.py
│   │   ├── document_serializer.py
│   │   └── follow_up_serializer.py
│   ├── views/
│   │   ├── enquiry_view.py           # EnquiryViewSet (main CRUD)
│   │   ├── product_view.py           # ProductViewSet
│   │   ├── follow_up_view.py         # FollowUpViewSet
│   │   └── document_view.py          # DocumentViewSet
│   └── urls.py
│
├── common/                            # Shared utilities, abstract models, lookups
│   ├── models/
│   │   ├── base.py                   # AuditedModel, MinimalModel, TenantModel (abstract)
│   │   ├── lookup_model.py           # Lookup table (config-driven enums)
│   │   └── __init__.py
│   ├── utils/
│   │   ├── constants_utils.py        # Enum constants (ENQUIRY_STATUSES, etc.)
│   │   ├── decorators.py             # @require_tenant, @atomic
│   │   └── serializer_utils.py       # Reusable serializer mixins
│   └── models/
│       ├── follow_up_model.py        # Generic follow-up (GenericForeignKey)
│       └── note_model.py             # Generic notes
│
├── DWERP_BE/
│   ├── settings.py                   # Django settings, installed apps, middleware
│   ├── urls.py                       # Root URL routing
│   ├── asgi.py
│   ├── wsgi.py
│   └── middleware.py
│
├── api/
│   └── v1/
│       ├── __init__.py
│       ├── auth_app/
│       │   ├── views/
│       │   │   ├── auth_view.py      # Login, signup, refresh, invite
│       │   │   └── user_view.py      # User list/update
│       │   └── urls.py
│       ├── enquiry_app/
│       │   ├── views/
│       │   │   ├── enquiry_view.py
│       │   │   ├── product_view.py
│       │   │   ├── follow_up_view.py
│       │   │   └── document_view.py
│       │   └── urls.py
│       └── urls.py
│
├── manage.py
├── pytest.ini
├── ruff.toml
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── CLAUDE.md                         # Developer guidance

```

---

## Core Architecture

### Multi-Tenancy
Every table (except `tenants`) has a `tenant_id` UUID foreign key. **All querysets must explicitly filter by `tenant_id`.** Implicit tenant scoping is **never** safe.

**Key points**:
- `TenantModel` is the root; all other entities inherit `tenant_id` from abstract `TenantModel` (in `common/models/base.py`)
- Row-level security (RLS) is enforced at the PostgreSQL layer via `current_setting('app.tenant_id')` (set by middleware)
- Service layer enforces `require_tenant()` decorator on all write operations

**Isolation**:
```python
# Always explicit
Enquiry.objects.filter(tenant_id=request.user.tenant_id)

# Never implicit
Enquiry.objects.all()  # UNSAFE — includes all tenants!
```

---

### Authentication Flow

1. **Client** sends `POST /auth/login/` with email + password
2. **AuthService** queries `UserModel` by email, checks password via Django's `check_password()`
3. **Response** includes `access_token` (JWT) + `refresh_token` (both HS256 signed)
4. **Client** stores token, sends `Authorization: Bearer <token>` on all requests

**JWT Token Structure** (HS256 signed):
```json
{
  "sub": "user-id-uuid",
  "email": "user@example.com",
  "tenant_id": "tenant-uuid",
  "iat": 1234567890,
  "exp": 1234571490
}
```

**Token Generation**: Uses `jwt.encode()` with `SECRET_KEY` (HS256).
**Token Verification**: Uses `jwt.decode()` with `SECRET_KEY` for standard validation; no external JWKS required.

---

### JWTAuthMiddleware Workflow

1. **Request arrives** → Middleware runs before view
2. **Check bypass list** → Skip auth for `/admin/`, `/schema/`, `/docs/`, etc.
3. **Extract Bearer token** from `Authorization: Bearer <token>` header
4. **Decode JWT** using `SECRET_KEY` (HS256 signature verification)
5. **Build CurrentUser** from JWT claims (`sub`, `email`, `tenant_id`)
6. **Load roles from DB** → Query `msbc_rbac.accounts.UserRole` for all roles in (user, tenant)
7. **Set RLS context** → Execute `set_config('app.tenant_id', '<uuid>')` in PostgreSQL session
8. **Pass to view** as `request.user` (CurrentUser dataclass)

**Error handling**:
- **No token** or invalid header → `request.user = _AnonymousUser(is_authenticated=False)`
- **Expired token** → Same, plus `request._jwt_expired = True`
- **Invalid signature** → Same
- **DRF permission classes** return **401** for any unauthenticated request to protected endpoints

---

### CurrentUser Dataclass

```python
@dataclass
class CurrentUser:
    id: uuid.UUID                           # User PK
    email: str                              # Unique per tenant
    tenant_id: uuid.UUID | None             # Active tenant
    roles: list[str] = field(...)           # All role names from DB
    raw_claims: dict = field(...)           # Original JWT payload (read-only)
    is_active: bool = True
    is_authenticated: bool = True
    is_anonymous: bool = False
```

---

### RBAC (Role-Based Access Control)

**Models** (from `msbc-rbac`):
- `Role` (in `msbc_rbac.core`) — role definition with `name`, `description`, `tenant_id`, `is_active`, `is_deleted`
- `Permission` (in `msbc_rbac.core`) — granular permission (e.g., "create_enquiry")
- `UserRole` (in `msbc_rbac.accounts`) — many-to-many link from user to role per tenant

**Unique Constraint**: `Role(name, tenant)` — prevents duplicate role names within a tenant.

**Standard DWERP Roles**:
| Role | Permissions | Notes |
|------|-------------|-------|
| `admin` | Full system access | Can invite users, manage roles |
| `director` | Director-level operations | Can approve quotations, manage teams |
| `manager` | Manager-level operations | Can create enquiries, assign work |
| `sales_rep` | Sales operations | Can create/update enquiries, view products |
| `estimator` | Read-only + own estimates | Can only view assigned enquiries, create quotes |

**Permission Factories**:

1. **`require_role(*allowed_roles)`** — Returns a DRF `BasePermission` class:
   ```python
   from auth_app.utils.guard_utils import require_role
   
   class EnquiryViewSet(ModelViewSet):
       def get_permissions(self):
           if self.action == 'create':
               return [require_role('admin', 'manager', 'sales_rep')()]
           return [IsAuthenticated()]
   ```
   Allows access if **any** of the user's roles match.

2. **`IsWriteAllowed()`** — Blocks mutating requests on the demo tenant:
   ```python
   class ProductViewSet(ModelViewSet):
       def get_permissions(self):
           if self.action in ('create', 'partial_update', 'destroy'):
               return [require_role('sales_rep')(), IsWriteAllowed()]
           return [IsAuthenticated()]
   ```

---

### Role Seeding (setup_rbac Command)

**Command**: `python manage.py setup_rbac`

**Behavior**:
1. Gets all active tenants from `TenantModel`
2. For each tenant, creates the 5 standard DWERP roles using `get_or_create(name=<role>, tenant=<tenant>)`
3. Prevents duplicates via `Role(name, tenant)` unique constraint
4. Calls `api_sync_db` to sync full RBAC structure (permissions, modules, submodules)
5. Displays progress: Created vs. Existing counts per tenant

**Output**:
```
→ Seeding roles for tenant: ACME Corp
  ✓ Created role: admin
  ✓ Created role: director
  ⊙ Role already exists: manager
  ⊙ Role already exists: sales_rep
  ✓ Created role: estimator
  → Tenant summary: Created 3, Existing 2

✓ Role setup completed! (Total Created: 15, Total Existing: 5)
```

---

## Database Models

### auth_app

**TenantModel** — Root of multi-tenancy
- `id` (UUID, PK)
- `name` (CharField, unique)
- `is_active` (BooleanField)
- `created_at`, `updated_at` (DateTimeField, auto)

**UserModel** — Extends Django's `AbstractUser`
- `id` (UUIDField, default=uuid4, PK)
- `email` (EmailField, unique per tenant via constraint)
- `full_name` (CharField)
- `department` (CharField, nullable)
- `phone` (CharField, nullable)
- `tenant` (ForeignKey → TenantModel)
- `password` (inherited from AbstractUser, uses `make_password()`)
- `is_active`, `is_staff`, `is_superuser` (inherited)
- `created_at`, `updated_at` (DateTimeField, auto)
- `USERNAME_FIELD = 'email'`

**msbc_rbac.accounts.UserRole** — Links UserModel to Role
- `user` (ForeignKey → User)
- `role` (ForeignKey → Role)
- `tenant` (ForeignKey → TenantModel)
- Unique constraint: `(user, role, tenant)`

### enquiry_app

**EnquiryModel** — Main entity (soft-deleted via AuditedModel)
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → TenantModel)
- `enquiry_type` (CharField, no choices; values from Lookup table)
- `enquiry_source` (CharField, no choices; values from Lookup table)
- `status` (CharField, values in `ENQUIRY_STATUSES` constant)
- `priority` (CharField, values in `ENQUIRY_PRIORITIES` constant)
- `created_by` (UUID, FK → User)
- `updated_by` (UUID, FK → User)
- `estimator_id` (UUID, FK → User, nullable; assigned user who estimates)
- `deleted_at` (DateTimeField, null; soft delete via AuditedModel)
- `created_at`, `updated_at` (DateTimeField, auto)

**ProductModel** — Line items (hard-deleted)
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → TenantModel)
- `enquiry_id` (UUID, FK → EnquiryModel, CASCADE)
- `product_category` (CharField, no choices; from Lookup)
- `product_name` (CharField)
- `quantity` (DecimalField)
- `unit_price` (DecimalField)
- `created_by`, `updated_by` (UUID, FK → User)
- `created_at`, `updated_at` (DateTimeField, auto)

**DocumentModel** — Attachments
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → TenantModel)
- `enquiry_id` (UUID, FK → EnquiryModel, CASCADE)
- `file` (FileField, stored in S3 or media)
- `file_type` (CharField)
- `uploaded_by` (UUID, FK → User)
- `created_at` (DateTimeField, auto)

**common.FollowUpModel** — Generic follow-ups via GenericForeignKey
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → TenantModel)
- `content_type` (ForeignKey → ContentType)
- `object_id` (UUIDField) — Links to enquiry, quotation, contact, etc.
- `follow_up_type` (CharField, no choices; from Lookup)
- `notes` (TextField)
- `status` (CharField)
- `created_by`, `updated_by` (UUID, FK → User)
- `created_at`, `updated_at` (DateTimeField, auto)

**common.LookupModel** — Config-driven enums
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → TenantModel, nullable for global defaults)
- `lookup_type` (CharField; e.g., "enquiry_type", "product_category")
- `lookup_value` (CharField; e.g., "leads", "high_priority")
- `label` (CharField; display name)
- `display_order` (IntegerField)
- Unique constraint: `(tenant_id, lookup_type, lookup_value)`

---

## API Endpoints

All endpoints require `Authorization: Bearer <token>` except public routes.

### Auth Endpoints
```
POST   /auth/signup/           — Create account
POST   /auth/login/            — Get access + refresh tokens
POST   /auth/refresh/          — Refresh access token
POST   /auth/forgot_password/  — Request password reset
POST   /auth/reset_password/   — Complete password reset
POST   /auth/verify_email/     — Verify email
POST   /auth/invite/           — Invite user (admin/director/manager only)
POST   /auth/resend_invite/    — Resend invite (admin/director/manager only)
GET    /auth/me/               — Get current user profile
PATCH  /auth/me/               — Update current user
```

### User Endpoints
```
GET    /users/                 — List tenant users
GET    /users/{id}/            — Get user details
PATCH  /users/{id}/            — Update user (admin/director/manager only)
```

### Enquiry Endpoints
```
GET    /enquiry/               — List enquiries (filtered by role & tenant)
POST   /enquiry/               — Create enquiry (sales_rep+)
GET    /enquiry/{id}/          — Get enquiry details
PATCH  /enquiry/{id}/          — Update enquiry (sales_rep+)
DELETE /enquiry/{id}/          — Soft delete
POST   /enquiry/{id}/products/ — Add product line item
PATCH  /enquiry/{id}/products/{pid}/ — Update product
DELETE /enquiry/{id}/products/{pid}/ — Delete product
```

### Product, FollowUp, Document Endpoints
(Similar pattern: GET list, POST create, PATCH update, DELETE soft/hard delete)

### API Docs
```
GET    /api/schema/            — OpenAPI 3.0 JSON
GET    /api/docs/              — Swagger UI
GET    /api/redoc/             — ReDoc
```

---

## Key Conventions

### Service Layer
All business logic lives in service classes (e.g., `EnquiryService`, `AuthService`). Views are thin:
```python
View → serializer.is_valid() → service method → serializer response
```

Example:
```python
class EnquiryViewSet(ModelViewSet):
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = EnquiryService.create_enquiry(
            request.user,
            request.user.tenant_id,
            serializer.validated_data
        )
        return Response(self.get_serializer(instance).data)
```

### No `choices=` on Models
Enum/status validation lives in the service or serializer, not as `choices=` on model fields. This allows values to evolve without migrations.

### Soft Deletes
- **AuditedModel** entities (enquiries, etc.) use `deleted_at` (DateTimeField, null)
- Always query via `.objects.active()` for live records
- Raw `.objects.all()` includes soft-deleted rows (rarely used)

### Tenant Requirement
Every service method that touches the DB requires `tenant_id`:
```python
def create_enquiry(user: CurrentUser, tenant_id: UUID, data: dict):
    # Validate tenant_id matches user
    if user.tenant_id != tenant_id:
        raise PermissionDenied()
    # Always filter by tenant
    Enquiry.objects.filter(tenant_id=tenant_id).create(...)
```

### Lookup Values (Config-Driven Enums)
Lookups are config-driven and can be extended by the admin without code changes:
```python
# Query lookup values
from common.models import LookupModel

enquiry_types = LookupModel.values_for('enquiry_type', tenant_id)
# Returns: ['leads', 'rfq', 'project', ...]
```

---

## Startup & Deployment

### Local Development
```bash
# 1. Create migrations
python manage.py makemigrations

# 2. Apply migrations
python manage.py migrate

# 3. Seed roles and lookup values
python manage.py setup_rbac
python manage.py seed_lookups

# 4. Create superuser (optional)
python manage.py createsuperuser

# 5. Run dev server
python manage.py runserver
# or with uv:
uv run manage.py runserver
```

### Docker
```bash
# Build and start containers
docker-compose up --build

# Run migrations inside container
docker exec -it dwerp_be python manage.py migrate
docker exec -it dwerp_be python manage.py setup_rbac
```

### Environment Variables
Required in `.env`:
```env
SECRET_KEY=<your-secret-key>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=dwerp
DB_USER=postgres
DB_PASSWORD=<password>
DB_HOST=localhost
DB_PORT=5432

PORT=8000
IP=0.0.0.0
BASE_URL=http://localhost:3000
```

**JWT Configuration**:
- **Token signing**: Uses `SECRET_KEY` (HS256)
- **Token expiry**: Set in `jwt_utils.py` (access token: 1 hour, refresh token: 7 days by default)
- **Decoding**: `jwt_utils.decode_access_token()` handles verification

---

## Testing

```bash
# Run all tests
pytest

# Run single app
pytest enquiry_app/

# Run single test
pytest -k "test_create_enquiry"

# Coverage report
pytest --cov=. --cov-report=term-missing
```

---

## Code Quality

```bash
# Lint
ruff check .

# Fix linting issues
ruff check . --fix
```

---

## External Integrations

### Cross-Service Tables
- `organizations` and `quotations` are managed by another service (shared PostgreSQL DB)
- Query via raw SQL; do **not** add Django migrations for these tables

---

## Common Debugging

| Issue | Solution |
|-------|----------|
| 401 on protected endpoint | Check token expiry, verify `Authorization: Bearer <token>` header |
| 403 on write endpoint | Check user's roles via `request.user.roles` in debugger |
| Tenant isolation error | Ensure all querysets filter by `tenant_id` explicitly |
| Stale role after update | Roles are loaded from DB, not JWT; check `msbc_rbac.accounts.UserRole` table |
| Duplicate role creation | Role(name, tenant) unique constraint prevents duplicates; use `get_or_create()` |
| RLS policy blocking query | Check `current_setting('app.tenant_id')` is set in PostgreSQL session |

---

## Team Contacts & Resources

- **Issue Tracking**: [Linear project]
- **Documentation**: [Confluence/Notion]
- **API Docs**: `GET /api/docs/` (Swagger UI)
- **Developer Email**: claudeseat3@msbcgroup.com

---

**Last Updated**: 2026-05-04
