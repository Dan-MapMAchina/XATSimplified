"""
API views for collectors.
"""
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
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LoadTestCompareSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        collector_ids = serializer.validated_data['collector_ids']

        # Get latest load test for each collector
        results = []
        for collector_id in collector_ids:
            try:
                collector = Collector.objects.get(
                    pk=collector_id,
                    owner=request.user
                )
                latest = LoadTestResult.objects.filter(
                    collector=collector
                ).order_by('-created_at').first()

                if latest:
                    results.append({
                        'collector_id': str(collector.id),
                        'collector_name': collector.name,
                        'specs': collector.specs_summary,
                        'data_points': [
                            {'utilization': pct, 'work_units': units}
                            for pct, units in latest.get_data_points()
                        ],
                        'max_units': latest.max_units,
                        'avg_units': latest.avg_units,
                        'created_at': latest.created_at
                    })
                else:
                    results.append({
                        'collector_id': str(collector.id),
                        'collector_name': collector.name,
                        'specs': collector.specs_summary,
                        'error': 'No load test results'
                    })
            except Collector.DoesNotExist:
                results.append({
                    'collector_id': str(collector_id),
                    'error': 'Collector not found'
                })

        return Response({
            'comparison': results,
            'count': len([r for r in results if 'error' not in r])
        })
