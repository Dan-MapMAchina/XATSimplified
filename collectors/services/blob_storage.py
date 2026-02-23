"""
Azure Blob Storage service for exporting trickle session data.
"""
import io
import csv
import json
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class BlobStorageService:
    """Handles Azure Blob Storage operations for performance data export."""

    def __init__(self, blob_target):
        self.blob_target = blob_target
        self._client = None

    def _get_container_client(self):
        """Get or create the Azure Blob container client."""
        if self._client:
            return self._client

        from azure.storage.blob import ContainerClient, BlobServiceClient

        if self.blob_target.auth_method == 'key_vault':
            from core.settings import get_secret_from_keyvault
            conn_str = get_secret_from_keyvault(
                self.blob_target.key_vault_secret_name
            )
            if not conn_str:
                raise ValueError(
                    f"Could not retrieve secret "
                    f"'{self.blob_target.key_vault_secret_name}' from Key Vault"
                )
            service_client = BlobServiceClient.from_connection_string(conn_str)
            self._client = service_client.get_container_client(
                self.blob_target.container_name
            )

        elif self.blob_target.auth_method == 'sas_token':
            account_url = (
                f"https://{self.blob_target.account_name}.blob.core.windows.net"
            )
            self._client = ContainerClient(
                account_url=account_url,
                container_name=self.blob_target.container_name,
                credential=self.blob_target.sas_token,
            )

        elif self.blob_target.auth_method == 'connection_string':
            service_client = BlobServiceClient.from_connection_string(
                self.blob_target.connection_string
            )
            self._client = service_client.get_container_client(
                self.blob_target.container_name
            )

        else:
            raise ValueError(
                f"Unknown auth method: {self.blob_target.auth_method}"
            )

        return self._client

    def test_connection(self):
        """Test connectivity to the blob target. Returns (success, message)."""
        try:
            container_client = self._get_container_client()
            container_client.get_container_properties()
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def generate_blob_path(self, session, export_format='csv'):
        """Generate the blob path for a session export."""
        collector_id = str(session.collector.id)
        date = session.started_at
        session_id = str(session.id)

        path_parts = []
        if self.blob_target.path_prefix:
            path_parts.append(self.blob_target.path_prefix.strip('/'))

        path_parts.extend([
            collector_id,
            date.strftime('%Y'),
            date.strftime('%m'),
            date.strftime('%d'),
            f"{session_id}.{export_format}",
        ])

        return '/'.join(path_parts)

    def export_session_csv(self, session, metrics_queryset):
        """Export session metrics to CSV bytes. Returns (data, record_count)."""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'timestamp', 'collector_id',
            'cpu_user', 'cpu_system', 'cpu_iowait', 'cpu_idle', 'cpu_steal',
            'mem_total', 'mem_used', 'mem_available', 'mem_buffers', 'mem_cached',
            'disk_read_bytes', 'disk_write_bytes', 'disk_read_ops', 'disk_write_ops',
            'net_rx_bytes', 'net_tx_bytes', 'net_rx_packets', 'net_tx_packets',
        ])

        record_count = 0
        for m in metrics_queryset.iterator():
            writer.writerow([
                m.timestamp.isoformat(),
                str(session.collector.id),
                m.cpu_user if m.cpu_user is not None else '',
                m.cpu_system if m.cpu_system is not None else '',
                m.cpu_iowait if m.cpu_iowait is not None else '',
                m.cpu_idle if m.cpu_idle is not None else '',
                m.cpu_steal if m.cpu_steal is not None else '',
                m.mem_total if m.mem_total is not None else '',
                m.mem_used if m.mem_used is not None else '',
                m.mem_available if m.mem_available is not None else '',
                m.mem_buffers if m.mem_buffers is not None else '',
                m.mem_cached if m.mem_cached is not None else '',
                m.disk_read_bytes if m.disk_read_bytes is not None else '',
                m.disk_write_bytes if m.disk_write_bytes is not None else '',
                m.disk_read_ops if m.disk_read_ops is not None else '',
                m.disk_write_ops if m.disk_write_ops is not None else '',
                m.net_rx_bytes if m.net_rx_bytes is not None else '',
                m.net_tx_bytes if m.net_tx_bytes is not None else '',
                m.net_rx_packets if m.net_rx_packets is not None else '',
                m.net_tx_packets if m.net_tx_packets is not None else '',
            ])
            record_count += 1

        return output.getvalue().encode('utf-8'), record_count

    def export_session_json(self, session, metrics_queryset):
        """Export session metrics to JSON bytes. Returns (data, record_count)."""
        records = []
        for m in metrics_queryset.iterator():
            records.append({
                'timestamp': m.timestamp.isoformat(),
                'collector_id': str(session.collector.id),
                'cpu': {
                    'user': m.cpu_user, 'system': m.cpu_system,
                    'iowait': m.cpu_iowait, 'idle': m.cpu_idle,
                    'steal': m.cpu_steal,
                },
                'memory': {
                    'total_mb': m.mem_total, 'used_mb': m.mem_used,
                    'available_mb': m.mem_available, 'buffers_mb': m.mem_buffers,
                    'cached_mb': m.mem_cached,
                },
                'disk': {
                    'read_bytes': m.disk_read_bytes,
                    'write_bytes': m.disk_write_bytes,
                    'read_ops': m.disk_read_ops,
                    'write_ops': m.disk_write_ops,
                },
                'network': {
                    'rx_bytes': m.net_rx_bytes, 'tx_bytes': m.net_tx_bytes,
                    'rx_packets': m.net_rx_packets,
                    'tx_packets': m.net_tx_packets,
                },
            })

        json_data = json.dumps({
            'session_id': str(session.id),
            'collector_id': str(session.collector.id),
            'collector_name': session.collector.name,
            'started_at': session.started_at.isoformat(),
            'ended_at': (
                session.ended_at.isoformat() if session.ended_at else None
            ),
            'sample_count': len(records),
            'exported_at': timezone.now().isoformat(),
            'metrics': records,
        }, indent=2).encode('utf-8')

        return json_data, len(records)

    def upload_blob(self, blob_path, data, content_type='text/csv'):
        """Upload data to Azure Blob Storage. Returns the blob URL."""
        from azure.storage.blob import ContentSettings

        container_client = self._get_container_client()
        blob_client = container_client.get_blob_client(blob_path)

        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

        return blob_client.url
