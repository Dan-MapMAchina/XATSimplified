"""
Core views for XATSimplified.
"""
import time
from django.http import JsonResponse
from django.db import connection
from django.conf import settings


def health_check(request):
    """
    Health check endpoint for load balancers and monitoring.

    Returns:
        - status: "healthy" or "unhealthy"
        - database: database connection status
        - timestamp: current server time
        - version: application version

    Usage:
        GET /health/
        GET /health/?detail=true  (includes additional info)
    """
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": "1.1.0",
    }

    # Check database connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health_status["database"] = "connected"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["database"] = f"error: {str(e)}"

    # Add response time
    health_status["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

    # Add detail if requested
    if request.GET.get("detail") == "true":
        health_status["details"] = {
            "debug_mode": settings.DEBUG,
            "database_engine": settings.DATABASES["default"]["ENGINE"],
            "python_version": __import__("sys").version.split()[0],
            "django_version": __import__("django").__version__,
        }

    # Return appropriate status code
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JsonResponse(health_status, status=status_code)


def api_root(request):
    """
    API root endpoint with available endpoints documentation.
    """
    return JsonResponse({
        "name": "XATSimplified API",
        "version": "1.1.0",
        "status": "active",
        "documentation": "https://github.com/Map-Machina/PerfAnalysis",
        "endpoints": {
            "health": "/health/",
            "auth": {
                "login": "/api/v1/auth/token/",
                "refresh": "/api/v1/auth/token/refresh/",
                "verify": "/api/v1/auth/token/verify/",
                "register": "/api/v1/auth/register/",
                "logout": "/api/v1/auth/logout/",
                "password_change": "/api/v1/auth/password/change/",
                "user": "/api/v1/auth/user/",
            },
            "collectors": {
                "list": "/api/v1/collectors/",
                "register": "/api/v1/register/",
                "metrics": "/api/v1/metrics/",
            },
            "benchmarks": {
                "list": "/api/v1/benchmarks/",
                "stats": "/api/v1/benchmarks/stats/",
            },
            "trickle": "/v1/trickle",
            "dashboard": {
                "collectors": "/dashboard/api/collectors/",
                "cpu": "/dashboard/api/collectors/{id}/cpu/",
                "memory": "/dashboard/api/collectors/{id}/memory/",
                "disk": "/dashboard/api/collectors/{id}/disk/",
                "network": "/dashboard/api/collectors/{id}/network/",
            },
        },
    })
