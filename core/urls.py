"""
URL configuration for XATSimplified project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.decorators.csrf import csrf_exempt

# Import TrickleView for pcc compatibility
from collectors.api.views import TrickleView
from .views import health_check, api_root

urlpatterns = [
    # Health check endpoint (for load balancers)
    path('health/', health_check, name='health_check'),

    # Root shows API documentation
    path('', api_root, name='root'),
    path('api/v1/', api_root, name='api_root'),

    path('admin/', admin.site.urls),

    # pcc trickle endpoint (pcd-compatible at /v1/trickle)
    # Note: csrf_exempt is required for API endpoints without session auth
    path('v1/trickle', csrf_exempt(TrickleView.as_view()), name='trickle'),

    # API endpoints
    path('api/v1/auth/', include('authentication.urls')),
    path('api/v1/', include('collectors.api.urls')),

    # Dashboard API endpoints (for perf-dashboard compatibility)
    path('dashboard/api/', include('collectors.api.dashboard_urls')),

    # Cloud provider endpoints
    path('', include('cloud_providers.urls')),

    # Allauth URLs
    path('accounts/', include('allauth.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
