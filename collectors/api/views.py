"""
API views for collectors.
"""
import requests
from django.utils import timezone
from django.db.models import Avg, Max, Min, Count
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from collectors.models import Collector, CollectedData, Benchmark, LoadTestResult, PerformanceMetric
from .serializers import (
    CollectorSerializer,
    CollectorCreateSerializer,
    CollectorWithKeySerializer,
    PCCRegisterSerializer,
    CollectedDataSerializer,
    BenchmarkSerializer,
    BenchmarkCreateSerializer,
    LoadTestResultSerializer,
    LoadTestCompareSerializer,
)
from .authentication import APIKeyAuthentication


# =============================================================================
# Collector Views
# =============================================================================

class CollectorListCreateView(generics.ListCreateAPIView):
    """
    List all collectors for the authenticated user or create a new one.

    GET: List collectors
    POST: Create new collector (returns API key for pcc)
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CollectorCreateSerializer
        return CollectorSerializer

    def get_queryset(self):
        return Collector.objects.filter(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create collector with owner
        collector = Collector.objects.create(
            owner=request.user,
            name=serializer.validated_data['name'],
            description=serializer.validated_data.get('description', '')
        )

        # Return with API key visible
        response_serializer = CollectorWithKeySerializer(
            collector,
            context={'request': request}
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CollectorDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a collector.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CollectorSerializer

    def get_queryset(self):
        return Collector.objects.filter(owner=self.request.user)


class RegenerateAPIKeyView(APIView):
    """
    Regenerate API key for a collector.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            collector = Collector.objects.get(pk=pk, owner=request.user)
        except Collector.DoesNotExist:
            return Response(
                {'error': 'Collector not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        new_key = collector.regenerate_api_key()
        return Response({
            'api_key': new_key,
            'message': 'API key regenerated successfully'
        })


# =============================================================================
# PCC Registration & Metrics Views (API Key Auth)
# =============================================================================

class PCCRegisterView(APIView):
    """
    Registration endpoint for pcc clients.
    Uses API key authentication instead of JWT.

    pcc sends system info on first contact, which updates the collector record.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [AllowAny]  # Auth handled by APIKeyAuthentication

    def post(self, request):
        collector = getattr(request, 'collector', None)
        if not collector:
            return Response(
                {'error': 'Invalid API key'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = PCCRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Update collector with system info
        data = serializer.validated_data
        collector.hostname = data.get('hostname', collector.hostname)
        collector.ip_address = data.get('ip_address', collector.ip_address)
        collector.os_name = data.get('os_name', collector.os_name)
        collector.os_version = data.get('os_version', collector.os_version)
        collector.kernel_version = data.get('kernel_version', collector.kernel_version)
        collector.processor_brand = data.get('processor_brand', collector.processor_brand)
        collector.processor_model = data.get('processor_model', collector.processor_model)
        collector.vcpus = data.get('vcpus', collector.vcpus)
        collector.memory_gib = data.get('memory_gib', collector.memory_gib)
        collector.storage_gib = data.get('storage_gib', collector.storage_gib)
        collector.storage_type = data.get('storage_type', collector.storage_type)

        # Update status and last seen
        collector.status = Collector.Status.CONNECTED
        collector.last_seen = timezone.now()
        collector.save()

        return Response({
            'status': 'registered',
            'collector_id': str(collector.id),
            'name': collector.name,
            'message': 'Collector registered successfully'
        })


class MetricsUploadView(APIView):
    """
    Upload metrics data from pcc.
    Uses API key authentication.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        collector = getattr(request, 'collector', None)
        if not collector:
            return Response(
                {'error': 'Invalid API key'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Update last seen
        collector.last_seen = timezone.now()
        collector.status = Collector.Status.CONNECTED
        collector.save(update_fields=['last_seen', 'status'])

        # Handle file upload
        uploaded_file = request.FILES.get('file')
        if uploaded_file:
            collected_data = CollectedData.objects.create(
                collector=collector,
                description=request.data.get('description', ''),
                file=uploaded_file
            )
            return Response({
                'status': 'uploaded',
                'data_id': str(collected_data.id),
                'file_size': collected_data.file_size
            }, status=status.HTTP_201_CREATED)

        # Handle JSON metrics (for trickle mode)
        metrics = request.data.get('metrics')
        if metrics:
            metrics_count = self._process_trickle_metrics(collector, metrics)
            return Response({
                'status': 'received',
                'metrics_count': metrics_count
            })

        # Handle raw ping data from pcd trickle mode
        # pcd forwards individual measurements from pcc
        ping_data = request.data
        if ping_data.get('subsystem') or ping_data.get('measurement'):
            metrics_count = self._process_ping_data(collector, ping_data)
            return Response({
                'status': 'received',
                'metrics_count': metrics_count
            })

        return Response(
            {'error': 'No file or metrics provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    def _process_trickle_metrics(self, collector, metrics):
        """
        Process an array of trickle metrics from pcc.
        Each metric is a dict with subsystem, timestamp, and measurement.
        """
        from datetime import datetime
        import re

        if not isinstance(metrics, list):
            metrics = [metrics]

        processed_count = 0

        # Group metrics by timestamp
        grouped = {}
        for m in metrics:
            ts = m.get('timestamp', 0)
            if ts not in grouped:
                grouped[ts] = {}
            subsystem = m.get('subsystem', '')
            grouped[ts][subsystem] = m.get('measurement', '')

        # Process each timestamp group
        for ts, subsystems in grouped.items():
            try:
                metric_data = {
                    'collector': collector,
                    'timestamp': datetime.fromtimestamp(ts, tz=timezone.utc) if ts else timezone.now(),
                }

                # Parse /proc/stat for CPU metrics
                if '/proc/stat' in subsystems:
                    cpu_data = self._parse_proc_stat(subsystems['/proc/stat'])
                    if cpu_data:
                        metric_data.update(cpu_data)

                # Parse /proc/meminfo for memory metrics
                if '/proc/meminfo' in subsystems:
                    mem_data = self._parse_meminfo(subsystems['/proc/meminfo'])
                    if mem_data:
                        metric_data.update(mem_data)

                # Parse /proc/diskstats for disk metrics
                if '/proc/diskstats' in subsystems:
                    disk_data = self._parse_diskstats(subsystems['/proc/diskstats'])
                    if disk_data:
                        metric_data.update(disk_data)

                # Parse /proc/net/dev for network metrics
                if '/proc/net/dev' in subsystems:
                    net_data = self._parse_netdev(subsystems['/proc/net/dev'])
                    if net_data:
                        metric_data.update(net_data)

                # Create or update the metric record
                PerformanceMetric.objects.update_or_create(
                    collector=collector,
                    timestamp=metric_data['timestamp'],
                    defaults={k: v for k, v in metric_data.items() if k not in ['collector', 'timestamp']}
                )
                processed_count += 1

            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error processing trickle metric: {e}")
                continue

        return processed_count

    def _process_ping_data(self, collector, ping_data):
        """
        Process a single ping data point from pcd trickle mode.
        """
        from datetime import datetime

        ts = ping_data.get('timestamp', 0)
        subsystem = ping_data.get('subsystem', '')
        measurement = ping_data.get('measurement', '')

        if not subsystem or not measurement:
            return 0

        try:
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else timezone.now()

            # Get or create the metric record for this timestamp
            metric, created = PerformanceMetric.objects.get_or_create(
                collector=collector,
                timestamp=timestamp,
                defaults={}
            )

            # Update based on subsystem
            if subsystem == '/proc/stat':
                cpu_data = self._parse_proc_stat(measurement)
                if cpu_data:
                    for key, value in cpu_data.items():
                        setattr(metric, key, value)
            elif subsystem == '/proc/meminfo':
                mem_data = self._parse_meminfo(measurement)
                if mem_data:
                    for key, value in mem_data.items():
                        setattr(metric, key, value)
            elif subsystem == '/proc/diskstats':
                disk_data = self._parse_diskstats(measurement)
                if disk_data:
                    for key, value in disk_data.items():
                        setattr(metric, key, value)
            elif subsystem == '/proc/net/dev':
                net_data = self._parse_netdev(measurement)
                if net_data:
                    for key, value in net_data.items():
                        setattr(metric, key, value)

            metric.save()
            return 1

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error processing ping data: {e}")
            return 0

    def _parse_proc_stat(self, measurement):
        """Parse /proc/stat and return CPU metrics."""
        if not measurement:
            return None

        for line in measurement.split('\n'):
            if line.startswith('cpu '):
                parts = line.split()
                if len(parts) >= 8:
                    user = int(parts[1])
                    nice = int(parts[2])
                    system = int(parts[3])
                    idle = int(parts[4])
                    iowait = int(parts[5]) if len(parts) > 5 else 0
                    irq = int(parts[6]) if len(parts) > 6 else 0
                    softirq = int(parts[7]) if len(parts) > 7 else 0
                    steal = int(parts[8]) if len(parts) > 8 else 0

                    total = user + nice + system + idle + iowait + irq + softirq + steal
                    if total > 0:
                        return {
                            'cpu_user': round(100.0 * (user + nice) / total, 2),
                            'cpu_system': round(100.0 * system / total, 2),
                            'cpu_iowait': round(100.0 * iowait / total, 2),
                            'cpu_idle': round(100.0 * idle / total, 2),
                            'cpu_steal': round(100.0 * steal / total, 2),
                        }
        return None

    def _parse_meminfo(self, measurement):
        """Parse /proc/meminfo and return memory metrics in MB."""
        if not measurement:
            return None

        values = {}
        for line in measurement.split('\n'):
            parts = line.split(':')
            if len(parts) == 2:
                key = parts[0].strip()
                val_parts = parts[1].strip().split()
                if val_parts:
                    try:
                        values[key] = int(val_parts[0])  # in kB
                    except ValueError:
                        pass

        mem_total = values.get('MemTotal', 0)
        mem_free = values.get('MemFree', 0)
        mem_available = values.get('MemAvailable', 0)
        buffers = values.get('Buffers', 0)
        cached = values.get('Cached', 0)

        if mem_total > 0:
            mem_used = mem_total - mem_available
            return {
                'mem_total': round(mem_total / 1024, 2),  # MB
                'mem_used': round(mem_used / 1024, 2),  # MB
                'mem_available': round(mem_available / 1024, 2),  # MB
                'mem_buffers': round(buffers / 1024, 2),  # MB
                'mem_cached': round(cached / 1024, 2),  # MB
            }
        return None

    def _parse_diskstats(self, measurement):
        """Parse /proc/diskstats and return disk I/O metrics."""
        import re

        if not measurement:
            return None

        total_read_bytes = 0
        total_write_bytes = 0
        total_read_ops = 0
        total_write_ops = 0
        sector_size = 512  # bytes

        for line in measurement.split('\n'):
            parts = line.split()
            if len(parts) >= 10:
                device_name = parts[2]
                # Only count whole devices (sda, nvme0n1, vda, etc.), not partitions
                if re.match(r'^(sd[a-z]|nvme\d+n\d+|vd[a-z]|xvd[a-z])$', device_name):
                    try:
                        read_ops = int(parts[3])
                        sectors_read = int(parts[5])
                        write_ops = int(parts[7])
                        sectors_written = int(parts[9])

                        total_read_ops += read_ops
                        total_read_bytes += sectors_read * sector_size
                        total_write_ops += write_ops
                        total_write_bytes += sectors_written * sector_size
                    except (ValueError, IndexError):
                        pass

        return {
            'disk_read_bytes': total_read_bytes,
            'disk_write_bytes': total_write_bytes,
            'disk_read_ops': total_read_ops,
            'disk_write_ops': total_write_ops,
        }

    def _parse_netdev(self, measurement):
        """Parse /proc/net/dev and return network metrics."""
        if not measurement:
            return None

        total_rx_bytes = 0
        total_tx_bytes = 0
        total_rx_packets = 0
        total_tx_packets = 0

        for line in measurement.split('\n'):
            if ':' not in line or 'Inter-' in line or 'face' in line:
                continue

            parts = line.split(':')
            if len(parts) == 2:
                iface = parts[0].strip()
                if iface == 'lo':
                    continue  # Skip loopback

                values = parts[1].split()
                if len(values) >= 10:
                    try:
                        rx_bytes = int(values[0])
                        rx_packets = int(values[1])
                        tx_bytes = int(values[8])
                        tx_packets = int(values[9])

                        total_rx_bytes += rx_bytes
                        total_rx_packets += rx_packets
                        total_tx_bytes += tx_bytes
                        total_tx_packets += tx_packets
                    except (ValueError, IndexError):
                        pass

        return {
            'net_rx_bytes': total_rx_bytes,
            'net_tx_bytes': total_tx_bytes,
            'net_rx_packets': total_rx_packets,
            'net_tx_packets': total_tx_packets,
        }


# =============================================================================
# Collected Data Views
# =============================================================================

class CollectedDataListView(generics.ListCreateAPIView):
    """
    List collected data for a specific collector.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CollectedDataSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        collector_id = self.kwargs['collector_id']
        return CollectedData.objects.filter(
            collector__owner=self.request.user,
            collector_id=collector_id
        )

    def perform_create(self, serializer):
        collector_id = self.kwargs['collector_id']
        collector = Collector.objects.get(
            pk=collector_id,
            owner=self.request.user
        )
        serializer.save(collector=collector)


class CollectedDataDetailView(generics.RetrieveDestroyAPIView):
    """
    Retrieve or delete collected data.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CollectedDataSerializer

    def get_queryset(self):
        return CollectedData.objects.filter(collector__owner=self.request.user)


# =============================================================================
# Benchmark Views
# =============================================================================

class BenchmarkListCreateView(generics.ListCreateAPIView):
    """
    List benchmarks or create a new one.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BenchmarkCreateSerializer
        return BenchmarkSerializer

    def get_queryset(self):
        queryset = Benchmark.objects.filter(owner=self.request.user)

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by collector
        collector_id = self.request.query_params.get('collector_id')
        if collector_id:
            queryset = queryset.filter(collector_id=collector_id)

        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class BenchmarkDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a benchmark.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = BenchmarkSerializer

    def get_queryset(self):
        return Benchmark.objects.filter(owner=self.request.user)


class BenchmarkStatsView(APIView):
    """
    Get benchmark statistics for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        benchmarks = Benchmark.objects.filter(owner=request.user)

        stats = {
            'total': benchmarks.count(),
            'by_status': {},
            'avg_scores': {},
        }

        # Count by status
        for status_choice in Benchmark.Status.choices:
            count = benchmarks.filter(status=status_choice[0]).count()
            stats['by_status'][status_choice[0]] = count

        # Average scores for completed benchmarks
        completed = benchmarks.filter(status=Benchmark.Status.COMPLETED)
        if completed.exists():
            avg = completed.aggregate(
                cpu=Avg('cpu_score'),
                memory=Avg('memory_score'),
                disk=Avg('disk_score'),
                network=Avg('network_score'),
                overall=Avg('overall_score')
            )
            stats['avg_scores'] = {
                'cpu': round(avg['cpu'] or 0, 1),
                'memory': round(avg['memory'] or 0, 1),
                'disk': round(avg['disk'] or 0, 1),
                'network': round(avg['network'] or 0, 1),
                'overall': round(avg['overall'] or 0, 1),
            }

        return Response(stats)


# =============================================================================
# LoadTest Views
# =============================================================================

class LoadTestResultListCreateView(generics.ListCreateAPIView):
    """
    List or create load test results.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LoadTestResultSerializer

    def get_queryset(self):
        queryset = LoadTestResult.objects.filter(owner=self.request.user)

        # Filter by collector
        collector_id = self.request.query_params.get('collector_id')
        if collector_id:
            queryset = queryset.filter(collector_id=collector_id)

        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class LoadTestResultDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a load test result.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LoadTestResultSerializer

    def get_queryset(self):
        return LoadTestResult.objects.filter(owner=self.request.user)


class LoadTestCompareView(APIView):
    """
    Compare load test results across multiple collectors.

    Supports both GET (query params) and POST (JSON body) for compatibility.
    GET /api/v1/loadtests/compare/?collector_ids=uuid1,uuid2&latest=true
    POST /api/v1/loadtest/compare/ with {"collector_ids": ["uuid1", "uuid2"]}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """GET method - accepts collector_ids as query parameter."""
        collector_ids_param = request.query_params.get('collector_ids', '')
        if not collector_ids_param:
            return Response(
                {'error': 'collector_ids parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Parse comma-separated IDs or JSON array
        if collector_ids_param.startswith('['):
            import json
            collector_ids = json.loads(collector_ids_param)
        else:
            collector_ids = [cid.strip() for cid in collector_ids_param.split(',')]

        return self._compare(request, collector_ids)

    def post(self, request):
        """POST method - accepts collector_ids in JSON body."""
        serializer = LoadTestCompareSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        collector_ids = serializer.validated_data['collector_ids']
        return self._compare(request, collector_ids)

    def _compare(self, request, collector_ids):
        """Common comparison logic for both GET and POST."""
        # Color palette for servers
        colors = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316']

        # Get latest load test for each collector
        servers = []
        for idx, collector_id in enumerate(collector_ids):
            try:
                collector = Collector.objects.get(
                    pk=collector_id,
                    owner=request.user
                )
                latest = LoadTestResult.objects.filter(
                    collector=collector
                ).order_by('-created_at').first()

                if latest:
                    # Format data to match perf-dashboard expected structure
                    data_points = [
                        {'busyPct': pct, 'workUnits': units}
                        for pct, units in latest.get_data_points()
                    ]

                    # Determine provider from vm_brand
                    provider_map = {
                        'aws': 'AWS',
                        'azure': 'Azure',
                        'gcp': 'GCP',
                        'oracle_cloud': 'OCI',
                        'vmware': 'VMware',
                        'bare_metal': 'Bare Metal',
                    }
                    provider = provider_map.get(collector.vm_brand, collector.vm_brand or 'Unknown')

                    # Calculate max work units for price-performance
                    max_units = max([d['workUnits'] for d in data_points], default=0)

                    # Get hourly cost (convert Decimal to float for JSON)
                    hourly_cost = float(collector.hourly_cost) if collector.hourly_cost else None

                    # Calculate price-performance: work units per dollar per hour
                    # Higher is better (more work units for your money)
                    price_performance = None
                    if hourly_cost and hourly_cost > 0 and max_units > 0:
                        price_performance = round(max_units / hourly_cost, 2)

                    servers.append({
                        'serverId': str(collector.id),
                        'serverName': collector.name,
                        'provider': provider,
                        'color': colors[idx % len(colors)],
                        'data': data_points,
                        'hourlyCost': hourly_cost,
                        'maxUnits': max_units,
                        'pricePerformance': price_performance,  # work units per $/hr
                    })
            except Collector.DoesNotExist:
                pass  # Skip non-existent collectors

        # Calculate ratios if we have servers
        ratios = {}
        if len(servers) >= 2:
            # Use first server as baseline
            baseline_max = max([d['workUnits'] for d in servers[0]['data']], default=1)
            for server in servers[1:]:
                server_max = max([d['workUnits'] for d in server['data']], default=0)
                ratios[server['serverId']] = round(server_max / baseline_max, 2) if baseline_max else 0

        return Response({
            'servers': servers,
            'ratios': ratios
        })


class RunLoadTestView(APIView):
    """
    Trigger a load test on a remote collector via pcd daemon.

    The collector must have pcd_address and pcd_apikey configured.
    This endpoint calls the pcd daemon's /v1/loadtest endpoint,
    which runs perfcpumeasure to measure CPU work units at each
    utilization level (10%, 20%, ... 100%).

    POST /api/v1/loadtests/run/<collector_id>/
    Body: { "notes": "optional notes" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, collector_id):
        # Get collector
        try:
            collector = Collector.objects.get(
                pk=collector_id,
                owner=request.user
            )
        except Collector.DoesNotExist:
            return Response(
                {'error': 'Collector not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if pcd connection is configured
        if not collector.pcd_address:
            return Response(
                {'error': 'Collector does not have pcd_address configured'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not collector.pcd_apikey:
            return Response(
                {'error': 'Collector does not have pcd_apikey configured'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Build pcd URL
        pcd_url = f"http://{collector.pcd_address}/v1/loadtest"

        try:
            # Call pcd daemon
            # pcd uses 'apikey' header (not X-API-Key)
            pcd_response = requests.post(
                pcd_url,
                headers={
                    'apikey': collector.pcd_apikey,
                    'Content-Type': 'application/json'
                },
                json={},
                timeout=300  # 5 minutes timeout for load test
            )

            if pcd_response.status_code != 200:
                return Response(
                    {
                        'error': f'pcd daemon returned error: {pcd_response.status_code}',
                        'detail': pcd_response.text
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )

            # Parse pcd response - format from perfcollector2:
            # {
            #     "hostname": "server01",
            #     "timestamp": 1234567890,
            #     "numCores": 4,
            #     "results": [
            #         {"busyPct": 10, "workUnits": 12345},
            #         {"busyPct": 20, "workUnits": 23456},
            #         ...
            #     ],
            #     "maxUnits": 123456,
            #     "avgUnits": 65432,
            #     "unitsPerSec": 1234.56
            # }
            pcd_data = pcd_response.json()

            # Check for error in response
            if pcd_data.get('error'):
                return Response(
                    {'error': f'pcd load test failed: {pcd_data["error"]}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            results = pcd_data.get('results', [])

            # Convert to our model format
            units_data = {}
            for result in results:
                util = result.get('busyPct', 0)
                units = result.get('workUnits', 0)
                field_name = f'units_{util}pct'
                units_data[field_name] = units

            # Create LoadTestResult
            notes = request.data.get('notes', '')
            loadtest = LoadTestResult.objects.create(
                owner=request.user,
                collector=collector,
                notes=notes,
                units_10pct=units_data.get('units_10pct', 0),
                units_20pct=units_data.get('units_20pct', 0),
                units_30pct=units_data.get('units_30pct', 0),
                units_40pct=units_data.get('units_40pct', 0),
                units_50pct=units_data.get('units_50pct', 0),
                units_60pct=units_data.get('units_60pct', 0),
                units_70pct=units_data.get('units_70pct', 0),
                units_80pct=units_data.get('units_80pct', 0),
                units_90pct=units_data.get('units_90pct', 0),
                units_100pct=units_data.get('units_100pct', 0),
            )

            # Return in perf-dashboard format
            serializer = LoadTestResultSerializer(loadtest)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except requests.exceptions.Timeout:
            return Response(
                {'error': 'pcd daemon timed out'},
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )
        except requests.exceptions.ConnectionError:
            return Response(
                {'error': f'Could not connect to pcd daemon at {collector.pcd_address}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            return Response(
                {'error': f'Error communicating with pcd daemon: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# =============================================================================
# PCC Captures View (for perf-dashboard Replay page)
# =============================================================================

class PCCCapturesView(APIView):
    """
    List available PCC captures/collections for replay.
    Returns collected data files in the format expected by perf-dashboard.

    GET /api/v1/pcc/captures
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import json
        import re
        import logging
        logger = logging.getLogger(__name__)

        # Debug: Log the requesting user
        logger.info(f"PCCCapturesView: user={request.user.username} (id={request.user.id})")

        # Get all collected data for this user
        collected_data = CollectedData.objects.filter(
            collector__owner=request.user
        ).select_related('collector')

        logger.info(f"PCCCapturesView: found {collected_data.count()} captures for user {request.user.username}")

        captures = []
        for data in collected_data:
            # Try to parse the collection file for actual metrics
            metrics_summary = self._parse_collection_metrics(data)

            captures.append({
                'id': str(data.id),
                'name': data.description or f"Collection {data.created_at.strftime('%Y-%m-%d %H:%M')}",
                'serverName': data.collector.name,
                'serverId': str(data.collector.id),
                'duration': f"{metrics_summary['sample_count']} samples",
                'capturedAt': data.created_at.isoformat(),
                'metrics': metrics_summary['available_metrics'],
                'sampleCount': metrics_summary['sample_count'],
                'summary': {
                    'avgCpu': metrics_summary['avg_cpu'],
                    'avgMemory': metrics_summary['avg_memory'],
                    'avgDiskIO': metrics_summary['avg_disk_io'],
                },
            })

        return Response({'captures': captures})

    def _parse_collection_metrics(self, data):
        """
        Parse the collection JSON file and calculate summary metrics.
        Returns dict with avg_cpu, avg_memory, avg_disk_io, sample_count, available_metrics.
        """
        import json
        import re

        result = {
            'avg_cpu': 0.0,
            'avg_memory': 0.0,
            'avg_disk_io': 0.0,
            'sample_count': 0,
            'available_metrics': []
        }

        if not data.file:
            return result

        try:
            # Read the collection file (newline-delimited JSON)
            file_path = data.file.path
            samples = []
            subsystems = set()

            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            sample = json.loads(line)
                            samples.append(sample)
                            subsystems.add(sample.get('subsystem', ''))
                        except json.JSONDecodeError:
                            continue

            result['sample_count'] = len(samples)

            # Determine available metrics from subsystems
            metrics_map = {
                '/proc/stat': 'cpu',
                '/proc/meminfo': 'memory',
                '/proc/diskstats': 'disk',
                '/proc/net/dev': 'network',
                '/proc/vmstat': 'vmstat',
            }
            result['available_metrics'] = [
                metrics_map[s] for s in subsystems if s in metrics_map
            ]

            # Parse CPU metrics from /proc/stat
            cpu_usages = []
            prev_cpu = None
            for sample in samples:
                if sample.get('subsystem') == '/proc/stat':
                    cpu_data = self._parse_proc_stat(sample.get('measurement', ''))
                    if cpu_data and prev_cpu:
                        # Calculate CPU usage as delta
                        usage = self._calc_cpu_usage(prev_cpu, cpu_data)
                        if usage is not None:
                            cpu_usages.append(usage)
                    prev_cpu = cpu_data

            if cpu_usages:
                result['avg_cpu'] = round(sum(cpu_usages) / len(cpu_usages), 1)

            # Parse memory metrics from /proc/meminfo
            memory_usages = []
            for sample in samples:
                if sample.get('subsystem') == '/proc/meminfo':
                    mem_usage = self._parse_meminfo(sample.get('measurement', ''))
                    if mem_usage is not None:
                        memory_usages.append(mem_usage)

            if memory_usages:
                result['avg_memory'] = round(sum(memory_usages) / len(memory_usages), 1)

            # Parse disk I/O from /proc/diskstats
            disk_ios = []
            prev_disk = None
            prev_timestamp = None
            for sample in samples:
                if sample.get('subsystem') == '/proc/diskstats':
                    disk_data = self._parse_diskstats(sample.get('measurement', ''))
                    timestamp = sample.get('timestamp', 0)
                    if disk_data and prev_disk and prev_timestamp:
                        # Calculate disk I/O rate (MB/s)
                        time_delta = timestamp - prev_timestamp
                        if time_delta > 0:
                            io_rate = self._calc_disk_io_rate(prev_disk, disk_data, time_delta)
                            if io_rate is not None:
                                disk_ios.append(io_rate)
                    prev_disk = disk_data
                    prev_timestamp = timestamp

            if disk_ios:
                result['avg_disk_io'] = round(sum(disk_ios) / len(disk_ios), 2)

        except Exception as e:
            # Log error but return default values
            import logging
            logging.getLogger(__name__).warning(f"Error parsing collection {data.id}: {e}")

        return result

    def _parse_proc_stat(self, measurement):
        """Parse /proc/stat CPU line and return dict of CPU times."""
        if not measurement:
            return None

        # Find the first cpu line (aggregate)
        for line in measurement.split('\n'):
            if line.startswith('cpu '):
                parts = line.split()
                if len(parts) >= 8:
                    return {
                        'user': int(parts[1]),
                        'nice': int(parts[2]),
                        'system': int(parts[3]),
                        'idle': int(parts[4]),
                        'iowait': int(parts[5]) if len(parts) > 5 else 0,
                        'irq': int(parts[6]) if len(parts) > 6 else 0,
                        'softirq': int(parts[7]) if len(parts) > 7 else 0,
                    }
        return None

    def _calc_cpu_usage(self, prev, curr):
        """Calculate CPU usage percentage from two samples."""
        if not prev or not curr:
            return None

        prev_total = sum(prev.values())
        curr_total = sum(curr.values())

        total_delta = curr_total - prev_total
        if total_delta <= 0:
            return None

        idle_delta = curr['idle'] - prev['idle']
        usage = 100.0 * (1.0 - (idle_delta / total_delta))
        return max(0.0, min(100.0, usage))

    def _parse_meminfo(self, measurement):
        """Parse /proc/meminfo and return memory usage percentage."""
        if not measurement:
            return None

        values = {}
        for line in measurement.split('\n'):
            parts = line.split(':')
            if len(parts) == 2:
                key = parts[0].strip()
                # Extract numeric value (in kB)
                val_parts = parts[1].strip().split()
                if val_parts:
                    try:
                        values[key] = int(val_parts[0])
                    except ValueError:
                        pass

        mem_total = values.get('MemTotal', 0)
        mem_available = values.get('MemAvailable', 0)

        if mem_total > 0:
            mem_used = mem_total - mem_available
            return 100.0 * (mem_used / mem_total)
        return None

    def _parse_diskstats(self, measurement):
        """Parse /proc/diskstats and return total read/write sectors."""
        if not measurement:
            return None

        total_read_sectors = 0
        total_write_sectors = 0

        for line in measurement.split('\n'):
            parts = line.split()
            # /proc/diskstats format: major minor name reads_completed reads_merged
            # sectors_read ms_reading writes_completed writes_merged sectors_written ...
            if len(parts) >= 10:
                device_name = parts[2]
                # Skip partitions (only count whole devices like sda, nvme0n1)
                if device_name.startswith('loop') or device_name.startswith('ram'):
                    continue
                # Skip partitions (sda1, nvme0n1p1, etc.)
                import re
                if re.match(r'^[a-z]+\d+$', device_name) or re.match(r'^nvme\d+n\d+p\d+$', device_name):
                    continue

                try:
                    sectors_read = int(parts[5])
                    sectors_written = int(parts[9])
                    total_read_sectors += sectors_read
                    total_write_sectors += sectors_written
                except (ValueError, IndexError):
                    pass

        return {
            'read_sectors': total_read_sectors,
            'write_sectors': total_write_sectors,
        }

    def _calc_disk_io_rate(self, prev, curr, time_delta):
        """Calculate disk I/O rate in MB/s from two samples."""
        if not prev or not curr or time_delta <= 0:
            return None

        # Sectors are typically 512 bytes
        sector_size = 512

        read_delta = curr['read_sectors'] - prev['read_sectors']
        write_delta = curr['write_sectors'] - prev['write_sectors']

        # Convert to MB/s
        total_bytes = (read_delta + write_delta) * sector_size
        mb_per_sec = total_bytes / (1024 * 1024) / time_delta

        return max(0.0, mb_per_sec)


class PCCCollectionDataView(APIView):
    """
    Get time-series data from a PCC collection for visualization.
    Returns parsed metrics with timestamps suitable for charting.

    GET /api/v1/pcc/captures/<uuid:capture_id>/data
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, capture_id):
        import json

        # Get the collection, ensuring user owns it
        try:
            data = CollectedData.objects.get(
                id=capture_id,
                collector__owner=request.user
            )
        except CollectedData.DoesNotExist:
            return Response(
                {'error': 'Collection not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Parse the collection file and extract time-series data
        time_series = self._parse_time_series(data)

        return Response({
            'id': str(data.id),
            'name': data.description or f"Collection {data.created_at.strftime('%Y-%m-%d %H:%M')}",
            'serverName': data.collector.name,
            'capturedAt': data.created_at.isoformat(),
            'timeSeries': time_series,
        })

    def _parse_time_series(self, data):
        """Parse the collection JSON file and extract time-series data."""
        import json
        from datetime import datetime

        result = {
            'timestamps': [],
            'cpu': [],
            'memory': [],
            'diskRead': [],
            'diskWrite': [],
            'networkRx': [],
            'networkTx': [],
        }

        if not data.file:
            return result

        try:
            file_path = data.file.path
            samples = []

            # Read the JSON file (newline-delimited JSON format)
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            sample = json.loads(line)
                            samples.append(sample)
                        except json.JSONDecodeError:
                            continue

            # Group samples by timestamp
            timestamp_data = {}
            for sample in samples:
                ts = sample.get('timestamp', 0)
                subsystem = sample.get('subsystem', '')
                measurement = sample.get('measurement', '')

                if ts not in timestamp_data:
                    timestamp_data[ts] = {}

                timestamp_data[ts][subsystem] = measurement

            # Sort by timestamp and process
            sorted_timestamps = sorted(timestamp_data.keys())

            prev_cpu = None
            prev_disk = None
            prev_net = None
            prev_ts = None

            for ts in sorted_timestamps:
                data_at_ts = timestamp_data[ts]

                # Convert timestamp to ISO format for frontend
                iso_ts = datetime.fromtimestamp(ts).isoformat()

                # CPU data
                cpu_data = None
                if '/proc/stat' in data_at_ts:
                    cpu_data = self._parse_proc_stat(data_at_ts['/proc/stat'])
                    if cpu_data and prev_cpu:
                        cpu_usage = self._calc_cpu_usage(prev_cpu, cpu_data)
                        if cpu_usage is not None:
                            result['timestamps'].append(iso_ts)
                            result['cpu'].append(round(cpu_usage, 2))

                            # Memory data
                            if '/proc/meminfo' in data_at_ts:
                                mem_usage = self._parse_meminfo(data_at_ts['/proc/meminfo'])
                                result['memory'].append(round(mem_usage, 2) if mem_usage else 0)
                            else:
                                result['memory'].append(0)

                            # Disk data
                            disk_data = None
                            if '/proc/diskstats' in data_at_ts:
                                disk_data = self._parse_diskstats(data_at_ts['/proc/diskstats'])
                                if disk_data and prev_disk and prev_ts:
                                    time_delta = ts - prev_ts
                                    if time_delta > 0:
                                        read_rate, write_rate = self._calc_disk_rates(prev_disk, disk_data, time_delta)
                                        result['diskRead'].append(round(read_rate, 2))
                                        result['diskWrite'].append(round(write_rate, 2))
                                    else:
                                        result['diskRead'].append(0)
                                        result['diskWrite'].append(0)
                                else:
                                    result['diskRead'].append(0)
                                    result['diskWrite'].append(0)
                            else:
                                result['diskRead'].append(0)
                                result['diskWrite'].append(0)

                            # Network data
                            net_data = None
                            if '/proc/net/dev' in data_at_ts:
                                net_data = self._parse_netdev(data_at_ts['/proc/net/dev'])
                                if net_data and prev_net and prev_ts:
                                    time_delta = ts - prev_ts
                                    if time_delta > 0:
                                        rx_rate, tx_rate = self._calc_net_rates(prev_net, net_data, time_delta)
                                        result['networkRx'].append(round(rx_rate, 2))
                                        result['networkTx'].append(round(tx_rate, 2))
                                    else:
                                        result['networkRx'].append(0)
                                        result['networkTx'].append(0)
                                else:
                                    result['networkRx'].append(0)
                                    result['networkTx'].append(0)
                            else:
                                result['networkRx'].append(0)
                                result['networkTx'].append(0)

                    prev_cpu = cpu_data

                # Update previous values for rate calculations
                if '/proc/diskstats' in data_at_ts:
                    prev_disk = self._parse_diskstats(data_at_ts['/proc/diskstats'])
                if '/proc/net/dev' in data_at_ts:
                    prev_net = self._parse_netdev(data_at_ts['/proc/net/dev'])
                prev_ts = ts

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error parsing time-series for {data.id}: {e}")

        return result

    def _parse_proc_stat(self, measurement):
        """Parse /proc/stat CPU line and return dict of CPU times."""
        if not measurement:
            return None

        for line in measurement.split('\n'):
            if line.startswith('cpu '):
                parts = line.split()
                if len(parts) >= 8:
                    return {
                        'user': int(parts[1]),
                        'nice': int(parts[2]),
                        'system': int(parts[3]),
                        'idle': int(parts[4]),
                        'iowait': int(parts[5]) if len(parts) > 5 else 0,
                        'irq': int(parts[6]) if len(parts) > 6 else 0,
                        'softirq': int(parts[7]) if len(parts) > 7 else 0,
                    }
        return None

    def _calc_cpu_usage(self, prev, curr):
        """Calculate CPU usage percentage from two samples."""
        if not prev or not curr:
            return None

        prev_total = sum(prev.values())
        curr_total = sum(curr.values())

        total_delta = curr_total - prev_total
        if total_delta <= 0:
            return None

        idle_delta = curr['idle'] - prev['idle']
        usage = 100.0 * (1.0 - (idle_delta / total_delta))
        return max(0.0, min(100.0, usage))

    def _parse_meminfo(self, measurement):
        """Parse /proc/meminfo and return memory usage percentage."""
        if not measurement:
            return None

        values = {}
        for line in measurement.split('\n'):
            parts = line.split(':')
            if len(parts) == 2:
                key = parts[0].strip()
                val_parts = parts[1].strip().split()
                if val_parts:
                    try:
                        values[key] = int(val_parts[0])
                    except ValueError:
                        pass

        mem_total = values.get('MemTotal', 0)
        mem_available = values.get('MemAvailable', 0)

        if mem_total > 0:
            mem_used = mem_total - mem_available
            return 100.0 * (mem_used / mem_total)
        return None

    def _parse_diskstats(self, measurement):
        """Parse /proc/diskstats and return total read/write sectors."""
        if not measurement:
            return None

        total_read_sectors = 0
        total_write_sectors = 0

        for line in measurement.split('\n'):
            parts = line.split()
            if len(parts) >= 10:
                device_name = parts[2]
                # Skip partitions
                import re
                if re.match(r'^(sd[a-z]|nvme\d+n\d+|vd[a-z]|xvd[a-z])$', device_name):
                    try:
                        sectors_read = int(parts[5])
                        sectors_written = int(parts[9])
                        total_read_sectors += sectors_read
                        total_write_sectors += sectors_written
                    except (ValueError, IndexError):
                        pass

        return {
            'read_sectors': total_read_sectors,
            'write_sectors': total_write_sectors,
        }

    def _calc_disk_rates(self, prev, curr, time_delta):
        """Calculate disk read/write rates in MB/s from two samples."""
        if not prev or not curr or time_delta <= 0:
            return 0, 0

        sector_size = 512  # bytes

        read_delta = curr['read_sectors'] - prev['read_sectors']
        write_delta = curr['write_sectors'] - prev['write_sectors']

        read_mb_per_sec = (read_delta * sector_size) / (1024 * 1024) / time_delta
        write_mb_per_sec = (write_delta * sector_size) / (1024 * 1024) / time_delta

        return max(0.0, read_mb_per_sec), max(0.0, write_mb_per_sec)

    def _parse_netdev(self, measurement):
        """Parse /proc/net/dev and return total RX/TX bytes."""
        if not measurement:
            return None

        total_rx_bytes = 0
        total_tx_bytes = 0

        for line in measurement.split('\n'):
            # Skip header lines
            if ':' not in line or 'Inter-' in line or 'face' in line:
                continue

            parts = line.split(':')
            if len(parts) == 2:
                iface = parts[0].strip()
                # Skip loopback
                if iface == 'lo':
                    continue

                values = parts[1].split()
                if len(values) >= 9:
                    try:
                        rx_bytes = int(values[0])
                        tx_bytes = int(values[8])
                        total_rx_bytes += rx_bytes
                        total_tx_bytes += tx_bytes
                    except (ValueError, IndexError):
                        pass

        return {
            'rx_bytes': total_rx_bytes,
            'tx_bytes': total_tx_bytes,
        }

    def _calc_net_rates(self, prev, curr, time_delta):
        """Calculate network RX/TX rates in Mbps from two samples."""
        if not prev or not curr or time_delta <= 0:
            return 0, 0

        rx_delta = curr['rx_bytes'] - prev['rx_bytes']
        tx_delta = curr['tx_bytes'] - prev['tx_bytes']

        # Convert bytes/s to Mbps (megabits per second)
        rx_mbps = (rx_delta * 8) / (1000 * 1000) / time_delta
        tx_mbps = (tx_delta * 8) / (1000 * 1000) / time_delta

        return max(0.0, rx_mbps), max(0.0, tx_mbps)


# =============================================================================
# Benchmark Comparison Views (for perf-dashboard Compare page)
# =============================================================================

# In-memory storage for active comparisons (in production, use Redis or database)
_active_comparisons = {}


class BenchmarkCompareStartView(APIView):
    """
    Start a benchmark comparison across multiple servers.
    This runs the perfcpumeasure load test on each server and collects results.

    POST /api/v1/pcc/benchmark/compare
    Body: {
        "servers": [
            {"server_id": "uuid1", "name": "Server 1", "server_info": {...}},
            {"server_id": "uuid2", "name": "Server 2", "server_info": {...}}
        ],
        "benchmark_id": "perfcollector-loadtest",
        "duration": "300s"
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import uuid
        import threading

        servers = request.data.get('servers', [])
        benchmark_id = request.data.get('benchmark_id', 'perfcollector-loadtest')
        duration = request.data.get('duration', '300s')

        if not servers:
            return Response(
                {'error': 'No servers provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate a comparison ID
        comparison_id = str(uuid.uuid4())

        # Initialize comparison state
        _active_comparisons[comparison_id] = {
            'comparison_id': comparison_id,
            'benchmark_id': benchmark_id,
            'duration': duration,
            'status': 'running',
            'progress': 0,
            'phase': 'initializing',
            'started_at': timezone.now().isoformat(),
            'servers': [
                {
                    'server_id': s.get('server_id'),
                    'name': s.get('name', s.get('server_id')),
                    'status': 'pending',
                    'progress': 0
                }
                for s in servers
            ],
            'results': {},
            'error': None
        }

        # Start the comparison in a background thread
        thread = threading.Thread(
            target=self._run_comparison,
            args=(comparison_id, servers, request.user, benchmark_id)
        )
        thread.daemon = True
        thread.start()

        return Response({
            'success': True,
            'comparison_id': comparison_id,
            'message': f'Benchmark comparison started for {len(servers)} servers'
        }, status=status.HTTP_201_CREATED)

    def _run_comparison(self, comparison_id, servers, user, benchmark_id):
        """Run load tests on all servers (in background thread)."""
        import logging
        logger = logging.getLogger(__name__)

        comparison = _active_comparisons.get(comparison_id)
        if not comparison:
            return

        total_servers = len(servers)
        completed = 0

        for i, server_config in enumerate(servers):
            server_id = server_config.get('server_id')

            # Update server status to running
            for s in comparison['servers']:
                if s['server_id'] == server_id:
                    s['status'] = 'running'
                    s['progress'] = 0
                    break

            comparison['phase'] = f'Running benchmark on {server_config.get("name", server_id)}'
            comparison['progress'] = int((completed / total_servers) * 100)

            try:
                # Get the collector
                collector = Collector.objects.get(pk=server_id, owner=user)

                # Check if pcd connection is configured
                if not collector.pcd_address or not collector.pcd_apikey:
                    raise Exception('Collector does not have pcd connection configured')

                # Build pcd URL
                pcd_url = f"http://{collector.pcd_address}/v1/loadtest"

                # Call pcd daemon
                pcd_response = requests.post(
                    pcd_url,
                    headers={
                        'apikey': collector.pcd_apikey,
                        'Content-Type': 'application/json'
                    },
                    json={},
                    timeout=300  # 5 minutes timeout for load test
                )

                if pcd_response.status_code != 200:
                    raise Exception(f'pcd daemon returned error: {pcd_response.status_code}')

                pcd_data = pcd_response.json()

                if pcd_data.get('error'):
                    raise Exception(f'pcd load test failed: {pcd_data["error"]}')

                results = pcd_data.get('results', [])

                # Convert to format expected by frontend
                data_points = [
                    {'busyPct': r.get('busyPct', 0), 'workUnits': r.get('workUnits', 0)}
                    for r in results
                ]

                # Calculate summary metrics
                work_units_list = [r['workUnits'] for r in data_points if r['workUnits']]
                max_units = max(work_units_list) if work_units_list else 0
                avg_units = sum(work_units_list) / len(work_units_list) if work_units_list else 0

                # Create timestamps (10 data points at 30s intervals)
                from datetime import datetime, timedelta
                base_time = datetime.now().replace(second=0, microsecond=0)
                timestamps = [
                    (base_time + timedelta(seconds=i*30)).isoformat()
                    for i in range(len(data_points))
                ]

                # Store results - raw_data format matches BenchmarkComparisonChart expected structure
                comparison['results'][server_id] = {
                    'success': True,
                    'metrics_collected': True,
                    'metrics': {
                        'avgCpu': sum(r['busyPct'] for r in data_points) / len(data_points) if data_points else 0,
                        'avgMemory': 0.0,
                        'avgDiskIO': 0.0,
                        'maxCpu': max(r['busyPct'] for r in data_points) if data_points else 0,
                        'maxMemory': 0.0,
                        'maxDiskIO': 0.0,
                    },
                    'samples': len(data_points),
                    'raw_data': {
                        # Format expected by BenchmarkComparisonChart (CollectionData type)
                        'timestamps': timestamps,
                        'cpu': {
                            'user': [r['busyPct'] * 0.7 for r in data_points],  # 70% user
                            'system': [r['busyPct'] * 0.3 for r in data_points],  # 30% system
                            'idle': [100 - r['busyPct'] for r in data_points],
                            'iowait': [0.0] * len(data_points),
                        },
                        'memory': {
                            'total': [16384] * len(data_points),  # 16GB placeholder
                            'used': [8192] * len(data_points),  # 8GB placeholder
                            'available': [8192] * len(data_points),
                            'cached': [2048] * len(data_points),
                            'buffers': [512] * len(data_points),
                        },
                        'disk': {
                            'read_bytes': [0] * len(data_points),
                            'write_bytes': [0] * len(data_points),
                            'read_ops': [0] * len(data_points),
                            'write_ops': [0] * len(data_points),
                        },
                        'network': {
                            'rx_bytes': [0] * len(data_points),
                            'tx_bytes': [0] * len(data_points),
                            'rx_packets': [0] * len(data_points),
                            'tx_packets': [0] * len(data_points),
                        },
                        # Additional load test specific data
                        'loadTestData': data_points,
                        'maxUnits': max_units,
                        'avgUnits': avg_units,
                    }
                }

                # Update server status
                for s in comparison['servers']:
                    if s['server_id'] == server_id:
                        s['status'] = 'completed'
                        s['progress'] = 100
                        break

                # Save load test result to database
                LoadTestResult.objects.create(
                    owner=user,
                    collector=collector,
                    notes=f'Benchmark comparison: {comparison_id}',
                    units_10pct=next((r['workUnits'] for r in results if r.get('busyPct') == 10), 0),
                    units_20pct=next((r['workUnits'] for r in results if r.get('busyPct') == 20), 0),
                    units_30pct=next((r['workUnits'] for r in results if r.get('busyPct') == 30), 0),
                    units_40pct=next((r['workUnits'] for r in results if r.get('busyPct') == 40), 0),
                    units_50pct=next((r['workUnits'] for r in results if r.get('busyPct') == 50), 0),
                    units_60pct=next((r['workUnits'] for r in results if r.get('busyPct') == 60), 0),
                    units_70pct=next((r['workUnits'] for r in results if r.get('busyPct') == 70), 0),
                    units_80pct=next((r['workUnits'] for r in results if r.get('busyPct') == 80), 0),
                    units_90pct=next((r['workUnits'] for r in results if r.get('busyPct') == 90), 0),
                    units_100pct=next((r['workUnits'] for r in results if r.get('busyPct') == 100), 0),
                )

            except Collector.DoesNotExist:
                comparison['results'][server_id] = {
                    'success': False,
                    'metrics_collected': False,
                    'error': 'Collector not found',
                    'metrics': {},
                    'samples': 0
                }
                for s in comparison['servers']:
                    if s['server_id'] == server_id:
                        s['status'] = 'failed'
                        break
            except requests.exceptions.Timeout:
                comparison['results'][server_id] = {
                    'success': False,
                    'metrics_collected': False,
                    'error': 'pcd daemon timed out',
                    'metrics': {},
                    'samples': 0
                }
                for s in comparison['servers']:
                    if s['server_id'] == server_id:
                        s['status'] = 'failed'
                        break
            except requests.exceptions.ConnectionError as e:
                comparison['results'][server_id] = {
                    'success': False,
                    'metrics_collected': False,
                    'error': f'Could not connect to pcd daemon',
                    'metrics': {},
                    'samples': 0
                }
                for s in comparison['servers']:
                    if s['server_id'] == server_id:
                        s['status'] = 'failed'
                        break
            except Exception as e:
                logger.error(f"Error running benchmark on {server_id}: {e}")
                comparison['results'][server_id] = {
                    'success': False,
                    'metrics_collected': False,
                    'error': str(e),
                    'metrics': {},
                    'samples': 0
                }
                for s in comparison['servers']:
                    if s['server_id'] == server_id:
                        s['status'] = 'failed'
                        break

            completed += 1
            comparison['progress'] = int((completed / total_servers) * 100)

        # Mark comparison as completed
        comparison['status'] = 'completed'
        comparison['completed_at'] = timezone.now().isoformat()
        comparison['phase'] = 'completed'
        comparison['progress'] = 100


@method_decorator(csrf_exempt, name='dispatch')
class TrickleView(APIView):
    """
    Trickle endpoint for pcc clients - matches the pcd /v1/trickle format.
    This allows pcc to send data directly to XATSimplified instead of through pcd.

    POST /v1/trickle
    Headers: apikey: <api_key> OR X-API-Key: <api_key>
    Body: {
        "identifier": "collection-id",
        "measurements": [
            {"timestamp": 1234567890, "subsystem": "/proc/stat", "measurement": "cpu  ..."},
            {"timestamp": 1234567890, "subsystem": "/proc/meminfo", "measurement": "MemTotal: ..."},
            ...
        ]
    }
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def post(self, request):
        from collectors.models import TrickleSession

        collector = getattr(request, 'collector', None)
        if not collector:
            return Response(
                {'error': 'Invalid API key'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Update last seen
        collector.last_seen = timezone.now()
        collector.status = Collector.Status.CONNECTED
        collector.save(update_fields=['last_seen', 'status'])

        # Parse TrickleRequest format from pcc
        identifier = request.data.get('identifier', '')
        measurements = request.data.get('measurements', [])

        if not measurements:
            return Response({
                'status': 'ok',
                'message': 'No measurements to process'
            })

        # Get or create active trickle session
        session, created = TrickleSession.objects.get_or_create(
            collector=collector,
            status=TrickleSession.Status.ACTIVE,
            defaults={
                'name': f"Trickle {identifier or timezone.now().strftime('%Y-%m-%d %H:%M')}"
            }
        )

        # Process the measurements using the same logic as MetricsUploadView
        metrics_count = self._process_trickle_measurements(collector, measurements)

        # Update session stats
        session.last_data_at = timezone.now()
        session.sample_count = (session.sample_count or 0) + metrics_count
        session.save(update_fields=['last_data_at', 'sample_count'])

        return Response({
            'status': 'ok',
            'identifier': identifier,
            'metrics_count': metrics_count,
            'session_id': str(session.id)
        })

    def _process_trickle_measurements(self, collector, measurements):
        """
        Process measurements from pcc trickle format.
        Measurements are: [{timestamp, subsystem, measurement}, ...]
        """
        from datetime import datetime

        if not isinstance(measurements, list):
            measurements = [measurements]

        processed_count = 0

        # Group measurements by timestamp
        grouped = {}
        for m in measurements:
            ts = m.get('timestamp', 0)
            if ts not in grouped:
                grouped[ts] = {}
            subsystem = m.get('subsystem', '')
            grouped[ts][subsystem] = m.get('measurement', '')

        # Process each timestamp group
        for ts, subsystems in grouped.items():
            try:
                metric_data = {
                    'collector': collector,
                    'timestamp': datetime.fromtimestamp(ts, tz=timezone.utc) if ts else timezone.now(),
                }

                # Parse /proc/stat for CPU metrics
                if '/proc/stat' in subsystems:
                    cpu_data = self._parse_proc_stat(subsystems['/proc/stat'])
                    if cpu_data:
                        metric_data.update(cpu_data)

                # Parse /proc/meminfo for memory metrics
                if '/proc/meminfo' in subsystems:
                    mem_data = self._parse_meminfo(subsystems['/proc/meminfo'])
                    if mem_data:
                        metric_data.update(mem_data)

                # Parse /proc/diskstats for disk metrics
                if '/proc/diskstats' in subsystems:
                    disk_data = self._parse_diskstats(subsystems['/proc/diskstats'])
                    if disk_data:
                        metric_data.update(disk_data)

                # Parse /proc/net/dev for network metrics
                if '/proc/net/dev' in subsystems:
                    net_data = self._parse_netdev(subsystems['/proc/net/dev'])
                    if net_data:
                        metric_data.update(net_data)

                # Create or update the metric record
                PerformanceMetric.objects.update_or_create(
                    collector=collector,
                    timestamp=metric_data['timestamp'],
                    defaults={k: v for k, v in metric_data.items() if k not in ['collector', 'timestamp']}
                )
                processed_count += 1

            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error processing trickle measurement: {e}")
                continue

        return processed_count

    def _parse_proc_stat(self, measurement):
        """Parse /proc/stat and return CPU metrics."""
        if not measurement:
            return None

        for line in measurement.split('\n'):
            if line.startswith('cpu '):
                parts = line.split()
                if len(parts) >= 8:
                    user = int(parts[1])
                    nice = int(parts[2])
                    system = int(parts[3])
                    idle = int(parts[4])
                    iowait = int(parts[5]) if len(parts) > 5 else 0
                    irq = int(parts[6]) if len(parts) > 6 else 0
                    softirq = int(parts[7]) if len(parts) > 7 else 0
                    steal = int(parts[8]) if len(parts) > 8 else 0

                    total = user + nice + system + idle + iowait + irq + softirq + steal
                    if total > 0:
                        return {
                            'cpu_user': round(100.0 * (user + nice) / total, 2),
                            'cpu_system': round(100.0 * system / total, 2),
                            'cpu_iowait': round(100.0 * iowait / total, 2),
                            'cpu_idle': round(100.0 * idle / total, 2),
                            'cpu_steal': round(100.0 * steal / total, 2),
                        }
        return None

    def _parse_meminfo(self, measurement):
        """Parse /proc/meminfo and return memory metrics in MB."""
        if not measurement:
            return None

        values = {}
        for line in measurement.split('\n'):
            parts = line.split(':')
            if len(parts) == 2:
                key = parts[0].strip()
                val_parts = parts[1].strip().split()
                if val_parts:
                    try:
                        values[key] = int(val_parts[0])  # in kB
                    except ValueError:
                        pass

        mem_total = values.get('MemTotal', 0)
        mem_free = values.get('MemFree', 0)
        mem_available = values.get('MemAvailable', 0)
        buffers = values.get('Buffers', 0)
        cached = values.get('Cached', 0)

        if mem_total > 0:
            mem_used = mem_total - mem_available
            return {
                'mem_total': round(mem_total / 1024, 2),  # MB
                'mem_used': round(mem_used / 1024, 2),  # MB
                'mem_available': round(mem_available / 1024, 2),  # MB
                'mem_buffers': round(buffers / 1024, 2),  # MB
                'mem_cached': round(cached / 1024, 2),  # MB
            }
        return None

    def _parse_diskstats(self, measurement):
        """Parse /proc/diskstats and return disk I/O metrics."""
        import re

        if not measurement:
            return None

        total_read_bytes = 0
        total_write_bytes = 0
        total_read_ops = 0
        total_write_ops = 0
        sector_size = 512  # bytes

        for line in measurement.split('\n'):
            parts = line.split()
            if len(parts) >= 10:
                device_name = parts[2]
                # Only count whole devices (sda, nvme0n1, vda, etc.), not partitions
                if re.match(r'^(sd[a-z]|nvme\d+n\d+|vd[a-z]|xvd[a-z])$', device_name):
                    try:
                        read_ops = int(parts[3])
                        sectors_read = int(parts[5])
                        write_ops = int(parts[7])
                        sectors_written = int(parts[9])

                        total_read_ops += read_ops
                        total_read_bytes += sectors_read * sector_size
                        total_write_ops += write_ops
                        total_write_bytes += sectors_written * sector_size
                    except (ValueError, IndexError):
                        pass

        return {
            'disk_read_bytes': total_read_bytes,
            'disk_write_bytes': total_write_bytes,
            'disk_read_ops': total_read_ops,
            'disk_write_ops': total_write_ops,
        }

    def _parse_netdev(self, measurement):
        """Parse /proc/net/dev and return network metrics."""
        if not measurement:
            return None

        total_rx_bytes = 0
        total_tx_bytes = 0
        total_rx_packets = 0
        total_tx_packets = 0

        for line in measurement.split('\n'):
            if ':' not in line or 'Inter-' in line or 'face' in line:
                continue

            parts = line.split(':')
            if len(parts) == 2:
                iface = parts[0].strip()
                if iface == 'lo':
                    continue  # Skip loopback

                values = parts[1].split()
                if len(values) >= 10:
                    try:
                        rx_bytes = int(values[0])
                        rx_packets = int(values[1])
                        tx_bytes = int(values[8])
                        tx_packets = int(values[9])

                        total_rx_bytes += rx_bytes
                        total_rx_packets += rx_packets
                        total_tx_bytes += tx_bytes
                        total_tx_packets += tx_packets
                    except (ValueError, IndexError):
                        pass

        return {
            'net_rx_bytes': total_rx_bytes,
            'net_tx_bytes': total_tx_bytes,
            'net_rx_packets': total_rx_packets,
            'net_tx_packets': total_tx_packets,
        }


class BenchmarkCompareStatusView(APIView):
    """
    Get the status of a benchmark comparison.

    GET /api/v1/pcc/benchmark/compare/<comparison_id>
    Query params:
        include_raw_data=true  - Include full time-series data in results
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, comparison_id):
        include_raw_data = request.query_params.get('include_raw_data', 'false').lower() == 'true'

        comparison = _active_comparisons.get(str(comparison_id))
        if not comparison:
            return Response(
                {
                    'success': False,
                    'error': 'Comparison not found or expired'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        response_data = {
            'success': True,
            'comparison_id': comparison['comparison_id'],
            'type': 'benchmark',
            'benchmark_id': comparison['benchmark_id'],
            'duration': comparison['duration'],
            'status': comparison['status'],
            'progress': comparison['progress'],
            'phase': comparison['phase'],
            'servers': comparison['servers'],
            'started_at': comparison['started_at'],
        }

        if comparison.get('completed_at'):
            response_data['completed_at'] = comparison['completed_at']

        if comparison.get('error'):
            response_data['error'] = comparison['error']

        # Include results if completed
        if comparison['status'] in ('completed', 'failed') and comparison.get('results'):
            if include_raw_data:
                response_data['results'] = comparison['results']
            else:
                # Return results without raw_data for lightweight polling
                response_data['results'] = {
                    server_id: {
                        'success': result.get('success'),
                        'metrics_collected': result.get('metrics_collected'),
                        'metrics': result.get('metrics'),
                        'samples': result.get('samples'),
                        'error': result.get('error'),
                    }
                    for server_id, result in comparison['results'].items()
                }

        return Response(response_data)
