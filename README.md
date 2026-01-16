# XATSimplified

Simplified performance monitoring backend for multi-server workload evaluation.

## Overview

XATSimplified is a streamlined Django backend designed to support the evaluation and comparison of performance across multiple servers or VMs. It integrates with:

- **pcc (Performance Collector Client)**: Lightweight agent that runs on monitored servers
- **perf-dashboard**: React-based visualization and comparison UI

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ARCHITECTURE                             │
└─────────────────────────────────────────────────────────────────┘

   Server 1              Server 2              Server 3
   ┌─────────┐           ┌─────────┐           ┌─────────┐
   │   pcc   │           │   pcc   │           │   pcc   │
   └────┬────┘           └────┬────┘           └────┬────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  XATSimplified   │
                    │  (Django API)    │
                    └────────┬─────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  perf-dashboard  │
                    │  (React UI)      │
                    └──────────────────┘
```

## Features

- **Simplified Models**: Only 5 models vs 17 in the original
- **Auto-Registration**: Servers self-register and auto-detect specs via pcc
- **Multi-Tenancy Ready**: Built on django-tenants for future expansion
- **JWT Authentication**: Secure API access for dashboard
- **API Key Auth**: Simple authentication for pcc clients
- **Load Test Comparison**: Compare CPU work units across servers

## Models

| Model | Purpose |
|-------|---------|
| `Tenant` | Multi-tenancy support (single tenant initially) |
| `Collector` | Represents a monitored server/VM |
| `CollectedData` | Uploaded performance data files |
| `Benchmark` | Performance benchmark runs with scores |
| `LoadTestResult` | CPU work units at different utilization levels |

## API Endpoints

### Authentication
- `POST /api/v1/auth/token/` - Get JWT token
- `POST /api/v1/auth/token/refresh/` - Refresh JWT token
- `GET /api/v1/auth/user/` - Get current user

### Collectors
- `GET /api/v1/collectors/` - List collectors
- `POST /api/v1/collectors/` - Create collector (returns API key)
- `GET /api/v1/collectors/<id>/` - Get collector details
- `POST /api/v1/collectors/<id>/regenerate-key/` - Regenerate API key

### pcc Endpoints (API Key Auth)
- `POST /api/v1/register/` - Register/update collector from pcc
- `POST /api/v1/metrics/` - Upload metrics data

### Benchmarks
- `GET /api/v1/benchmarks/` - List benchmarks
- `POST /api/v1/benchmarks/` - Create benchmark
- `GET /api/v1/benchmarks/stats/` - Get benchmark statistics

### Load Tests
- `GET /api/v1/loadtest/` - List load test results
- `POST /api/v1/loadtest/` - Create load test result
- `POST /api/v1/loadtest/compare/` - Compare multiple collectors

## Quick Start

### Using Docker

```bash
# Start PostgreSQL and Django
docker-compose up -d

# Create default tenant
docker-compose exec web python manage.py create_tenant
```

### Manual Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your settings

# Create PostgreSQL database
createdb xatsimplified

# Run migrations
python manage.py migrate_schemas --shared

# Create default tenant
python manage.py create_tenant

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

## pcc Integration

### 1. Create a Collector in Dashboard

```bash
curl -X POST http://localhost:8000/api/v1/collectors/ \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "web-server-01"}'
```

Response includes API key:
```json
{
  "id": "abc123...",
  "name": "web-server-01",
  "api_key": "xyz789...",
  "install_command": "curl -s http://localhost:8000/install.sh | API_KEY=xyz789... bash"
}
```

### 2. Install pcc on Server

```bash
# On the server to monitor
curl -s http://localhost:8000/install.sh | API_KEY=xyz789... bash
```

### 3. pcc Auto-Registers

pcc automatically sends system info:
- Hostname, IP address
- OS name and version
- CPU info (brand, model, count)
- Memory size
- Storage info

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | (required) |
| `DEBUG` | Debug mode | `False` |
| `DATABASE_URL` | PostgreSQL connection | (required) |
| `ALLOWED_HOSTS` | Allowed hostnames | `localhost` |
| `CORS_ALLOWED_ORIGINS` | CORS origins for dashboard | `http://localhost:3000` |

## Development

```bash
# Run tests
python manage.py test

# Check code style
flake8 .

# Create migrations
python manage.py makemigrations
```

## License

MIT License
