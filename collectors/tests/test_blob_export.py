"""
Tests for Azure Blob Storage export endpoints.

Covers:
- BlobTarget CRUD (list, create, detail, update, delete)
- BlobTarget validation (credentials required per auth_method)
- BlobTarget PATCH without re-sending credentials
- BlobTarget connectivity test
- Session export to blob (async background)
- Session export status
- Ownership isolation (user A can't see user B's targets)
- BlobStorageService (CSV/JSON export, path generation)
"""
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from django_tenants.test.cases import TenantTestCase

from collectors.models import (
    Collector, TrickleSession, PerformanceMetric,
    BlobTarget, BlobExport, Tenant, Domain,
)
from collectors.services.blob_storage import BlobStorageService

User = get_user_model()

# The test tenant domain used by TenantTestCase
TENANT_TEST_DOMAIN = 'tenant.test.com'


class BlobExportTestBase(TenantTestCase):
    """Base class with shared fixtures for blob export tests.

    Uses APIClient with HTTP_HOST header instead of TenantClient
    to avoid get_primary_domain() schema routing issues.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = 'test-tenant'

    @classmethod
    def setup_domain(cls, domain):
        domain.is_primary = True

    def setUp(self):
        super().setUp()
        # Use APIClient with explicit HTTP_HOST instead of TenantClient
        # TenantTestCase.setUpClass already sets connection to tenant schema
        self.client = APIClient(HTTP_HOST=TENANT_TEST_DOMAIN)

        # Create users
        self.user = User.objects.create_user(
            username='testuser', password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otheruser', password='otherpass123'
        )

        # Create collector and session
        self.collector = Collector.objects.create(
            owner=self.user,
            name='test-collector',
            api_key='test-api-key-12345678',
        )

        self.session = TrickleSession.objects.create(
            collector=self.collector,
            status=TrickleSession.Status.COMPLETED,
            sample_count=5,
        )
        # started_at is auto_now_add, so update it explicitly
        started_at = timezone.now() - timedelta(hours=1)
        ended_at = timezone.now()
        TrickleSession.objects.filter(pk=self.session.pk).update(
            started_at=started_at, ended_at=ended_at,
        )
        self.session.refresh_from_db()

        # Create metrics for the session
        for i in range(5):
            PerformanceMetric.objects.create(
                collector=self.collector,
                timestamp=self.session.started_at + timedelta(minutes=i * 12),
                cpu_user=25.0 + i,
                cpu_system=10.0,
                cpu_idle=65.0 - i,
                mem_total=16384.0,
                mem_used=8192.0 + i * 100,
                mem_available=8192.0 - i * 100,
            )

        # Authenticate
        self._authenticate(self.user)

    def _authenticate(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}'
        )

    def _create_blob_target(self, user=None, **kwargs):
        defaults = {
            'owner': user or self.user,
            'name': f'test-target-{uuid.uuid4().hex[:6]}',
            'account_name': 'teststorageacct',
            'container_name': 'perfdata',
            'auth_method': 'connection_string',
            'connection_string': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net',
        }
        defaults.update(kwargs)
        return BlobTarget.objects.create(**defaults)


# =============================================================================
# BlobTarget CRUD Tests
# =============================================================================

class BlobTargetListCreateTests(BlobExportTestBase):
    """Tests for GET/POST /api/v1/blob-targets/"""

    def test_list_empty(self):
        resp = self.client.get('/api/v1/blob-targets/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['count'], 0)

    def test_list_returns_own_targets(self):
        self._create_blob_target(name='my-target')
        self._create_blob_target(user=self.other_user, name='other-target')

        resp = self.client.get('/api/v1/blob-targets/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['name'], 'my-target')

    def test_create_with_connection_string(self):
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'new-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'connection_string',
            'connection_string': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json()
        self.assertEqual(data['name'], 'new-target')
        self.assertEqual(data['owner_username'], 'testuser')
        # connection_string should be write-only
        self.assertNotIn('connection_string', data)

    def test_create_with_sas_token(self):
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'sas-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'sas_token',
            'sas_token': 'sv=2021-06-08&ss=b&srt=sco&sp=rwdlacyx&se=2027-01-01&sig=fake',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('sas_token', resp.json())

    def test_create_with_key_vault(self):
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'kv-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'key_vault',
            'key_vault_secret_name': 'my-storage-secret',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_requires_auth(self):
        client = APIClient(HTTP_HOST=TENANT_TEST_DOMAIN)  # No auth
        resp = client.post('/api/v1/blob-targets/', {
            'name': 'no-auth-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'connection_string',
            'connection_string': 'fake',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_duplicate_name_fails(self):
        self._create_blob_target(name='dup-name')
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'dup-name',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'connection_string',
            'connection_string': 'fake',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class BlobTargetDetailTests(BlobExportTestBase):
    """Tests for GET/PUT/PATCH/DELETE /api/v1/blob-targets/<uuid>/"""

    def test_get_detail(self):
        target = self._create_blob_target(name='detail-target')
        resp = self.client.get(f'/api/v1/blob-targets/{target.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['name'], 'detail-target')

    def test_get_other_users_target_404(self):
        target = self._create_blob_target(user=self.other_user, name='other')
        resp = self.client.get(f'/api/v1/blob-targets/{target.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_non_credential_fields(self):
        target = self._create_blob_target()
        resp = self.client.patch(f'/api/v1/blob-targets/{target.id}/', {
            'export_format': 'json',
            'path_prefix': 'new/prefix',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['export_format'], 'json')
        self.assertEqual(resp.json()['path_prefix'], 'new/prefix')

    def test_patch_update_credentials(self):
        target = self._create_blob_target()
        resp = self.client.patch(f'/api/v1/blob-targets/{target.id}/', {
            'connection_string': 'NewConnectionString=test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        target.refresh_from_db()
        self.assertEqual(target.connection_string, 'NewConnectionString=test')

    def test_patch_change_auth_method_requires_new_creds(self):
        target = self._create_blob_target()
        resp = self.client.patch(f'/api/v1/blob-targets/{target.id}/', {
            'auth_method': 'sas_token',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sas_token', resp.json())

    def test_patch_change_auth_method_with_creds(self):
        target = self._create_blob_target()
        resp = self.client.patch(f'/api/v1/blob-targets/{target.id}/', {
            'auth_method': 'sas_token',
            'sas_token': 'sv=2021-06-08&sig=fake',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        target.refresh_from_db()
        self.assertEqual(target.auth_method, 'sas_token')

    def test_delete(self):
        target = self._create_blob_target()
        resp = self.client.delete(f'/api/v1/blob-targets/{target.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BlobTarget.objects.filter(pk=target.id).exists())

    def test_delete_other_users_target_404(self):
        target = self._create_blob_target(user=self.other_user)
        resp = self.client.delete(f'/api/v1/blob-targets/{target.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(BlobTarget.objects.filter(pk=target.id).exists())


# =============================================================================
# BlobTarget Validation Tests
# =============================================================================

class BlobTargetValidationTests(BlobExportTestBase):
    """Tests for BlobTargetSerializer validation."""

    def test_create_missing_connection_string(self):
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'bad-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'connection_string',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('connection_string', resp.json())

    def test_create_missing_sas_token(self):
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'bad-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'sas_token',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sas_token', resp.json())

    def test_create_missing_key_vault_secret(self):
        resp = self.client.post('/api/v1/blob-targets/', {
            'name': 'bad-target',
            'account_name': 'storageacct',
            'container_name': 'mycontainer',
            'auth_method': 'key_vault',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('key_vault_secret_name', resp.json())

    def test_credentials_are_write_only(self):
        target = self._create_blob_target(
            sas_token='secret-sas',
            connection_string='secret-conn',
        )
        resp = self.client.get(f'/api/v1/blob-targets/{target.id}/')
        data = resp.json()
        self.assertNotIn('sas_token', data)
        self.assertNotIn('connection_string', data)


# =============================================================================
# BlobTarget Connectivity Test
# =============================================================================

class BlobTargetTestConnectivityTests(BlobExportTestBase):
    """Tests for POST /api/v1/blob-targets/<uuid>/test/"""

    @patch('collectors.services.blob_storage.BlobStorageService.test_connection')
    def test_connectivity_success(self, mock_test):
        mock_test.return_value = (True, 'Connection successful')
        target = self._create_blob_target()

        resp = self.client.post(f'/api/v1/blob-targets/{target.id}/test/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['message'], 'Connection successful')

        target.refresh_from_db()
        self.assertTrue(target.last_test_success)
        self.assertIsNotNone(target.last_tested_at)

    @patch('collectors.services.blob_storage.BlobStorageService.test_connection')
    def test_connectivity_failure(self, mock_test):
        mock_test.return_value = (False, 'Auth failed')
        target = self._create_blob_target()

        resp = self.client.post(f'/api/v1/blob-targets/{target.id}/test/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['message'], 'Auth failed')

        target.refresh_from_db()
        self.assertFalse(target.last_test_success)

    def test_connectivity_other_users_target_404(self):
        target = self._create_blob_target(user=self.other_user)
        resp = self.client.post(f'/api/v1/blob-targets/{target.id}/test/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# =============================================================================
# Session Export Tests
# =============================================================================

class SessionExportBlobTests(BlobExportTestBase):
    """Tests for POST /api/v1/sessions/<uuid>/export-blob/"""

    @patch('collectors.api.views.SessionExportBlobView._run_export')
    def test_export_returns_202(self, mock_run):
        target = self._create_blob_target()
        resp = self.client.post(
            f'/api/v1/sessions/{self.session.id}/export-blob/',
            {'blob_target_id': str(target.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        data = resp.json()
        self.assertIn('id', data)
        self.assertEqual(data['session'], str(self.session.id))

    @patch('collectors.api.views.SessionExportBlobView._run_export')
    def test_export_creates_record(self, mock_run):
        target = self._create_blob_target()
        resp = self.client.post(
            f'/api/v1/sessions/{self.session.id}/export-blob/',
            {'blob_target_id': str(target.id)},
            format='json',
        )
        export_id = resp.json()['id']
        export = BlobExport.objects.get(pk=export_id)
        self.assertEqual(export.session, self.session)
        self.assertEqual(export.blob_target, target)
        self.assertEqual(export.owner, self.user)

    def test_export_nonexistent_session_404(self):
        target = self._create_blob_target()
        fake_id = uuid.uuid4()
        resp = self.client.post(
            f'/api/v1/sessions/{fake_id}/export-blob/',
            {'blob_target_id': str(target.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_export_nonexistent_blob_target_404(self):
        fake_id = uuid.uuid4()
        resp = self.client.post(
            f'/api/v1/sessions/{self.session.id}/export-blob/',
            {'blob_target_id': str(fake_id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_export_missing_blob_target_id(self):
        resp = self.client.post(
            f'/api/v1/sessions/{self.session.id}/export-blob/',
            {},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_other_users_session_404(self):
        other_collector = Collector.objects.create(
            owner=self.other_user,
            name='other-collector',
            api_key='other-api-key-12345678',
        )
        other_session = TrickleSession.objects.create(
            collector=other_collector,
            status=TrickleSession.Status.COMPLETED,
        )
        target = self._create_blob_target()
        resp = self.client.post(
            f'/api/v1/sessions/{other_session.id}/export-blob/',
            {'blob_target_id': str(target.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# =============================================================================
# Session Export Status Tests
# =============================================================================

class SessionExportBlobStatusTests(BlobExportTestBase):
    """Tests for GET /api/v1/sessions/<uuid>/export-blob/status/"""

    def test_status_empty(self):
        resp = self.client.get(
            f'/api/v1/sessions/{self.session.id}/export-blob/status/'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data['session_id'], str(self.session.id))
        self.assertEqual(len(data['exports']), 0)

    def test_status_with_exports(self):
        target = self._create_blob_target()
        BlobExport.objects.create(
            owner=self.user,
            session=self.session,
            blob_target=target,
            status=BlobExport.Status.COMPLETED,
            records_exported=5,
            file_size_bytes=1024,
            export_format='csv',
        )
        BlobExport.objects.create(
            owner=self.user,
            session=self.session,
            blob_target=target,
            status=BlobExport.Status.FAILED,
            error_message='Auth failed',
        )

        resp = self.client.get(
            f'/api/v1/sessions/{self.session.id}/export-blob/status/'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(len(data['exports']), 2)

    def test_status_nonexistent_session_404(self):
        resp = self.client.get(
            f'/api/v1/sessions/{uuid.uuid4()}/export-blob/status/'
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# =============================================================================
# BlobStorageService Unit Tests
# =============================================================================

class BlobStorageServiceTests(BlobExportTestBase):
    """Unit tests for BlobStorageService."""

    def test_generate_blob_path_csv(self):
        target = self._create_blob_target(path_prefix='exports')
        service = BlobStorageService(target)
        path = service.generate_blob_path(self.session, 'csv')

        self.assertIn(str(self.collector.id), path)
        self.assertIn(str(self.session.id), path)
        self.assertTrue(path.startswith('exports/'))
        self.assertTrue(path.endswith('.csv'))

    def test_generate_blob_path_json(self):
        target = self._create_blob_target(path_prefix='')
        service = BlobStorageService(target)
        path = service.generate_blob_path(self.session, 'json')

        self.assertNotIn('//', path)
        self.assertTrue(path.endswith('.json'))

    def test_generate_blob_path_includes_date(self):
        target = self._create_blob_target(path_prefix='data')
        service = BlobStorageService(target)
        path = service.generate_blob_path(self.session, 'csv')

        year = self.session.started_at.strftime('%Y')
        month = self.session.started_at.strftime('%m')
        day = self.session.started_at.strftime('%d')
        self.assertIn(f'/{year}/{month}/{day}/', path)

    def test_export_session_csv(self):
        target = self._create_blob_target()
        service = BlobStorageService(target)
        metrics = PerformanceMetric.objects.filter(
            collector=self.collector,
        ).order_by('timestamp')

        data, count = service.export_session_csv(self.session, metrics)

        self.assertEqual(count, 5)
        self.assertIsInstance(data, bytes)
        lines = data.decode('utf-8').strip().split('\n')
        self.assertEqual(len(lines), 6)  # header + 5 rows
        header = lines[0]
        self.assertIn('timestamp', header)
        self.assertIn('cpu_user', header)
        # Verify rate columns are present in CSV header
        for col in [
            'disk_read_iops', 'disk_write_iops',
            'disk_read_mbps', 'disk_write_mbps',
            'net_rx_mbps', 'net_tx_mbps',
            'net_rx_pps', 'net_tx_pps',
        ]:
            self.assertIn(col, header, f"Missing rate column: {col}")

    def test_export_session_json(self):
        target = self._create_blob_target()
        service = BlobStorageService(target)
        metrics = PerformanceMetric.objects.filter(
            collector=self.collector,
        ).order_by('timestamp')

        data, count = service.export_session_json(self.session, metrics)

        self.assertEqual(count, 5)
        self.assertIsInstance(data, bytes)
        import json
        parsed = json.loads(data)
        self.assertEqual(parsed['session_id'], str(self.session.id))
        self.assertEqual(len(parsed['metrics']), 5)
        self.assertIn('cpu', parsed['metrics'][0])
        self.assertIn('memory', parsed['metrics'][0])
        # Verify rate fields present in disk and network objects
        metric = parsed['metrics'][0]
        self.assertIn('disk', metric)
        for key in ['read_iops', 'write_iops', 'read_mbps', 'write_mbps']:
            self.assertIn(key, metric['disk'], f"Missing disk rate key: {key}")
        self.assertIn('network', metric)
        for key in ['rx_mbps', 'tx_mbps', 'rx_pps', 'tx_pps']:
            self.assertIn(key, metric['network'], f"Missing network rate key: {key}")

    def test_export_session_csv_with_rate_fields(self):
        """Verify that populated rate fields appear in CSV data rows."""
        target = self._create_blob_target()
        service = BlobStorageService(target)

        # Update a metric to have rate fields
        metric = PerformanceMetric.objects.filter(
            collector=self.collector,
        ).order_by('timestamp').first()
        metric.disk_read_iops = 150.5
        metric.disk_write_iops = 75.0
        metric.disk_read_mbps = 12.3
        metric.disk_write_mbps = 6.1
        metric.net_rx_mbps = 100.0
        metric.net_tx_mbps = 50.0
        metric.net_rx_pps = 5000.0
        metric.net_tx_pps = 2500.0
        metric.save()

        metrics = PerformanceMetric.objects.filter(
            collector=self.collector,
        ).order_by('timestamp')

        data, count = service.export_session_csv(self.session, metrics)
        lines = data.decode('utf-8').strip().split('\n')

        # Parse header to find column indices
        import csv
        import io
        reader = csv.reader(io.StringIO(lines[0] + '\n' + lines[1]))
        header = next(reader)
        first_row = next(reader)

        iops_idx = header.index('disk_read_iops')
        self.assertEqual(first_row[iops_idx], '150.5')
        rx_mbps_idx = header.index('net_rx_mbps')
        self.assertEqual(first_row[rx_mbps_idx], '100.0')

    def test_export_session_json_with_rate_fields(self):
        """Verify that populated rate fields appear in JSON output."""
        target = self._create_blob_target()
        service = BlobStorageService(target)

        # Update a metric to have rate fields
        metric = PerformanceMetric.objects.filter(
            collector=self.collector,
        ).order_by('timestamp').first()
        metric.disk_read_iops = 150.5
        metric.net_rx_mbps = 100.0
        metric.save()

        metrics = PerformanceMetric.objects.filter(
            collector=self.collector,
        ).order_by('timestamp')

        data, count = service.export_session_json(self.session, metrics)
        import json
        parsed = json.loads(data)
        first_metric = parsed['metrics'][0]

        self.assertEqual(first_metric['disk']['read_iops'], 150.5)
        self.assertEqual(first_metric['network']['rx_mbps'], 100.0)
        # Fields without data should be None
        self.assertIsNone(first_metric['disk']['write_iops'])
        self.assertIsNone(first_metric['network']['tx_pps'])

    def test_export_session_csv_empty(self):
        target = self._create_blob_target()
        service = BlobStorageService(target)
        empty_qs = PerformanceMetric.objects.none()

        data, count = service.export_session_csv(self.session, empty_qs)

        self.assertEqual(count, 0)
        lines = data.decode('utf-8').strip().split('\n')
        self.assertEqual(len(lines), 1)  # header only

    @patch('collectors.services.blob_storage.BlobStorageService._get_container_client')
    def test_upload_blob(self, mock_get_client):
        mock_blob_client = MagicMock()
        mock_blob_client.url = 'https://test.blob.core.windows.net/container/path.csv'
        mock_container = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_get_client.return_value = mock_container

        target = self._create_blob_target()
        service = BlobStorageService(target)

        url = service.upload_blob('path.csv', b'data', 'text/csv')

        self.assertEqual(url, 'https://test.blob.core.windows.net/container/path.csv')
        mock_blob_client.upload_blob.assert_called_once()

    @patch('collectors.services.blob_storage.BlobStorageService._get_container_client')
    def test_test_connection_success(self, mock_get_client):
        mock_container = MagicMock()
        mock_get_client.return_value = mock_container

        target = self._create_blob_target()
        service = BlobStorageService(target)
        success, message = service.test_connection()

        self.assertTrue(success)
        self.assertEqual(message, 'Connection successful')

    @patch('collectors.services.blob_storage.BlobStorageService._get_container_client')
    def test_test_connection_failure(self, mock_get_client):
        mock_container = MagicMock()
        mock_container.get_container_properties.side_effect = Exception('Auth error')
        mock_get_client.return_value = mock_container

        target = self._create_blob_target()
        service = BlobStorageService(target)
        success, message = service.test_connection()

        self.assertFalse(success)
        self.assertIn('Auth error', message)


# =============================================================================
# Background Export Integration Test
# =============================================================================

class BlobExportBackgroundTests(BlobExportTestBase):
    """Tests for the background export worker (_run_export)."""

    @patch('collectors.services.blob_storage.BlobStorageService.upload_blob')
    def test_run_export_success(self, mock_upload):
        mock_upload.return_value = 'https://test.blob.core.windows.net/c/path.csv'

        target = self._create_blob_target()
        export = BlobExport.objects.create(
            owner=self.user,
            session=self.session,
            blob_target=target,
            status=BlobExport.Status.IN_PROGRESS,
            started_at=timezone.now(),
            export_format='csv',
        )

        # _run_export is an instance method; create a view instance to call it
        from collectors.api.views import SessionExportBlobView
        view = SessionExportBlobView()
        view._run_export(str(export.id))

        export.refresh_from_db()
        self.assertEqual(export.status, BlobExport.Status.COMPLETED)
        self.assertEqual(export.records_exported, 5)
        self.assertGreater(export.file_size_bytes, 0)
        self.assertIsNotNone(export.completed_at)
        self.assertEqual(
            export.blob_url,
            'https://test.blob.core.windows.net/c/path.csv'
        )

        # Session should be marked as SAVED
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, TrickleSession.Status.SAVED)

    @patch('collectors.services.blob_storage.BlobStorageService.upload_blob')
    def test_run_export_failure(self, mock_upload):
        mock_upload.side_effect = Exception('Upload failed: auth error')

        target = self._create_blob_target()
        export = BlobExport.objects.create(
            owner=self.user,
            session=self.session,
            blob_target=target,
            status=BlobExport.Status.IN_PROGRESS,
            started_at=timezone.now(),
            export_format='csv',
        )

        from collectors.api.views import SessionExportBlobView
        view = SessionExportBlobView()
        view._run_export(str(export.id))

        export.refresh_from_db()
        self.assertEqual(export.status, BlobExport.Status.FAILED)
        self.assertIn('Upload failed', export.error_message)
        self.assertEqual(export.retry_count, 1)
        self.assertIsNotNone(export.completed_at)

    @patch('collectors.services.blob_storage.BlobStorageService.upload_blob')
    def test_run_export_json_format(self, mock_upload):
        mock_upload.return_value = 'https://test.blob.core.windows.net/c/path.json'

        target = self._create_blob_target()
        export = BlobExport.objects.create(
            owner=self.user,
            session=self.session,
            blob_target=target,
            status=BlobExport.Status.IN_PROGRESS,
            started_at=timezone.now(),
            export_format='json',
        )

        from collectors.api.views import SessionExportBlobView
        view = SessionExportBlobView()
        view._run_export(str(export.id))

        export.refresh_from_db()
        self.assertEqual(export.status, BlobExport.Status.COMPLETED)
        self.assertEqual(export.records_exported, 5)
        # Verify JSON was passed (content_type is 3rd positional arg)
        call_args = mock_upload.call_args
        self.assertEqual(call_args.args[2], 'application/json')
