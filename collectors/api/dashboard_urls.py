"""
Dashboard API URL configuration for perf-dashboard compatibility.
"""
from django.urls import path
from . import dashboard_views

urlpatterns = [
    # Collector list for dropdown
    path('collectors/', dashboard_views.CollectorListAPI.as_view(), name='dashboard-collector-list'),

    # Time-series metrics endpoints (from CollectedData JSON files)
    path('collectors/<uuid:collector_id>/cpu/', dashboard_views.CollectorCPUDataAPI.as_view(), name='dashboard-cpu'),
    path('collectors/<uuid:collector_id>/memory/', dashboard_views.CollectorMemoryDataAPI.as_view(), name='dashboard-memory'),
    path('collectors/<uuid:collector_id>/disk/', dashboard_views.CollectorDiskDataAPI.as_view(), name='dashboard-disk'),
    path('collectors/<uuid:collector_id>/network/', dashboard_views.CollectorNetworkDataAPI.as_view(), name='dashboard-network'),

    # Live trickle metrics endpoints (from PerformanceMetric model)
    path('collectors/<uuid:collector_id>/live/', dashboard_views.CollectorLiveMetricsAPI.as_view(), name='dashboard-live'),
    path('collectors/<uuid:collector_id>/trickle-status/', dashboard_views.TrickleStatusAPI.as_view(), name='dashboard-trickle-status'),

    # Trickle session management endpoints
    path('trickle/active/', dashboard_views.ActiveTrickleSessionsAPI.as_view(), name='dashboard-active-sessions'),
    path('trickle/check-inactive/', dashboard_views.CheckAndCompleteInactiveSessionsAPI.as_view(), name='dashboard-check-inactive'),
    path('collectors/<uuid:collector_id>/sessions/', dashboard_views.CollectorSessionsAPI.as_view(), name='dashboard-collector-sessions'),
    path('collectors/<uuid:collector_id>/session-dates/', dashboard_views.CollectorSessionDatesAPI.as_view(), name='dashboard-session-dates'),
    path('sessions/<uuid:session_id>/', dashboard_views.SessionDataAPI.as_view(), name='dashboard-session-data'),
    path('sessions/<uuid:session_id>/complete/', dashboard_views.CompleteSessionAPI.as_view(), name='dashboard-complete-session'),
]
