# Claude Code Project Guide - XATSimplified

**Version**: 1.1
**Last Updated**: 2026-01-27
**Project Status**: Active Development - PRODUCTION CODEBASE
**Parent Project**: PerfAnalysis

---

## ⚠️ CRITICAL: THIS IS THE PRODUCTION BACKEND

```
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║   🟢 XATSimplified IS THE PRODUCTION BACKEND                               ║
║                                                                            ║
║   ALL backend functionality for PerfAnalysis MUST be implemented here.    ║
║                                                                            ║
║   • XATbackend/     → REFERENCE ONLY (do not modify for production)       ║
║   • XATSimplified/  → PRODUCTION CODE (all new features go here) ✅        ║
║                                                                            ║
║   When implementing backend features:                                      ║
║   1. You MAY review XATbackend for patterns/reference                     ║
║   2. Implement ALL functionality HERE in XATSimplified                    ║
║   3. Ensure all API endpoints work with perf-dashboard frontend           ║
║   4. Follow Django best practices and project conventions                 ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
```

---

## CRITICAL REQUIREMENT: Agent-First Workflow

**THIS IS MANDATORY AND NON-NEGOTIABLE**: Every request, every task, every question MUST begin with agent selection.

### The Rule

```
┌─────────────────────────────────────────────────────────────┐
│ BEFORE YOU DO ANYTHING ELSE:                                 │
│                                                               │
│ 1. READ THE REQUEST                                          │
│ 2. IDENTIFY THE APPROPRIATE AGENT(S)                         │
│ 3. STATE WHICH AGENT(S) YOU ARE INVOKING                     │
│ 4. PROCEED WITH THE AGENT'S EXPERTISE                        │
│                                                               │
│ NO EXCEPTIONS. NO SHORTCUTS. AGENT SELECTION IS MANDATORY.   │
└─────────────────────────────────────────────────────────────┘
```

### Agent Reference for XATSimplified

| Agent | Use For |
|-------|---------|
| **Backend Python Developer** | Django views, models, serializers |
| **Django Tenants Specialist** | Multi-tenancy, tenant isolation |
| **Security Architect** | Authentication, authorization, OWASP |
| **DevOps Engineer** | Docker, deployment, CI/CD |
| **Data Architect** | Database schema, queries, PostgreSQL |
| **API Architect** | REST API design, endpoints |
| **Integration Architect** | Cross-component workflows |

---

## Project Structure

```
XATSimplified/
├── authentication/     # JWT auth, user management
├── cloud_providers/    # OCI, Azure, AWS integrations
├── collectors/         # Performance collectors management
├── core/              # Django settings, URLs, WSGI
├── templates/         # Django templates (if any)
├── media/             # Uploaded files
├── manage.py          # Django management
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container build
└── docker-compose.yml # Local development
```

---

## Technology Stack

- **Framework**: Django 4.2.9
- **Database**: PostgreSQL (with django-tenants multi-tenancy)
- **Authentication**: JWT (djangorestframework-simplejwt)
- **API**: Django REST Framework 3.14.0
- **Rate Limiting**: django-ratelimit 4.1.0
- **Error Tracking**: Sentry SDK 1.39.1
- **Secrets Management**: Azure Key Vault (optional)
- **Deployment**: Docker, Azure App Service

---

## New Features (v1.1 - January 2026)

### 1. Rate Limiting (django-ratelimit)

Protects API endpoints from abuse with configurable rate limits:

| Endpoint Type | Default Rate | Environment Variable |
|--------------|--------------|---------------------|
| Authentication (login/register) | 5/minute | `RATELIMIT_AUTH` |
| General API | 60/minute | `RATELIMIT_API` |
| Upload endpoints | 10/minute | `RATELIMIT_UPLOAD` |
| Trickle data | 120/minute | `RATELIMIT_TRICKLE` |

**Configuration:**
```bash
RATELIMIT_ENABLE=True          # Enable/disable rate limiting
RATELIMIT_AUTH=5/m             # Auth endpoints
RATELIMIT_API=60/m             # General API
REDIS_URL=redis://localhost:6379/0  # Use Redis for production
```

### 2. Sentry Error Tracking

Automatic error capture and performance monitoring:

```bash
# Required
SENTRY_DSN=https://xxx@sentry.io/project

# Optional tuning
SENTRY_ENVIRONMENT=production       # Environment name
SENTRY_TRACES_SAMPLE_RATE=0.1      # Performance monitoring (10%)
SENTRY_PROFILES_SAMPLE_RATE=0.1    # Profiling (10%)
```

**Features:**
- Automatic Django exception capture
- Performance transaction tracing
- PII filtering enabled by default

### 3. Password Change Endpoint

Authenticated users can change their password:

```
POST /api/v1/auth/password/change/
Authorization: Bearer <jwt_token>

{
    "old_password": "current_password",
    "new_password": "new_secure_password",
    "new_password2": "new_secure_password"
}

Response: {"message": "Password changed successfully"}
```

**Security Features:**
- Validates current password before change
- Enforces Django password validators
- Rate limited to 5 requests/minute per user

### 4. Azure Key Vault Integration

Secure secrets management for Azure deployments:

```bash
# Enable Key Vault
AZURE_KEY_VAULT_URL=https://your-vault.vault.azure.net/

# Secrets retrieved from Key Vault:
# - django-secret-key → Django SECRET_KEY
# - (add more as needed)
```

**Fallback Behavior:**
- If Key Vault is unavailable, falls back to environment variables
- If Key Vault URL is not set, uses environment variables directly
- Graceful degradation for local development

---

## Key API Endpoints

Implement all production API endpoints here. Example patterns:

```python
# Authentication
POST /api/v1/auth/token/           # JWT token login
POST /api/v1/auth/token/refresh/   # Refresh JWT token
POST /api/v1/auth/token/verify/    # Verify JWT token
POST /api/v1/auth/register/        # User registration
POST /api/v1/auth/logout/          # Logout (blacklist token)
POST /api/v1/auth/password/change/ # Change password (NEW)
GET  /api/v1/auth/user/            # Current user info

# Collectors
GET  /api/collectors/       # List user's collectors
POST /api/collectors/       # Create new collector
GET  /api/collectors/{id}/  # Get collector details

# Performance Data
POST /api/performance/upload/    # Upload performance data
GET  /api/performance/export/    # Export data for reporting

# Trickle Data (real-time)
POST /api/trickle/ingest/   # Receive trickled metrics
GET  /api/trickle/status/   # Check trickle status

# Dashboard
GET  /api/dashboard/collectors/{id}/cpu/      # CPU metrics
GET  /api/dashboard/collectors/{id}/memory/   # Memory metrics
GET  /api/dashboard/collectors/{id}/disk/     # Disk metrics
GET  /api/dashboard/collectors/{id}/network/  # Network metrics
```

---

## Development Commands

```bash
# Start development server
python manage.py runserver

# Run with Docker
docker-compose up

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run tests
python manage.py test
```

---

## Integration Points

### perf-dashboard (React Frontend)
- All API calls from perf-dashboard should target XATSimplified
- Update `src/config/api.ts` to point to XATSimplified endpoints
- JWT tokens issued by XATSimplified auth

### perfcollector2 (Go Data Collector)
- Trickle mode uploads data to XATSimplified `/api/trickle/ingest/`
- API key authentication via `apikey` header
- Real-time metrics storage in PostgreSQL

### automated-Reporting (R Reports)
- Export data from XATSimplified for R analysis
- Future: Direct database connection to XATSimplified DB

---

## Environment Variables Reference

### Core Django
```bash
SECRET_KEY=your-secret-key           # Django secret (or use Key Vault)
DEBUG=False                          # Never True in production
ALLOWED_HOSTS=example.com,*.example.com
DATABASE_URL=postgresql://user:pass@host:5432/db
```

### Authentication & Security
```bash
# Rate Limiting
RATELIMIT_ENABLE=True                # Enable/disable rate limiting
RATELIMIT_AUTH=5/m                   # Auth endpoints rate
RATELIMIT_API=60/m                   # General API rate
RATELIMIT_UPLOAD=10/m                # Upload endpoints rate
RATELIMIT_TRICKLE=120/m              # Trickle data rate

# Error Tracking (Sentry)
SENTRY_DSN=https://xxx@sentry.io/project
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.1

# Azure Key Vault (optional)
AZURE_KEY_VAULT_URL=https://vault.vault.azure.net/
```

### Caching
```bash
REDIS_URL=redis://localhost:6379/0   # Redis for rate limiting (production)
```

---

## Conversation Logging Requirement

**MANDATORY**: Append all exchanges to `CONVERSATION_LOG.md` in the repository root.
