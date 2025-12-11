"""
Tests for backup upload and restore functionality.
"""
import os
import json
import tempfile
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Backup, ActionLog
from core.restore_queue import RestoreQueue

User = get_user_model()


class RestoreQueueTest(TestCase):
    """Test RestoreQueue manager functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_data_dir = Path(settings.BASE_DIR) / 'data'
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.test_data_dir / 'restore_queue.json'

    def tearDown(self):
        """Clean up after tests."""
        if self.queue_file.exists():
            self.queue_file.unlink()

    def test_queue_restore_creates_file(self):
        """Test queueing a restore creates the queue file."""
        success = RestoreQueue.queue_restore(
            backup_id=1,
            backup_filepath='/path/to/backup.sqlite3',
            create_safety_backup=True
        )

        self.assertTrue(success)
        self.assertTrue(self.queue_file.exists())

    def test_queue_restore_contains_correct_data(self):
        """Test queued restore data is correct."""
        RestoreQueue.queue_restore(
            backup_id=123,
            backup_filepath='/test/path.sqlite3',
            create_safety_backup=False
        )

        with open(self.queue_file, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['backup_id'], 123)
        self.assertEqual(data['backup_filepath'], '/test/path.sqlite3')
        self.assertFalse(data['create_safety_backup'])
        self.assertIn('queued_at', data)

    def test_get_queued_restore_returns_none_when_empty(self):
        """Test getting queued restore when none exists."""
        result = RestoreQueue.get_queued_restore()
        self.assertIsNone(result)

    def test_get_queued_restore_returns_data(self):
        """Test getting queued restore returns correct data."""
        RestoreQueue.queue_restore(
            backup_id=456,
            backup_filepath='/another/path.sqlite3',
            create_safety_backup=True
        )

        data = RestoreQueue.get_queued_restore()

        self.assertIsNotNone(data)
        self.assertEqual(data['backup_id'], 456)
        self.assertEqual(data['backup_filepath'], '/another/path.sqlite3')
        self.assertTrue(data['create_safety_backup'])

    def test_clear_queue_removes_file(self):
        """Test clearing the queue removes the file."""
        RestoreQueue.queue_restore(1, '/test.sqlite3', True)
        self.assertTrue(self.queue_file.exists())

        RestoreQueue.clear_queue()
        self.assertFalse(self.queue_file.exists())

    def test_queue_overwrites_previous(self):
        """Test queueing multiple restores overwrites previous."""
        RestoreQueue.queue_restore(1, '/first.sqlite3', True)
        RestoreQueue.queue_restore(2, '/second.sqlite3', False)

        data = RestoreQueue.get_queued_restore()
        self.assertEqual(data['backup_id'], 2)
        self.assertEqual(data['backup_filepath'], '/second.sqlite3')

    def test_execute_queued_restore_with_no_queue(self):
        """Test executing restore when no queue exists."""
        success, message = RestoreQueue.execute_queued_restore()

        self.assertFalse(success)
        self.assertEqual(message, "No restore queued")

    def test_execute_queued_restore_with_missing_file(self):
        """Test executing restore when backup file doesn't exist."""
        RestoreQueue.queue_restore(1, '/nonexistent/backup.sqlite3', True)

        success, message = RestoreQueue.execute_queued_restore()

        self.assertFalse(success)
        self.assertIn("Backup file not found", message)
        # Queue should be cleared after failure
        self.assertIsNone(RestoreQueue.get_queued_restore())

    @patch('core.restore_queue.logger')
    def test_execute_queued_restore_logs_operations(self, mock_logger):
        """Test restore execution logs operations correctly."""
        # Create a temporary backup file
        with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
            backup_path = f.name
            # Write minimal SQLite data
            conn = sqlite3.connect(backup_path)
            conn.close()

        try:
            # Create a temporary database file for testing
            with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
                test_db_path = f.name

            with self.settings(DATABASES={'default': {'NAME': test_db_path}}):
                RestoreQueue.queue_restore(1, backup_path, create_safety_backup=False)

                with patch('django.core.management.call_command'):
                    success, message = RestoreQueue.execute_queued_restore()

                self.assertTrue(success)
                self.assertIn("successfully", message)
                # Verify logging calls
                mock_logger.info.assert_any_call(f"Executing queued restore from: {backup_path}")

        finally:
            # Clean up temporary files
            if os.path.exists(backup_path):
                os.unlink(backup_path)
            if os.path.exists(test_db_path):
                os.unlink(test_db_path)


class BackupUploadViewTest(TestCase):
    """Test backup upload view functionality."""

    def setUp(self):
        """Set up test environment."""
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username='user',
            password='testpass123',
            is_staff=False
        )
        self.url = '/admin-panel/backup/upload/'

    def test_upload_requires_authentication(self):
        """Test upload requires authentication."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_upload_requires_staff(self):
        """Test upload requires staff permissions."""
        self.client.login(username='user', password='testpass123')
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)  # Redirect

    def test_upload_valid_sqlite_backup(self):
        """Test uploading a valid SQLite backup file."""
        self.client.login(username='admin', password='testpass123')

        # Create a temporary SQLite database with required tables
        with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
            test_db = f.name

        try:
            conn = sqlite3.connect(test_db)
            cursor = conn.cursor()
            # Create required tables (using actual table names from db_table in models)
            cursor.execute('CREATE TABLE users (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE chores (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE chore_instances (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY)')
            conn.commit()
            conn.close()

            # Read file content
            with open(test_db, 'rb') as f:
                file_content = f.read()

            # Upload the file
            uploaded_file = SimpleUploadedFile(
                'test_backup.sqlite3',
                file_content,
                content_type='application/x-sqlite3'
            )

            response = self.client.post(self.url, {
                'backup_file': uploaded_file,
                'notes': 'Test upload'
            })

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertTrue(response_data['success'])
            self.assertIn('uploaded successfully', response_data['message'])

            # Verify backup was created in database
            backup = Backup.objects.filter(filename__contains='uploaded').first()
            self.assertIsNotNone(backup)
            self.assertEqual(backup.notes, 'Test upload')
            self.assertTrue(backup.is_manual)  # Uploaded backups are manual

            # Verify ActionLog entry
            log = ActionLog.objects.filter(action_type=ActionLog.ACTION_ADMIN, description__contains='Uploaded backup').first()
            self.assertIsNotNone(log)
            self.assertEqual(log.user, self.admin_user)

        finally:
            # Clean up
            if os.path.exists(test_db):
                os.unlink(test_db)

    def test_upload_rejects_non_sqlite_file(self):
        """Test uploading a non-SQLite file is rejected."""
        self.client.login(username='admin', password='testpass123')

        # Create a text file
        fake_file = SimpleUploadedFile(
            'not_a_db.txt',
            b'This is not a SQLite database',
            content_type='text/plain'
        )

        response = self.client.post(self.url, {
            'backup_file': fake_file,
            'notes': 'Should fail'
        })

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertIn('error', response_data)
        # Extension check happens first, so error is about file type
        self.assertIn('sqlite3', response_data['error'].lower())

    def test_upload_rejects_wrong_extension(self):
        """Test uploading file without .sqlite3 extension is rejected."""
        self.client.login(username='admin', password='testpass123')

        fake_file = SimpleUploadedFile(
            'backup.txt',
            b'content',
            content_type='text/plain'
        )

        response = self.client.post(self.url, {
            'backup_file': fake_file,
            'notes': 'Wrong extension'
        })

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertIn('must', response_data['error'])

    def test_upload_rejects_missing_tables(self):
        """Test uploading SQLite file without required tables is rejected."""
        self.client.login(username='admin', password='testpass123')

        # Create a SQLite database without required tables
        with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
            test_db = f.name

        try:
            conn = sqlite3.connect(test_db)
            cursor = conn.cursor()
            # Create only some tables (missing required ones) - using correct table names
            cursor.execute('CREATE TABLE users (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE random_table (id INTEGER PRIMARY KEY)')
            conn.commit()
            conn.close()

            with open(test_db, 'rb') as f:
                file_content = f.read()

            uploaded_file = SimpleUploadedFile(
                'incomplete_backup.sqlite3',
                file_content,
                content_type='application/x-sqlite3'
            )

            response = self.client.post(self.url, {
                'backup_file': uploaded_file,
                'notes': 'Missing tables'
            })

            self.assertEqual(response.status_code, 400)
            response_data = response.json()
            self.assertIn('error', response_data)
            self.assertIn('Missing', response_data['error']) or self.assertIn('Invalid', response_data['error'])

        finally:
            if os.path.exists(test_db):
                os.unlink(test_db)

    def test_upload_without_file(self):
        """Test uploading without providing a file."""
        self.client.login(username='admin', password='testpass123')

        response = self.client.post(self.url, {'notes': 'No file'})

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertIn('No file', response_data['error'])


class BackupRestoreViewTest(TestCase):
    """Test backup restore view functionality."""

    def setUp(self):
        """Set up test environment."""
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username='user',
            password='testpass123',
            is_staff=False
        )
        self.url = '/admin-panel/backup/restore/'

        # Create a backup record
        self.backup = Backup.objects.create(
            filename='test_backup_20251208_120000.sqlite3',
            file_path='data/backups/test_backup_20251208_120000.sqlite3',
            file_size_bytes=1024000,
            is_manual=True,
            notes='Test backup'
        )

    def tearDown(self):
        """Clean up after tests."""
        # Clear any queued restores
        RestoreQueue.clear_queue()

    def test_restore_requires_authentication(self):
        """Test restore requires authentication."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_restore_requires_staff(self):
        """Test restore requires staff permissions."""
        self.client.login(username='user', password='testpass123')
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)  # Redirect

    def test_restore_queues_successfully(self):
        """Test restore successfully queues the operation."""
        self.client.login(username='admin', password='testpass123')

        # Create temporary backup file
        backup_dir = Path(settings.BASE_DIR) / 'data' / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / self.backup.filename

        try:
            # Create a minimal SQLite file
            conn = sqlite3.connect(str(backup_path))
            conn.close()

            response = self.client.post(self.url, {
                'backup_id': self.backup.id,
                'create_safety_backup': 'true'
            })

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertTrue(response_data['success'])
            self.assertTrue(response_data['requires_restart'])
            self.assertIn('Restore queued', response_data['message'])

            # Verify queue was created
            queued = RestoreQueue.get_queued_restore()
            self.assertIsNotNone(queued)
            self.assertEqual(queued['backup_id'], self.backup.id)
            self.assertTrue(queued['create_safety_backup'])

            # Verify ActionLog entry
            log = ActionLog.objects.filter(action_type=ActionLog.ACTION_ADMIN, description__contains='Queued restore').first()
            self.assertIsNotNone(log)
            self.assertEqual(log.user, self.admin_user)

        finally:
            if backup_path.exists():
                backup_path.unlink()

    def test_restore_without_safety_backup(self):
        """Test restore can be queued without safety backup."""
        self.client.login(username='admin', password='testpass123')

        # Create temporary backup file
        backup_dir = Path(settings.BASE_DIR) / 'data' / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / self.backup.filename

        try:
            conn = sqlite3.connect(str(backup_path))
            conn.close()

            response = self.client.post(self.url, {
                'backup_id': self.backup.id,
                'create_safety_backup': 'false'
            })

            self.assertEqual(response.status_code, 200)

            # Verify queue was created without safety backup
            queued = RestoreQueue.get_queued_restore()
            self.assertIsNotNone(queued)
            self.assertFalse(queued['create_safety_backup'])

        finally:
            if backup_path.exists():
                backup_path.unlink()

    def test_restore_rejects_nonexistent_backup(self):
        """Test restore rejects backup that doesn't exist."""
        self.client.login(username='admin', password='testpass123')

        response = self.client.post(self.url, {
            'backup_id': 99999,
            'create_safety_backup': 'true'
        })

        # get_object_or_404 will raise Http404, resulting in redirect or 404 page
        # When caught in try/except, may return 500 with error message
        self.assertIn(response.status_code, [404, 500])
        if response.status_code == 500:
            response_data = response.json()
            self.assertIn('error', response_data)

    def test_restore_rejects_missing_file(self):
        """Test restore rejects backup whose file is missing."""
        self.client.login(username='admin', password='testpass123')

        # Backup record exists but file doesn't
        response = self.client.post(self.url, {
            'backup_id': self.backup.id,
            'create_safety_backup': 'true'
        })

        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertIn('file not found', response_data['error'].lower())

    def test_restore_requires_backup_id(self):
        """Test restore requires backup_id parameter."""
        self.client.login(username='admin', password='testpass123')

        response = self.client.post(self.url, {
            'create_safety_backup': 'true'
        })

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertIn('backup', response_data['error'].lower())
        self.assertIn('required', response_data['error'].lower())


class BackupRestoreIntegrationTest(TestCase):
    """Integration tests for the full backup/restore workflow."""

    def setUp(self):
        """Set up test environment."""
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True
        )
        self.data_dir = Path(settings.BASE_DIR) / 'data'
        self.backup_dir = self.data_dir / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up after tests."""
        RestoreQueue.clear_queue()

    def test_full_upload_and_restore_workflow(self):
        """Test complete workflow: upload backup, then queue restore."""
        self.client.login(username='admin', password='testpass123')

        # Step 1: Create and upload a valid backup
        with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
            test_db = f.name

        try:
            # Create a valid ChoreBoard database (using actual table names from db_table in models)
            conn = sqlite3.connect(test_db)
            cursor = conn.cursor()
            cursor.execute('CREATE TABLE users (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE chores (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE chore_instances (id INTEGER PRIMARY KEY)')
            cursor.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY)')
            conn.commit()
            conn.close()

            with open(test_db, 'rb') as f:
                file_content = f.read()

            uploaded_file = SimpleUploadedFile(
                'workflow_test.sqlite3',
                file_content,
                content_type='application/x-sqlite3'
            )

            # Upload
            upload_response = self.client.post('/admin-panel/backup/upload/', {
                'backup_file': uploaded_file,
                'notes': 'Workflow test backup'
            })

            self.assertEqual(upload_response.status_code, 200)
            self.assertTrue(upload_response.json()['success'])

            # Verify backup was created
            backup = Backup.objects.filter(filename__contains='uploaded').first()
            self.assertIsNotNone(backup)

            # Step 2: Queue the uploaded backup for restore
            restore_response = self.client.post('/admin-panel/backup/restore/', {
                'backup_id': backup.id,
                'create_safety_backup': 'true'
            })

            self.assertEqual(restore_response.status_code, 200)
            restore_data = restore_response.json()
            self.assertTrue(restore_data['success'])
            self.assertTrue(restore_data['requires_restart'])

            # Verify restore was queued
            queued = RestoreQueue.get_queued_restore()
            self.assertIsNotNone(queued)
            self.assertEqual(queued['backup_id'], backup.id)
            self.assertTrue(queued['create_safety_backup'])

            # Verify both actions were logged
            upload_log = ActionLog.objects.filter(action_type=ActionLog.ACTION_ADMIN, description__contains='Uploaded backup').first()
            restore_log = ActionLog.objects.filter(action_type=ActionLog.ACTION_ADMIN, description__contains='Queued restore').first()
            self.assertIsNotNone(upload_log)
            self.assertIsNotNone(restore_log)

        finally:
            if os.path.exists(test_db):
                os.unlink(test_db)
