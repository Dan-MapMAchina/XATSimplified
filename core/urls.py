"""
URL configuration for XATSimplified project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import RedirectView

# Import TrickleView for pcc compatibility
from collectors.api.views import TrickleView

urlpatterns = [
    # Root redirect to API info or dashboard
    path('', RedirectView.as_view(url='/api/v1/', permanent=False), name='root'),
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
