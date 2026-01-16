"""
Admin configuration for collectors app.
"""
from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain, Collector, CollectedData, Benchmark, LoadTestResult


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'schema_name', 'is_active', 'created_on']
    list_filter = ['is_active']
    search_fields = ['name', 'schema_name']


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ['domain', 'tenant', 'is_primary']
    list_filter = ['is_primary']
    search_fields = ['domain']


@admin.register(Collector)
class CollectorAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'status', 'hostname', 'vcpus', 'memory_gib', 'last_seen', 'created_at']
    list_filter = ['status', 'vm_brand', 'processor_brand', 'created_at']
    search_fields = ['name', 'hostname', 'owner__username']
    readonly_fields = ['id', 'api_key', 'created_at', 'updated_at']
    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'owner', 'name', 'description', 'status')
        }),
        ('Authentication', {
            'fields': ('api_key',),
            'classes': ('collapse',)
        }),
        ('System Info', {
            'fields': ('hostname', 'ip_address', 'os_name', 'os_version', 'kernel_version')
        }),
        ('Hardware Specs', {
            'fields': ('vm_brand', 'processor_brand', 'processor_model', 'vcpus', 'memory_gib', 'storage_gib', 'storage_type')
        }),
        ('Timestamps', {
            'fields': ('last_seen', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CollectedData)
class CollectedDataAdmin(admin.ModelAdmin):
    list_display = ['collector', 'description', 'file_size', 'row_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['collector__name', 'description']
    readonly_fields = ['id', 'file_size', 'created_at']


@admin.register(Benchmark)
class BenchmarkAdmin(admin.ModelAdmin):
    list_display = ['collector', 'owner', 'status', 'overall_score', 'cpu_score', 'start_time', 'created_at']
    list_filter = ['status', 'benchmark_type', 'created_at']
    search_fields = ['collector__name', 'owner__username']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(LoadTestResult)
class LoadTestResultAdmin(admin.ModelAdmin):
    list_display = ['collector', 'owner', 'max_units', 'avg_units', 'created_at']
    list_filter = ['created_at']
    search_fields = ['collector__name', 'owner__username']
    readonly_fields = ['id', 'created_at']
