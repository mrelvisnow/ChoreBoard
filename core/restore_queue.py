"""
Restore queue manager for handling database restores on server startup.
"""
import json
import os
import logging
from pathlib import Path
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

RESTORE_QUEUE_FILE = Path(settings.BASE_DIR) / 'data' / 'restore_queue.json'


class RestoreQueue:
    """Manager for queueing and executing database restores."""

    @staticmethod
    def queue_restore(backup_id, backup_filepath, create_safety_backup=True):
        """
        Queue a backup for restore on next server restart.

        Args:
            backup_id: ID of the Backup model instance
            backup_filepath: Full path to the backup file
            create_safety_backup: Whether to create a safety backup before restoring

        Returns:
            bool: True if queued successfully
        """
        try:
            queue_data = {
                'backup_id': backup_id,
                'backup_filepath': backup_filepath,
                'create_safety_backup': create_safety_backup,
                'queued_at': timezone.now().isoformat()
            }

            # Ensure data directory exists
            RESTORE_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Write to queue file
            with open(RESTORE_QUEUE_FILE, 'w') as f:
                json.dump(queue_data, f, indent=2)

            logger.info(f"Queued restore of backup {backup_id} (safety_backup={create_safety_backup})")
            return True

        except Exception as e:
            logger.error(f"Error queueing restore: {str(e)}")
            return False

    @staticmethod
    def get_queued_restore():
        """
        Get queued restore if exists.

        Returns:
            dict or None: Queue data if exists, None otherwise
        """
        try:
            if not RESTORE_QUEUE_FILE.exists():
                return None

            with open(RESTORE_QUEUE_FILE, 'r') as f:
                return json.load(f)

        except Exception as e:
            logger.error(f"Error reading restore queue: {str(e)}")
            return None

    @staticmethod
    def clear_queue():
        """Remove queued restore."""
        try:
            if RESTORE_QUEUE_FILE.exists():
                os.remove(RESTORE_QUEUE_FILE)
                logger.info("Cleared restore queue")

        except Exception as e:
            logger.error(f"Error clearing restore queue: {str(e)}")

    @staticmethod
    def execute_queued_restore():
        """
        Execute queued restore during server startup.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            queue_data = RestoreQueue.get_queued_restore()
            if not queue_data:
                return False, "No restore queued"

            backup_filepath = queue_data['backup_filepath']
            create_safety_backup = queue_data.get('create_safety_backup', True)

            logger.info(f"Executing queued restore from: {backup_filepath}")

            # Verify backup file exists
            if not os.path.exists(backup_filepath):
                RestoreQueue.clear_queue()
                return False, f"Backup file not found: {backup_filepath}"

            # Get current database path
            db_path = settings.DATABASES['default']['NAME']

            # Create safety backup if requested
            if create_safety_backup:
                logger.info("Creating safety backup before restore...")
                try:
                    from django.core.management import call_command
                    call_command('create_backup', notes='Auto-backup before restore', auto=False)
                    logger.info("✓ Safety backup created")
                except Exception as e:
                    logger.warning(f"Could not create safety backup: {str(e)}")

            # Close all database connections before replacing file
            from django.db import connections
            logger.info("Closing all database connections...")
            for conn in connections.all():
                conn.close()

            # Replace database file using atomic operation
            import shutil
            import tempfile
            import sqlite3

            logger.info(f"Replacing database: {db_path}")

            # Create temp file in same directory to ensure same filesystem
            db_dir = os.path.dirname(db_path)
            temp_fd, temp_path = tempfile.mkstemp(suffix='.sqlite3', dir=db_dir)
            os.close(temp_fd)

            try:
                # Copy to temp file first
                shutil.copy2(backup_filepath, temp_path)

                # Verify integrity of copied file
                logger.info("Verifying copied database integrity...")
                conn = sqlite3.connect(temp_path)
                cursor = conn.cursor()
                cursor.execute('PRAGMA integrity_check')
                integrity_result = cursor.fetchone()[0]
                conn.close()

                if integrity_result != 'ok':
                    os.remove(temp_path)
                    RestoreQueue.clear_queue()
                    return False, f"Copied database failed integrity check: {integrity_result}"

                # Atomic replace (on same filesystem)
                os.replace(temp_path, db_path)

            except Exception as e:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise e

            # Clear queue
            RestoreQueue.clear_queue()

            logger.info("✓ Database restored successfully")
            return True, "Database restored successfully"

        except Exception as e:
            logger.error(f"Error executing restore: {str(e)}", exc_info=True)
            RestoreQueue.clear_queue()
            return False, f"Restore failed: {str(e)}"
