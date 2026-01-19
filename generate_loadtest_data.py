#!/usr/bin/env python
"""
Generate realistic load test data for XATSimplified.

Creates multiple collectors with varying specs and load test results
to simulate a real-world server comparison scenario.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from collectors.models import Collector, LoadTestResult, Benchmark
from decimal import Decimal
import random

# Server configurations representing different cloud/hardware options
SERVERS = [
    {
        'name': 'aws-m5-xlarge',
        'description': 'AWS M5.xlarge - General purpose',
        'hostname': 'ip-10-0-1-101.ec2.internal',
        'ip_address': '10.0.1.101',
        'os_name': 'Amazon Linux',
        'os_version': '2023',
        'kernel_version': '6.1.0-aws',
        'vm_brand': 'aws',
        'processor_brand': 'intel',
        'processor_model': 'Intel Xeon Platinum 8259CL @ 2.50GHz',
        'vcpus': 4,
        'memory_gib': Decimal('16.0'),
        'storage_gib': Decimal('100.0'),
        'storage_type': 'nvme',
        # Performance: moderate baseline
        'perf_multiplier': 1.0,
    },
    {
        'name': 'aws-m5-2xlarge',
        'description': 'AWS M5.2xlarge - General purpose (larger)',
        'hostname': 'ip-10-0-1-102.ec2.internal',
        'ip_address': '10.0.1.102',
        'os_name': 'Amazon Linux',
        'os_version': '2023',
        'kernel_version': '6.1.0-aws',
        'vm_brand': 'aws',
        'processor_brand': 'intel',
        'processor_model': 'Intel Xeon Platinum 8259CL @ 2.50GHz',
        'vcpus': 8,
        'memory_gib': Decimal('32.0'),
        'storage_gib': Decimal('200.0'),
        'storage_type': 'nvme',
        # Performance: ~2x the xlarge
        'perf_multiplier': 1.95,
    },
    {
        'name': 'azure-d4s-v3',
        'description': 'Azure Standard_D4s_v3 - General purpose',
        'hostname': 'azure-vm-d4s-001',
        'ip_address': '10.1.0.50',
        'os_name': 'Ubuntu',
        'os_version': '22.04 LTS',
        'kernel_version': '5.15.0-azure',
        'vm_brand': 'azure',
        'processor_brand': 'intel',
        'processor_model': 'Intel Xeon E5-2673 v4 @ 2.30GHz',
        'vcpus': 4,
        'memory_gib': Decimal('16.0'),
        'storage_gib': Decimal('128.0'),
        'storage_type': 'ssd',
        # Performance: slightly lower than AWS due to older CPU
        'perf_multiplier': 0.92,
    },
    {
        'name': 'oci-vm-standard-e4',
        'description': 'OCI VM.Standard.E4.Flex - AMD EPYC',
        'hostname': 'oci-instance-001',
        'ip_address': '10.2.0.100',
        'os_name': 'Oracle Linux',
        'os_version': '8.9',
        'kernel_version': '5.15.0-oci',
        'vm_brand': 'oracle_cloud',
        'processor_brand': 'amd',
        'processor_model': 'AMD EPYC 7J13 64-Core Processor',
        'vcpus': 4,
        'memory_gib': Decimal('16.0'),
        'storage_gib': Decimal('100.0'),
        'storage_type': 'block',
        # Performance: AMD EPYC has excellent per-core performance
        'perf_multiplier': 1.15,
    },
    {
        'name': 'oci-ampere-a1',
        'description': 'OCI Ampere A1.Flex - ARM-based',
        'hostname': 'oci-ampere-001',
        'ip_address': '10.2.0.101',
        'os_name': 'Oracle Linux',
        'os_version': '8.9',
        'kernel_version': '5.15.0-oci',
        'vm_brand': 'oracle_cloud',
        'processor_brand': 'ampere',
        'processor_model': 'Ampere Altra Q80-30',
        'vcpus': 4,
        'memory_gib': Decimal('24.0'),
        'storage_gib': Decimal('100.0'),
        'storage_type': 'block',
        # Performance: ARM has different characteristics, good efficiency
        'perf_multiplier': 0.88,
    },
    {
        'name': 'bare-metal-dell-r640',
        'description': 'Dell PowerEdge R640 - Bare metal',
        'hostname': 'dell-r640-rack1-u10',
        'ip_address': '192.168.100.10',
        'os_name': 'Red Hat Enterprise Linux',
        'os_version': '9.2',
        'kernel_version': '5.14.0-rhel9',
        'vm_brand': 'bare_metal',
        'processor_brand': 'intel',
        'processor_model': 'Intel Xeon Gold 6248R @ 3.00GHz',
        'vcpus': 48,
        'memory_gib': Decimal('256.0'),
        'storage_gib': Decimal('1800.0'),
        'storage_type': 'nvme',
        # Performance: bare metal with high-end Xeon
        'perf_multiplier': 12.5,
    },
    {
        'name': 'gcp-n2-standard-4',
        'description': 'GCP N2 Standard 4 - Intel Cascade Lake',
        'hostname': 'gcp-n2-std-4-001',
        'ip_address': '10.3.0.50',
        'os_name': 'Debian',
        'os_version': '12 (bookworm)',
        'kernel_version': '6.1.0-gcp',
        'vm_brand': 'gcp',
        'processor_brand': 'intel',
        'processor_model': 'Intel Xeon @ 2.80GHz (Cascade Lake)',
        'vcpus': 4,
        'memory_gib': Decimal('16.0'),
        'storage_gib': Decimal('100.0'),
        'storage_type': 'ssd',
        # Performance: Cascade Lake is efficient
        'perf_multiplier': 1.05,
    },
    {
        'name': 'vmware-esxi-vm',
        'description': 'VMware ESXi 8.0 - On-premises VM',
        'hostname': 'vmware-prod-app01',
        'ip_address': '192.168.50.101',
        'os_name': 'Ubuntu',
        'os_version': '20.04 LTS',
        'kernel_version': '5.4.0-generic',
        'vm_brand': 'vmware',
        'processor_brand': 'intel',
        'processor_model': 'Intel Xeon E5-2680 v4 @ 2.40GHz',
        'vcpus': 4,
        'memory_gib': Decimal('16.0'),
        'storage_gib': Decimal('200.0'),
        'storage_type': 'ssd',
        # Performance: older CPU, virtualization overhead
        'perf_multiplier': 0.78,
    },
]

# Base work units at each utilization level (for a 4 vCPU baseline)
BASE_WORK_UNITS = {
    10: 850,
    20: 1700,
    30: 2500,
    40: 3300,
    50: 4100,
    60: 4850,
    70: 5600,
    80: 6300,
    90: 6950,
    100: 7500,
}


def generate_work_units(server_config):
    """Generate work units with realistic variance."""
    multiplier = server_config['perf_multiplier']
    vcpu_factor = server_config['vcpus'] / 4  # Normalize to 4 vCPU baseline

    work_units = {}
    for pct, base_units in BASE_WORK_UNITS.items():
        # Apply multipliers with some random variance (±5%)
        variance = random.uniform(0.95, 1.05)
        units = int(base_units * multiplier * vcpu_factor * variance)
        work_units[f'units_{pct}pct'] = units

    return work_units


def main():
    print("=" * 60)
    print("XATSimplified Load Test Data Generator")
    print("=" * 60)
    print()

    # Get or create test user
    user, created = User.objects.get_or_create(
        username='loadtest_admin',
        defaults={
            'email': 'loadtest@example.com',
            'first_name': 'LoadTest',
            'last_name': 'Admin',
        }
    )
    if created:
        user.set_password('loadtest123')
        user.save()
        print(f"Created user: {user.username}")
    else:
        print(f"Using existing user: {user.username}")

    print()
    print("Creating collectors and load test results...")
    print("-" * 60)

    collectors_created = 0
    loadtests_created = 0

    for server in SERVERS:
        # Check if collector already exists
        collector, created = Collector.objects.get_or_create(
            owner=user,
            name=server['name'],
            defaults={
                'description': server['description'],
                'hostname': server['hostname'],
                'ip_address': server['ip_address'],
                'os_name': server['os_name'],
                'os_version': server['os_version'],
                'kernel_version': server['kernel_version'],
                'vm_brand': server['vm_brand'],
                'processor_brand': server['processor_brand'],
                'processor_model': server['processor_model'],
                'vcpus': server['vcpus'],
                'memory_gib': server['memory_gib'],
                'storage_gib': server['storage_gib'],
                'storage_type': server['storage_type'],
                'status': 'connected',
            }
        )

        if created:
            collectors_created += 1
            print(f"✓ Created collector: {server['name']}")
        else:
            # Update existing collector
            for field in ['description', 'hostname', 'ip_address', 'os_name',
                         'os_version', 'kernel_version', 'vm_brand', 'processor_brand',
                         'processor_model', 'vcpus', 'memory_gib', 'storage_gib',
                         'storage_type']:
                setattr(collector, field, server[field])
            collector.status = 'connected'
            collector.save()
            print(f"• Updated collector: {server['name']}")

        # Generate load test results (3 runs per server for variance)
        for run in range(3):
            work_units = generate_work_units(server)

            loadtest = LoadTestResult.objects.create(
                owner=user,
                collector=collector,
                notes=f"Benchmark run {run + 1} - {server['description']}",
                **work_units
            )
            loadtests_created += 1

        print(f"  → Created 3 load test runs")

    print()
    print("-" * 60)
    print(f"Summary:")
    print(f"  • Collectors: {collectors_created} created, {len(SERVERS) - collectors_created} updated")
    print(f"  • Load tests: {loadtests_created} created")
    print()

    # Print comparison preview
    print("=" * 60)
    print("Performance Comparison Preview (max work units @ 100%)")
    print("=" * 60)
    print()
    print(f"{'Server':<25} {'vCPUs':>6} {'Memory':>8} {'Max Units':>12}")
    print("-" * 60)

    for server in SERVERS:
        collector = Collector.objects.get(owner=user, name=server['name'])
        latest = LoadTestResult.objects.filter(collector=collector).order_by('-created_at').first()
        if latest:
            print(f"{server['name']:<25} {server['vcpus']:>6} {str(server['memory_gib']) + ' GB':>8} {latest.units_100pct:>12,}")

    print()
    print("=" * 60)
    print("Login credentials:")
    print(f"  Username: loadtest_admin")
    print(f"  Password: loadtest123")
    print("=" * 60)


if __name__ == '__main__':
    main()
