"""
AWS (Amazon Web Services) Service

This service handles authentication with AWS using boto3 SDK
and fetches EC2 instances from your AWS account.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# AWS SDK imports
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False
    logger.warning("AWS SDK (boto3) not installed. Run: pip install boto3")


@dataclass
class AWSInstance:
    """Represents an AWS EC2 Instance"""
    id: str
    name: str
    instance_type: str
    state: str
    region: str
    availability_zone: str
    launch_time: str
    image_id: Optional[str] = None
    platform: Optional[str] = None
    private_ip: Optional[str] = None
    public_ip: Optional[str] = None
    vpc_id: Optional[str] = None
    subnet_id: Optional[str] = None
    vcpus: Optional[int] = None
    memory_gb: Optional[float] = None
    tags: Optional[Dict[str, str]] = None


# EC2 instance type specs (vCPUs, Memory GB)
EC2_INSTANCE_SPECS = {
    "t3.micro": {"vcpus": 2, "memory_gb": 1},
    "t3.small": {"vcpus": 2, "memory_gb": 2},
    "t3.medium": {"vcpus": 2, "memory_gb": 4},
    "t3.large": {"vcpus": 2, "memory_gb": 8},
    "t3.xlarge": {"vcpus": 4, "memory_gb": 16},
    "t3.2xlarge": {"vcpus": 8, "memory_gb": 32},
    "t2.micro": {"vcpus": 1, "memory_gb": 1},
    "t2.small": {"vcpus": 1, "memory_gb": 2},
    "t2.medium": {"vcpus": 2, "memory_gb": 4},
    "t2.large": {"vcpus": 2, "memory_gb": 8},
    "m5.large": {"vcpus": 2, "memory_gb": 8},
    "m5.xlarge": {"vcpus": 4, "memory_gb": 16},
    "m5.2xlarge": {"vcpus": 8, "memory_gb": 32},
    "m5.4xlarge": {"vcpus": 16, "memory_gb": 64},
    "m6i.large": {"vcpus": 2, "memory_gb": 8},
    "m6i.xlarge": {"vcpus": 4, "memory_gb": 16},
    "m6i.2xlarge": {"vcpus": 8, "memory_gb": 32},
    "c5.large": {"vcpus": 2, "memory_gb": 4},
    "c5.xlarge": {"vcpus": 4, "memory_gb": 8},
    "c5.2xlarge": {"vcpus": 8, "memory_gb": 16},
    "r5.large": {"vcpus": 2, "memory_gb": 16},
    "r5.xlarge": {"vcpus": 4, "memory_gb": 32},
    "r5.2xlarge": {"vcpus": 8, "memory_gb": 64},
}


class AWSService:
    """Service for interacting with AWS APIs"""

    def __init__(self, profile_name: str = None, region: str = None):
        if not AWS_AVAILABLE:
            raise ImportError("AWS SDK (boto3) not installed. Run: pip install boto3")

        self.profile_name = profile_name
        self.region = region or os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
        self._session = None
        self._ec2_client = None
        self._ec2_resource = None

    @property
    def session(self):
        """Get or create boto3 session"""
        if self._session is None:
            try:
                if os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY'):
                    self._session = boto3.Session(region_name=self.region)
                elif self.profile_name:
                    self._session = boto3.Session(profile_name=self.profile_name, region_name=self.region)
                else:
                    self._session = boto3.Session(region_name=self.region)
            except ProfileNotFound as e:
                raise Exception(f"AWS profile '{self.profile_name}' not found in ~/.aws/credentials")
        return self._session

    @property
    def ec2_client(self):
        """Get or create EC2 client"""
        if self._ec2_client is None:
            self._ec2_client = self.session.client('ec2')
        return self._ec2_client

    @property
    def ec2_resource(self):
        """Get or create EC2 resource"""
        if self._ec2_resource is None:
            self._ec2_resource = self.session.resource('ec2')
        return self._ec2_resource

    def test_connection(self) -> Dict[str, Any]:
        """Test the AWS connection by fetching account info."""
        try:
            sts = self.session.client('sts')
            identity = sts.get_caller_identity()
            instances = self.get_instances()

            return {
                "success": True,
                "account_id": identity['Account'],
                "user_arn": identity['Arn'],
                "region": self.region,
                "instance_count": len(instances),
            }
        except NoCredentialsError:
            return {
                "success": False,
                "error": "No AWS credentials found. Configure credentials in ~/.aws/credentials or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.",
            }
        except ClientError as e:
            return {
                "success": False,
                "error": f"AWS authentication error: {e.response['Error']['Message']}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_regions(self) -> List[Dict[str, str]]:
        """Get list of available AWS regions."""
        try:
            response = self.ec2_client.describe_regions()
            return [
                {"id": region['RegionName'], "name": region['RegionName']}
                for region in response['Regions']
            ]
        except Exception as e:
            logger.error(f"Failed to get regions: {e}")
            return []

    def get_instances(self, region: str = None) -> List[AWSInstance]:
        """Get all EC2 instances."""
        instances = []

        try:
            if region and region != self.region:
                client = self.session.client('ec2', region_name=region)
            else:
                client = self.ec2_client
                region = self.region

            response = client.describe_instances()

            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    name = "Unnamed"
                    tags = {}
                    if instance.get('Tags'):
                        for tag in instance['Tags']:
                            tags[tag['Key']] = tag['Value']
                            if tag['Key'] == 'Name':
                                name = tag['Value']

                    instance_type = instance['InstanceType']
                    specs = EC2_INSTANCE_SPECS.get(instance_type, {"vcpus": 0, "memory_gb": 0})

                    instances.append(AWSInstance(
                        id=instance['InstanceId'],
                        name=name,
                        instance_type=instance_type,
                        state=instance['State']['Name'],
                        region=region,
                        availability_zone=instance['Placement']['AvailabilityZone'],
                        launch_time=instance['LaunchTime'].isoformat() if instance.get('LaunchTime') else None,
                        image_id=instance.get('ImageId'),
                        platform=instance.get('Platform', 'linux'),
                        private_ip=instance.get('PrivateIpAddress'),
                        public_ip=instance.get('PublicIpAddress'),
                        vpc_id=instance.get('VpcId'),
                        subnet_id=instance.get('SubnetId'),
                        vcpus=specs["vcpus"],
                        memory_gb=specs["memory_gb"],
                        tags=tags,
                    ))
        except Exception as e:
            logger.error(f"Failed to get instances: {e}")

        return instances

    def start_instance(self, instance_id: str) -> Dict[str, Any]:
        """Start an EC2 instance."""
        try:
            response = self.ec2_client.start_instances(InstanceIds=[instance_id])
            current_state = response['StartingInstances'][0]['CurrentState']['Name']
            return {"success": True, "message": "Instance starting", "state": current_state}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop_instance(self, instance_id: str) -> Dict[str, Any]:
        """Stop an EC2 instance."""
        try:
            response = self.ec2_client.stop_instances(InstanceIds=[instance_id])
            current_state = response['StoppingInstances'][0]['CurrentState']['Name']
            return {"success": True, "message": "Instance stopping", "state": current_state}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """Get the current status of an instance."""
        try:
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = response['Reservations'][0]['Instances'][0]
            name = "Unnamed"
            if instance.get('Tags'):
                for tag in instance['Tags']:
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                        break
            return {
                "success": True,
                "state": instance['State']['Name'],
                "name": name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton instance cache
_aws_service = None


def get_aws_service(profile: str = None, region: str = None) -> Optional[AWSService]:
    """Get or create AWS service instance."""
    global _aws_service
    if not AWS_AVAILABLE:
        return None
    try:
        if _aws_service is None:
            _aws_service = AWSService(profile_name=profile, region=region)
        return _aws_service
    except Exception as e:
        logger.error(f"Failed to initialize AWS service: {e}")
        return None


# AWS EC2 cost estimates (USD/hour for on-demand in us-east-1)
EC2_INSTANCE_COSTS = {
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "t2.micro": 0.0116,
    "t2.small": 0.023,
    "t2.medium": 0.0464,
    "t2.large": 0.0928,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "m6i.large": 0.096,
    "m6i.xlarge": 0.192,
    "m6i.2xlarge": 0.384,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "c5.2xlarge": 0.34,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
    "r5.2xlarge": 0.504,
}


def estimate_aws_cost(instance_type: str, region: str, is_running: bool) -> Dict[str, Any]:
    """Estimate AWS EC2 cost."""
    if not is_running:
        return {"cost": 0.0, "currency": "USD", "is_estimate": True}

    hourly_cost = EC2_INSTANCE_COSTS.get(instance_type, 0.05)
    daily_cost = hourly_cost * 24

    return {
        "cost": round(daily_cost, 2),
        "currency": "USD",
        "is_estimate": True,
    }
