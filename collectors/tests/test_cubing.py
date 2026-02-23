"""
Tests for CubingService — validates the data cubing logic ported from cube.go.

Tests verify:
- svalue() core normalization formula
- cube_cpu() delta-based CPU percentage calculation
- cube_disk() cumulative counter → IOPS/MB/s conversion
- cube_network() cumulative counter → Mbit/s and pps conversion
- cube_memory() direct memory calculation
- Edge cases: counter rollover, zero interval, first sample, negative deltas
- Integration: two consecutive trickle POSTs → cubed PerformanceMetric values
"""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from django_tenants.test.cases import TenantTestCase

from collectors.models import Collector, TrickleSession, PerformanceMetric, Tenant, Domain
from collectors.services.cubing import CubingService

User = get_user_model()

TENANT_TEST_DOMAIN = 'tenant.test.com'


class SvalueTests(TestCase):
    """Tests for the core svalue() normalization formula."""

    def test_basic_rate_calculation(self):
        """svalue with 1-second interval should return delta per second."""
        # tvi = 1 * 100 = 100
        result = CubingService.svalue(1000, 2000, 100)
        # (2000 - 1000) / 100 * 100 = 1000
        self.assertEqual(result, 1000.0)

    def test_two_second_interval(self):
        """svalue with 2-second interval should halve the rate."""
        # tvi = 2 * 100 = 200
        result = CubingService.svalue(1000, 3000, 200)
        # (3000 - 1000) / 200 * 100 = 1000
        self.assertEqual(result, 1000.0)

    def test_zero_tvi_returns_zero(self):
        """svalue with zero time interval should return 0 (not divide by zero)."""
        result = CubingService.svalue(1000, 2000, 0)
        self.assertEqual(result, 0.0)

    def test_no_change(self):
        """svalue with identical values should return 0."""
        result = CubingService.svalue(5000, 5000, 100)
        self.assertEqual(result, 0.0)

    def test_negative_delta(self):
        """svalue with counter rollover (curr < prev) returns negative."""
        result = CubingService.svalue(2000, 1000, 100)
        self.assertLess(result, 0)


class CubeCPUTests(TestCase):
    """Tests for cube_cpu() delta-based CPU percentage calculation."""

    def test_basic_cpu_calculation(self):
        """50% user CPU utilization over 1 second."""
        # Jiffies: [user, nice, system, idle, iowait, irq, softirq, steal]
        prev = [100, 0, 0, 100, 0, 0, 0, 0]  # 50% user, 50% idle
        curr = [200, 0, 0, 200, 0, 0, 0, 0]  # Delta: 100 user, 100 idle = 50%
        result = CubingService.cube_cpu(prev, curr)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['cpu_user'], 50.0)
        self.assertAlmostEqual(result['cpu_idle'], 50.0)
        self.assertAlmostEqual(result['cpu_system'], 0.0)

    def test_all_idle(self):
        """100% idle CPU."""
        prev = [100, 0, 50, 500, 0, 0, 0, 0]
        curr = [100, 0, 50, 600, 0, 0, 0, 0]  # Only idle increased
        result = CubingService.cube_cpu(prev, curr)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['cpu_idle'], 100.0)
        self.assertAlmostEqual(result['cpu_user'], 0.0)
        self.assertAlmostEqual(result['cpu_system'], 0.0)

    def test_full_cpu_utilization(self):
        """100% CPU utilization (all user)."""
        prev = [100, 0, 0, 100, 0, 0, 0, 0]
        curr = [300, 0, 0, 100, 0, 0, 0, 0]  # Only user increased
        result = CubingService.cube_cpu(prev, curr)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['cpu_user'], 100.0)
        self.assertAlmostEqual(result['cpu_idle'], 0.0)

    def test_mixed_utilization(self):
        """Mixed CPU utilization: 25% user, 25% system, 50% idle."""
        prev = [0, 0, 0, 0, 0, 0, 0, 0]
        curr = [25, 0, 25, 50, 0, 0, 0, 0]
        result = CubingService.cube_cpu(prev, curr)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['cpu_user'], 25.0)
        self.assertAlmostEqual(result['cpu_system'], 25.0)
        self.assertAlmostEqual(result['cpu_idle'], 50.0)

    def test_with_iowait_and_steal(self):
        """CPU with iowait and steal."""
        prev = [0, 0, 0, 0, 0, 0, 0, 0]
        curr = [20, 0, 10, 50, 10, 0, 0, 10]  # 20% user, 10% sys, 10% iowait, 10% steal, 50% idle
        result = CubingService.cube_cpu(prev, curr)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['cpu_user'], 20.0)
        self.assertAlmostEqual(result['cpu_system'], 10.0)
        self.assertAlmostEqual(result['cpu_iowait'], 10.0)
        self.assertAlmostEqual(result['cpu_steal'], 10.0)
        self.assertAlmostEqual(result['cpu_idle'], 50.0)

    def test_no_previous_returns_none(self):
        """First sample with no previous should return None."""
        result = CubingService.cube_cpu(None, [100, 0, 50, 500, 0, 0, 0, 0])
        self.assertIsNone(result)

    def test_short_jiffies_returns_none(self):
        """Jiffies list with fewer than 8 elements returns None."""
        result = CubingService.cube_cpu([100, 0, 50], [200, 0, 100])
        self.assertIsNone(result)

    def test_counter_no_change(self):
        """No change in counters reports 100% idle (cube.go edge case)."""
        same = [100, 0, 50, 500, 0, 0, 0, 0]
        result = CubingService.cube_cpu(same, same)
        self.assertIsNotNone(result)
        # busy_delta = 0, so busy = 0, idle = 100
        self.assertAlmostEqual(result['cpu_idle'], 100.0)

    def test_real_proc_stat_data(self):
        """Test with realistic /proc/stat values."""
        # Simulating 1 second of a moderately busy system
        prev = [350000, 500, 120000, 800000, 5000, 1000, 2000, 0]
        curr = [350080, 500, 120020, 800890, 5005, 1000, 2005, 0]
        # Delta: user=80, nice=0, system=20, idle=890, iowait=5, irq=0, softirq=5, steal=0
        # Total delta = 80 + 0 + 20 + 890 + 5 + 0 + 5 + 0 = 1000
        result = CubingService.cube_cpu(prev, curr)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['cpu_user'], 8.0)   # 80/1000 * 100
        self.assertAlmostEqual(result['cpu_system'], 2.0)  # 20/1000 * 100
        self.assertAlmostEqual(result['cpu_iowait'], 0.5)  # 5/1000 * 100
        self.assertAlmostEqual(result['cpu_idle'], 89.0)   # 100 - 11.0


class CubeDiskTests(TestCase):
    """Tests for cube_disk() cumulative counter → rate conversion."""

    def test_basic_iops(self):
        """1000 read ops in 1 second = 1000 IOPS."""
        prev = {'read_ops': 100000, 'write_ops': 50000, 'read_bytes': 0, 'write_bytes': 0}
        curr = {'read_ops': 101000, 'write_ops': 50500, 'read_bytes': 0, 'write_bytes': 0}
        result = CubingService.cube_disk(prev, curr, 1.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['disk_read_iops'], 1000.0)
        self.assertAlmostEqual(result['disk_write_iops'], 500.0)

    def test_throughput_mbps(self):
        """1MB read in 1 second = 1 MB/s."""
        mb = 1024 * 1024
        prev = {'read_ops': 0, 'write_ops': 0, 'read_bytes': 0, 'write_bytes': 0}
        curr = {'read_ops': 0, 'write_ops': 0, 'read_bytes': mb, 'write_bytes': 2 * mb}
        result = CubingService.cube_disk(prev, curr, 1.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['disk_read_mbps'], 1.0, places=3)
        self.assertAlmostEqual(result['disk_write_mbps'], 2.0, places=3)

    def test_two_second_interval(self):
        """Rates should be halved for 2-second interval."""
        prev = {'read_ops': 0, 'write_ops': 0, 'read_bytes': 0, 'write_bytes': 0}
        curr = {'read_ops': 2000, 'write_ops': 1000, 'read_bytes': 0, 'write_bytes': 0}
        result = CubingService.cube_disk(prev, curr, 2.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['disk_read_iops'], 1000.0)
        self.assertAlmostEqual(result['disk_write_iops'], 500.0)

    def test_no_previous_returns_none(self):
        """No previous stats returns None."""
        result = CubingService.cube_disk(None, {'read_ops': 100}, 1.0)
        self.assertIsNone(result)

    def test_zero_interval_returns_none(self):
        """Zero interval returns None."""
        prev = {'read_ops': 0, 'write_ops': 0, 'read_bytes': 0, 'write_bytes': 0}
        curr = {'read_ops': 100, 'write_ops': 50, 'read_bytes': 0, 'write_bytes': 0}
        result = CubingService.cube_disk(prev, curr, 0)
        self.assertIsNone(result)

    def test_counter_rollover_returns_zero(self):
        """Counter rollover (curr < prev) should return 0, not negative."""
        prev = {'read_ops': 100000, 'write_ops': 50000, 'read_bytes': 999999, 'write_bytes': 999999}
        curr = {'read_ops': 100, 'write_ops': 100, 'read_bytes': 100, 'write_bytes': 100}
        result = CubingService.cube_disk(prev, curr, 1.0)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result['disk_read_iops'], 0)
        self.assertGreaterEqual(result['disk_write_iops'], 0)
        self.assertGreaterEqual(result['disk_read_mbps'], 0)
        self.assertGreaterEqual(result['disk_write_mbps'], 0)


class CubeNetworkTests(TestCase):
    """Tests for cube_network() cumulative counter → rate conversion."""

    def test_basic_network_rates(self):
        """1 Mbit/s = 125000 bytes/sec."""
        bytes_for_1mbps = 125000  # 1 Mbit = 125000 bytes
        prev = {'rx_bytes': 0, 'tx_bytes': 0, 'rx_packets': 0, 'tx_packets': 0}
        curr = {'rx_bytes': bytes_for_1mbps, 'tx_bytes': bytes_for_1mbps * 2,
                'rx_packets': 1000, 'tx_packets': 500}
        result = CubingService.cube_network(prev, curr, 1.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['net_rx_mbps'], 1.0, places=3)
        self.assertAlmostEqual(result['net_tx_mbps'], 2.0, places=3)
        self.assertAlmostEqual(result['net_rx_pps'], 1000.0)
        self.assertAlmostEqual(result['net_tx_pps'], 500.0)

    def test_gigabit_rate(self):
        """~1 Gbit/s rate."""
        bytes_for_1gbps = 125000000  # 1 Gbit = 125000000 bytes
        prev = {'rx_bytes': 0, 'tx_bytes': 0, 'rx_packets': 0, 'tx_packets': 0}
        curr = {'rx_bytes': bytes_for_1gbps, 'tx_bytes': 0,
                'rx_packets': 100000, 'tx_packets': 0}
        result = CubingService.cube_network(prev, curr, 1.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['net_rx_mbps'], 1000.0, places=0)

    def test_no_previous_returns_none(self):
        """No previous stats returns None."""
        result = CubingService.cube_network(None, {'rx_bytes': 100}, 1.0)
        self.assertIsNone(result)

    def test_zero_interval_returns_none(self):
        """Zero interval returns None."""
        prev = {'rx_bytes': 0, 'tx_bytes': 0, 'rx_packets': 0, 'tx_packets': 0}
        result = CubingService.cube_network(prev, prev, 0)
        self.assertIsNone(result)

    def test_counter_rollover_returns_zero(self):
        """Counter rollover should return 0."""
        prev = {'rx_bytes': 999999999, 'tx_bytes': 999999999,
                'rx_packets': 999999, 'tx_packets': 999999}
        curr = {'rx_bytes': 100, 'tx_bytes': 100,
                'rx_packets': 100, 'tx_packets': 100}
        result = CubingService.cube_network(prev, curr, 1.0)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result['net_rx_mbps'], 0)
        self.assertGreaterEqual(result['net_tx_mbps'], 0)
        self.assertGreaterEqual(result['net_rx_pps'], 0)
        self.assertGreaterEqual(result['net_tx_pps'], 0)


class CubeMemoryTests(TestCase):
    """Tests for cube_memory() direct memory calculation."""

    def test_basic_memory_calculation(self):
        """Test memory used calculation from cube.go formula."""
        meminfo = {
            'mem_total': 16384.0,   # 16 GB in MB
            'mem_free': 4096.0,
            'mem_buffers': 512.0,
            'mem_cached': 4096.0,
            'mem_slab': 256.0,
            'mem_available': 8192.0,
        }
        result = CubingService.cube_memory(meminfo)
        self.assertIsNotNone(result)
        # nousedmem = 4096 + 512 + 4096 + 256 = 8960
        # used = 16384 - 8960 = 7424
        self.assertAlmostEqual(result['mem_used'], 7424.0)
        self.assertAlmostEqual(result['mem_total'], 16384.0)
        self.assertAlmostEqual(result['mem_available'], 8192.0)

    def test_nousedmem_exceeds_total(self):
        """When free + buffers + cached + slab > total, cap at total."""
        meminfo = {
            'mem_total': 1000.0,
            'mem_free': 500.0,
            'mem_buffers': 300.0,
            'mem_cached': 400.0,
            'mem_slab': 200.0,
            'mem_available': 800.0,
        }
        result = CubingService.cube_memory(meminfo)
        self.assertIsNotNone(result)
        # nousedmem = 500 + 300 + 400 + 200 = 1400 > 1000, so capped at 1000
        # used = 1000 - 1000 = 0
        self.assertAlmostEqual(result['mem_used'], 0.0)

    def test_none_returns_none(self):
        """None input returns None."""
        result = CubingService.cube_memory(None)
        self.assertIsNone(result)

    def test_zero_total_returns_none(self):
        """Zero mem_total returns None."""
        result = CubingService.cube_memory({'mem_total': 0, 'mem_free': 0})
        self.assertIsNone(result)

    def test_missing_fields_default_to_zero(self):
        """Missing meminfo fields should default to 0."""
        meminfo = {
            'mem_total': 8192.0,
            'mem_free': 2048.0,
            'mem_available': 4096.0,
            # buffers, cached, slab missing — should default to 0
        }
        result = CubingService.cube_memory(meminfo)
        self.assertIsNotNone(result)
        # nousedmem = 2048 + 0 + 0 + 0 = 2048
        # used = 8192 - 2048 = 6144
        self.assertAlmostEqual(result['mem_used'], 6144.0)


# =============================================================================
# Trickle Pipeline Integration Tests
# =============================================================================

class TrickleCubingIntegrationTests(TenantTestCase):
    """
    Integration tests: POST consecutive trickle samples → verify cubed metrics.

    These tests exercise the full pipeline: TrickleView → CubingService →
    PerformanceMetric storage, validating that:
    - First sample stores cumulative counters but no rates (no delta yet)
    - Second sample computes correct delta-based rates
    - Session.previous_sample persists between requests
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = 'test-cubing-tenant'

    @classmethod
    def setup_domain(cls, domain):
        domain.is_primary = True

    def setUp(self):
        super().setUp()
        self.client = APIClient(HTTP_HOST=TENANT_TEST_DOMAIN)

        self.user = User.objects.create_user(
            username='cubinguser', password='testpass123'
        )
        self.collector = Collector.objects.create(
            owner=self.user,
            name='cubing-test-collector',
            api_key='cubing-test-key-12345678',
        )

    def _trickle_post(self, timestamp, proc_stat, meminfo, diskstats=None, netdev=None):
        """Helper to POST a trickle payload."""
        measurements = [
            {'timestamp': timestamp, 'subsystem': '/proc/stat', 'measurement': proc_stat},
            {'timestamp': timestamp, 'subsystem': '/proc/meminfo', 'measurement': meminfo},
        ]
        if diskstats:
            measurements.append(
                {'timestamp': timestamp, 'subsystem': '/proc/diskstats', 'measurement': diskstats}
            )
        if netdev:
            measurements.append(
                {'timestamp': timestamp, 'subsystem': '/proc/net/dev', 'measurement': netdev}
            )

        return self.client.post(
            '/v1/trickle',
            data=json.dumps({
                'identifier': 'cubing-integration-test',
                'measurements': measurements,
            }),
            content_type='application/json',
            HTTP_APIKEY=self.collector.api_key,
            HTTP_HOST=TENANT_TEST_DOMAIN,
        )

    def _build_proc_stat(self, user, nice, system, idle, iowait=0, irq=0, softirq=0, steal=0):
        """Build a /proc/stat measurement string."""
        return (
            f"cpu  {user} {nice} {system} {idle} {iowait} {irq} {softirq} {steal} 0 0\n"
            f"cpu0 {user} {nice} {system} {idle} {iowait} {irq} {softirq} {steal} 0 0\n"
        )

    def _build_meminfo(self, total_kb=16777216, free_kb=4194304, buffers_kb=524288,
                       cached_kb=4194304, slab_kb=262144, available_kb=8388608):
        """Build a /proc/meminfo measurement string."""
        return (
            f"MemTotal:       {total_kb} kB\n"
            f"MemFree:        {free_kb} kB\n"
            f"MemAvailable:   {available_kb} kB\n"
            f"Buffers:        {buffers_kb} kB\n"
            f"Cached:         {cached_kb} kB\n"
            f"Slab:           {slab_kb} kB\n"
        )

    def _build_diskstats(self, read_ops, write_ops, read_sectors, write_sectors):
        """Build a /proc/diskstats measurement string (sda device)."""
        # Format: major minor name reads merged_reads read_sectors read_ms
        #         writes merged_writes write_sectors write_ms ...
        return (
            f"   8       0 sda {read_ops} 0 {read_sectors} 0 "
            f"{write_ops} 0 {write_sectors} 0 0 0 0 0 0 0 0\n"
        )

    def _build_netdev(self, rx_bytes, tx_bytes, rx_packets, tx_packets):
        """Build a /proc/net/dev measurement string."""
        return (
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|"
            "bytes    packets errs drop fifo colls carrier compressed\n"
            f"  eth0: {rx_bytes}  {rx_packets}    0    0    0     0          0         0 "
            f" {tx_bytes}  {tx_packets}    0    0    0     0       0          0\n"
            f"    lo:    1000     100    0    0    0     0          0         0 "
            f"   1000     100    0    0    0     0       0          0\n"
        )

    def test_first_sample_has_no_cpu_rates(self):
        """First trickle sample: no previous → CPU should be None (no delta)."""
        ts = int(timezone.now().timestamp())
        proc_stat = self._build_proc_stat(100000, 0, 50000, 800000, 5000, 1000, 2000, 0)
        meminfo = self._build_meminfo()

        resp = self._trickle_post(ts, proc_stat, meminfo)
        self.assertEqual(resp.status_code, 200)

        metric = PerformanceMetric.objects.filter(collector=self.collector).first()
        self.assertIsNotNone(metric)
        # First sample: no previous jiffies → no CPU cubing → CPU fields should be None
        self.assertIsNone(metric.cpu_user)
        self.assertIsNone(metric.cpu_system)

        # Memory should be cubed (no delta needed)
        self.assertIsNotNone(metric.mem_total)
        self.assertGreater(metric.mem_total, 0)

    def test_two_samples_produce_cubed_cpu(self):
        """Two consecutive trickle POSTs: second should have cubed CPU percentages."""
        base_ts = int(timezone.now().timestamp())

        # Sample 1: baseline jiffies
        proc_stat_1 = self._build_proc_stat(100000, 0, 50000, 800000, 5000, 1000, 2000, 0)
        meminfo = self._build_meminfo()
        resp1 = self._trickle_post(base_ts, proc_stat_1, meminfo)
        self.assertEqual(resp1.status_code, 200)

        # Sample 2: 1 second later, jiffies increased
        # Delta: user=80, nice=0, system=20, idle=890, iowait=5, irq=0, softirq=5, steal=0
        # Total delta = 1000
        proc_stat_2 = self._build_proc_stat(100080, 0, 50020, 800890, 5005, 1000, 2005, 0)
        resp2 = self._trickle_post(base_ts + 1, proc_stat_2, meminfo)
        self.assertEqual(resp2.status_code, 200)

        metrics = PerformanceMetric.objects.filter(
            collector=self.collector
        ).order_by('timestamp')
        self.assertEqual(metrics.count(), 2)

        second_metric = metrics[1]
        # Verify cubed CPU percentages (delta-based)
        self.assertIsNotNone(second_metric.cpu_user)
        self.assertAlmostEqual(second_metric.cpu_user, 8.0, places=1)   # 80/1000 * 100
        self.assertAlmostEqual(second_metric.cpu_system, 2.0, places=1)  # 20/1000 * 100
        self.assertAlmostEqual(second_metric.cpu_idle, 89.0, places=1)   # 890/1000 * 100

    def test_two_samples_produce_cubed_disk_rates(self):
        """Two samples with /proc/diskstats → second has IOPS and MB/s."""
        base_ts = int(timezone.now().timestamp())
        proc_stat = self._build_proc_stat(100000, 0, 50000, 800000)
        meminfo = self._build_meminfo()

        # Sample 1: disk baseline
        # read_ops=10000, write_ops=5000, read_sectors=100000, write_sectors=50000
        disk1 = self._build_diskstats(10000, 5000, 100000, 50000)
        resp1 = self._trickle_post(base_ts, proc_stat, meminfo, diskstats=disk1)
        self.assertEqual(resp1.status_code, 200)

        # Sample 2: 1 second later
        # read_ops += 200, write_ops += 100, read_sectors += 2048, write_sectors += 1024
        disk2 = self._build_diskstats(10200, 5100, 102048, 51024)
        proc_stat_2 = self._build_proc_stat(100080, 0, 50020, 800900)
        resp2 = self._trickle_post(base_ts + 1, proc_stat_2, meminfo, diskstats=disk2)
        self.assertEqual(resp2.status_code, 200)

        second_metric = PerformanceMetric.objects.filter(
            collector=self.collector
        ).order_by('timestamp').last()

        # Verify disk rates
        self.assertIsNotNone(second_metric.disk_read_iops)
        self.assertAlmostEqual(second_metric.disk_read_iops, 200.0, places=0)   # 200 ops / 1 sec
        self.assertAlmostEqual(second_metric.disk_write_iops, 100.0, places=0)  # 100 ops / 1 sec
        # Read throughput: 2048 sectors * 512 bytes = 1,048,576 bytes = 1 MB/s
        self.assertAlmostEqual(second_metric.disk_read_mbps, 1.0, places=1)
        # Write throughput: 1024 sectors * 512 bytes = 524,288 bytes ≈ 0.5 MB/s
        self.assertAlmostEqual(second_metric.disk_write_mbps, 0.5, places=1)

    def test_two_samples_produce_cubed_network_rates(self):
        """Two samples with /proc/net/dev → second has Mbit/s and pps."""
        base_ts = int(timezone.now().timestamp())
        proc_stat = self._build_proc_stat(100000, 0, 50000, 800000)
        meminfo = self._build_meminfo()

        # Sample 1: network baseline
        net1 = self._build_netdev(1000000, 500000, 10000, 5000)
        resp1 = self._trickle_post(base_ts, proc_stat, meminfo, netdev=net1)
        self.assertEqual(resp1.status_code, 200)

        # Sample 2: 1 second later
        # rx_bytes += 125000 (1 Mbit), tx_bytes += 62500 (0.5 Mbit)
        # rx_packets += 1000, tx_packets += 500
        net2 = self._build_netdev(1125000, 562500, 11000, 5500)
        proc_stat_2 = self._build_proc_stat(100080, 0, 50020, 800900)
        resp2 = self._trickle_post(base_ts + 1, proc_stat_2, meminfo, netdev=net2)
        self.assertEqual(resp2.status_code, 200)

        second_metric = PerformanceMetric.objects.filter(
            collector=self.collector
        ).order_by('timestamp').last()

        # Verify network rates
        self.assertIsNotNone(second_metric.net_rx_mbps)
        self.assertAlmostEqual(second_metric.net_rx_mbps, 1.0, places=1)    # 125000 bytes/s = 1 Mbit/s
        self.assertAlmostEqual(second_metric.net_tx_mbps, 0.5, places=1)    # 62500 bytes/s = 0.5 Mbit/s
        self.assertAlmostEqual(second_metric.net_rx_pps, 1000.0, places=0)  # 1000 packets/s
        self.assertAlmostEqual(second_metric.net_tx_pps, 500.0, places=0)   # 500 packets/s

    def test_memory_cubed_on_first_sample(self):
        """Memory cubing works on the first sample (no delta needed)."""
        ts = int(timezone.now().timestamp())
        proc_stat = self._build_proc_stat(100000, 0, 50000, 800000)
        # 16 GB total, 4 GB free, 512 MB buffers, 4 GB cached, 256 MB slab, 8 GB available
        meminfo = self._build_meminfo(
            total_kb=16777216, free_kb=4194304, buffers_kb=524288,
            cached_kb=4194304, slab_kb=262144, available_kb=8388608,
        )

        resp = self._trickle_post(ts, proc_stat, meminfo)
        self.assertEqual(resp.status_code, 200)

        metric = PerformanceMetric.objects.filter(collector=self.collector).first()
        self.assertIsNotNone(metric)
        # mem_total = 16777216 / 1024 = 16384 MB
        self.assertAlmostEqual(metric.mem_total, 16384.0, places=0)
        # mem_used = total - (free + buffers + cached + slab)
        # = 16384 - (4096 + 512 + 4096 + 256) = 16384 - 8960 = 7424
        self.assertAlmostEqual(metric.mem_used, 7424.0, places=0)
        self.assertAlmostEqual(metric.mem_available, 8192.0, places=0)

    def test_session_previous_sample_persists(self):
        """previous_sample is saved between POSTs for correct delta state."""
        base_ts = int(timezone.now().timestamp())
        proc_stat = self._build_proc_stat(100000, 0, 50000, 800000)
        meminfo = self._build_meminfo()

        resp1 = self._trickle_post(base_ts, proc_stat, meminfo)
        self.assertEqual(resp1.status_code, 200)

        # Verify previous_sample was saved on the session
        session = TrickleSession.objects.filter(collector=self.collector).first()
        self.assertIsNotNone(session)
        self.assertIsNotNone(session.previous_sample)
        self.assertEqual(session.previous_sample['timestamp'], base_ts)
        self.assertIn('cpu_jiffies', session.previous_sample)

    def test_three_samples_all_cubed_correctly(self):
        """Three consecutive samples: samples 2 and 3 have cubed rates."""
        base_ts = int(timezone.now().timestamp())
        meminfo = self._build_meminfo()

        # Sample 1
        proc_stat_1 = self._build_proc_stat(100000, 0, 50000, 800000)
        self._trickle_post(base_ts, proc_stat_1, meminfo)

        # Sample 2 (1 second later): 50% user, 50% idle
        proc_stat_2 = self._build_proc_stat(100500, 0, 50000, 800500)
        self._trickle_post(base_ts + 1, proc_stat_2, meminfo)

        # Sample 3 (2 seconds later): 100% user
        proc_stat_3 = self._build_proc_stat(101500, 0, 50000, 800500)
        self._trickle_post(base_ts + 2, proc_stat_3, meminfo)

        metrics = PerformanceMetric.objects.filter(
            collector=self.collector
        ).order_by('timestamp')
        self.assertEqual(metrics.count(), 3)

        # Sample 1: no CPU cubing
        self.assertIsNone(metrics[0].cpu_user)

        # Sample 2: delta = user 500, idle 500, total 1000 → 50% user, 50% idle
        self.assertAlmostEqual(metrics[1].cpu_user, 50.0, places=1)
        self.assertAlmostEqual(metrics[1].cpu_idle, 50.0, places=1)

        # Sample 3: delta = user 1000, idle 0, total 1000 → 100% user, 0% idle
        self.assertAlmostEqual(metrics[2].cpu_user, 100.0, places=1)
        self.assertAlmostEqual(metrics[2].cpu_idle, 0.0, places=1)

    def test_first_sample_disk_rates_are_none(self):
        """First sample has cumulative disk counters but no rates."""
        ts = int(timezone.now().timestamp())
        proc_stat = self._build_proc_stat(100000, 0, 50000, 800000)
        meminfo = self._build_meminfo()
        disk = self._build_diskstats(10000, 5000, 100000, 50000)

        resp = self._trickle_post(ts, proc_stat, meminfo, diskstats=disk)
        self.assertEqual(resp.status_code, 200)

        metric = PerformanceMetric.objects.filter(collector=self.collector).first()
        # Cumulative counters should be stored
        self.assertIsNotNone(metric.disk_read_ops)
        self.assertIsNotNone(metric.disk_write_ops)
        # Rate fields should be None (no previous sample)
        self.assertIsNone(metric.disk_read_iops)
        self.assertIsNone(metric.disk_write_iops)
        self.assertIsNone(metric.disk_read_mbps)
        self.assertIsNone(metric.disk_write_mbps)
