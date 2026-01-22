# Claude Code Project Guide - XATSimplified

**Version**: 1.0
**Last Updated**: 2026-01-20
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

- **Framework**: Django 4.x
- **Database**: PostgreSQL
- **Authentication**: JWT (djangorestframework-simplejwt)
- **API**: Django REST Framework
- **Deployment**: Docker, Azure App Service

---

## Key API Endpoints

Implement all production API endpoints here. Example patterns:

```python
# Authentication
POST /api/auth/login/       # JWT token login
POST /api/auth/refresh/     # Refresh JWT token

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

## Conversation Logging Requirement

**MANDATORY**: Append all exchanges to `CONVERSATION_LOG.md` in the repository root.
