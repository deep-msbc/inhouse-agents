# Django enquiry_app Refactor & Implementation

**Project Context**: DWERP is a multi-tenant B2B SaaS platform built with Django 5.2, DRF, PostgreSQL, JWT authentication (HS256), and RBAC via `msbc-rbac` (v0.0.29). This refactor restructures the enquiry_app to follow established architecture, naming conventions, and separation of concerns.

---

## 📌 Architecture & Folder Structure

```
enquiry_app/                           # Core app — models, serializers, services
├── models/
│   ├── __init__.py
│   ├── enquiry_model.py         # EnquiryModel
│   ├── product_model.py         # ProductModel
│   └── document_model.py        # DocumentModel
│
├── serializers/
│   ├── __init__.py
│   ├── enquiry_serializer.py    # EnquirySerializer, EnquiryDetailSerializer
│   ├── product_serializer.py    # ProductSerializer
│   └── document_serializer.py   # DocumentSerializer
│
├── services/
│   ├── __init__.py
│   ├── enquiry_service.py       # EnquiryService (CRUD, status transitions, filtering)
│   ├── product_service.py       # ProductService
│   └── document_service.py      # DocumentService
│
├── utils/
│   ├── __init__.py
│   ├── status_utils.py          # Status transition helpers
│   └── validators_utils.py      # Custom validation logic
│
├── migrations/
│   └── ...
│
├── management/
│   └── commands/
│       └── seed_enquiry_data.py
│
└── tests/
    ├── __init__.py
    ├── test_enquiry_service.py
    ├── test_models.py
    └── test_serializers.py

api/v1/enquiry_app/                   # API layer — views and URL routing
├── views/
│   ├── __init__.py
│   ├── enquiry_view.py          # EnquiryViewSet
│   ├── product_view.py          # ProductViewSet
│   ├── document_view.py         # DocumentViewSet
│   └── follow_up_view.py        # FollowUpViewSet
│
├── urls.py                      # URL routing for all enquiry_app endpoints
└── tests/
    ├── __init__.py
    ├── test_enquiry_views.py
    ├── test_product_views.py
    └── test_integration.py
```

### Separation: App vs API Layer

**enquiry_app/** (core business logic):
- Models, serializers, services, utilities
- Reusable across different API versions or client types
- No HTTP knowledge — pure domain logic

**api/v1/enquiry_app/** (HTTP API layer):
- ViewSets (thin, delegate to services)
- URL routing
- API-specific tests
- Imports services and serializers from `enquiry_app/`

**Key Rule**: Services and models in the app are version-agnostic. The API layer (`api/v1/`) is where versioning, HTTP routing, and view logic lives.

---

## 📛 Strict Naming Conventions (MANDATORY)

### Models
- **File name**: `<feature>_model.py`
- **Class name**: `<Feature>Model`
- **Examples**:
  - `enquiry_model.py` → `EnquiryModel`
  - `product_model.py` → `ProductModel`
  - `document_model.py` → `DocumentModel`

### Serializers
- **File name**: `<feature>_serializer.py`
- **Class name**: `<Feature>Serializer` or `<Feature>DetailSerializer`
- **Examples**:
  - `enquiry_serializer.py` → `EnquirySerializer`, `EnquiryDetailSerializer`
  - `product_serializer.py` → `ProductSerializer`

### Views
- **Location**: `api/v1/<app>/views/` (NOT in app itself)
- **File name**: `<feature>_view.py`
- **Class name**: `<Feature>ViewSet`
- **Examples**:
  - `api/v1/enquiry_app/views/enquiry_view.py` → `EnquiryViewSet`
  - `api/v1/enquiry_app/views/product_view.py` → `ProductViewSet`

### Services
- **File name**: `<feature>_service.py`
- **Class name**: `<Feature>Service`
- **Private repository**: `_<Feature>Repository` (internal to service only)
- **Examples**:
  - `enquiry_service.py` → `EnquiryService` with `_EnquiryRepository`
  - `product_service.py` → `ProductService` with `_ProductRepository`

### Utils
- **File name**: `<purpose>_utils.py`
- Keep functions reusable, generic, and app-specific
- **Examples**:
  - `status_utils.py` → Helper functions for status transitions
  - `validators_utils.py` → Reusable validation functions

---

## 🏗️ Service Layer Architecture (MANDATORY)

**Design Principle**: Views are intentionally thin; all business logic lives in service classes. This ensures reusability, testability, and maintainability.

### Call Chain
```
HTTP Request
    ↓
View (thin — input validation only)
    ↓
Serializer.is_valid() (data validation)
    ↓
Service Method (business logic, orchestration)
    ↓
Repository (ORM queries, DB access)
    ↓
Database
    ↓
Response (serializer wraps result)
```

### Service Class Pattern

Each service owns a domain (e.g., `EnquiryService`, `ProductService`):
- Contains public methods for all business operations (create, update, delete, status change, etc.)
- Handles validation, authorization, tenant scoping, state transitions
- Wraps write operations with `@transaction.atomic`
- Uses private `_Repository` class for all DB access

```python
# enquiry_app/services/enquiry_service.py
from django.db import transaction
from django.core.exceptions import ValidationError

class EnquiryService:
    def __init__(self, repository=None):
        self._repo = repository or _EnquiryRepository()
    
    @transaction.atomic
    def create_enquiry(self, tenant_id: UUID, user_id: UUID, **data):
        """Create a new enquiry for the tenant."""
        # 1. Validate tenant access
        if not self._repo.tenant_exists(tenant_id):
            raise ValidationError("Invalid tenant")
        
        # 2. Prepare data
        enquiry_data = {
            **data,
            'tenant_id': tenant_id,
            'created_by': user_id,
        }
        
        # 3. Create via repository
        enquiry = self._repo.create_enquiry(enquiry_data)
        
        # 4. Return domain object (view serializes)
        return enquiry
    
    def get_enquiry(self, tenant_id: UUID, enquiry_id: UUID):
        """Fetch a single enquiry (tenant-scoped)."""
        return self._repo.get_enquiry_by_id(tenant_id, enquiry_id)
    
    @transaction.atomic
    def update_status(self, tenant_id: UUID, enquiry_id: UUID, new_status: str):
        """Transition enquiry to new status with validation."""
        enquiry = self.get_enquiry(tenant_id, enquiry_id)
        
        # Validate transition
        valid_next = get_valid_status_transitions(enquiry.status)
        if new_status not in valid_next:
            raise ValidationError(
                f"Cannot transition from {enquiry.status} to {new_status}"
            )
        
        # Update
        return self._repo.update_enquiry(enquiry.id, {'status': new_status})

class _EnquiryRepository:
    """Private repository for EnquiryService — DB access via ORM only."""
    
    def tenant_exists(self, tenant_id: UUID) -> bool:
        from auth_app.models import TenantModel
        return TenantModel.objects.filter(id=tenant_id).exists()
    
    def create_enquiry(self, data: dict):
        from enquiry_app.models import EnquiryModel
        return EnquiryModel.objects.create(**data)
    
    def get_enquiry_by_id(self, tenant_id: UUID, enquiry_id: UUID):
        from enquiry_app.models import EnquiryModel
        return (
            EnquiryModel.objects
            .filter(tenant_id=tenant_id, id=enquiry_id)
            .first()
        )
    
    def update_enquiry(self, enquiry_id: UUID, data: dict):
        from enquiry_app.models import EnquiryModel
        enquiry = EnquiryModel.objects.get(id=enquiry_id)
        for key, value in data.items():
            setattr(enquiry, key, value)
        enquiry.save()
        return enquiry
```

### View Layer (Thin)

Views delegate all logic to services. Views live in `api/v1/<app>/views/`:

```python
# api/v1/enquiry_app/views/enquiry_view.py
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from auth_app.utils.guard_utils import require_role, IsWriteAllowed
from enquiry_app.services.enquiry_service import EnquiryService
from enquiry_app.serializers.enquiry_serializer import EnquirySerializer
from drf_spectacular.utils import extend_schema

_WRITE_ROLES = ('admin', 'director', 'manager', 'sales_rep')

class EnquiryViewSet(ModelViewSet):
    serializer_class = EnquirySerializer
    service = EnquiryService()
    
    def get_permissions(self):
        """Role-based permission guards per action."""
        if self.action in ('create', 'partial_update', 'destroy', 'restore', 'reopen'):
            return [require_role(*_WRITE_ROLES)(), IsWriteAllowed()]
        return [IsAuthenticated()]
    
    @extend_schema(
        tags=["Enquiries"],
        summary="List all enquiries for authenticated tenant",
    )
    def list(self, request):
        """Fetch all enquiries for the authenticated tenant."""
        enquiries = self.service.list_enquiries(request.user.tenant_id)
        serializer = self.get_serializer(enquiries, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        tags=["Enquiries"],
        summary="Create a new enquiry",
    )
    def create(self, request):
        """Create a new enquiry for the authenticated tenant."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Delegate to service
        enquiry = self.service.create_enquiry(
            tenant_id=request.user.tenant_id,
            user_id=request.user.id,
            **serializer.validated_data
        )
        
        # Serialize response
        return Response(
            EnquirySerializer(enquiry).data,
            status=201
        )
    
    @action(detail=True, methods=['post'])
    @extend_schema(
        tags=["Enquiries"],
        summary="Transition enquiry to new status",
    )
    def update_status(self, request, pk=None):
        """Transition enquiry status with validation."""
        new_status = request.data.get('status')
        
        enquiry = self.service.update_status(
            tenant_id=request.user.tenant_id,
            enquiry_id=pk,
            new_status=new_status
        )
        
        return Response(EnquirySerializer(enquiry).data)
```

### Key Rules
1. **All business logic in services** — Never in views, serializers, or models
2. **Services are stateless** — Only instance variable is the repository
3. **Transactions at service level** — `@transaction.atomic` on all write methods
4. **Tenant filtering explicit** — Every repository query filters by `tenant_id`
5. **Services return domain objects** — Views serialize for HTTP response
6. **Services raise exceptions** — Views catch and convert to HTTP responses
7. **ORM-only database access** — Never use raw SQL (`connection.cursor()`, `raw()`)

---

## 🔐 Multi-Tenancy & Authentication Requirements

### Every Model Must Filter by `tenant_id`

```python
# enquiry_app/models/enquiry_model.py
from common.models.base import AuditedModel
from auth_app.models import TenantModel
from django.db import models

class EnquiryModel(AuditedModel):
    """Top-level enquiry entity with soft delete."""
    
    tenant = models.ForeignKey(TenantModel, on_delete=models.CASCADE)
    # ... other fields
    
    class Meta:
        db_table = 'enquiry'
        app_label = 'enquiry_app'
        # ⚠️ Index on (tenant_id, status) for efficient filtering
        indexes = [
            models.Index(fields=['tenant_id', 'status'], name='idx_tenant_status'),
        ]
```

### Every Query Must Include `tenant_id` Filter

```python
# ✅ CORRECT
enquiries = EnquiryModel.objects.filter(
    tenant_id=request.user.tenant_id,
    status='open'
)

# ❌ WRONG — will include other tenants' data
enquiries = EnquiryModel.objects.filter(status='open')
```

### Request Context

The JWT middleware (`auth_app/middleware.py`) provides authenticated user context on every request:

```python
# request.user is CurrentUser dataclass with:
request.user.id           # UUID of authenticated user
request.user.email        # User email
request.user.tenant_id    # UUID of current tenant
request.user.roles        # list of role names (loaded from DB)
request.user.is_authenticated  # True if valid JWT

# Use these in services/views:
service.create_enquiry(
    tenant_id=request.user.tenant_id,  # ALWAYS from request
    user_id=request.user.id,
    **data
)
```

---

## 🔒 RBAC & Permission Guards (MANDATORY)

### Role-Based Access Control

Standard DWERP roles (seeded via `setup_rbac` command):
| Role | Access Level |
|------|--------------|
| `admin` | Full system access |
| `director` | Director level access |
| `manager` | Manager level access |
| `sales_rep` | Sales representative access |
| `estimator` | Read-only access |

### Permission Classes

Use these permission factories in `get_permissions()`:

```python
from auth_app.utils.guard_utils import require_role, IsWriteAllowed
from rest_framework.permissions import IsAuthenticated

# Example: EnquiryViewSet
class EnquiryViewSet(ModelViewSet):
    def get_permissions(self):
        """
        - Public endpoints: AllowAny
        - Protected endpoints: IsAuthenticated
        - Write endpoints: require specific roles + IsWriteAllowed
        """
        if self.action == 'list':
            return [IsAuthenticated()]
        
        if self.action in ('create', 'partial_update', 'destroy'):
            # Require one of these roles AND allow writes
            return [
                require_role('admin', 'director', 'manager', 'sales_rep')(),
                IsWriteAllowed()  # Blocks writes on demo tenant
            ]
        
        return [IsAuthenticated()]
```

### Permission Factory Details

- **`require_role(*roles)`** — Returns a DRF permission class. Allows access if user has **any** of the specified roles. Roles loaded from DB (authoritative source).
- **`IsWriteAllowed()`** — Blocks POST, PATCH, DELETE on demo tenant (`DEMO_TENANT_ID` setting). Allows all GET requests.

---

## 🧩 Enums Handling (DB-Driven, Not Hardcoded)

**CRITICAL**: Never use Django `choices=` on model fields. All enums must be stored in database tables.

### Pattern: Use `common.Lookup` Table

```python
# ✅ CORRECT — Query from DB
from common.models.lookup_model import LookupModel

enquiry_types = LookupModel.values_for('enquiry_type', tenant_id)
# Returns: ['Phone Inquiry', 'Email Inquiry', 'Walk-in', ...]

# In serializers:
class EnquirySerializer(serializers.ModelSerializer):
    enquiry_type = serializers.CharField()  # No choices
    
    def validate_enquiry_type(self, value):
        valid_types = LookupModel.values_for('enquiry_type', self.context['tenant_id'])
        if value not in valid_types:
            raise serializers.ValidationError(f"Invalid enquiry_type: {value}")
        return value
```

### State Machine Constants (Not Lookups)

Business logic statuses live in `common/utils/constants_utils.py`:

```python
# ✅ CORRECT — Use constants for state machines
from common.utils.constants_utils import (
    ENQUIRY_STATUSES,
    VALID_STATUS_TRANSITIONS,
    ENQUIRY_PRIORITIES
)

# In service:
valid_next_statuses = VALID_STATUS_TRANSITIONS.get(current_status, [])
if new_status not in valid_next_statuses:
    raise ValidationError(f"Invalid status transition: {current_status} → {new_status}")
```

---

## 🔄 Shared Modules (common app)

### Move These to `common/models/`

**FollowUpModel** — Generic follow-ups via `GenericForeignKey`:
```python
# common/models/follow_up_model.py
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from common.models.base import MinimalModel

class FollowUpModel(MinimalModel):
    """Generic follow-ups for any entity (enquiry, quotation, contact)."""
    tenant = models.ForeignKey(TenantModel, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    description = models.TextField()
    # ... other fields
```

**NoteModel** — Generic notes with same pattern:
```python
# common/models/note_model.py
class NoteModel(MinimalModel):
    """Generic notes for any entity."""
    tenant = models.ForeignKey(TenantModel, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    text = models.TextField()
    created_by = models.UUIDField()  # Not FK — external reference
```

### Parent Model Setup

On `EnquiryModel`, add reverse relations:

```python
from django.contrib.contenttypes.fields import GenericRelation
from common.models.follow_up_model import FollowUpModel
from common.models.note_model import NoteModel

class EnquiryModel(AuditedModel):
    # ... fields
    follow_ups = GenericRelation(FollowUpModel, content_type_field='content_type', object_id_field='object_id')
    notes = GenericRelation(NoteModel, content_type_field='content_type', object_id_field='object_id')
    
    # Usage:
    # enquiry.follow_ups.all()
    # enquiry.notes.create(text="...")
```

---

## 🧱 Model Design Guidelines

### Use Abstract Base Models

From `common/models/base.py`:
- **`AuditedModel`** — Top-level entities (enquiries, contacts). Includes:
  - `tenant_id` (ForeignKey)
  - `created_at`, `updated_at` (timestamps)
  - `deleted_at` (soft delete)
  - `created_by`, `updated_by` (UUID, not FK)
  - `SoftDeleteManager` with `.active()` and `.deleted()` methods

- **`MinimalModel`** — Child/line-item tables (products, follow-ups). Includes:
  - `tenant_id` (ForeignKey)
  - `created_at`, `updated_at` (timestamps)

### Custom Managers

```python
from common.models.base import AuditedModel

class EnquiryModel(AuditedModel):
    # ✅ SoftDeleteManager automatically included
    # Usage: EnquiryModel.objects.active() → excludes soft-deleted
    #        EnquiryModel.objects.all() → includes soft-deleted (for recovery)
    
    status = models.CharField(max_length=20)  # No choices
    
    class Meta:
        db_table = 'enquiry'
        app_label = 'enquiry_app'
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'created_at']),
        ]
```

---

## 🔌 Serializer Guidelines

### Keep Serializers Modular

```python
# enquiry_app/serializers/enquiry_serializer.py
from rest_framework import serializers
from enquiry_app.models import EnquiryModel

class EnquirySerializer(serializers.ModelSerializer):
    """List/Create serializer — minimal fields."""
    class Meta:
        model = EnquiryModel
        fields = ['id', 'enquiry_type', 'status', 'priority', 'created_at']
        read_only_fields = ['id', 'created_at']

class EnquiryDetailSerializer(serializers.ModelSerializer):
    """Detail serializer — full context."""
    products = ProductSerializer(many=True, read_only=True)
    notes = NoteSerializer(many=True, read_only=True)
    
    class Meta:
        model = EnquiryModel
        fields = [
            'id', 'enquiry_type', 'status', 'priority',
            'products', 'notes', 'created_at', 'updated_at'
        ]
```

### Shared Validation

```python
# enquiry_app/utils/validators_utils.py
def validate_enquiry_type(value, tenant_id):
    """Reusable validation for enquiry_type lookup."""
    valid_types = LookupModel.values_for('enquiry_type', tenant_id)
    if value not in valid_types:
        raise serializers.ValidationError(f"Invalid enquiry_type: {value}")
    return value

# In serializer:
class EnquirySerializer(serializers.ModelSerializer):
    def validate_enquiry_type(self, value):
        return validate_enquiry_type(value, self.context['tenant_id'])
```

---

## 🎯 View Guidelines

### Use ViewSets with `get_permissions()`

```python
# api/v1/enquiry_app/views/enquiry_view.py
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from auth_app.utils.guard_utils import require_role, IsWriteAllowed
from enquiry_app.services.enquiry_service import EnquiryService
from enquiry_app.serializers.enquiry_serializer import EnquirySerializer

_WRITE_ROLES = ('admin', 'director', 'manager', 'sales_rep')

class EnquiryViewSet(ModelViewSet):
    serializer_class = EnquirySerializer
    service = EnquiryService()
    
    def get_permissions(self):
        """Define permissions per action."""
        if self.action in ('create', 'partial_update', 'destroy'):
            return [
                require_role('admin', 'director', 'manager', 'sales_rep')(),
                IsWriteAllowed()
            ]
        return [IsAuthenticated()]
    
    @extend_schema(
        tags=["Enquiries"],
        summary="Create a new enquiry",
        description="Only admin, director, manager, and sales_rep roles can create."
    )
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        enquiry = self.service.create_enquiry(
            tenant_id=request.user.tenant_id,
            user_id=request.user.id,
            **serializer.validated_data
        )
        
        return Response(
            EnquiryDetailSerializer(enquiry).data,
            status=201
        )
```

### Thin Views

- Views validate input only (via serializer)
- Views call service methods
- Views serialize response
- **No business logic in views**

---

## 🔁 DRY Principle & Code Organization

### Identify & Eliminate Duplication

**Common patterns across models**:
- Tenant scoping → Put in service repository
- Status validation → Put in `status_utils.py`
- Field validation → Put in `validators_utils.py`
- Lookup queries → Use `common.Lookup` table

**Example**: Status transition logic

```python
# enquiry_app/utils/status_utils.py
from common.utils.constants_utils import VALID_STATUS_TRANSITIONS

def get_valid_next_statuses(current_status: str) -> list[str]:
    """Get all valid next statuses from current state."""
    return VALID_STATUS_TRANSITIONS.get(current_status, [])

def validate_status_transition(current: str, next_status: str) -> bool:
    """Check if transition is valid."""
    return next_status in get_valid_next_statuses(current)

# In service:
from enquiry_app.utils.status_utils import validate_status_transition

@transaction.atomic
def update_status(self, tenant_id, enquiry_id, new_status):
    enquiry = self.get_enquiry(tenant_id, enquiry_id)
    if not validate_status_transition(enquiry.status, new_status):
        raise ValidationError(f"Invalid transition: {enquiry.status} → {new_status}")
    return self._repo.update_enquiry(enquiry.id, {'status': new_status})
```

### Placement Rules

| What | Where |
|------|-------|
| Model-specific logic | Inside model or custom manager |
| Enquiry-specific reusable logic | `enquiry_app/utils/` |
| Multi-app reusable logic | `common/utils/` or `common/models/` |
| Enums (dropdowns, admin-configurable) | `common.Lookup` table |
| State machine constants | `common/utils/constants_utils.py` |

---

## 🧼 Code Quality Standards

### Naming & Formatting
✅ Follow established conventions (models, serializers, views, services)
✅ Use snake_case for functions/variables, PascalCase for classes
✅ Meaningful, descriptive names

### Separation of Concerns
✅ Service layer handles business logic
✅ Views delegate to services
✅ Repositories handle DB access via ORM
✅ Serializers handle data validation/transformation

### Avoid
❌ Code duplication across services
❌ Hardcoded enum values
❌ Business logic in views
❌ Raw SQL queries — always use ORM
❌ Implicit tenant filtering

### Testing
✅ Unit tests for services
✅ Integration tests for views
✅ Always test with tenant_id filtering
✅ Test all RBAC permission guards

---

## 🎯 Expected Outcome

✅ Fully modular `enquiry_app` following service layer architecture
✅ Clean folder-based separation (models, views, serializers, services, utils)
✅ Strict naming conventions applied throughout
✅ DB-driven enums using `common.Lookup` table
✅ Reusable common app components (`FollowUp`, `Note`, base models)
✅ All business logic in services, thin views
✅ Every query includes explicit `tenant_id` filtering
✅ RBAC guards on all write actions
✅ ORM-only database access (no raw SQL)
✅ DRY, scalable, production-ready codebase
✅ Swagger documentation via `@extend_schema` decorators

---

**This file reflects all architectural decisions, RBAC implementation, service layer patterns, multi-tenancy requirements, and best practices established for DWERP.**
