"""
Tests for Bug #6: Inactive Chore Instances Remain on Board

This test verifies that when a chore template is deactivated (is_active=False),
its ChoreInstances should not appear on the board.
"""
from django.test import TestCase, Client
from django.utils import timezone
from datetime import datetime, timedelta
from chores.models import Chore, ChoreInstance
from users.models import User


class InactiveChoreInstanceTest(TestCase):
    """Test that inactive chores' instances don't appear on the board"""

    def setUp(self):
        """Set up test data"""
        # Create test users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )

        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@test.com',
            password='testpass123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        # Create test client
        self.client = Client()

    def test_inactive_pool_chore_not_on_board(self):
        """
        CRITICAL TEST: When a pool chore is deactivated, its instances
        should not appear on the board.
        """
        # Create an active pool chore
        chore = Chore.objects.create(
            name='Test Pool Chore',
            description='This is a test pool chore',
            points=10.00,
            is_pool=True,
            is_active=True,
            schedule_type=Chore.DAILY,
            distribution_time=datetime.now().time()
        )

        # Create a ChoreInstance for today
        today = timezone.now().date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))

        instance = ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.POOL,
            points_value=chore.points,
            due_at=due_at,
            distribution_at=timezone.now()
        )

        # Verify instance appears on board (before deactivation)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        # Get pool chores from context
        pool_chores = response.context.get('pool_chores', [])
        pool_chore_ids = [c.id for c in pool_chores]

        self.assertIn(
            instance.id,
            pool_chore_ids,
            "Active chore instance should appear on board"
        )

        # Deactivate the chore
        chore.is_active = False
        chore.save()

        # Verify instance DOES NOT appear on board (after deactivation)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        pool_chores = response.context.get('pool_chores', [])
        pool_chore_ids = [c.id for c in pool_chores]

        self.assertNotIn(
            instance.id,
            pool_chore_ids,
            "FAILED: Inactive chore instance should NOT appear on board"
        )

    def test_inactive_assigned_chore_not_on_board(self):
        """
        Test that when an assigned chore is deactivated, its instances
        should not appear on the board.
        """
        # Create an active assigned chore
        chore = Chore.objects.create(
            name='Test Assigned Chore',
            description='This is a test assigned chore',
            points=15.00,
            is_pool=False,
            assigned_to=self.user1,
            is_active=True,
            schedule_type=Chore.DAILY,
            distribution_time=datetime.now().time()
        )

        # Create a ChoreInstance for today
        today = timezone.now().date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))

        instance = ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user1,
            points_value=chore.points,
            due_at=due_at,
            distribution_at=timezone.now()
        )

        # Verify instance appears on board (before deactivation)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        # Get all chores from context (pool + assigned)
        all_chores = list(response.context.get('pool_chores', [])) + \
                     list(response.context.get('overdue_assigned', [])) + \
                     list(response.context.get('ontime_assigned', []))
        all_chore_ids = [c.id for c in all_chores]

        self.assertIn(
            instance.id,
            all_chore_ids,
            "Active assigned chore instance should appear on board"
        )

        # Deactivate the chore
        chore.is_active = False
        chore.save()

        # Verify instance DOES NOT appear on board (after deactivation)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        all_chores = list(response.context.get('pool_chores', [])) + \
                     list(response.context.get('overdue_assigned', [])) + \
                     list(response.context.get('ontime_assigned', []))
        all_chore_ids = [c.id for c in all_chores]

        self.assertNotIn(
            instance.id,
            all_chore_ids,
            "FAILED: Inactive assigned chore instance should NOT appear on board"
        )

    def test_reactivated_chore_appears_on_board(self):
        """
        Test that when a chore is reactivated, its existing instances
        reappear on the board.
        """
        # Create an active chore
        chore = Chore.objects.create(
            name='Test Reactivation Chore',
            description='This chore will be deactivated then reactivated',
            points=20.00,
            is_pool=True,
            is_active=True,
            schedule_type=Chore.DAILY,
            distribution_time=datetime.now().time()
        )

        # Create a ChoreInstance for today
        today = timezone.now().date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))

        instance = ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.POOL,
            points_value=chore.points,
            due_at=due_at,
            distribution_at=timezone.now()
        )

        # Deactivate the chore
        chore.is_active = False
        chore.save()

        # Verify instance does not appear
        response = self.client.get('/')
        pool_chores = response.context.get('pool_chores', [])
        pool_chore_ids = [c.id for c in pool_chores]
        self.assertNotIn(instance.id, pool_chore_ids)

        # Reactivate the chore
        chore.is_active = True
        chore.save()

        # Verify instance reappears on board
        response = self.client.get('/')
        pool_chores = response.context.get('pool_chores', [])
        pool_chore_ids = [c.id for c in pool_chores]

        self.assertIn(
            instance.id,
            pool_chore_ids,
            "Reactivated chore instance should appear on board again"
        )

    def test_completed_instances_unaffected_by_deactivation(self):
        """
        Test that completed instances are not affected by chore deactivation.
        Completed instances should remain in history regardless of chore status.
        """
        # Create an active chore
        chore = Chore.objects.create(
            name='Test Completed Chore',
            description='This chore will be completed then deactivated',
            points=25.00,
            is_pool=True,
            is_active=True,
            schedule_type=Chore.DAILY,
            distribution_time=datetime.now().time()
        )

        # Create a completed ChoreInstance
        today = timezone.now().date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))

        instance = ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.COMPLETED,
            points_value=chore.points,
            due_at=due_at,
            distribution_at=timezone.now()
        )

        # Deactivate the chore
        chore.is_active = False
        chore.save()

        # Verify completed instance still exists (not filtered out)
        # Note: This test assumes completed instances are queryable separately
        # and should remain accessible regardless of chore active status
        completed_instance = ChoreInstance.objects.filter(
            id=instance.id,
            status=ChoreInstance.COMPLETED
        ).first()

        self.assertIsNotNone(
            completed_instance,
            "Completed instance should still exist after chore deactivation"
        )

    def test_multiple_instances_filtered_on_deactivation(self):
        """
        Test that when a chore with multiple instances is deactivated,
        all its pending instances disappear from the board.
        """
        # Create an active chore
        chore = Chore.objects.create(
            name='Test Multi Instance Chore',
            description='This chore has multiple instances',
            points=30.00,
            is_pool=True,
            is_active=True,
            schedule_type=Chore.DAILY,
            distribution_time=datetime.now().time()
        )

        # Create multiple instances for different days
        today = timezone.now().date()
        instances = []

        for i in range(3):
            due_date = today + timedelta(days=i)
            due_at = timezone.make_aware(datetime.combine(due_date, datetime.max.time()))

            instance = ChoreInstance.objects.create(
                chore=chore,
                status=ChoreInstance.POOL,
                points_value=chore.points,
                due_at=due_at,
                distribution_at=timezone.now()
            )
            instances.append(instance)

        # Deactivate the chore
        chore.is_active = False
        chore.save()

        # Verify NONE of the instances appear on board
        response = self.client.get('/')
        pool_chores = response.context.get('pool_chores', [])
        pool_chore_ids = [c.id for c in pool_chores]

        for instance in instances:
            self.assertNotIn(
                instance.id,
                pool_chore_ids,
                f"Instance {instance.id} should not appear after chore deactivation"
            )

    def test_admin_panel_shows_inactive_chore_status(self):
        """
        Test that the admin panel correctly shows inactive status for deactivated chores.
        This verifies that the UI reflects the database state accurately.
        """
        self.client.force_login(self.admin_user)

        # Create and deactivate a chore
        chore = Chore.objects.create(
            name='Test Admin Panel Chore',
            description='Testing admin panel display',
            points=35.00,
            is_pool=True,
            is_active=True,
            schedule_type=Chore.DAILY,
            distribution_time=datetime.now().time()
        )

        # Deactivate
        chore.is_active = False
        chore.save()

        # Fetch the chore list page
        response = self.client.get('/admin-panel/chores/')
        self.assertEqual(response.status_code, 200)

        # Verify the chore appears in the list with inactive status
        chores_list = response.context.get('chores', [])
        test_chore = next((c for c in chores_list if c.id == chore.id), None)

        self.assertIsNotNone(test_chore, "Deactivated chore should appear in admin list")
        self.assertFalse(test_chore.is_active, "Chore should show as inactive")
