# ⚡ Django CLI Tool

A command-line tool for scaffolding Django projects with apps, boilerplate code, and microservices architecture.

## 🚀 Features

- ✅ **Auto Django Installation**: Checks and installs Django if missing
- ✅ **Project Scaffolding**: Creates complete Django project structure
- ✅ **App Generation**: Creates apps with complete boilerplate code
- ✅ **Microservices Support**: Create multiple independent Django services
- ✅ **Auto Configuration**: Updates settings.py and urls.py automatically
- ✅ **PostgreSQL Integration**: Environment-based database configuration
- ✅ **Health Checks**: Built-in health monitoring endpoints
- ✅ **Logging**: Structured logging configuration
- ✅ **API Documentation**: Swagger UI integration with JWT support
- ✅ **JWT Authentication**: Built-in JWT authentication with RSA key generation
- ✅ **Template Generation**: Creates basic HTML templates for each app
- ✅ **Ready-to-Use**: Includes models, views, forms, serializers, and tests
- ✅ **Migration Patch**: Create custom migration file name based on timestamp and appname

## 📥 Installation

Install the package using `pip` from the in-house repository:

```bash
pip install djcli
```

## ⚡ Usage

### Create New Project

```bash
# Create project with multiple apps
djcli startproject project_name app1 app2 app3

# Create project with --app flags
djcli startproject project_name --app app1 --app app2 --app app3

# Create basic project (no apps)
djcli startproject project_name

# Create project with API documentation
djcli startproject project_name --api

# Create project with JWT authentication (requires --api)
djcli startproject project_name --api --auth

# Create project in specific directory
djcli startproject project_name --path /custom/path
```

### Add App to Existing Project

```bash
# Add single app to existing project
djcli startapp --app app_name --project project_name

# Add app with microservices structure
djcli startapp --app app_name --project project_name --services

# If project is in separate folder
djcli startapp --app app_name --project "/path/to/project"
```

### Create Microservices Architecture

```bash
# Create multiple independent Django services
djcli startservices services1:order_app services2:user_app,profile_app

# Create services in specific directory
djcli startservices auth user services1:order_app --path /microservices

# Create service without apps
djcli startservices services1
```

### Arguments

**startproject:**
- `project_name`: Name of your Django project
- `app_names`: Space-separated list of apps to create
- `--app`: Specify individual apps (can be used multiple times)
- `--path`: Custom directory path where project will be created
- `--api`: Include Django REST Framework with Swagger UI
- `--auth`: Include JWT authentication app (requires --api flag)

**startapp:**
- `--app`: Name of the app to create
- `--project`: Target project for new app
- `--services`: Generate app with microservices structure

**startservices:**
- `services`: Service definitions in format 'service:app1,app2' or just 'service'
- `--path`: Base path where to create services
- `--auth`: Include authentication service with JWT support

## 📂 Generated Project Structure

### Single Project Structure
```
project_name/
├── project_name/
│   ├── __init__.py
│   ├── settings.py                    # Auto-updated with new apps & JWT config
│   ├── urls.py                        # Auto-updated with app routes & health check
│   ├── health_check.py                # Health monitoring endpoint
│   ├── migration_naming_patch.py      # To create the customozed migration file name 
│   ├── logger.py                      # Logging configuration
│   ├── wsgi.py
│   └── asgi.py
├── authentication/          # Authentication app (with --auth flag)
│   ├── __init__.py
│   ├── models.py           # AuthToken model for JWT management
│   ├── views.py            # Login/Register endpoints
│   ├── urls.py             # Authentication URLs
│   ├── admin.py            # Admin registration
│   ├── serializers.py      # Auth serializers
│   ├── jwt_utils.py        # JWT token utilities
│   ├── jwks_view.py        # JWKS endpoint for token validation
│   ├── apps.py
│   └── migrations/
├── keys/                    # RSA key pair (auto-generated with --auth)
│   ├── private.pem         # JWT signing key
│   └── public.pem          # JWT verification key
├── app1/                    # Generated app
│   ├── __init__.py
│   ├── models.py           # Sample model included
│   ├── views.py            # Basic view function
│   ├── urls.py             # URL patterns
│   ├── admin.py            # Admin registration
│   ├── tests.py            # Sample test case
│   ├── forms.py            # Django form
│   ├── serializers.py      # DRF serializer
│   ├── apps.py
│   ├── migrations/
│   └── templates/app1/
│       └── index.html      # Basic template
├── manage.py
├── .env                     # Environment variables
├── .gitignore              # Git ignore rules
├── Dockerfile              # Docker configuration
├── docker-compose.yml      # Docker compose setup
├── requirements.txt        # Python dependencies (includes JWT libs with --auth)
├── .dockerignore          # Docker ignore rules
└── README.md               # Auto-generated setup guide
```

### Microservices Structure
```
microservices/
├── authservice/             # Authentication service
│   ├── authservice/
│   │   ├── __init__.py
│   │   ├── settings.py                  # Environment-based config
│   │   ├── urls.py                      # Service URLs with health check
│   │   ├── health_check.py              # Service health endpoint
│   │   ├── migration_naming_patch.py    # To create the customozed migration file name 
│   │   ├── logger.py                    # Service logging
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── authentication/     # Authentication app
│   │   ├── models/         # Separate model files
│   │   │   ├── __init__.py
│   │   │   ├── entity1_model.py
│   │   │   └── entity2_model.py
│   │   ├── tests/          # Organized test structure
│   │   │   ├── __init__.py
│   │   │   ├── unit/
│   │   │   ├── integration/
│   │   │   └── fixtures/
│   │   ├── views.py        # Enhanced views
│   │   ├── urls.py         # App endpoints
│   │   ├── admin.py        # Admin registration
│   │   └── apps.py
│   ├── apis/               # API structure
│   │   └── v1/
│   │       └── authentication/
│   │           ├── serializers/
│   │           │   ├── entity1_serializers.py
│   │           │   └── entity2_serializers.py
│   │           └── views/
│   │               ├── entity1_views.py
│   │               └── entity2_views.py
│   ├── manage.py
│   ├── .env                # Environment variables
│   ├── .gitignore         # Git ignore rules
│   ├── Dockerfile         # Docker configuration
│   ├── docker-compose.yml # Docker compose setup
│   ├── docker-compose.prod.yml # Production compose
│   ├── requirements.txt   # Python dependencies
│   ├── .dockerignore     # Docker ignore rules
│   └── README.md          # Service-specific setup guide
├── user/                   # User management service
│   ├── user/              # Same structure with JWT validation
│   ├── user_app/          # User app with models/ and tests/
│   ├── profile_app/       # Profile app with models/ and tests/
│   ├── apis/v1/           # API endpoints with JWT middleware
│   ├── manage.py
│   ├── .env
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   ├── requirements.txt   # Python dependencies
│   ├── .dockerignore
│   └── README.md
└── payment/                # Payment service
    ├── payment/           # Same complete structure
    ├── manage.py
    ├── .env
    ├── .gitignore
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt
    ├── .dockerignore
    └── README.md
```

## 🛠️ After Project Generation

### 1. Navigate to Project

```bash
cd project_name  # For single project
# OR
cd microservices/auth  # For microservice
```

### 2. Setup Environment

```bash
# Create virtual environment
python -m venv venv         # Windows
python3 -m venv venv   # Linux/Mac

# Activate environment
venv\Scripts\activate      # Windows
source venv/bin/activate   # Linux/Mac

# Install dependencies (auto-installed by tool)
pip install django psycopg[binary] python-decouple
```

### 3. Configure Environment Variables

Update the `.env` file with your settings:
```bash
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432
```

### 4. Database Setup

```bash
# Create and apply migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser
```

### 5. Run Development Server

```bash
python manage.py runserver
```

### 6. Access Your Application

- **Main App**: `http://127.0.0.1:8000/`
- **Health Check**: `http://127.0.0.1:8000/health/`
- **Admin Panel**: `http://127.0.0.1:8000/admin/`
- **API Documentation**: `http://127.0.0.1:8000/swagger/` (if --api flag used)
- **Authentication Endpoints** (if --auth flag used):
  - Register: `http://127.0.0.1:8000/auth/register/`
  - Login: `http://127.0.0.1:8000/auth/login/`
  - JWKS: `http://127.0.0.1:8000/.well-known/jwks.json`


### 7. Running Microservices

For microservices, each service runs independently:
```bash
# Terminal 1 - Auth Service
cd auth 
python manage.py runserver 8001

# Terminal 2 - User Service  
cd user 
python manage.py runserver 8002

# Terminal 3 - Payment Service
cd payment 
python manage.py runserver 8003
```



## 🔐 JWT Authentication Features (--auth flag)

When using the `--auth` flag, the tool generates a complete JWT authentication system:

### Authentication Components
- **RSA Key Pair**: Auto-generated private/public keys for JWT signing
- **JWT Utilities**: Token generation, validation, and JWKS endpoint
- **Auth Models**: Token management with blacklisting support
- **API Endpoints**: Login, register, and token validation
- **Swagger Integration**: JWT authentication in API documentation

### Generated Auth Endpoints
- `POST /auth/register/` - User registration with JWT token
- `POST /auth/login/` - User login with JWT token
- `GET /.well-known/jwks.json` - JWKS endpoint for token validation
- `GET /health/` - Health check endpoint

### JWT Token Features
- **RSA256 Signing**: Secure asymmetric key encryption
- **Token Expiration**: 1-hour default expiration time
- **JTI Support**: Unique token identifiers for blacklisting
- **User Claims**: User ID and email embedded in tokens
- **Cross-Service Validation**: JWKS endpoint for microservices

### Security Features
- **Environment Variables**: Secure key storage configuration
- **Token Blacklisting**: Database-backed token revocation
- **CORS Ready**: Cross-origin resource sharing support
- **Production Ready**: Separate production configurations

## 🧩 Generated Boilerplate Per App

### Standard Project Apps
- **models.py**: Sample model with title and created_at fields
- **views.py**: Basic index view rendering template
- **urls.py**: URL pattern for the index view
- **admin.py**: Admin registration for the sample model
- **tests.py**: Basic test case for model creation
- **forms.py**: ModelForm for the sample model
- **serializers.py**: DRF serializer (ready for API development)
- **templates/app_name/index.html**: Basic HTML template)
- **templates/app_name/index.html**: Basic HTML template

### Microservices Apps (Enhanced Structure)
- **models/**: Separate model files (entity1_model.py, entity2_model.py)
- **tests/**: Organized testing structure (unit/, integration/, fixtures/)
- **apis/v1/**: Versioned API structure with serializers and views
- **views.py**: Enhanced views with logging
- **urls.py**: URL patterns
- **admin.py**: Admin registration

### Project-Level Files (All Projects)
- **.env**: Environment variables configuration
- **.gitignore**: Git ignore rules for Python/Django
- **Dockerfile**: Container configuration
- **docker-compose.yml**: Multi-service orchestration
- **requirements.txt**: Python dependencies
- **.dockerignore**: Docker ignore rules
- **README.md**: Project-specific setup instructions

## 🔗 Generated URLs & Features

### Single Project URLs
- **App URLs**: `http://127.0.0.1:8000/app_name/`
- **Health Check**: `http://127.0.0.1:8000/health/`
- **Admin Panel**: `http://127.0.0.1:8000/admin/`
- **API Documentation**: `http://127.0.0.1:8000/swagger/` (with --api flag)

### Microservice URLs
Each service runs on different ports:
- **Auth Service**: `http://127.0.0.1:8001/`
- **User Service**: `http://127.0.0.1:8002/`
- **Payment Service**: `http://127.0.0.1:8003/`

### Built-in Features
- ✅ **Environment Variables**: Secure configuration management
- ✅ **PostgreSQL Ready**: Database configuration included
- ✅ **Health Monitoring**: `/health/` endpoint for service monitoring
- ✅ **Structured Logging**: File and console logging configured
- ✅ **API Documentation**: Swagger UI with JWT authentication support

- ✅ **Admin Interface**: Django admin with model registration
- ✅ **Docker Ready**: Dockerfile and docker-compose.yml included
- ✅ **Git Ready**: .gitignore and .dockerignore configured
- ✅ **Dependency Management**: requirements.txt with all dependencies
- ✅ **JWT Authentication**: Complete RSA-based token system (with --auth)
- ✅ **Organized Testing**: Separate unit, integration, and fixture folders (microservices)
- ✅ **API Versioning**: v1 API structure for future scalability (microservices)
- ✅ **Production Ready**: Separate production configurations (microservices)
- ✅ **Migration Patch**: Create custom migration file name based on timestamp and appname

## 📋 Requirements

- **Python 3.9+**
- **Django** (auto-installed by tool)
- **psycopg[binary]** (auto-installed for PostgreSQL support)
- **python-decouple** (auto-installed for environment variables)
- **Docker** (optional, for containerized deployment)
- **Git** (optional, for version control)

### Auto-Installed Dependencies
The tool automatically installs:
- Django
- psycopg[binary] (PostgreSQL adapter)
- python-decouple (environment variables)
- djangorestframework (with --api flag)
- drf-yasg (Swagger UI with --api flag)
- PyJWT (JWT token handling with --auth flag)
- cryptography (RSA key generation with --auth flag)

## 🚀 Quick Start Examples

### Single Project Example
```bash
# Create a blog project with authentication
djcli startproject myblog post comment user --api --auth

cd myblog

# Activate environment (auto-created)
venv\Scripts\activate      # Windows
source venv/bin/activate   # Linux/Mac

# Configure .env file
# Update database credentials and secret key

# Setup database
python manage.py makemigrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser

# Run server
python manage.py runserver
```

### Microservices Example
```bash
# Create microservices architecture
djcli startservices user:user_app,profile_app payment:payment_app --path ./microservices

cd microservices

# Setup each service
# Terminal 1 - User Service  
cd user 
python manage.py makemigrations
python manage.py migrate
python manage.py runserver 8001

# Terminal 2 - Payment Service
cd payment 
python manage.py makemigrations
python manage.py migrate
python manage.py runserver 8002
```

### Access Your Applications
- **Single Project**: `http://127.0.0.1:8000/`
- **User Service**: `http://127.0.0.1:8001/`
- **Payment Service**: `http://127.0.0.1:8002/`

## 💡 Tips

- Run commands from the directory where you want to create the project
- App names should follow Python naming conventions (lowercase, underscores)
- The tool automatically handles Django installation if missing
- Each generated project/service includes its own README.md with specific setup instructions
- Use microservices for scalable, independent deployments
- Configure environment variables in `.env` files for security
- Health check endpoints help with monitoring and load balancing
- Swagger UI provides interactive API documentation when using --api flag
- **JWT Authentication Tips**:
  - The `--auth` flag requires the `--api` flag to be used together
  - RSA keys are auto-generated in the `keys/` directory
  - JWT tokens expire after 1 hour by default
  - Use the JWKS endpoint for cross-service token validation
  - Keep your private keys secure and never commit them to version control




## 🔧 Advanced Usage

### Environment Variables
Each project includes environment-based configuration:
- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (True/False)
- `ALLOWED_HOSTS`: Comma-separated allowed hosts
- `DB_*`: Database connection settings

### Docker Support
Every project includes Docker configuration:
```bash
# Build and run with Docker
docker-compose up --build

# Run individual service
docker build -t myproject .
docker run -p 8000:8000 myproject
```

## 🔐 JWT Authentication Usage

### Register a New User
```bash
curl -X POST http://127.0.0.1:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "securepassword123",
    "password_confirm": "securepassword123"
  }'
```

### Login and Get JWT Token
```bash
curl -X POST http://127.0.0.1:8000/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "securepassword123"
  }'
```

### Use JWT Token in API Requests
```bash
curl -X GET http://127.0.0.1:8000/api/protected-endpoint/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN_HERE"
```

### Validate Tokens Across Services
```bash
# Get public keys for token validation
curl http://127.0.0.1:8001/.well-known/jwks.json
```

### JWT Configuration
The authentication system includes these environment variables in `.env`:
```bash
# JWT Configuration (auto-configured)
JWT_PRIVATE_KEY_PATH=keys/private.pem
JWT_PUBLIC_KEY_PATH=keys/public.pem
JWT_ISSUER=your_project_name
JWT_ALGORITHM=RS256
```

## 🔧 Advanced Usage

### Microservices Benefits
- **Independent Deployment**: Each service can be deployed separately
- **Technology Flexibility**: Different services can use different technologies
- **Scalability**: Scale individual services based on demand
- **Fault Isolation**: Issues in one service don't affect others
- **Team Independence**: Different teams can work on different services
- **Organized Structure**: Separate models, tests, and API folders
- **Version Control**: Each service has its own git repository structure
- **JWT Authentication**: Complete RSA-based token system (with --auth)
