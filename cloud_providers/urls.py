"""
Cloud Providers URL Configuration
"""

from django.urls import path
from . import views

app_name = 'cloud_providers'

urlpatterns = [
    # OCI endpoints
    path('api/v1/cloud/oci/status', views.oci_status, name='oci_status'),
    path('api/v1/cloud/oci/connect', views.oci_connect, name='oci_connect'),
    path('api/v1/cloud/oci/disconnect', views.oci_disconnect, name='oci_disconnect'),
    path('api/v1/cloud/oci/compartments', views.oci_compartments, name='oci_compartments'),
    path('api/v1/cloud/oci/instances', views.oci_instances, name='oci_instances'),
    # OCI instance control
    path('api/v1/cloud/oci/instances/<str:instance_id>/start', views.oci_start_instance, name='oci_start_instance'),
    path('api/v1/cloud/oci/instances/<str:instance_id>/stop', views.oci_stop_instance, name='oci_stop_instance'),
    path('api/v1/cloud/oci/instances/<str:instance_id>/status', views.oci_instance_status, name='oci_instance_status'),
    # OCI PCC deployment
    path('api/v1/cloud/oci/instances/<str:instance_id>/deploy-pcc', views.oci_deploy_pcc, name='oci_deploy_pcc'),
    path('api/v1/cloud/oci/instances/<str:instance_id>/validate-pcc', views.oci_validate_pcc, name='oci_validate_pcc'),
    path('api/v1/cloud/oci/instances/<str:instance_id>/stop-pcc', views.oci_stop_pcc, name='oci_stop_pcc'),

    # AWS endpoints
    path('api/v1/cloud/aws/status', views.aws_status, name='aws_status'),
    path('api/v1/cloud/aws/connect', views.aws_connect, name='aws_connect'),
    path('api/v1/cloud/aws/disconnect', views.aws_disconnect, name='aws_disconnect'),
    path('api/v1/cloud/aws/regions', views.aws_regions, name='aws_regions'),
    path('api/v1/cloud/aws/instances', views.aws_instances, name='aws_instances'),
    # AWS instance control
    path('api/v1/cloud/aws/instances/<str:instance_id>/start', views.aws_start_instance, name='aws_start_instance'),
    path('api/v1/cloud/aws/instances/<str:instance_id>/stop', views.aws_stop_instance, name='aws_stop_instance'),
    path('api/v1/cloud/aws/instances/<str:instance_id>/status', views.aws_instance_status, name='aws_instance_status'),
    # AWS PCC deployment
    path('api/v1/cloud/aws/instances/<str:instance_id>/deploy-pcc', views.aws_deploy_pcc, name='aws_deploy_pcc'),
    path('api/v1/cloud/aws/instances/<str:instance_id>/validate-pcc', views.aws_validate_pcc, name='aws_validate_pcc'),
    path('api/v1/cloud/aws/instances/<str:instance_id>/stop-pcc', views.aws_stop_pcc, name='aws_stop_pcc'),
    path('api/v1/cloud/aws/instances/<str:instance_id>/set-pcc-status', views.aws_set_pcc_status, name='aws_set_pcc_status'),
]
