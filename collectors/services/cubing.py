"""
Data Cubing Service — Python port of perfcollector2/parser/cube.go

Converts raw /proc cumulative counters into visualization-ready rates
and percentages using delta calculations between consecutive samples.

This is the "secret sauce" — the intellectual property core of the
performance data pipeline that transforms raw Linux metrics into
meaningful performance insights.

Reference: perfcollector2/parser/cube.go (Go implementation)
"""


class CubingService:
    """
    Ports the cubing logic from pcprocess (Go) into Python.

    Key concepts:
    - CPU metrics require delta between two consecutive jiffies samples
    - Disk/Network metrics require delta of cumulative counters / elapsed time
    - Memory metrics are direct conversions (no delta needed)
    - svalue() is the core normalization formula from cube.go line 169
    """

    USER_HZ = 100       # Linux constant: jiffies per second (x86)
    SECTOR_SIZE = 512    # Bytes per disk sector

    # ─── Core normalization ──────────────────────────────────────────

    @staticmethod
    def svalue(prev, curr, tvi):
        """
        Core normalization from cube.go line 169.

        Formula: (curr - prev) / tvi * 100

        With tvi = elapsed_seconds * USER_HZ:
            = (curr - prev) / (elapsed * 100) * 100
            = (curr - prev) / elapsed
            = delta per second

        Args:
            prev: Previous counter value
            curr: Current counter value
            tvi: Time interval in hundredths of seconds (elapsed * USER_HZ)

        Returns:
            Rate per second (the * 100 and / USER_HZ cancel out)
        """
        if tvi == 0:
            return 0.0
        return (float(curr) - float(prev)) / float(tvi) * 100.0

    # ─── CPU cubing ──────────────────────────────────────────────────

    @staticmethod
    def _get_all_busy(jiffies):
        """
        Compute (total, busy) from jiffies list.

        Port of cube.go getAllBusy().

        Args:
            jiffies: list of [user, nice, system, idle, iowait, irq, softirq, steal]

        Returns:
            (total, busy) tuple
        """
        user, nice, system, idle, iowait, irq, softirq, steal = (
            float(jiffies[0]), float(jiffies[1]), float(jiffies[2]),
            float(jiffies[3]), float(jiffies[4]), float(jiffies[5]),
            float(jiffies[6]), float(jiffies[7])
        )
        busy = user + nice + system + iowait + irq + softirq + steal
        total = busy + idle
        return total, busy

    @staticmethod
    def _calculate_component(prev_jiffies, curr_jiffies, component_index):
        """
        Calculate CPU percentage for a single component using delta method.

        Port of cube.go calculateUser/calculateSystem/etc pattern.

        Edge cases from cube.go:
        - If curr_busy <= prev_busy: return 0 (no busy work done)
        - If curr_total <= prev_total: return 100 (counter wrapped)
        - Clamp to [0, 100]

        Args:
            prev_jiffies: Previous sample [user, nice, system, idle, iowait, irq, softirq, steal]
            curr_jiffies: Current sample [user, nice, system, idle, iowait, irq, softirq, steal]
            component_index: Index into jiffies list for the component

        Returns:
            Percentage (0-100)
        """
        prev_total, prev_busy = CubingService._get_all_busy(prev_jiffies)
        curr_total, curr_busy = CubingService._get_all_busy(curr_jiffies)

        if curr_busy <= prev_busy:
            return 0.0
        if curr_total <= prev_total:
            return 100.0

        delta_total = curr_total - prev_total
        delta_component = float(curr_jiffies[component_index]) - float(prev_jiffies[component_index])

        return min(100.0, max(0.0, delta_component / delta_total * 100.0))

    @classmethod
    def cube_cpu(cls, prev_jiffies, curr_jiffies):
        """
        Convert delta jiffies into CPU percentages.

        Port of cube.go CubeStat().

        Args:
            prev_jiffies: Previous [user, nice, system, idle, iowait, irq, softirq, steal]
            curr_jiffies: Current  [user, nice, system, idle, iowait, irq, softirq, steal]

        Returns:
            dict with cpu_user, cpu_system, cpu_iowait, cpu_steal, cpu_idle
            or None if inputs are invalid
        """
        if prev_jiffies is None or curr_jiffies is None:
            return None

        if len(prev_jiffies) < 8 or len(curr_jiffies) < 8:
            return None

        # Component indices: 0=user, 1=nice, 2=system, 3=idle, 4=iowait, 5=irq, 6=softirq, 7=steal
        user = cls._calculate_component(prev_jiffies, curr_jiffies, 0)
        nice = cls._calculate_component(prev_jiffies, curr_jiffies, 1)
        system = cls._calculate_component(prev_jiffies, curr_jiffies, 2)
        iowait = cls._calculate_component(prev_jiffies, curr_jiffies, 4)
        steal = cls._calculate_component(prev_jiffies, curr_jiffies, 7)

        # Busy = sum of all non-idle (same as cube.go calculateBusy)
        prev_total, prev_busy = cls._get_all_busy(prev_jiffies)
        curr_total, curr_busy = cls._get_all_busy(curr_jiffies)

        if curr_busy <= prev_busy:
            busy = 0.0
        elif curr_total <= prev_total:
            busy = 100.0
        else:
            busy = min(100.0, max(0.0,
                (curr_busy - prev_busy) / (curr_total - prev_total) * 100.0
            ))

        idle = 100.0 - busy

        return {
            'cpu_user': round(user + nice, 2),   # Combine user + nice like existing code
            'cpu_system': round(system, 2),
            'cpu_iowait': round(iowait, 2),
            'cpu_steal': round(steal, 2),
            'cpu_idle': round(idle, 2),
        }

    # ─── Disk cubing ─────────────────────────────────────────────────

    @classmethod
    def cube_disk(cls, prev_stats, curr_stats, interval_seconds):
        """
        Convert cumulative disk counters to IOPS and MB/s rates.

        Port of cube.go CubeDiskstats().

        Args:
            prev_stats: dict with read_ops, write_ops, read_bytes, write_bytes
            curr_stats: dict with same keys
            interval_seconds: Time between samples in seconds

        Returns:
            dict with disk_read_iops, disk_write_iops, disk_read_mbps, disk_write_mbps
            or None if inputs are invalid
        """
        if prev_stats is None or curr_stats is None:
            return None
        if interval_seconds is None or interval_seconds <= 0:
            return None

        tvi = int(interval_seconds * cls.USER_HZ)
        if tvi == 0:
            return None

        # IOPS: operations per second
        read_iops = cls.svalue(
            prev_stats.get('read_ops', 0),
            curr_stats.get('read_ops', 0),
            tvi
        )
        write_iops = cls.svalue(
            prev_stats.get('write_ops', 0),
            curr_stats.get('write_ops', 0),
            tvi
        )

        # Throughput: bytes per second → MB/s
        read_bytes_per_sec = cls.svalue(
            prev_stats.get('read_bytes', 0),
            curr_stats.get('read_bytes', 0),
            tvi
        )
        write_bytes_per_sec = cls.svalue(
            prev_stats.get('write_bytes', 0),
            curr_stats.get('write_bytes', 0),
            tvi
        )

        # Convert bytes/sec to MB/sec
        read_mbps = read_bytes_per_sec / (1024.0 * 1024.0)
        write_mbps = write_bytes_per_sec / (1024.0 * 1024.0)

        # Handle counter rollover: negative rates mean counter wrapped
        if read_iops < 0:
            read_iops = 0.0
        if write_iops < 0:
            write_iops = 0.0
        if read_mbps < 0:
            read_mbps = 0.0
        if write_mbps < 0:
            write_mbps = 0.0

        return {
            'disk_read_iops': round(read_iops, 2),
            'disk_write_iops': round(write_iops, 2),
            'disk_read_mbps': round(read_mbps, 4),
            'disk_write_mbps': round(write_mbps, 4),
        }

    # ─── Network cubing ──────────────────────────────────────────────

    @classmethod
    def cube_network(cls, prev_stats, curr_stats, interval_seconds):
        """
        Convert cumulative network counters to per-second rates.

        Port of cube.go CubeNetDev().

        Args:
            prev_stats: dict with rx_bytes, tx_bytes, rx_packets, tx_packets
            curr_stats: dict with same keys
            interval_seconds: Time between samples in seconds

        Returns:
            dict with net_rx_mbps (Mbit/s), net_tx_mbps, net_rx_pps, net_tx_pps
            or None if inputs are invalid
        """
        if prev_stats is None or curr_stats is None:
            return None
        if interval_seconds is None or interval_seconds <= 0:
            return None

        tvi = int(interval_seconds * cls.USER_HZ)
        if tvi == 0:
            return None

        # Bytes per second
        rx_bytes_per_sec = cls.svalue(
            prev_stats.get('rx_bytes', 0),
            curr_stats.get('rx_bytes', 0),
            tvi
        )
        tx_bytes_per_sec = cls.svalue(
            prev_stats.get('tx_bytes', 0),
            curr_stats.get('tx_bytes', 0),
            tvi
        )

        # Packets per second
        rx_pps = cls.svalue(
            prev_stats.get('rx_packets', 0),
            curr_stats.get('rx_packets', 0),
            tvi
        )
        tx_pps = cls.svalue(
            prev_stats.get('tx_packets', 0),
            curr_stats.get('tx_packets', 0),
            tvi
        )

        # Convert bytes/sec to Mbit/sec (network standard)
        rx_mbps = rx_bytes_per_sec * 8.0 / (1000.0 * 1000.0)
        tx_mbps = tx_bytes_per_sec * 8.0 / (1000.0 * 1000.0)

        # Handle counter rollover
        if rx_mbps < 0:
            rx_mbps = 0.0
        if tx_mbps < 0:
            tx_mbps = 0.0
        if rx_pps < 0:
            rx_pps = 0.0
        if tx_pps < 0:
            tx_pps = 0.0

        return {
            'net_rx_mbps': round(rx_mbps, 4),
            'net_tx_mbps': round(tx_mbps, 4),
            'net_rx_pps': round(rx_pps, 2),
            'net_tx_pps': round(tx_pps, 2),
        }

    # ─── Memory cubing ───────────────────────────────────────────────

    @staticmethod
    def cube_memory(meminfo):
        """
        Convert /proc/meminfo values to usable metrics.

        Port of cube.go CubeMeminfo(). No delta needed — direct conversion.

        Formula from sysstat/cube.go:
            nousedmem = MemFree + Buffers + Cached + Slab
            if nousedmem > MemTotal: nousedmem = MemTotal
            MemUsed = MemTotal - nousedmem

        Args:
            meminfo: dict with mem_total, mem_free, mem_buffers, mem_cached, mem_slab (in kB)
                     OR already in MB — caller's responsibility to pass consistent units

        Returns:
            dict with mem_total, mem_used, mem_available, mem_buffers, mem_cached (in MB)
            or None if inputs are invalid
        """
        if meminfo is None:
            return None

        mem_total = meminfo.get('mem_total', 0)
        mem_free = meminfo.get('mem_free', 0)
        mem_buffers = meminfo.get('mem_buffers', 0)
        mem_cached = meminfo.get('mem_cached', 0)
        mem_slab = meminfo.get('mem_slab', 0)
        mem_available = meminfo.get('mem_available', 0)

        if mem_total <= 0:
            return None

        # nousedmem calculation from cube.go
        nousedmem = mem_free + mem_buffers + mem_cached + mem_slab
        if nousedmem > mem_total:
            nousedmem = mem_total

        mem_used = mem_total - nousedmem

        return {
            'mem_total': round(mem_total, 2),
            'mem_used': round(mem_used, 2),
            'mem_available': round(mem_available, 2),
            'mem_buffers': round(mem_buffers, 2),
            'mem_cached': round(mem_cached, 2),
        }
