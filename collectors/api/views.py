"""
API views for collectors.
"""
import requests
from django.utils import timezone
from django.db.models import Avg, Max, Min, Count
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from collectors.models import Collector, CollectedData, Benchmark, LoadTestResult
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
            # TODO: Process and store metrics
            return Response({
                'status': 'received',
                'metrics_count': len(metrics) if isinstance(metrics, list) else 1
            })

        return Response(
            {'error': 'No file or metrics provided'},
            status=status.HTTP_400_BAD_REQUEST
        )


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
