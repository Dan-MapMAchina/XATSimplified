"""
API URL configuration for collectors.
"""
from django.urls import path
from . import views

urlpatterns = [
    # Collector registration and management
    path('collectors/', views.CollectorListCreateView.as_view(), name='collector-list'),
    path('collectors/<uuid:pk>/', views.CollectorDetailView.as_view(), name='collector-detail'),
    path('collectors/<uuid:pk>/regenerate-key/', views.RegenerateAPIKeyView.as_view(), name='collector-regenerate-key'),

    # pcc registration endpoint (uses API key auth)
    path('register/', views.PCCRegisterView.as_view(), name='pcc-register'),

    # Metrics upload endpoint (uses API key auth)
    path('metrics/', views.MetricsUploadView.as_view(), name='metrics-upload'),

    # Collected data
    path('collectors/<uuid:collector_id>/data/', views.CollectedDataListView.as_view(), name='collected-data-list'),
    path('data/<uuid:pk>/', views.CollectedDataDetailView.as_view(), name='collected-data-detail'),

    # Benchmarks
    path('benchmarks/', views.BenchmarkListCreateView.as_view(), name='benchmark-list'),
    path('benchmarks/<uuid:pk>/', views.BenchmarkDetailView.as_view(), name='benchmark-detail'),
    path('benchmarks/stats/', views.BenchmarkStatsView.as_view(), name='benchmark-stats'),

    # LoadTest results (both singular and plural paths for compatibility)
    path('loadtest/', views.LoadTestResultListCreateView.as_view(), name='loadtest-list'),
    path('loadtest/<uuid:pk>/', views.LoadTestResultDetailView.as_view(), name='loadtest-detail'),
    path('loadtest/compare/', views.LoadTestCompareView.as_view(), name='loadtest-compare'),

    # perf-dashboard compatible endpoints (plural "loadtests")
    path('loadtests/', views.LoadTestResultListCreateView.as_view(), name='loadtests-list'),
    path('loadtests/<uuid:pk>/', views.LoadTestResultDetailView.as_view(), name='loadtests-detail'),
    path('loadtests/compare/', views.LoadTestCompareView.as_view(), name='loadtests-compare'),

    # Run load test on remote collector via pcd daemon
    path('loadtests/run/<uuid:collector_id>/', views.RunLoadTestView.as_view(), name='loadtests-run'),
    path('loadtest/run/<uuid:collector_id>/', views.RunLoadTestView.as_view(), name='loadtest-run'),
]
