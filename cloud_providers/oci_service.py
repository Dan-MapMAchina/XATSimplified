"""
OCI (Oracle Cloud Infrastructure) Service

This service handles authentication with OCI using the local ~/.oci/config
and fetches compute instances from your OCI tenancy.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# OCI SDK imports
try:
    import oci
    from oci.config import from_file as oci_config_from_file
    from oci.core import ComputeClient
    from oci.identity import IdentityClient
    OCI_AVAILABLE = True
except ImportError:
    OCI_AVAILABLE = False
    logger.warning("OCI SDK not installed. Run: pip install oci")


@dataclass
class OCIInstance:
    """Represents an OCI Compute Instance"""
    id: str
    name: str
    compartment_id: str
    availability_domain: str
    shape: str
    lifecycle_state: str
    region: str
    time_created: str
    image_id: Optional[str] = None
    fault_domain: Optional[str] = None
    private_ip: Optional[str] = None
    public_ip: Optional[str] = None
    ocpus: Optional[float] = None
    memory_gb: Optional[float] = None
    freeform_tags: Optional[Dict[str, str]] = None


class OCIService:
    """Service for interacting with OCI APIs"""

    def __init__(self, config_file: str = "~/.oci/config", profile: str = "DEFAULT"):
        if not OCI_AVAILABLE:
            raise ImportError("OCI SDK not installed. Run: pip install oci")

        self.config_file = os.path.expanduser(config_file)
        self.profile = profile
        self._config = None
        self._compute_client = None
        self._identity_client = None

    @property
    def config(self) -> Dict[str, Any]:
        """Load and cache OCI config"""
        if self._config is None:
            self._config = oci_config_from_file(self.config_file, self.profile)
        return self._config

    @property
    def compute_client(self) -> 'ComputeClient':
        """Get or create compute client"""
        if self._compute_client is None:
            self._compute_client = ComputeClient(self.config)
        return self._compute_client

    @property
    def identity_client(self) -> 'IdentityClient':
        """Get or create identity client"""
        if self._identity_client is None:
            self._identity_client = IdentityClient(self.config)
        return self._identity_client

    def test_connection(self) -> Dict[str, Any]:
        """Test the OCI connection by fetching tenancy info."""
        try:
            tenancy_id = self.config["tenancy"]
            tenancy = self.identity_client.get_tenancy(tenancy_id).data

            instances = self.get_instances()

            return {
                "success": True,
                "tenancy_name": tenancy.name,
                "tenancy_id": tenancy_id,
                "region": self.config.get("region", "unknown"),
                "instance_count": len(instances),
            }
        except Exception as e:
            logger.error(f"OCI connection test failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_compartments(self) -> List[Dict[str, Any]]:
        """Get all compartments in the tenancy."""
        tenancy_id = self.config["tenancy"]
        compartments = []

        # Add root compartment
        compartments.append({
            "id": tenancy_id,
            "name": "root",
            "description": "Root compartment",
        })

        # List child compartments
        response = self.identity_client.list_compartments(
            compartment_id=tenancy_id,
            compartment_id_in_subtree=True,
            lifecycle_state="ACTIVE"
        )

        for compartment in response.data:
            compartments.append({
                "id": compartment.id,
                "name": compartment.name,
                "description": compartment.description,
            })

        return compartments

    def get_instances(self, compartment_id: Optional[str] = None) -> List[OCIInstance]:
        """Get all compute instances in a compartment or all compartments."""
        instances = []

        if compartment_id:
            compartment_ids = [compartment_id]
        else:
            compartments = self.get_compartments()
            compartment_ids = [c["id"] for c in compartments]

        region = self.config.get("region", "unknown")

        for comp_id in compartment_ids:
            try:
                response = self.compute_client.list_instances(compartment_id=comp_id)

                for instance in response.data:
                    private_ip = None
                    public_ip = None

                    try:
                        vnic_attachments = self.compute_client.list_vnic_attachments(
                            compartment_id=comp_id,
                            instance_id=instance.id
                        ).data

                        if vnic_attachments:
                            vnic_id = vnic_attachments[0].vnic_id
                            network_client = oci.core.VirtualNetworkClient(self.config)
                            vnic = network_client.get_vnic(vnic_id).data
                            private_ip = vnic.private_ip
                            public_ip = vnic.public_ip
                    except Exception as e:
                        logger.warning(f"Failed to get network info for {instance.display_name}: {e}")

                    ocpus = None
                    memory_gb = None
                    if instance.shape_config:
                        ocpus = instance.shape_config.ocpus
                        memory_gb = instance.shape_config.memory_in_gbs

                    instances.append(OCIInstance(
                        id=instance.id,
                        name=instance.display_name,
                        compartment_id=instance.compartment_id,
                        availability_domain=instance.availability_domain,
                        shape=instance.shape,
                        lifecycle_state=instance.lifecycle_state,
                        region=region,
                        time_created=instance.time_created.isoformat() if instance.time_created else None,
                        image_id=instance.image_id,
                        fault_domain=instance.fault_domain,
                        private_ip=private_ip,
                        public_ip=public_ip,
                        ocpus=ocpus,
                        memory_gb=memory_gb,
                        freeform_tags=instance.freeform_tags,
                    ))
            except Exception as e:
                logger.warning(f"Failed to list instances in compartment {comp_id}: {e}")

        return instances

    def start_instance(self, instance_id: str) -> Dict[str, Any]:
        """Start a compute instance."""
        try:
            self.compute_client.instance_action(instance_id, "START")
            return {"success": True, "message": "Instance starting", "lifecycle_state": "STARTING"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop_instance(self, instance_id: str) -> Dict[str, Any]:
        """Stop a compute instance."""
        try:
            self.compute_client.instance_action(instance_id, "STOP")
            return {"success": True, "message": "Instance stopping", "lifecycle_state": "STOPPING"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """Get the current status of an instance."""
        try:
            instance = self.compute_client.get_instance(instance_id).data
            return {
                "success": True,
                "lifecycle_state": instance.lifecycle_state,
                "name": instance.display_name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton instance cache
_oci_service = None


def get_oci_service(profile: str = "DEFAULT") -> Optional[OCIService]:
    """Get or create OCI service instance."""
    global _oci_service
    if not OCI_AVAILABLE:
        return None
    try:
        if _oci_service is None or _oci_service.profile != profile:
            _oci_service = OCIService(profile=profile)
        return _oci_service
    except Exception as e:
        logger.error(f"Failed to initialize OCI service: {e}")
        return None


# OCI shape cost estimates (USD/hour)
OCI_SHAPE_COSTS = {
    "VM.Standard.E2.1.Micro": 0.0,  # Always Free
    "VM.Standard.A1.Flex": 0.0,  # Always Free up to 4 OCPUs, 24GB RAM
    "VM.Standard.E4.Flex": 0.025,
    "VM.Standard.E5.Flex": 0.025,
    "VM.Standard3.Flex": 0.05,
    "VM.Standard.E2.1": 0.03,
    "VM.Standard.E2.2": 0.06,
    "VM.Standard.E2.4": 0.12,
}


def estimate_oci_cost(shape: str, region: str, is_running: bool) -> Dict[str, Any]:
    """Estimate OCI compute cost."""
    if not is_running:
        return {"cost": 0.0, "currency": "USD", "is_estimate": True}

    hourly_cost = OCI_SHAPE_COSTS.get(shape, 0.05)
    daily_cost = hourly_cost * 24

    return {
        "cost": round(daily_cost, 2),
        "currency": "USD",
        "is_estimate": True,
    }
