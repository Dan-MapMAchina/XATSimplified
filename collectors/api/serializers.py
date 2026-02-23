"""
API serializers for collectors.
"""
from rest_framework import serializers
from collectors.models import (
    Collector, CollectedData, Benchmark, LoadTestResult,
    BlobTarget, BlobExport,
)


class CollectorSerializer(serializers.ModelSerializer):
    """Serializer for Collector model."""
    owner_username = serializers.ReadOnlyField(source='owner.username')
    specs_summary = serializers.ReadOnlyField()
    has_pcd_config = serializers.SerializerMethodField()

    class Meta:
        model = Collector
        fields = [
            'id', 'name', 'description', 'status', 'last_seen',
            'hostname', 'ip_address', 'os_name', 'os_version', 'kernel_version',
            'vm_brand', 'processor_brand', 'processor_model',
            'vcpus', 'memory_gib', 'storage_gib', 'storage_type',
            'hourly_cost',
            'pcd_address', 'pcd_apikey', 'has_pcd_config',
            'created_at', 'updated_at',
            'owner_username', 'specs_summary'
        ]
        read_only_fields = [
            'id', 'status', 'last_seen', 'hostname', 'ip_address',
            'os_name', 'os_version', 'kernel_version',
            'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'pcd_apikey': {'write_only': True}  # Don't expose API key in reads
        }

    def get_has_pcd_config(self, obj):
        """Check if pcd connection is configured."""
        return bool(obj.pcd_address and obj.pcd_apikey)


class CollectorCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a Collector."""
    api_key = serializers.ReadOnlyField()

    class Meta:
        model = Collector
        fields = ['id', 'name', 'description', 'api_key']
        read_only_fields = ['id', 'api_key']


class CollectorWithKeySerializer(serializers.ModelSerializer):
    """Serializer that includes API key (for creation response)."""
    install_command = serializers.SerializerMethodField()

    class Meta:
        model = Collector
        fields = [
            'id', 'name', 'description', 'api_key', 'status',
            'created_at', 'install_command'
        ]
        read_only_fields = ['id', 'api_key', 'status', 'created_at']

    def get_install_command(self, obj):
        """Generate install command for this collector."""
        request = self.context.get('request')
        if request:
            host = request.get_host()
            scheme = 'https' if request.is_secure() else 'http'
            return f"curl -s {scheme}://{host}/install.sh | API_KEY={obj.api_key} bash"
        return f"API_KEY={obj.api_key} pcc"


class PCCRegisterSerializer(serializers.Serializer):
    """Serializer for pcc registration data."""
    hostname = serializers.CharField(max_length=255)
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    os_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    os_version = serializers.CharField(max_length=50, required=False, allow_blank=True)
    kernel_version = serializers.CharField(max_length=100, required=False, allow_blank=True)

    # Hardware specs
    processor_brand = serializers.ChoiceField(
        choices=Collector.ProcessorBrand.choices,
        required=False,
        default=Collector.ProcessorBrand.UNKNOWN
    )
    processor_model = serializers.CharField(max_length=200, required=False, allow_blank=True)
    vcpus = serializers.IntegerField(required=False, min_value=1, allow_null=True)
    memory_gib = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    storage_gib = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    storage_type = serializers.ChoiceField(
        choices=Collector.StorageType.choices,
        required=False,
        default=Collector.StorageType.UNKNOWN
    )


class CollectedDataSerializer(serializers.ModelSerializer):
    """Serializer for CollectedData model."""
    collector_name = serializers.ReadOnlyField(source='collector.name')

    class Meta:
        model = CollectedData
        fields = [
            'id', 'collector', 'collector_name', 'description',
            'file', 'file_size', 'row_count',
            'data_start', 'data_end', 'created_at'
        ]
        read_only_fields = ['id', 'file_size', 'created_at']


class BenchmarkSerializer(serializers.ModelSerializer):
    """Serializer for Benchmark model."""
    collector_name = serializers.ReadOnlyField(source='collector.name')
    owner_username = serializers.ReadOnlyField(source='owner.username')
    is_complete = serializers.ReadOnlyField()

    class Meta:
        model = Benchmark
        fields = [
            'id', 'collector', 'collector_name', 'owner_username',
            'name', 'benchmark_type', 'status',
            'start_time', 'end_time', 'duration_seconds',
            'cpu_score', 'memory_score', 'disk_score', 'network_score', 'overall_score',
            'error_message', 'is_complete',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'owner_username', 'created_at', 'updated_at']


class BenchmarkCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a Benchmark."""

    class Meta:
        model = Benchmark
        fields = ['collector', 'name', 'benchmark_type']


class LoadTestResultSerializer(serializers.ModelSerializer):
    """Serializer for LoadTestResult model.

    Returns data in the format expected by perf-dashboard:
    - collectorId (not collector)
    - serverName (not collector_name)
    - provider (from collector.vm_brand)
    - data (not data_points) with busyPct/workUnits
    - createdAt (camelCase)
    - maxUnits/avgUnits (camelCase)
    """
    # Map to perf-dashboard expected field names (camelCase)
    collectorId = serializers.CharField(source='collector.id', read_only=True)
    serverName = serializers.CharField(source='collector.name', read_only=True)
    provider = serializers.SerializerMethodField()
    benchmarkId = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()
    maxUnits = serializers.ReadOnlyField(source='max_units')
    avgUnits = serializers.ReadOnlyField(source='avg_units')
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = LoadTestResult
        fields = [
            'id', 'collectorId', 'serverName', 'provider', 'benchmarkId',
            'data', 'maxUnits', 'avgUnits', 'notes', 'createdAt',
            # Also include original fields for backward compatibility / creation
            'collector', 'units_10pct', 'units_20pct', 'units_30pct', 'units_40pct',
            'units_50pct', 'units_60pct', 'units_70pct', 'units_80pct',
            'units_90pct', 'units_100pct',
        ]
        read_only_fields = ['id', 'createdAt']

    def get_provider(self, obj):
        """Get provider name from collector's vm_brand."""
        provider_map = {
            'aws': 'AWS',
            'azure': 'Azure',
            'gcp': 'GCP',
            'oracle_cloud': 'OCI',
            'vmware': 'VMware',
            'bare_metal': 'Bare Metal',
        }
        vm_brand = obj.collector.vm_brand if obj.collector else None
        return provider_map.get(vm_brand, vm_brand or 'Unknown')

    def get_benchmarkId(self, obj):
        """Get benchmark ID or null."""
        return str(obj.benchmark.id) if obj.benchmark else None

    def get_data(self, obj):
        """Return data points in perf-dashboard format with camelCase keys."""
        return [
            {'busyPct': pct, 'workUnits': units}
            for pct, units in obj.get_data_points()
        ]


class LoadTestCompareSerializer(serializers.Serializer):
    """Serializer for load test comparison request."""
    collector_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=2,
        max_length=10,
        help_text="List of collector IDs to compare"
    )


# =============================================================================
# Azure Blob Storage Serializers
# =============================================================================

class BlobTargetSerializer(serializers.ModelSerializer):
    """Serializer for BlobTarget model."""
    owner_username = serializers.ReadOnlyField(source='owner.username')
    export_count = serializers.SerializerMethodField()

    class Meta:
        model = BlobTarget
        fields = [
            'id', 'name', 'account_name', 'container_name',
            'auth_method', 'key_vault_secret_name',
            'sas_token', 'connection_string',
            'path_prefix', 'export_format',
            'is_active', 'last_tested_at', 'last_test_success',
            'created_at', 'updated_at', 'owner_username', 'export_count',
        ]
        read_only_fields = [
            'id', 'last_tested_at', 'last_test_success',
            'created_at', 'updated_at',
        ]
        extra_kwargs = {
            'sas_token': {'write_only': True},
            'connection_string': {'write_only': True},
        }

    def get_export_count(self, obj):
        return obj.exports.count()

    def validate(self, data):
        # On update (PATCH/PUT), fall back to existing instance values
        instance = self.instance
        auth_method = data.get(
            'auth_method',
            getattr(instance, 'auth_method', 'connection_string')
        )

        if auth_method == 'key_vault':
            has_secret = data.get('key_vault_secret_name') or (
                instance and instance.key_vault_secret_name
            )
            if not has_secret:
                raise serializers.ValidationError(
                    {'key_vault_secret_name': 'Required when auth_method is key_vault'}
                )
        elif auth_method == 'sas_token':
            has_token = data.get('sas_token') or (
                instance and instance.sas_token
            )
            if not has_token:
                raise serializers.ValidationError(
                    {'sas_token': 'Required when auth_method is sas_token'}
                )
        elif auth_method == 'connection_string':
            has_conn = data.get('connection_string') or (
                instance and instance.connection_string
            )
            if not has_conn:
                raise serializers.ValidationError(
                    {'connection_string': 'Required when auth_method is connection_string'}
                )
        return data


class BlobExportSerializer(serializers.ModelSerializer):
    """Serializer for BlobExport model."""
    session_name = serializers.SerializerMethodField()
    blob_target_name = serializers.ReadOnlyField(source='blob_target.name')
    collector_name = serializers.ReadOnlyField(source='session.collector.name')

    class Meta:
        model = BlobExport
        fields = [
            'id', 'session', 'session_name', 'blob_target', 'blob_target_name',
            'collector_name', 'status', 'blob_path', 'blob_url',
            'records_exported', 'file_size_bytes', 'export_format',
            'error_message', 'retry_count',
            'started_at', 'completed_at', 'created_at',
        ]
        read_only_fields = [
            'id', 'status', 'blob_path', 'blob_url',
            'records_exported', 'file_size_bytes',
            'error_message', 'retry_count',
            'started_at', 'completed_at', 'created_at',
        ]

    def get_session_name(self, obj):
        return obj.session.name or str(obj.session.id)
