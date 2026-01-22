"""
Dashboard API views for performance metrics.
Parses real /proc data from CollectedData JSON files.
"""
import json
import re
from datetime import datetime, timedelta
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from collectors.models import Collector, CollectedData, PerformanceMetric


class ProcDataParser:
    """Parse /proc filesystem data from JSON measurements."""
    
    @staticmethod
    def parse_cpu_stat(measurement: str) -> dict:
        """Parse /proc/stat CPU line into percentages."""
        lines = measurement.strip().split('\n')
        for line in lines:
            if line.startswith('cpu '):
                parts = line.split()
                # cpu user nice system idle iowait irq softirq steal guest guest_nice
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                iowait = int(parts[5]) if len(parts) > 5 else 0
                irq = int(parts[6]) if len(parts) > 6 else 0
                softirq = int(parts[7]) if len(parts) > 7 else 0
                steal = int(parts[8]) if len(parts) > 8 else 0
                
                total = user + nice + system + idle + iowait + irq + softirq + steal
                if total == 0:
                    return {'user': 0, 'system': 0, 'iowait': 0, 'idle': 100, 'steal': 0}
                
                return {
                    'user': round((user + nice) / total * 100, 2),
                    'system': round((system + irq + softirq) / total * 100, 2),
                    'iowait': round(iowait / total * 100, 2),
                    'idle': round(idle / total * 100, 2),
                    'steal': round(steal / total * 100, 2),
                    'total_jiffies': total
                }
        return None
    
    @staticmethod
    def parse_meminfo(measurement: str) -> dict:
        """Parse /proc/meminfo into memory stats."""
        mem = {}
        for line in measurement.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                # Extract numeric value (in kB)
                match = re.search(r'(\d+)', value)
                if match:
                    mem[key.strip()] = int(match.group(1))
        
        total = mem.get('MemTotal', 0)
        free = mem.get('MemFree', 0)
        available = mem.get('MemAvailable', 0)
        buffers = mem.get('Buffers', 0)
        cached = mem.get('Cached', 0)
        
        used = total - available if available else total - free - buffers - cached
        
        return {
            'total_mb': round(total / 1024, 2),
            'used_mb': round(used / 1024, 2),
            'available_mb': round(available / 1024 if available else (free + buffers + cached) / 1024, 2),
            'buffers_mb': round(buffers / 1024, 2),
            'cached_mb': round(cached / 1024, 2),
            'used_percent': round(used / total * 100, 2) if total else 0
        }
    
    @staticmethod
    def parse_diskstats(measurement: str) -> dict:
        """Parse /proc/diskstats for disk I/O."""
        disks = {}
        for line in measurement.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 14:
                device = parts[2]
                # Skip partitions (only get main devices like sda, nvme0n1)
                if re.match(r'^(sd[a-z]|nvme\d+n\d+|vd[a-z])$', device):
                    disks[device] = {
                        'read_ops': int(parts[3]),
                        'read_sectors': int(parts[5]),
                        'write_ops': int(parts[7]),
                        'write_sectors': int(parts[9]),
                        # Sectors are typically 512 bytes
                        'read_bytes': int(parts[5]) * 512,
                        'write_bytes': int(parts[9]) * 512,
                    }
        return disks
    
    @staticmethod
    def parse_netdev(measurement: str) -> dict:
        """Parse /proc/net/dev for network stats."""
        interfaces = {}
        for line in measurement.strip().split('\n'):
            if ':' in line and not line.strip().startswith('Inter') and not line.strip().startswith('face'):
                parts = line.split(':')
                iface = parts[0].strip()
                if iface == 'lo':
                    continue  # Skip loopback
                
                stats = parts[1].split()
                if len(stats) >= 16:
                    interfaces[iface] = {
                        'rx_bytes': int(stats[0]),
                        'rx_packets': int(stats[1]),
                        'rx_errors': int(stats[2]),
                        'tx_bytes': int(stats[8]),
                        'tx_packets': int(stats[9]),
                        'tx_errors': int(stats[10]),
                    }
        return interfaces


class BaseDashboardMetricsAPI(APIView):
    """Base class for dashboard metrics endpoints."""
    permission_classes = [IsAuthenticated]
    
    def get_collector(self, collector_id):
        try:
            return Collector.objects.get(id=collector_id)
        except Collector.DoesNotExist:
            return None
    
    def get_time_range(self):
        hours = int(self.request.query_params.get('hours', 24))
        end_time = timezone.now()
        start_time = end_time - timedelta(hours=hours)
        return start_time, end_time, hours
    
    def load_collected_data(self, collector):
        """Load and parse all collected data for a collector."""
        collected = CollectedData.objects.filter(collector=collector).order_by('-created_at').first()
        if not collected or not collected.file:
            return []
        
        try:
            collected.file.seek(0)
            content = collected.file.read().decode('utf-8')
            lines = content.strip().split('\n')
            
            data_points = []
            for line in lines:
                if line.strip():
                    data_points.append(json.loads(line))
            return data_points
        except Exception as e:
            print(f"Error loading collected data: {e}")
            return []


class CollectorListAPI(BaseDashboardMetricsAPI):
    """List collectors for the authenticated user."""
    
    def get(self, request):
        collectors = Collector.objects.filter(owner=request.user)
        return Response([{
            'id': str(c.id),
            'name': c.name,
            'description': getattr(c, 'description', ''),
        } for c in collectors])


class CollectorCPUDataAPI(BaseDashboardMetricsAPI):
    """Get CPU metrics for a collector."""
    
    def get(self, request, collector_id):
        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)
        
        data_points = self.load_collected_data(collector)
        if not data_points:
            return Response({'error': 'No data available'}, status=404)
        
        # Extract CPU data
        timestamps = []
        cpu_user = []
        cpu_system = []
        cpu_iowait = []
        cpu_idle = []
        cpu_steal = []
        
        prev_cpu = None
        for dp in data_points:
            if dp.get('subsystem') == '/proc/stat':
                ts = datetime.fromtimestamp(dp['timestamp'], tz=timezone.utc).isoformat()
                cpu = ProcDataParser.parse_cpu_stat(dp['measurement'])
                
                if cpu and prev_cpu:
                    # Calculate delta percentages
                    delta_total = cpu['total_jiffies'] - prev_cpu['total_jiffies']
                    if delta_total > 0:
                        timestamps.append(ts)
                        cpu_user.append(cpu['user'])
                        cpu_system.append(cpu['system'])
                        cpu_iowait.append(cpu['iowait'])
                        cpu_idle.append(cpu['idle'])
                        cpu_steal.append(cpu['steal'])
                
                prev_cpu = cpu
        
        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'timestamps': timestamps,
            'cpu_user': cpu_user,
            'cpu_system': cpu_system,
            'cpu_iowait': cpu_iowait,
            'cpu_idle': cpu_idle,
            'cpu_steal': cpu_steal,
        })


class CollectorMemoryDataAPI(BaseDashboardMetricsAPI):
    """Get memory metrics for a collector."""
    
    def get(self, request, collector_id):
        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)
        
        data_points = self.load_collected_data(collector)
        if not data_points:
            return Response({'error': 'No data available'}, status=404)
        
        timestamps = []
        mem_used_percent = []
        mem_total = []
        mem_used = []
        mem_available = []
        mem_buffers = []
        mem_cached = []
        
        for dp in data_points:
            if dp.get('subsystem') == '/proc/meminfo':
                ts = datetime.fromtimestamp(dp['timestamp'], tz=timezone.utc).isoformat()
                mem = ProcDataParser.parse_meminfo(dp['measurement'])
                
                if mem:
                    timestamps.append(ts)
                    mem_used_percent.append(mem['used_percent'])
                    mem_total.append(mem['total_mb'])
                    mem_used.append(mem['used_mb'])
                    mem_available.append(mem['available_mb'])
                    mem_buffers.append(mem['buffers_mb'])
                    mem_cached.append(mem['cached_mb'])
        
        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'timestamps': timestamps,
            'mem_used_percent': mem_used_percent,
            'mem_total': mem_total,
            'mem_used': mem_used,
            'mem_available': mem_available,
            'mem_buffers': mem_buffers,
            'mem_cached': mem_cached,
        })


class CollectorDiskDataAPI(BaseDashboardMetricsAPI):
    """Get disk I/O metrics for a collector."""
    
    def get(self, request, collector_id):
        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)
        
        data_points = self.load_collected_data(collector)
        if not data_points:
            return Response({'error': 'No data available'}, status=404)
        
        timestamps = []
        disk_read_iops = []
        disk_write_iops = []
        disk_read_mbps = []
        disk_write_mbps = []
        
        prev_disk = None
        prev_ts = None
        
        for dp in data_points:
            if dp.get('subsystem') == '/proc/diskstats':
                ts = dp['timestamp']
                disks = ProcDataParser.parse_diskstats(dp['measurement'])
                
                # Sum all disks
                total_read_ops = sum(d['read_ops'] for d in disks.values())
                total_write_ops = sum(d['write_ops'] for d in disks.values())
                total_read_bytes = sum(d['read_bytes'] for d in disks.values())
                total_write_bytes = sum(d['write_bytes'] for d in disks.values())
                
                if prev_disk and prev_ts:
                    delta_t = ts - prev_ts
                    if delta_t > 0:
                        timestamps.append(datetime.fromtimestamp(ts, tz=timezone.utc).isoformat())
                        disk_read_iops.append(round((total_read_ops - prev_disk['read_ops']) / delta_t, 2))
                        disk_write_iops.append(round((total_write_ops - prev_disk['write_ops']) / delta_t, 2))
                        disk_read_mbps.append(round((total_read_bytes - prev_disk['read_bytes']) / delta_t / 1024 / 1024, 2))
                        disk_write_mbps.append(round((total_write_bytes - prev_disk['write_bytes']) / delta_t / 1024 / 1024, 2))
                
                prev_disk = {
                    'read_ops': total_read_ops,
                    'write_ops': total_write_ops,
                    'read_bytes': total_read_bytes,
                    'write_bytes': total_write_bytes,
                }
                prev_ts = ts
        
        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'timestamps': timestamps,
            'disk_read_iops': disk_read_iops,
            'disk_write_iops': disk_write_iops,
            'disk_read_mbps': disk_read_mbps,
            'disk_write_mbps': disk_write_mbps,
        })


class CollectorNetworkDataAPI(BaseDashboardMetricsAPI):
    """Get network throughput metrics for a collector."""
    
    def get(self, request, collector_id):
        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)
        
        data_points = self.load_collected_data(collector)
        if not data_points:
            return Response({'error': 'No data available'}, status=404)
        
        timestamps = []
        net_rx_mbps = []
        net_tx_mbps = []
        net_rx_pps = []
        net_tx_pps = []
        
        prev_net = None
        prev_ts = None
        
        for dp in data_points:
            if dp.get('subsystem') == '/proc/net/dev':
                ts = dp['timestamp']
                interfaces = ProcDataParser.parse_netdev(dp['measurement'])
                
                # Sum all interfaces (excluding loopback)
                total_rx_bytes = sum(i['rx_bytes'] for i in interfaces.values())
                total_tx_bytes = sum(i['tx_bytes'] for i in interfaces.values())
                total_rx_packets = sum(i['rx_packets'] for i in interfaces.values())
                total_tx_packets = sum(i['tx_packets'] for i in interfaces.values())
                
                if prev_net and prev_ts:
                    delta_t = ts - prev_ts
                    if delta_t > 0:
                        timestamps.append(datetime.fromtimestamp(ts, tz=timezone.utc).isoformat())
                        net_rx_mbps.append(round((total_rx_bytes - prev_net['rx_bytes']) / delta_t / 1024 / 1024, 2))
                        net_tx_mbps.append(round((total_tx_bytes - prev_net['tx_bytes']) / delta_t / 1024 / 1024, 2))
                        net_rx_pps.append(round((total_rx_packets - prev_net['rx_packets']) / delta_t, 2))
                        net_tx_pps.append(round((total_tx_packets - prev_net['tx_packets']) / delta_t, 2))
                
                prev_net = {
                    'rx_bytes': total_rx_bytes,
                    'tx_bytes': total_tx_bytes,
                    'rx_packets': total_rx_packets,
                    'tx_packets': total_tx_packets,
                }
                prev_ts = ts
        
        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'timestamps': timestamps,
            'net_rx_mbps': net_rx_mbps,
            'net_tx_mbps': net_tx_mbps,
            'net_rx_pps': net_rx_pps,
            'net_tx_pps': net_tx_pps,
        })


class CollectorLiveMetricsAPI(BaseDashboardMetricsAPI):
    """
    Get live metrics for a collector from trickle mode data.
    This queries the PerformanceMetric model which stores real-time trickle data.

    Query params:
        - minutes: Number of minutes of data to return (default 10)
        - since: ISO timestamp to get data after (alternative to minutes)
    """

    def get(self, request, collector_id):
        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)

        # Determine time range
        minutes = int(request.query_params.get('minutes', 10))
        since_param = request.query_params.get('since')

        if since_param:
            try:
                start_time = datetime.fromisoformat(since_param.replace('Z', '+00:00'))
            except ValueError:
                start_time = timezone.now() - timedelta(minutes=minutes)
        else:
            start_time = timezone.now() - timedelta(minutes=minutes)

        # Query PerformanceMetric for this collector
        metrics = PerformanceMetric.objects.filter(
            collector=collector,
            timestamp__gte=start_time
        ).order_by('timestamp')

        if not metrics.exists():
            return Response({
                'collector_id': str(collector.id),
                'collector_name': collector.name,
                'has_live_data': False,
                'message': 'No live metrics available. Start trickle mode collection.',
                'timestamps': [],
                'cpu': {},
                'memory': {},
                'disk': {},
                'network': {},
            })

        # Build response
        timestamps = []
        cpu_user = []
        cpu_system = []
        cpu_iowait = []
        cpu_idle = []
        cpu_steal = []

        mem_total = []
        mem_used = []
        mem_available = []
        mem_buffers = []
        mem_cached = []

        disk_read_bytes = []
        disk_write_bytes = []
        disk_read_ops = []
        disk_write_ops = []

        net_rx_bytes = []
        net_tx_bytes = []
        net_rx_packets = []
        net_tx_packets = []

        for m in metrics:
            timestamps.append(m.timestamp.isoformat())

            # CPU metrics
            cpu_user.append(m.cpu_user or 0)
            cpu_system.append(m.cpu_system or 0)
            cpu_iowait.append(m.cpu_iowait or 0)
            cpu_idle.append(m.cpu_idle or 0)
            cpu_steal.append(m.cpu_steal or 0)

            # Memory metrics
            mem_total.append(m.mem_total or 0)
            mem_used.append(m.mem_used or 0)
            mem_available.append(m.mem_available or 0)
            mem_buffers.append(m.mem_buffers or 0)
            mem_cached.append(m.mem_cached or 0)

            # Disk metrics (cumulative counters)
            disk_read_bytes.append(m.disk_read_bytes or 0)
            disk_write_bytes.append(m.disk_write_bytes or 0)
            disk_read_ops.append(m.disk_read_ops or 0)
            disk_write_ops.append(m.disk_write_ops or 0)

            # Network metrics (cumulative counters)
            net_rx_bytes.append(m.net_rx_bytes or 0)
            net_tx_bytes.append(m.net_tx_bytes or 0)
            net_rx_packets.append(m.net_rx_packets or 0)
            net_tx_packets.append(m.net_tx_packets or 0)

        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'has_live_data': True,
            'sample_count': len(timestamps),
            'timestamps': timestamps,
            'cpu': {
                'user': cpu_user,
                'system': cpu_system,
                'iowait': cpu_iowait,
                'idle': cpu_idle,
                'steal': cpu_steal,
            },
            'memory': {
                'total_mb': mem_total,
                'used_mb': mem_used,
                'available_mb': mem_available,
                'buffers_mb': mem_buffers,
                'cached_mb': mem_cached,
            },
            'disk': {
                'read_bytes': disk_read_bytes,
                'write_bytes': disk_write_bytes,
                'read_ops': disk_read_ops,
                'write_ops': disk_write_ops,
            },
            'network': {
                'rx_bytes': net_rx_bytes,
                'tx_bytes': net_tx_bytes,
                'rx_packets': net_rx_packets,
                'tx_packets': net_tx_packets,
            },
        })


class TrickleStatusAPI(BaseDashboardMetricsAPI):
    """
    Get trickle mode status for a collector.
    Shows whether live data is being received and last update time.
    """

    def get(self, request, collector_id):
        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)

        # Get the latest metric
        latest_metric = PerformanceMetric.objects.filter(
            collector=collector
        ).order_by('-timestamp').first()

        # Get count of metrics in last 5 minutes
        five_min_ago = timezone.now() - timedelta(minutes=5)
        recent_count = PerformanceMetric.objects.filter(
            collector=collector,
            timestamp__gte=five_min_ago
        ).count()

        # Total metrics count
        total_count = PerformanceMetric.objects.filter(collector=collector).count()

        # Determine status
        is_active = recent_count > 0

        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'trickle_active': is_active,
            'last_data_at': latest_metric.timestamp.isoformat() if latest_metric else None,
            'metrics_last_5min': recent_count,
            'total_metrics': total_count,
            'collector_status': collector.status,
            'collector_last_seen': collector.last_seen.isoformat() if collector.last_seen else None,
        })


class ActiveTrickleSessionsAPI(BaseDashboardMetricsAPI):
    """
    Get all active trickle sessions across all collectors.
    This provides a live view of currently streaming collectors.
    """

    def get(self, request):
        from collectors.models import TrickleSession

        # Get or create active sessions for collectors with recent data
        five_min_ago = timezone.now() - timedelta(minutes=5)

        # Find collectors with recent trickle data
        active_collectors = Collector.objects.filter(
            owner=request.user,
            metrics__timestamp__gte=five_min_ago
        ).distinct()

        active_sessions = []
        for collector in active_collectors:
            # Get or create active session
            session, created = TrickleSession.objects.get_or_create(
                collector=collector,
                status=TrickleSession.Status.ACTIVE,
                defaults={
                    'name': f"Trickle {timezone.now().strftime('%Y-%m-%d %H:%M')}"
                }
            )

            # Update session with latest data info
            latest_metric = PerformanceMetric.objects.filter(
                collector=collector
            ).order_by('-timestamp').first()

            if latest_metric:
                session.last_data_at = latest_metric.timestamp
                session.sample_count = PerformanceMetric.objects.filter(
                    collector=collector,
                    timestamp__gte=session.started_at
                ).count()
                session.save(update_fields=['last_data_at', 'sample_count'])

            # Get recent metrics for live preview
            recent_metrics = PerformanceMetric.objects.filter(
                collector=collector,
                timestamp__gte=five_min_ago
            ).order_by('-timestamp')[:10]

            avg_cpu = 0
            avg_mem = 0
            if recent_metrics:
                cpu_values = [100 - (m.cpu_idle or 0) for m in recent_metrics if m.cpu_idle is not None]
                mem_values = [m.mem_used or 0 for m in recent_metrics if m.mem_used is not None]
                if cpu_values:
                    avg_cpu = round(sum(cpu_values) / len(cpu_values), 1)
                if mem_values and recent_metrics[0].mem_total:
                    avg_mem = round((sum(mem_values) / len(mem_values)) / recent_metrics[0].mem_total * 100, 1)

            active_sessions.append({
                'session_id': str(session.id),
                'collector_id': str(collector.id),
                'collector_name': collector.name,
                'started_at': session.started_at.isoformat(),
                'last_data_at': session.last_data_at.isoformat() if session.last_data_at else None,
                'sample_count': session.sample_count,
                'duration_seconds': session.duration_seconds,
                'avg_cpu_percent': avg_cpu,
                'avg_mem_percent': avg_mem,
            })

        return Response({
            'active_count': len(active_sessions),
            'sessions': active_sessions,
        })


class CollectorSessionsAPI(BaseDashboardMetricsAPI):
    """
    List all trickle sessions for a specific collector.
    Sessions are grouped by date for the dropdown navigation.

    Query params:
        - status: Filter by status (active, completed, saved, all). Default: all
    """

    def get(self, request, collector_id):
        from collectors.models import TrickleSession

        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)

        # Get status filter
        status_filter = request.query_params.get('status', 'all')

        # Build query
        sessions_qs = TrickleSession.objects.filter(collector=collector)
        if status_filter != 'all':
            sessions_qs = sessions_qs.filter(status=status_filter)

        sessions_qs = sessions_qs.order_by('-started_at')

        # Group sessions by date
        sessions_by_date = {}
        for session in sessions_qs:
            date_key = session.started_at.strftime('%Y-%m-%d')
            if date_key not in sessions_by_date:
                sessions_by_date[date_key] = []

            sessions_by_date[date_key].append({
                'session_id': str(session.id),
                'name': session.name,
                'status': session.status,
                'started_at': session.started_at.isoformat(),
                'ended_at': session.ended_at.isoformat() if session.ended_at else None,
                'sample_count': session.sample_count,
                'duration_seconds': session.duration_seconds,
            })

        # Build dates list for dropdown
        dates = sorted(sessions_by_date.keys(), reverse=True)

        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'dates': dates,
            'sessions_by_date': sessions_by_date,
            'total_sessions': sessions_qs.count(),
        })


class CollectorSessionDatesAPI(BaseDashboardMetricsAPI):
    """
    Get list of dates with saved sessions for a collector.
    Used to populate the date dropdown in the UI.
    """

    def get(self, request, collector_id):
        from collectors.models import TrickleSession

        collector = self.get_collector(collector_id)
        if not collector:
            return Response({'error': 'Collector not found'}, status=404)

        # Get distinct dates from saved/completed sessions
        sessions = TrickleSession.objects.filter(
            collector=collector,
            status__in=[TrickleSession.Status.COMPLETED, TrickleSession.Status.SAVED]
        ).order_by('-started_at')

        # Build unique dates
        dates = []
        seen_dates = set()
        for session in sessions:
            date_key = session.started_at.strftime('%Y-%m-%d')
            if date_key not in seen_dates:
                seen_dates.add(date_key)
                # Count sessions for this date
                date_count = TrickleSession.objects.filter(
                    collector=collector,
                    started_at__date=session.started_at.date(),
                    status__in=[TrickleSession.Status.COMPLETED, TrickleSession.Status.SAVED]
                ).count()
                dates.append({
                    'date': date_key,
                    'session_count': date_count,
                })

        return Response({
            'collector_id': str(collector.id),
            'collector_name': collector.name,
            'dates': dates,
        })


class SessionDataAPI(BaseDashboardMetricsAPI):
    """
    Get metrics data for a specific session.
    Returns all PerformanceMetric data for the session's time range.
    """

    def get(self, request, session_id):
        from collectors.models import TrickleSession

        try:
            session = TrickleSession.objects.get(id=session_id)
        except TrickleSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)

        # Verify ownership
        if session.collector.owner != request.user:
            return Response({'error': 'Not authorized'}, status=403)

        # Determine time range
        start_time = session.started_at
        end_time = session.ended_at or session.last_data_at or timezone.now()

        # Get metrics for this session
        metrics = PerformanceMetric.objects.filter(
            collector=session.collector,
            timestamp__gte=start_time,
            timestamp__lte=end_time
        ).order_by('timestamp')

        # Build response (similar to CollectorLiveMetricsAPI)
        timestamps = []
        cpu_user = []
        cpu_system = []
        cpu_iowait = []
        cpu_idle = []
        cpu_steal = []

        mem_total = []
        mem_used = []
        mem_available = []
        mem_buffers = []
        mem_cached = []

        disk_read_bytes = []
        disk_write_bytes = []
        disk_read_ops = []
        disk_write_ops = []

        net_rx_bytes = []
        net_tx_bytes = []
        net_rx_packets = []
        net_tx_packets = []

        for m in metrics:
            timestamps.append(m.timestamp.isoformat())
            cpu_user.append(m.cpu_user or 0)
            cpu_system.append(m.cpu_system or 0)
            cpu_iowait.append(m.cpu_iowait or 0)
            cpu_idle.append(m.cpu_idle or 0)
            cpu_steal.append(m.cpu_steal or 0)
            mem_total.append(m.mem_total or 0)
            mem_used.append(m.mem_used or 0)
            mem_available.append(m.mem_available or 0)
            mem_buffers.append(m.mem_buffers or 0)
            mem_cached.append(m.mem_cached or 0)
            disk_read_bytes.append(m.disk_read_bytes or 0)
            disk_write_bytes.append(m.disk_write_bytes or 0)
            disk_read_ops.append(m.disk_read_ops or 0)
            disk_write_ops.append(m.disk_write_ops or 0)
            net_rx_bytes.append(m.net_rx_bytes or 0)
            net_tx_bytes.append(m.net_tx_bytes or 0)
            net_rx_packets.append(m.net_rx_packets or 0)
            net_tx_packets.append(m.net_tx_packets or 0)

        return Response({
            'session_id': str(session.id),
            'session_name': session.name,
            'session_status': session.status,
            'collector_id': str(session.collector.id),
            'collector_name': session.collector.name,
            'started_at': session.started_at.isoformat(),
            'ended_at': session.ended_at.isoformat() if session.ended_at else None,
            'sample_count': len(timestamps),
            'timestamps': timestamps,
            'cpu': {
                'user': cpu_user,
                'system': cpu_system,
                'iowait': cpu_iowait,
                'idle': cpu_idle,
                'steal': cpu_steal,
            },
            'memory': {
                'total_mb': mem_total,
                'used_mb': mem_used,
                'available_mb': mem_available,
                'buffers_mb': mem_buffers,
                'cached_mb': mem_cached,
            },
            'disk': {
                'read_bytes': disk_read_bytes,
                'write_bytes': disk_write_bytes,
                'read_ops': disk_read_ops,
                'write_ops': disk_write_ops,
            },
            'network': {
                'rx_bytes': net_rx_bytes,
                'tx_bytes': net_tx_bytes,
                'rx_packets': net_rx_packets,
                'tx_packets': net_tx_packets,
            },
        })


class CompleteSessionAPI(BaseDashboardMetricsAPI):
    """
    Mark an active session as completed and save it.
    This is called when a trickle collection ends.
    """

    def post(self, request, session_id):
        from collectors.models import TrickleSession

        try:
            session = TrickleSession.objects.get(id=session_id)
        except TrickleSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)

        # Verify ownership
        if session.collector.owner != request.user:
            return Response({'error': 'Not authorized'}, status=403)

        if session.status != TrickleSession.Status.ACTIVE:
            return Response({'error': 'Session is not active'}, status=400)

        # Mark as completed
        session.status = TrickleSession.Status.COMPLETED
        session.ended_at = session.last_data_at or timezone.now()

        # Update final sample count
        session.sample_count = PerformanceMetric.objects.filter(
            collector=session.collector,
            timestamp__gte=session.started_at,
            timestamp__lte=session.ended_at
        ).count()

        # Optionally set name from request
        if request.data.get('name'):
            session.name = request.data['name']

        session.save()

        return Response({
            'session_id': str(session.id),
            'status': session.status,
            'ended_at': session.ended_at.isoformat(),
            'sample_count': session.sample_count,
            'message': 'Session marked as completed',
        })


class CheckAndCompleteInactiveSessionsAPI(BaseDashboardMetricsAPI):
    """
    Check for and automatically complete inactive sessions.
    A session is considered inactive if no data received for the timeout period.

    Query params:
        - timeout_minutes: Inactivity threshold (default: 2 minutes)
    """

    def post(self, request):
        from collectors.models import TrickleSession

        timeout_minutes = int(request.query_params.get('timeout_minutes', 2))
        timeout_threshold = timezone.now() - timedelta(minutes=timeout_minutes)

        # Find active sessions with no recent data
        inactive_sessions = TrickleSession.objects.filter(
            status=TrickleSession.Status.ACTIVE,
            collector__owner=request.user,
            last_data_at__lt=timeout_threshold
        )

        completed_count = 0
        completed_sessions = []

        for session in inactive_sessions:
            session.status = TrickleSession.Status.COMPLETED
            session.ended_at = session.last_data_at or timeout_threshold

            # Update final sample count
            session.sample_count = PerformanceMetric.objects.filter(
                collector=session.collector,
                timestamp__gte=session.started_at,
                timestamp__lte=session.ended_at
            ).count()

            session.save()
            completed_count += 1
            completed_sessions.append({
                'session_id': str(session.id),
                'collector_name': session.collector.name,
                'sample_count': session.sample_count,
            })

        return Response({
            'completed_count': completed_count,
            'completed_sessions': completed_sessions,
        })
