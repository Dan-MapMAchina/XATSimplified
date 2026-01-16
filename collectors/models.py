"""
Simplified models for XATSimplified.

Models:
- Tenant: Multi-tenancy support (django-tenants)
- Domain: Domain routing for tenants
- Collector: Represents a monitored server/VM
- CollectedData: Uploaded performance data files
- Benchmark: Performance benchmark runs
- LoadTestResult: CPU work units at utilization levels
"""
import uuid
import secrets
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    """
    Tenant model for multi-tenancy.
    Each tenant gets an isolated PostgreSQL schema.
    """
    name = models.CharField(max_length=100)
    created_on = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    # Default true, schema will be created automatically
    auto_create_schema = True

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Domain(DomainMixin):
    """
    Domain model for tenant routing.
    Maps domains/subdomains to tenants.
    """
    pass


class Collector(models.Model):
    """
    Represents a monitored server or VM.

    Supports two registration modes:
    1. Manual: User enters name, pcc auto-populates specs on first contact
    2. Auto: pcc registers and populates everything automatically

    The api_key is used for pcc authentication.
    """

    # Status choices
    class Status(models.TextChoices):
        PENDING = 'pending', 'Waiting for collector'
        CONNECTED = 'connected', 'Connected'
        DISCONNECTED = 'disconnected', 'Disconnected'
        ERROR = 'error', 'Error'

    # VM brand choices
    class VMBrand(models.TextChoices):
        DELL = 'dell', 'Dell'
        HP = 'hp', 'HP'
        LENOVO = 'lenovo', 'Lenovo'
        ORACLE_CLOUD = 'oracle_cloud', 'Oracle Cloud'
        AZURE = 'azure', 'Azure'
        AWS = 'aws', 'AWS'
        GCP = 'gcp', 'Google Cloud'
        VMWARE = 'vmware', 'VMware'
        BARE_METAL = 'bare_metal', 'Bare Metal'
        OTHER = 'other', 'Other'
        UNKNOWN = 'unknown', 'Unknown'

    # Processor brand choices
    class ProcessorBrand(models.TextChoices):
        INTEL = 'intel', 'Intel'
        AMD = 'amd', 'AMD'
        ARM = 'arm', 'ARM'
        AMPERE = 'ampere', 'Ampere'
        OTHER = 'other', 'Other'
        UNKNOWN = 'unknown', 'Unknown'

    # Storage type choices
    class StorageType(models.TextChoices):
        NVME = 'nvme', 'NVMe SSD'
        SSD = 'ssd', 'SSD'
        HDD = 'hdd', 'HDD'
        BLOCK = 'block', 'Block Storage'
        OTHER = 'other', 'Other'
        UNKNOWN = 'unknown', 'Unknown'

    # Core fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='collectors')
    name = models.CharField(max_length=100, help_text="Friendly name for this server")
    description = models.TextField(blank=True, help_text="Optional description")

    # API authentication
    api_key = models.CharField(
        max_length=64,
        unique=True,
        default=secrets.token_urlsafe,
        help_text="API key for pcc authentication"
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    last_seen = models.DateTimeField(null=True, blank=True)

    # Auto-detected fields (populated by pcc on first contact)
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    os_name = models.CharField(max_length=100, blank=True, help_text="e.g., Ubuntu 22.04")
    os_version = models.CharField(max_length=50, blank=True)
    kernel_version = models.CharField(max_length=100, blank=True)

    # Hardware specs (auto-detected or manual)
    vm_brand = models.CharField(
        max_length=20,
        choices=VMBrand.choices,
        default=VMBrand.UNKNOWN
    )
    processor_brand = models.CharField(
        max_length=20,
        choices=ProcessorBrand.choices,
        default=ProcessorBrand.UNKNOWN
    )
    processor_model = models.CharField(max_length=200, blank=True)
    vcpus = models.PositiveIntegerField(null=True, blank=True, help_text="Number of vCPUs")
    memory_gib = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Memory in GiB"
    )
    storage_gib = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Storage in GiB"
    )
    storage_type = models.CharField(
        max_length=20,
        choices=StorageType.choices,
        default=StorageType.UNKNOWN
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['api_key']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name'],
                name='unique_collector_name_per_owner'
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.status})"

    def regenerate_api_key(self):
        """Generate a new API key."""
        self.api_key = secrets.token_urlsafe(32)
        self.save(update_fields=['api_key'])
        return self.api_key

    @property
    def specs_summary(self):
        """Return a summary of hardware specs."""
        parts = []
        if self.vcpus:
            parts.append(f"{self.vcpus} vCPUs")
        if self.memory_gib:
            parts.append(f"{self.memory_gib} GiB RAM")
        if self.processor_model:
            parts.append(self.processor_model)
        return " | ".join(parts) if parts else "Specs pending"


def collected_data_path(instance, filename):
    """Generate upload path for collected data files."""
    return f"collectors/{instance.collector.id}/{filename}"


class CollectedData(models.Model):
    """
    Uploaded performance data files from pcc.
    """
    ALLOWED_EXTENSIONS = ['csv', 'json', 'txt', 'log', 'gz', 'zip']

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collector = models.ForeignKey(
        Collector,
        on_delete=models.CASCADE,
        related_name='collected_data'
    )
    description = models.CharField(max_length=200, blank=True)
    file = models.FileField(
        upload_to=collected_data_path,
        validators=[FileExtensionValidator(allowed_extensions=ALLOWED_EXTENSIONS)]
    )
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")
    row_count = models.PositiveIntegerField(null=True, blank=True, help_text="Number of data rows")

    # Time range of data in file
    data_start = models.DateTimeField(null=True, blank=True)
    data_end = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Collected data"
        indexes = [
            models.Index(fields=['collector', '-created_at']),
        ]

    def __str__(self):
        return f"{self.collector.name} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size
        super().save(*args, **kwargs)


class Benchmark(models.Model):
    """
    Performance benchmark run for comparing servers.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COLLECTING = 'collecting', 'Collecting Data'
        RUNNING = 'running', 'Running Analysis'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='benchmarks')
    collector = models.ForeignKey(
        Collector,
        on_delete=models.CASCADE,
        related_name='benchmarks'
    )

    # Benchmark metadata
    name = models.CharField(max_length=100, blank=True)
    benchmark_type = models.CharField(max_length=50, default='standard')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Timing
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    # Scores (0-100 scale)
    cpu_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    memory_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    disk_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    network_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    overall_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # Error tracking
    error_message = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['collector', '-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.collector.name} - {self.status} ({self.created_at.strftime('%Y-%m-%d')})"

    @property
    def is_complete(self):
        return self.status == self.Status.COMPLETED


class LoadTestResult(models.Model):
    """
    CPU work units at different utilization levels.
    Used for comparing raw compute performance across servers.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loadtest_results')
    collector = models.ForeignKey(
        Collector,
        on_delete=models.CASCADE,
        related_name='loadtest_results'
    )
    benchmark = models.ForeignKey(
        Benchmark,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loadtest_results'
    )

    # Work units at each utilization level
    # Separate fields for efficient querying and comparison
    units_10pct = models.PositiveIntegerField(default=0, help_text="Work units at 10% CPU")
    units_20pct = models.PositiveIntegerField(default=0, help_text="Work units at 20% CPU")
    units_30pct = models.PositiveIntegerField(default=0, help_text="Work units at 30% CPU")
    units_40pct = models.PositiveIntegerField(default=0, help_text="Work units at 40% CPU")
    units_50pct = models.PositiveIntegerField(default=0, help_text="Work units at 50% CPU")
    units_60pct = models.PositiveIntegerField(default=0, help_text="Work units at 60% CPU")
    units_70pct = models.PositiveIntegerField(default=0, help_text="Work units at 70% CPU")
    units_80pct = models.PositiveIntegerField(default=0, help_text="Work units at 80% CPU")
    units_90pct = models.PositiveIntegerField(default=0, help_text="Work units at 90% CPU")
    units_100pct = models.PositiveIntegerField(default=0, help_text="Work units at 100% CPU")

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['collector', '-created_at']),
            models.Index(fields=['owner', '-created_at']),
        ]

    def __str__(self):
        return f"{self.collector.name} - LoadTest ({self.created_at.strftime('%Y-%m-%d')})"

    def get_data_points(self):
        """Return list of (utilization_pct, work_units) tuples."""
        return [
            (10, self.units_10pct),
            (20, self.units_20pct),
            (30, self.units_30pct),
            (40, self.units_40pct),
            (50, self.units_50pct),
            (60, self.units_60pct),
            (70, self.units_70pct),
            (80, self.units_80pct),
            (90, self.units_90pct),
            (100, self.units_100pct),
        ]

    @property
    def max_units(self):
        """Return maximum work units achieved."""
        return max(
            self.units_10pct, self.units_20pct, self.units_30pct,
            self.units_40pct, self.units_50pct, self.units_60pct,
            self.units_70pct, self.units_80pct, self.units_90pct,
            self.units_100pct
        )

    @property
    def avg_units(self):
        """Return average work units across all levels."""
        total = sum([
            self.units_10pct, self.units_20pct, self.units_30pct,
            self.units_40pct, self.units_50pct, self.units_60pct,
            self.units_70pct, self.units_80pct, self.units_90pct,
            self.units_100pct
        ])
        return total // 10
