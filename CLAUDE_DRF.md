# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Getting Started

**Fresh Setup** (after pulling code or resetting DB):
```bash
# 1. Create migrations for model changes
python manage.py makemigrations

# 2. Apply all migrations
python manage.py migrate

# 3. Seed static roles to all active tenants
python manage.py setup_rbac

# 4. Start dev server
python manage.py runserver
# or with uv (preferred):
uv run manage.py runserver
```

**Seed lookup values** (if needed):
```bash
python manage.py seed_lookups
```

**RBAC & Role Management**:
```bash
# Seed static DWERP roles to all active tenants (idempotent via get_or_create)
# Also syncs full RBAC structure (permissions, modules) via api_sync_db
python manage.py setup_rbac
```

## Commands

**Run dev server**
```bash
python manage.py runserver
# or with uv (preferred):
uv run manage.py runserver
```

**manage.py shortcuts** (single-arg shortcuts baked into manage.py):
```bash
python manage.py r     # runserver
python manage.py m     # migrate
python manage.py mm    # makemigrations
python manage.py sm    # showmigrations
python manage.py sh    # shell
python manage.py user  # createsuperuser
python manage.py setup_rbac  # seed roles to all tenants
```

**Migrations**
```bash
python manage.py mm <app_label>   # e.g. python manage.py mm enquiry_app
python manage.py m
```

**Lint**
```bash
ruff check .
ruff check . --fix
```

**Tests**
```bash
pytest
pytest enquiry_app/             # single app
pytest -k "test_create_enquiry" # single test by name
pytest --cov=. --cov-report=term-missing
```

**Docker (dev)**
```bash
docker-compose up
docker-compose up --build
```

**Seed lookup values**
```bash
python manage.py seed_lookups
```

## Project Structure

```
DWERP_BE/
├── auth_app/                          # Users, tenants, authentication, RBAC
│   ├── models/
│   │   ├── tenant_model.py           # Multi-tenancy root
│   │   └── user_model.py             # AbstractUser-based user model
│   ├── utils/
│   │   ├── guard_utils.py            # Permission classes (require_role, IsWriteAllowed)
│   │   └── jwt_utils.py              # JWT encode/decode
│   ├── serializers/                  # Auth, user, tenant serializers
│   ├── services/
│   │   └── auth_service.py           # Signup, login, invite, password reset
│   ├── middleware.py                 # JWTAuthMiddleware (token decode, role load, RLS)
│   └── management/commands/
│       └── setup_rbac.py             # Seed roles to all tenants
│
├── enquiry_app/                       # Enquiries, products, documents, follow-ups
│   ├── models/                        # Enquiry, Product, Document models
│   ├── services/
│   │   └── enquiry_service.py        # CRUD, status transitions, role-based filtering
│   ├── serializers/                  # Enquiry, Product, FollowUp, Document serializers
│   └── views/                        # ViewSets for each model
│
├── common/                            # Shared utilities and abstract models
│   ├── models/
│   │   ├── base.py                   # AuditedModel, MinimalModel, TenantModel (abstract)
│   │   ├── lookup_model.py           # Config-driven enums (enquiry_type, product_category)
│   │   ├── follow_up_model.py        # Generic follow-ups (GenericForeignKey)
│   │   └── note_model.py             # Generic notes
│   └── utils/
│       ├── constants_utils.py        # Business logic constants (ENQUIRY_STATUSES, transitions)
│       ├── decorators.py             # @require_tenant, @atomic
│       └── serializer_utils.py       # Reusable mixins
│
├── DWERP_BE/                          # Project settings
│   ├── settings.py                   # Django config, installed apps, middleware
│   ├── urls.py                       # Root URL routing
│   └── wsgi.py, asgi.py
│
├── api/
│   └── v1/
│       ├── auth_app/
│       │   ├── views/                # AuthViewSet, UserViewSet
│       │   └── urls.py               # /auth/, /users/ endpoints
│       └── enquiry_app/
│           ├── views/                # EnquiryViewSet, ProductViewSet, etc.
│           └── urls.py               # /enquiry/, /products/ endpoints
│
├── manage.py                          # Django management
├── pytest.ini                         # Pytest config
├── ruff.toml                          # Linter config
├── docker-compose.yml                 # Local dev containers
├── Dockerfile                         # Production image
├── requirements.txt                   # Dependencies
├── .env.example                       # Environment template
├── CLAUDE.md                          # This file (developer guidance)
└── info.md                            # Comprehensive project documentation
```

### Key Directory Notes

| Path | Purpose |
|------|---------|
| `auth_app/` | User authentication, JWT verification, RBAC (roles, permissions) |
| `enquiry_app/` | Business logic for enquiries, products, documents |
| `common/` | Shared models (base classes), utilities, constants, lookups |
| `api/v1/` | REST API views and URL routing |
| `DWERP_BE/` | Django project settings and root configuration |

---

## Architecture

### Tech Stack
Django 5.2 + Django REST Framework, PostgreSQL (psycopg3), JWT authentication (HS256), gunicorn in production.

### App Layout
Three Django apps, each with a clear responsibility boundary:

| App | Owns |
|-----|------|
| `auth_app` | `users`, `tenants` tables; JWT verification; RBAC; invite flow |
| `enquiry_app` | enquiries, products, documents, status history |
| `common` | Abstract base models; shared sub-resources (FollowUpModel, NoteModel); Lookup table; shared utils |

### Multi-Tenancy
Every table (except `tenants`) carries a `tenant_id` UUID for row-level isolation. This comes from the `TenantModel` abstract base in `common/models/base.py`. **Every queryset must filter by `tenant_id` — it is never implicit.** The service layer enforces this via `require_tenant()`.

### Authentication & User Model
**UserModel** extends Django's `AbstractUser` with DWERP-specific fields:
- `email` — USERNAME_FIELD (unique per tenant)
- `full_name`, `department`, `phone` — custom fields
- `tenant` — ForeignKey to TenantModel (multi-tenancy)
- Password management uses `password` field (inherited from AbstractUser via `make_password()`)

**JWT Middleware** (`auth_app/middleware.py`):
- Decodes Bearer JWT from `Authorization: Bearer <token>` header
- Verifies token via Supabase JWKS (ES256) or fallback (HS256)
- Sets `request.user` to `CurrentUser` dataclass with loaded roles
- **Unauthenticated requests** → `request.user = _AnonymousUser(is_authenticated=False)` → DRF returns **401** for protected endpoints
- **X-Tenant-ID header** allows immediate tenant switch without token reissue

**Role Loading**: After JWT decode, middleware queries `msbc_rbac.accounts.UserRole` to load all roles for the user in the active tenant. Roles are loaded from the **authoritative DB row**, not from JWT claims (which may be stale).

### RBAC (Role-Based Access Control)
Uses `msbc-rbac` package (`v0.0.29`). Roles are defined in `msbc_rbac.core.models.Role`:
- **Unique constraint**: `(name, tenant)` — prevents duplicate role names per tenant
- **Soft delete**: `is_deleted` flag and `is_active` for role lifecycle
- **Roles per user**: One user can have **multiple roles** via `msbc_rbac.accounts.UserRole`

**Standard DWERP roles** (seeded via `setup_rbac` command):
| Role | Access Level |
|------|--------------|
| `admin` | Full system access |
| `director` | Director level access |
| `manager` | Manager level access |
| `sales_rep` | Sales representative access |
| `estimator` | Estimator read-only access |

**Permission Factories** in `auth_app/utils/guard_utils.py`:
- `require_role(*allowed_roles)` — returns a DRF `BasePermission` class. Allows access if **any** of user's roles match. Use in `get_permissions()` on ViewSets.
- `IsWriteAllowed()` — blocks **mutating requests** (POST, PATCH, DELETE) on the demo tenant. Allows reads on any tenant.

**Usage in ViewSets**:
```python
from auth_app.utils.guard_utils import require_role, IsWriteAllowed
from rest_framework.permissions import IsAuthenticated

class EnquiryViewSet(ModelViewSet):
    def get_permissions(self):
        if self.action in ('create', 'partial_update', 'destroy'):
            return [require_role('admin', 'director', 'manager', 'sales_rep')(), IsWriteAllowed()]
        return [IsAuthenticated()]
```

### Model Conventions
- **No `choices=` on any model field.** All enum/status validation lives in the service or serializer layer so values can evolve without migrations.
- `AuditedModel` (top-level entities: enquiries, orgs, quotations…): soft delete via `deleted_at`, `created_by`/`updated_by` UUID, `SoftDeleteManager` with `.active()` / `.deleted()`.
- `MinimalModel` (child/line-item tables: products, follow-ups…): tenant + timestamps only, hard-deleted.
- Soft deletes: always use `EnquiryModel.objects.active()` for live records; raw `.objects.all()` includes soft-deleted rows.

### Enum Strategy — Lookup vs Constants
Two distinct patterns:
1. **`common.Lookup` table** — config-driven dropdowns that the admin can extend without code changes: `enquiry_type`, `enquiry_source`, `followup_type`, `product_category`. Query via `Lookup.values_for(lookup_type, tenant_id)`. Tenant-specific overrides stack on top of global defaults (`tenant_id IS NULL`).
2. **Constants in `constants_utils.py`** — state-machine statuses and priorities that are part of business logic and must not change at runtime: `ENQUIRY_STATUSES`, `VALID_STATUS_TRANSITIONS`, `ENQUIRY_PRIORITIES`.

### Service Layer Architecture

**Design Principle**: Views are intentionally thin; all business logic lives in service classes. This separates concerns and makes logic reusable, testable, and maintainable.

**Call Chain**:
```
HTTP Request
    ↓
View (thin — validates input only)
    ↓
Serializer.is_valid() (data validation)
    ↓
Service Method (business logic, orchestration)
    ↓
Repository (raw DB access, queries)
    ↓
Database
    ↓
Response (serializer wraps result)
```

**Service Classes** (`auth_app/services/`, `enquiry_app/services/`):
- Each service owns a domain (e.g., `AuthService`, `EnquiryService`)
- Contains public methods for all business operations (create, update, delete, status change, etc.)
- Handles validation, authorization, tenant scoping, state transitions
- Wraps write operations with `@transaction.atomic` for data consistency
- Never directly accessed by external code; only through views

**Repository Classes** (private `_*Repository` in services):
- DB access via Django ORM queries (`.filter()`, `.get()`, `.exclude()`, `.annotate()`, etc.)
- Called only by the containing service
- **Never use raw SQL** — always use ORM for queries, filters, and aggregations
- Example: `EnquiryService` has private `_EnquiryRepository` for queryset building

**Example Service Pattern**:
```python
# auth_app/services/auth_service.py
class AuthService:
    def __init__(self, repository=None):
        self._repo = repository or _AuthRepository()
    
    @transaction.atomic
    def signup(self, email: str, password: str, tenant_id: UUID, **data):
        # 1. Validate email not in use
        if self._repo.user_exists(email, tenant_id):
            raise ValueError("Email already registered")
        
        # 2. Hash password
        hashed = make_password(password)
        
        # 3. Create user
        user = self._repo.create_user(email, hashed, tenant_id, **data)
        
        # 4. Return result (view serializes)
        return user
    
    def login(self, email: str, password: str, tenant_id: UUID):
        # 1. Find user
        user = self._repo.get_user_by_email(email, tenant_id)
        if not user or not check_password(password, user.password):
            raise AuthenticationError("Invalid credentials")
        
        # 2. Generate tokens
        access_token = create_access_token(user)
        refresh_token = create_refresh_token(user)
        
        # 3. Return tokens
        return {'user': user, 'access_token': access_token, 'refresh_token': refresh_token}

class _AuthRepository:
    """Private repository for AuthService."""
    def user_exists(self, email: str, tenant_id: UUID) -> bool:
        return UserModel.objects.filter(email=email, tenant_id=tenant_id).exists()
    
    def create_user(self, email: str, password: str, tenant_id: UUID, **data):
        return UserModel.objects.create(
            email=email,
            password=password,
            tenant_id=tenant_id,
            **data
        )
    
    def get_user_by_email(self, email: str, tenant_id: UUID):
        return UserModel.objects.filter(email=email, tenant_id=tenant_id).first()
```

**View Usage** (thin and simple):
```python
# api/v1/auth_app/views/auth_view.py
class AuthViewSet(ViewSet):
    @action(detail=False, methods=['post'])
    def signup(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Delegate to service
        user = AuthService.signup(
            email=serializer.validated_data['email'],
            password=serializer.validated_data['password'],
            tenant_id=request.user.tenant_id,
            full_name=serializer.validated_data.get('full_name')
        )
        
        # Serialize response
        return Response(UserSerializer(user).data, status=201)
```

**Key Rules**:
1. **All business logic in services** — Never in views, serializers, or models
2. **Services are stateless** — No instance variables except the repository
3. **Transactions at service level** — `@transaction.atomic` on write methods
4. **Tenant filtering always explicit** — Every query in repository filters by `tenant_id`
5. **Services return domain objects** — Views serialize them for response
6. **Services raise exceptions** — Views catch and convert to HTTP responses

### Shared Sub-Resources
`FollowUpModel` and `NoteModel` in `common` use `GenericForeignKey` (`content_type` + `object_id`) so a single table serves enquiries, quotations, contacts, or any future entity without schema changes. Add a `GenericRelation` on the parent model to enable reverse access and efficient cascades.

### Cross-Service Tables
`organizations` and `quotations` are managed by another service sharing the same PostgreSQL database. This Django backend queries them using Django ORM where needed. Do not add Django migrations for these tables. Always use ORM queries (`.filter()`, `.get()`, etc.) — never raw SQL (`connection.cursor()`, `raw()`).

### Swagger / API Docs
- `GET /api/schema/` — OpenAPI 3 JSON
- `GET /api/docs/` — Swagger UI
- `GET /api/redoc/` — ReDoc

Decorate all ViewSet actions with `@extend_schema(tags=[...], summary="...", ...)` from `drf_spectacular.utils`.

### URL Structure
```
/health/           → health check (no auth)
/auth/             → auth_app (signup, login, refresh, invite, me…)
/users/            → auth_app (list/update tenant users)
/enquiry/          → enquiry_app (CRUD + nested products/follow-ups/documents)
/api/schema/       → OpenAPI schema
/api/docs/         → Swagger UI
/api/redoc/        → ReDoc
```

### Settings Env Vars
Required in `.env`:
```
SECRET_KEY, DEBUG, ALLOWED_HOSTS
DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
PORT, IP, BASE_URL
```

**JWT Configuration**: Token generation and verification uses `SECRET_KEY` with HS256 algorithm. Access tokens expire in 1 hour; refresh tokens in 7 days (configurable in `auth_app/utils/jwt_utils.py`).