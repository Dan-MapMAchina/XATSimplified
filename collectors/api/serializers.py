"""
API serializers for collectors.
"""
from rest_framework import serializers
from collectors.models import Collector, CollectedData, Benchmark, LoadTestResult


class CollectorSerializer(serializers.ModelSerializer):
    """Serializer for Collector model."""
    owner_username = serializers.ReadOnlyField(source='owner.username')
    specs_summary = serializers.ReadOnlyField()

    class Meta:
        model = Collector
        fields = [
            'id', 'name', 'description', 'status', 'last_seen',
            'hostname', 'ip_address', 'os_name', 'os_version', 'kernel_version',
            'vm_brand', 'processor_brand', 'processor_model',
            'vcpus', 'memory_gib', 'storage_gib', 'storage_type',
            'created_at', 'updated_at',
            'owner_username', 'specs_summary'
        ]
        read_only_fields = [
            'id', 'status', 'last_seen', 'hostname', 'ip_address',
            'os_name', 'os_version', 'kernel_version',
            'created_at', 'updated_at'
        ]


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
    """Serializer for LoadTestResult model."""
    collector_name = serializers.ReadOnlyField(source='collector.name')
    data_points = serializers.SerializerMethodField()
    max_units = serializers.ReadOnlyField()
    avg_units = serializers.ReadOnlyField()

    class Meta:
        model = LoadTestResult
        fields = [
            'id', 'collector', 'collector_name', 'benchmark',
            'units_10pct', 'units_20pct', 'units_30pct', 'units_40pct', 'units_50pct',
            'units_60pct', 'units_70pct', 'units_80pct', 'units_90pct', 'units_100pct',
            'data_points', 'max_units', 'avg_units',
            'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_data_points(self, obj):
        """Return data points as list of dicts for easy charting."""
        return [
            {'utilization': pct, 'work_units': units}
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
