"""
Cloud Providers API Views

REST API endpoints for cloud provider operations.
Supports OCI (Oracle Cloud Infrastructure) and AWS (Amazon Web Services).
"""

import json
import logging
import os
from datetime import datetime
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .oci_service import get_oci_service, estimate_oci_cost, OCI_AVAILABLE
from .aws_service import get_aws_service, estimate_aws_cost, AWS_AVAILABLE

logger = logging.getLogger(__name__)

# Simple file-based PCC status store
PCC_STATUS_FILE = os.path.expanduser("~/.pcc_status.json")


def load_pcc_status() -> dict:
    """Load PCC status from file."""
    try:
        if os.path.exists(PCC_STATUS_FILE):
            with open(PCC_STATUS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load PCC status: {e}")
    return {}


def save_pcc_status(status: dict) -> None:
    """Save PCC status to file."""
    try:
        with open(PCC_STATUS_FILE, 'w') as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save PCC status: {e}")


def update_instance_pcc_status(instance_id: str, installed: bool, version: str = None) -> None:
    """Update PCC status for a specific instance."""
    status = load_pcc_status()
    status[instance_id] = {
        "installed": installed,
        "version": version or "1.0.0",
        "updated_at": datetime.utcnow().isoformat(),
    }
    save_pcc_status(status)


def get_instance_pcc_status(instance_id: str) -> dict:
    """Get PCC status for a specific instance."""
    status = load_pcc_status()
    return status.get(instance_id, {"installed": False, "version": None})


# =============================================================================
# OCI Endpoints
# =============================================================================

@csrf_exempt
@require_http_methods(["GET"])
def oci_status(request):
    """
    Check OCI SDK availability and connection status.
    GET /api/v1/cloud/oci/status
    """
    if not OCI_AVAILABLE:
        return JsonResponse({
            "available": False,
            "error": "OCI SDK not installed. Run: pip install oci",
        }, status=503)

    oci_service = get_oci_service()
    if not oci_service:
        return JsonResponse({
            "available": True,
            "connected": False,
            "error": "Failed to initialize OCI service. Check ~/.oci/config",
        }, status=500)

    result = oci_service.test_connection()

    if result["success"]:
        return JsonResponse({
            "available": True,
            "connected": True,
            "tenancy_name": result["tenancy_name"],
            "tenancy_id": result["tenancy_id"],
            "region": result["region"],
            "instance_count": result["instance_count"],
        })
    else:
        return JsonResponse({
            "available": True,
            "connected": False,
            "error": result["error"],
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def oci_connect(request):
    """
    Test OCI connection with provided credentials.
    POST /api/v1/cloud/oci/connect
    """
    if not OCI_AVAILABLE:
        return JsonResponse({
            "success": False,
            "error": "OCI SDK not installed. Run: pip install oci",
        }, status=503)

    try:
        body = json.loads(request.body) if request.body else {}
        profile = body.get("profile", "DEFAULT")
    except json.JSONDecodeError:
        profile = "DEFAULT"

    oci_service = get_oci_service(profile=profile)
    if not oci_service:
        return JsonResponse({
            "success": False,
            "error": "Failed to initialize OCI service. Check ~/.oci/config",
        }, status=500)

    result = oci_service.test_connection()

    if result["success"]:
        return JsonResponse({
            "success": True,
            "tenancy_name": result["tenancy_name"],
            "tenancy_id": result["tenancy_id"],
            "region": result["region"],
            "instance_count": result["instance_count"],
        })
    else:
        return JsonResponse({
            "success": False,
            "error": result["error"],
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def oci_disconnect(request):
    """
    Disconnect from OCI.
    POST /api/v1/cloud/oci/disconnect
    """
    return JsonResponse({
        "success": True,
        "message": "Disconnected from OCI",
    })


@csrf_exempt
@require_http_methods(["GET"])
def oci_compartments(request):
    """
    Get all OCI compartments.
    GET /api/v1/cloud/oci/compartments
    """
    if not OCI_AVAILABLE:
        return JsonResponse({"error": "OCI SDK not installed"}, status=503)

    oci_service = get_oci_service()
    if not oci_service:
        return JsonResponse({"error": "Failed to initialize OCI service"}, status=500)

    try:
        compartments = oci_service.get_compartments()
        return JsonResponse({"compartments": compartments})
    except Exception as e:
        logger.error(f"Failed to get compartments: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def oci_instances(request):
    """
    Get all OCI compute instances.
    GET /api/v1/cloud/oci/instances
    GET /api/v1/cloud/oci/instances?compartment_id=ocid1.compartment...
    """
    if not OCI_AVAILABLE:
        return JsonResponse({"error": "OCI SDK not installed"}, status=503)

    oci_service = get_oci_service()
    if not oci_service:
        return JsonResponse({"error": "Failed to initialize OCI service"}, status=500)

    compartment_id = request.GET.get("compartment_id")

    try:
        instances = oci_service.get_instances(compartment_id)

        resources = []
        for instance in instances:
            status_map = {
                "RUNNING": "running",
                "STOPPED": "stopped",
                "STARTING": "starting",
                "STOPPING": "stopping",
                "TERMINATED": "stopped",
                "TERMINATING": "stopping",
            }
            status = status_map.get(instance.lifecycle_state, "unknown")
            is_running = status == "running"

            cost = estimate_oci_cost(instance.shape, instance.region, is_running)

            resources.append({
                "id": instance.id,
                "name": instance.name,
                "provider": "oci",
                "region": instance.region,
                "location": f"OCI {instance.availability_domain}",
                "type": "vm",
                "instanceType": instance.shape,
                "status": status,
                "ipAddress": instance.public_ip,
                "privateIp": instance.private_ip,
                "os": "Linux",
                "cpuCores": int(instance.ocpus) if instance.ocpus else None,
                "memoryGB": int(instance.memory_gb) if instance.memory_gb else None,
                "pccInstalled": get_instance_pcc_status(instance.id).get("installed", False),
                "pccVersion": get_instance_pcc_status(instance.id).get("version"),
                "collectionStatus": "collecting" if get_instance_pcc_status(instance.id).get("installed") else "idle",
                "tags": instance.freeform_tags,
                "compartmentId": instance.compartment_id,
                "dailyCostRunning": cost["cost"] if is_running else estimate_oci_cost(instance.shape, instance.region, True)["cost"],
                "dailyCostStopped": 0.0,
                "costCurrency": cost["currency"],
                "costIsEstimate": cost["is_estimate"],
            })

        return JsonResponse({"instances": resources, "count": len(resources)})

    except Exception as e:
        logger.error(f"Failed to get instances: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def oci_start_instance(request, instance_id):
    """Start an OCI instance."""
    if not OCI_AVAILABLE:
        return JsonResponse({"error": "OCI SDK not installed"}, status=503)

    oci_service = get_oci_service()
    if not oci_service:
        return JsonResponse({"error": "Failed to initialize OCI service"}, status=500)

    result = oci_service.start_instance(instance_id)
    if result.get("success"):
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def oci_stop_instance(request, instance_id):
    """Stop an OCI instance."""
    if not OCI_AVAILABLE:
        return JsonResponse({"error": "OCI SDK not installed"}, status=503)

    oci_service = get_oci_service()
    if not oci_service:
        return JsonResponse({"error": "Failed to initialize OCI service"}, status=500)

    result = oci_service.stop_instance(instance_id)
    if result.get("success"):
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def oci_instance_status(request, instance_id):
    """Get OCI instance status."""
    if not OCI_AVAILABLE:
        return JsonResponse({"error": "OCI SDK not installed"}, status=503)

    oci_service = get_oci_service()
    if not oci_service:
        return JsonResponse({"error": "Failed to initialize OCI service"}, status=500)

    result = oci_service.get_instance_status(instance_id)
    if result.get("success"):
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def oci_deploy_pcc(request, instance_id):
    """Deploy PCC to an OCI instance (placeholder)."""
    update_instance_pcc_status(instance_id, True, "1.0.0")
    return JsonResponse({
        "success": True,
        "message": "PCC deployment initiated",
        "pcc_version": "1.0.0",
    })


@csrf_exempt
@require_http_methods(["GET"])
def oci_validate_pcc(request, instance_id):
    """Validate PCC on an OCI instance."""
    pcc_status = get_instance_pcc_status(instance_id)
    return JsonResponse({
        "success": True,
        "pcc_installed": pcc_status.get("installed", False),
        "pcc_running": pcc_status.get("installed", False),
        "pcc_version": pcc_status.get("version"),
    })


@csrf_exempt
@require_http_methods(["POST"])
def oci_stop_pcc(request, instance_id):
    """Stop PCC on an OCI instance."""
    update_instance_pcc_status(instance_id, False)
    return JsonResponse({
        "success": True,
        "message": "PCC stopped",
    })


# =============================================================================
# AWS Endpoints
# =============================================================================

@csrf_exempt
@require_http_methods(["GET"])
def aws_status(request):
    """
    Check AWS SDK availability and connection status.
    GET /api/v1/cloud/aws/status
    """
    if not AWS_AVAILABLE:
        return JsonResponse({
            "available": False,
            "error": "AWS SDK (boto3) not installed. Run: pip install boto3",
        }, status=503)

    aws_service = get_aws_service()
    if not aws_service:
        return JsonResponse({
            "available": True,
            "connected": False,
            "error": "Failed to initialize AWS service. Check credentials.",
        }, status=500)

    result = aws_service.test_connection()

    if result["success"]:
        return JsonResponse({
            "available": True,
            "connected": True,
            "account_id": result["account_id"],
            "region": result["region"],
            "instance_count": result["instance_count"],
        })
    else:
        return JsonResponse({
            "available": True,
            "connected": False,
            "error": result["error"],
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def aws_connect(request):
    """
    Test AWS connection.
    POST /api/v1/cloud/aws/connect
    """
    if not AWS_AVAILABLE:
        return JsonResponse({
            "success": False,
            "error": "AWS SDK (boto3) not installed. Run: pip install boto3",
        }, status=503)

    try:
        body = json.loads(request.body) if request.body else {}
        profile = body.get("profile")
        region = body.get("region")
    except json.JSONDecodeError:
        profile = None
        region = None

    aws_service = get_aws_service(profile=profile, region=region)
    if not aws_service:
        return JsonResponse({
            "success": False,
            "error": "Failed to initialize AWS service. Check credentials.",
        }, status=500)

    result = aws_service.test_connection()

    if result["success"]:
        return JsonResponse({
            "success": True,
            "account_id": result["account_id"],
            "region": result["region"],
            "instance_count": result["instance_count"],
        })
    else:
        return JsonResponse({
            "success": False,
            "error": result["error"],
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def aws_disconnect(request):
    """
    Disconnect from AWS.
    POST /api/v1/cloud/aws/disconnect
    """
    return JsonResponse({
        "success": True,
        "message": "Disconnected from AWS",
    })


@csrf_exempt
@require_http_methods(["GET"])
def aws_regions(request):
    """
    Get available AWS regions.
    GET /api/v1/cloud/aws/regions
    """
    if not AWS_AVAILABLE:
        return JsonResponse({"error": "AWS SDK not installed"}, status=503)

    aws_service = get_aws_service()
    if not aws_service:
        return JsonResponse({"error": "Failed to initialize AWS service"}, status=500)

    try:
        regions = aws_service.get_regions()
        return JsonResponse({"regions": regions})
    except Exception as e:
        logger.error(f"Failed to get regions: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def aws_instances(request):
    """
    Get all AWS EC2 instances.
    GET /api/v1/cloud/aws/instances
    GET /api/v1/cloud/aws/instances?region=us-west-2
    """
    if not AWS_AVAILABLE:
        return JsonResponse({"error": "AWS SDK not installed"}, status=503)

    aws_service = get_aws_service()
    if not aws_service:
        return JsonResponse({"error": "Failed to initialize AWS service"}, status=500)

    region = request.GET.get("region")

    try:
        instances = aws_service.get_instances(region)

        resources = []
        for instance in instances:
            status_map = {
                "running": "running",
                "stopped": "stopped",
                "pending": "starting",
                "stopping": "stopping",
                "terminated": "stopped",
                "shutting-down": "stopping",
            }
            status = status_map.get(instance.state, "unknown")
            is_running = status == "running"

            cost = estimate_aws_cost(instance.instance_type, instance.region, is_running)

            resources.append({
                "id": instance.id,
                "name": instance.name,
                "provider": "aws",
                "region": instance.region,
                "location": f"AWS {instance.availability_zone}",
                "type": "vm",
                "instanceType": instance.instance_type,
                "status": status,
                "ipAddress": instance.public_ip,
                "privateIp": instance.private_ip,
                "os": "Windows" if instance.platform == "windows" else "Linux",
                "cpuCores": instance.vcpus,
                "memoryGB": instance.memory_gb,
                "pccInstalled": get_instance_pcc_status(instance.id).get("installed", False),
                "pccVersion": get_instance_pcc_status(instance.id).get("version"),
                "collectionStatus": "collecting" if get_instance_pcc_status(instance.id).get("installed") else "idle",
                "tags": instance.tags,
                "vpcId": instance.vpc_id,
                "subnetId": instance.subnet_id,
                "dailyCostRunning": cost["cost"] if is_running else estimate_aws_cost(instance.instance_type, instance.region, True)["cost"],
                "dailyCostStopped": 0.0,
                "costCurrency": cost["currency"],
                "costIsEstimate": cost["is_estimate"],
            })

        return JsonResponse({"instances": resources, "count": len(resources)})

    except Exception as e:
        logger.error(f"Failed to get instances: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def aws_start_instance(request, instance_id):
    """Start an AWS instance."""
    if not AWS_AVAILABLE:
        return JsonResponse({"error": "AWS SDK not installed"}, status=503)

    aws_service = get_aws_service()
    if not aws_service:
        return JsonResponse({"error": "Failed to initialize AWS service"}, status=500)

    result = aws_service.start_instance(instance_id)
    if result.get("success"):
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def aws_stop_instance(request, instance_id):
    """Stop an AWS instance."""
    if not AWS_AVAILABLE:
        return JsonResponse({"error": "AWS SDK not installed"}, status=503)

    aws_service = get_aws_service()
    if not aws_service:
        return JsonResponse({"error": "Failed to initialize AWS service"}, status=500)

    result = aws_service.stop_instance(instance_id)
    if result.get("success"):
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def aws_instance_status(request, instance_id):
    """Get AWS instance status."""
    if not AWS_AVAILABLE:
        return JsonResponse({"error": "AWS SDK not installed"}, status=503)

    aws_service = get_aws_service()
    if not aws_service:
        return JsonResponse({"error": "Failed to initialize AWS service"}, status=500)

    result = aws_service.get_instance_status(instance_id)
    if result.get("success"):
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def aws_deploy_pcc(request, instance_id):
    """Deploy PCC to an AWS instance (placeholder)."""
    update_instance_pcc_status(instance_id, True, "1.0.0")
    return JsonResponse({
        "success": True,
        "message": "PCC deployment initiated",
        "pcc_version": "1.0.0",
    })


@csrf_exempt
@require_http_methods(["GET"])
def aws_validate_pcc(request, instance_id):
    """Validate PCC on an AWS instance."""
    pcc_status = get_instance_pcc_status(instance_id)
    return JsonResponse({
        "success": True,
        "pcc_installed": pcc_status.get("installed", False),
        "pcc_running": pcc_status.get("installed", False),
        "pcc_version": pcc_status.get("version"),
    })


@csrf_exempt
@require_http_methods(["POST"])
def aws_stop_pcc(request, instance_id):
    """Stop PCC on an AWS instance."""
    update_instance_pcc_status(instance_id, False)
    return JsonResponse({
        "success": True,
        "message": "PCC stopped",
    })


@csrf_exempt
@require_http_methods(["POST"])
def aws_set_pcc_status(request, instance_id):
    """Set PCC status manually for an AWS instance."""
    try:
        body = json.loads(request.body) if request.body else {}
        installed = body.get("installed", False)
        version = body.get("version", "1.0.0")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    update_instance_pcc_status(instance_id, installed, version)
    return JsonResponse({
        "success": True,
        "message": "PCC status updated",
        "pcc_installed": installed,
        "pcc_version": version,
    })
