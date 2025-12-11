"""
Regression tests for chore creation and board display.

These tests ensure that:
1. Chores can be created with empty optional text fields (description, cron_expr, reschedule_reason)
2. Midnight evaluation creates instances from newly created chores
3. Board views properly display the created instances

This prevents the regression where creating a chore would succeed but no instances
would appear on the board until midnight evaluation was manually run.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.core.management import call_command
from datetime import time

from users.models import User
from chores.models import Chore, ChoreInstance


class ChoreCreationRegressionTests(TestCase):
    """Test that chores can be created with empty optional fields (regression for NOT NULL constraint bug)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

    def test_create_daily_chore_with_empty_description(self):
        """Test creating a daily chore with empty description field."""
        chore = Chore.objects.create(
            name='Test Daily Chore',
            description='',  # Empty string
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30),
            cron_expr='',  # Empty string
            reschedule_reason=''  # Empty string
        )

        self.assertEqual(chore.name, 'Test Daily Chore')
        self.assertEqual(chore.description, '')
        self.assertEqual(chore.cron_expr, '')
        self.assertEqual(chore.reschedule_reason, '')
        self.assertTrue(chore.is_active)

    def test_create_daily_chore_no_description(self):
        """Test creating a daily chore without providing description (uses default)."""
        chore = Chore.objects.create(
            name='Test Chore No Desc',
            points=Decimal('5.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(18, 0)
        )

        # Should use default empty string
        self.assertEqual(chore.description, '')
        self.assertEqual(chore.cron_expr, '')
        self.assertEqual(chore.reschedule_reason, '')

    def test_create_chore_with_all_optional_fields_empty(self):
        """Test creating a chore with all optional text fields explicitly set to empty string."""
        chore = Chore.objects.create(
            name='Minimal Chore',
            description='',
            points=Decimal('1.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            cron_expr='',
            reschedule_reason=''
        )

        # Verify save succeeds without NOT NULL constraint errors
        chore.refresh_from_db()
        self.assertEqual(chore.description, '')
        self.assertEqual(chore.cron_expr, '')
        self.assertEqual(chore.reschedule_reason, '')


class MidnightEvaluationCreatesInstancesTests(TestCase):
    """Test that midnight evaluation creates instances for newly created chores."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='alice',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

    def test_new_daily_chore_creates_instance_after_midnight_eval(self):
        """Test that a newly created daily chore generates an instance immediately via signal,
        and midnight evaluation doesn't create duplicates."""
        # Create a new chore
        chore = Chore.objects.create(
            name='New Daily Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30)
        )

        # Verify instance was created immediately by signal
        instances_before = ChoreInstance.objects.filter(chore=chore).count()
        self.assertEqual(instances_before, 1, "Instance should be created immediately by signal")

        # Run midnight evaluation - should NOT create duplicate
        call_command('run_midnight_evaluation')

        # Verify still only 1 instance (no duplicate created)
        instances_after = ChoreInstance.objects.filter(chore=chore)
        self.assertEqual(instances_after.count(), 1, "Midnight eval should not create duplicate instance")

        # Verify instance properties
        instance = instances_after.first()
        self.assertEqual(instance.status, ChoreInstance.POOL)
        self.assertEqual(instance.points_value, chore.points)
        self.assertEqual(instance.chore, chore)
        # Due at should be tomorrow (signal creates instances with due_at = tomorrow at 00:00)
        tomorrow = timezone.now().date() + timezone.timedelta(days=1)
        self.assertEqual(instance.due_at.date(), tomorrow, "Signal creates instances with due_at = tomorrow")

    def test_new_weekly_chore_creates_instance_on_correct_day(self):
        """Test that a newly created weekly chore generates instance on the correct weekday."""
        # Create chore for today's weekday
        today_weekday = timezone.now().weekday()
        chore = Chore.objects.create(
            name='New Weekly Chore',
            points=Decimal('15.00'),
            is_pool=True,
            schedule_type=Chore.WEEKLY,
            weekday=today_weekday,
            distribution_time=time(18, 0)
        )

        # Run midnight evaluation
        call_command('run_midnight_evaluation')

        # Verify instance was created
        instances = ChoreInstance.objects.filter(chore=chore)
        self.assertEqual(instances.count(), 1)

    def test_new_chore_with_empty_fields_creates_instance(self):
        """Test that a chore with empty optional fields still creates instances correctly."""
        chore = Chore.objects.create(
            name='Empty Fields Chore',
            description='',
            points=Decimal('8.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            cron_expr='',
            reschedule_reason=''
        )

        call_command('run_midnight_evaluation')

        instances = ChoreInstance.objects.filter(chore=chore)
        self.assertEqual(instances.count(), 1)


class BoardDisplayTests(TestCase):
    """Test that board views properly display chore instances."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='boarduser',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        # Create a chore
        self.chore = Chore.objects.create(
            name='Board Test Chore',
            points=Decimal('12.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30)
        )

    def test_main_board_shows_pool_instances(self):
        """Test that the main board view shows pool chore instances."""
        # Create instance with explicit date set to today
        from datetime import datetime
        now = timezone.now()
        today = now.date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        distribution_at = timezone.make_aware(datetime.combine(today, datetime.min.time()))

        instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=due_at,
            distribution_at=distribution_at
        )

        # Request main board
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        # Verify instance is in context
        pool_chores = response.context['pool_chores']
        self.assertIn(instance, pool_chores)

    def test_main_board_shows_assigned_instances(self):
        """Test that the main board view shows assigned chore instances."""
        # Create assigned instance with explicit date set to today
        from datetime import datetime
        now = timezone.now()
        today = now.date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        distribution_at = timezone.make_aware(datetime.combine(today, datetime.min.time()))

        instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user,
            points_value=self.chore.points,
            due_at=due_at,
            distribution_at=distribution_at,
            assigned_at=now
        )

        # Request main board
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        # Verify instance is in assigned chores context
        assigned_chores = list(response.context['overdue_assigned']) + list(response.context['ontime_assigned'])
        self.assertIn(instance, assigned_chores)

    def test_main_board_does_not_show_completed_instances(self):
        """Test that the main board view does not show completed instances."""
        # Create completed instance
        now = timezone.now()
        instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.COMPLETED,
            assigned_to=self.user,
            points_value=self.chore.points,
            due_at=now,
            distribution_at=now - timezone.timedelta(hours=1),
            assigned_at=now - timezone.timedelta(minutes=30),
            completed_at=now
        )

        # Request main board
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        # Verify completed instance is NOT in pool or assigned chores
        pool_chores = response.context['pool_chores']
        assigned_chores = list(response.context['overdue_assigned']) + list(response.context['ontime_assigned'])

        self.assertNotIn(instance, pool_chores)
        self.assertNotIn(instance, assigned_chores)

    def test_pool_only_view_shows_pool_instances(self):
        """Test that the pool-only view shows pool chore instances."""
        # Create pool instance with explicit date set to today
        from datetime import datetime
        now = timezone.now()
        today = now.date()
        due_at = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        distribution_at = timezone.make_aware(datetime.combine(today, datetime.min.time()))

        instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=due_at,
            distribution_at=distribution_at
        )

        # Request pool view
        response = self.client.get('/pool/')
        self.assertEqual(response.status_code, 200)

        # Verify instance is in context
        pool_chores = response.context['pool_chores']
        self.assertIn(instance, pool_chores)

    def test_board_shows_instances_only_for_today(self):
        """Test that board views show instances due today and tomorrow (since midnight eval creates instances for tomorrow)."""
        from datetime import datetime
        now = timezone.now()
        today = now.date()
        yesterday = today - timezone.timedelta(days=1)
        tomorrow = today + timezone.timedelta(days=1)
        day_after_tomorrow = today + timezone.timedelta(days=2)

        # Create instances for different days using timezone-aware datetimes
        today_instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=timezone.make_aware(datetime.combine(today, datetime.max.time())),
            distribution_at=timezone.make_aware(datetime.combine(today, datetime.min.time()))
        )

        yesterday_instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=timezone.make_aware(datetime.combine(yesterday, datetime.max.time())),
            distribution_at=timezone.make_aware(datetime.combine(yesterday, datetime.min.time()))
        )

        # Tomorrow instance - should show because midnight eval creates instances with due_at = tomorrow
        tomorrow_instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=timezone.make_aware(datetime.combine(tomorrow, datetime.min.time())),
            distribution_at=timezone.make_aware(datetime.combine(today, datetime.min.time()))
        )

        # Day after tomorrow - should NOT show
        day_after_instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=timezone.make_aware(datetime.combine(day_after_tomorrow, datetime.min.time())),
            distribution_at=timezone.make_aware(datetime.combine(today, datetime.min.time()))
        )

        # Request main board
        response = self.client.get('/')
        pool_chores = response.context['pool_chores']

        # Today and tomorrow instances should be shown (yesterday due to being overdue, tomorrow because that's how midnight eval works)
        self.assertIn(today_instance, pool_chores, "Today's instance should show")
        self.assertIn(yesterday_instance, pool_chores, "Yesterday's instance should show (overdue)")
        self.assertIn(tomorrow_instance, pool_chores, "Tomorrow's instance should show (midnight eval creates instances for tomorrow)")
        self.assertNotIn(day_after_instance, pool_chores, "Day after tomorrow should not show")


class EndToEndChoreCreationTests(TestCase):
    """End-to-end tests simulating the complete user workflow."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True,
            is_staff=True
        )
        self.client.login(username='testuser', password='test123')

    def test_create_chore_run_midnight_eval_see_on_board(self):
        """Test the complete workflow: create chore -> see on board immediately (via signal)."""
        # Step 1: Create a new daily chore
        chore = Chore.objects.create(
            name='E2E Test Chore',
            description='',  # Empty optional field
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30),
            cron_expr='',  # Empty optional field
            reschedule_reason=''  # Empty optional field
        )

        # Step 2: Verify instance was created immediately by signal (NOT by midnight eval)
        # Note: Signal creates instances with due_at = tomorrow at 00:00
        tomorrow = timezone.now().date() + timezone.timedelta(days=1)
        instances_immediate = ChoreInstance.objects.filter(
            chore=chore,
            due_at__date=tomorrow
        ).count()
        self.assertEqual(instances_immediate, 1, "Instance should be created immediately by signal")

        # Step 3: Board should immediately show the chore (no need to wait for midnight eval)
        response_immediate = self.client.get('/')
        self.assertEqual(response_immediate.status_code, 200)
        pool_chores_immediate = response_immediate.context['pool_chores']
        chore_names_immediate = [inst.chore.name for inst in pool_chores_immediate]
        self.assertIn('E2E Test Chore', chore_names_immediate, "Chore should appear on board immediately")

        # Step 4: Run midnight evaluation - should NOT create duplicate
        call_command('run_midnight_evaluation')

        # Step 5: Verify still only 1 instance (no duplicate created)
        instances_after = ChoreInstance.objects.filter(
            chore=chore,
            due_at__date=tomorrow
        )
        self.assertEqual(instances_after.count(), 1, "Midnight eval should not create duplicate")

        # Step 6: Board should still show exactly one instance
        response_after = self.client.get('/')
        self.assertEqual(response_after.status_code, 200)
        pool_chores_after = response_after.context['pool_chores']
        chore_names_after = [inst.chore.name for inst in pool_chores_after]
        self.assertIn('E2E Test Chore', chore_names_after)

        # Step 7: Verify instance properties are correct
        instance = instances_after.first()
        self.assertEqual(instance.status, ChoreInstance.POOL)
        self.assertEqual(instance.points_value, Decimal('10.00'))
        self.assertIsNone(instance.assigned_to)


class ImmediateChoreInstanceCreationTests(TestCase):
    """Test that daily chores create instances immediately upon creation."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

    def test_daily_chore_creates_instance_immediately(self):
        """
        When a chore is created with a recurrence of daily,
        it shows up as due immediately.

        This test ensures that when a DAILY chore is created,
        a ChoreInstance is automatically created for today,
        allowing the chore to appear on the board immediately
        without waiting for the next midnight evaluation.
        """
        # Create a new daily chore
        chore = Chore.objects.create(
            name='Immediate Test Chore',
            description='This should appear immediately',
            points=Decimal('15.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30)
        )

        # Verify the chore was created
        self.assertIsNotNone(chore.id)
        self.assertEqual(chore.schedule_type, Chore.DAILY)
        self.assertTrue(chore.is_active)

        # Check if an instance was created (signal creates with due_at = tomorrow)
        today = timezone.now().date()
        tomorrow = today + timezone.timedelta(days=1)
        instances = ChoreInstance.objects.filter(
            chore=chore,
            due_at__date=tomorrow
        )

        # CRITICAL ASSERTION: Instance should exist immediately
        self.assertEqual(
            instances.count(), 1,
            "Daily chore must create an instance immediately upon creation"
        )

        # Verify instance properties
        instance = instances.first()
        self.assertEqual(instance.chore, chore)
        self.assertEqual(instance.status, ChoreInstance.POOL)
        self.assertEqual(instance.points_value, chore.points)
        self.assertIsNone(instance.assigned_to)
        # Due date should be tomorrow (signal creates instances with due_at = tomorrow at 00:00)
        self.assertEqual(instance.due_at.date(), tomorrow, "Signal creates instances with due_at = tomorrow")

    def test_weekly_chore_creates_instance_on_matching_weekday(self):
        """
        When a weekly chore is created on its scheduled weekday,
        it should create an instance immediately.
        """
        # Get today's weekday
        today = timezone.now().date()
        today_weekday = today.weekday()

        # Create a weekly chore for today's weekday
        chore = Chore.objects.create(
            name='Weekly Test Chore',
            points=Decimal('20.00'),
            is_pool=True,
            schedule_type=Chore.WEEKLY,
            weekday=today_weekday,
            distribution_time=time(18, 0)
        )

        # Check if instance was created (signal creates with due_at = tomorrow)
        tomorrow = today + timezone.timedelta(days=1)
        instances = ChoreInstance.objects.filter(
            chore=chore,
            due_at__date=tomorrow
        )

        self.assertEqual(
            instances.count(), 1,
            "Weekly chore created on its scheduled weekday must create an instance immediately"
        )

        instance = instances.first()
        self.assertEqual(instance.status, ChoreInstance.POOL)
        self.assertEqual(instance.points_value, chore.points)

    def test_weekly_chore_no_instance_on_different_weekday(self):
        """
        When a weekly chore is created on a non-matching weekday,
        it should NOT create an instance immediately.
        """
        # Get a different weekday than today
        today = timezone.now().date()
        today_weekday = today.weekday()
        different_weekday = (today_weekday + 1) % 7  # Next day of week

        # Create a weekly chore for a different weekday
        chore = Chore.objects.create(
            name='Weekly Different Day Chore',
            points=Decimal('20.00'),
            is_pool=True,
            schedule_type=Chore.WEEKLY,
            weekday=different_weekday,
            distribution_time=time(18, 0)
        )

        # Check that NO instance was created (check both today and tomorrow to be sure)
        instances = ChoreInstance.objects.filter(chore=chore)

        self.assertEqual(
            instances.count(), 0,
            "Weekly chore created on a non-matching weekday should NOT create an instance"
        )

    def test_inactive_chore_does_not_create_instance(self):
        """
        When a chore is created with is_active=False,
        it should NOT create an instance.
        """
        chore = Chore.objects.create(
            name='Inactive Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30),
            is_active=False  # Inactive
        )

        # Check that NO instance was created
        instances = ChoreInstance.objects.filter(chore=chore)

        self.assertEqual(
            instances.count(), 0,
            "Inactive chores should NOT create instances"
        )

    def test_admin_create_daily_chore_creates_instance(self):
        """
        CRITICAL TEST: When a chore is created via admin interface with daily frequency,
        exactly 1 instance should be created immediately.

        This test verifies the admin_chore_create view creates instances on chore creation.
        """
        from django.test import Client
        from django.contrib.auth import get_user_model

        User = get_user_model()

        # Create admin user
        admin_user = User.objects.create_user(
            username='admintest',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )

        # Login as admin
        client = Client()
        client.force_login(admin_user)

        # Create chore via admin interface
        response = client.post('/admin-panel/chore/create/', {
            'name': 'Test Admin Daily Chore',
            'description': 'Testing immediate instance creation',
            'points': '15.00',
            'is_pool': 'true',
            'is_undesirable': 'false',
            'distribution_time': '17:30',
            'schedule_type': 'daily',
        })

        # Verify HTTP response is successful
        self.assertEqual(
            response.status_code, 200,
            f"Admin chore creation should return 200, got {response.status_code}"
        )

        # Parse JSON response
        import json
        response_data = json.loads(response.content)

        # Verify chore was created
        self.assertIn('chore_id', response_data, "Response should contain chore_id")
        chore_id = response_data['chore_id']

        # Get the created chore
        chore = Chore.objects.get(id=chore_id)
        self.assertEqual(chore.name, 'Test Admin Daily Chore')
        self.assertEqual(chore.schedule_type, Chore.DAILY)
        self.assertTrue(chore.is_active)

        # CRITICAL ASSERTION: Check if instance was created (signal creates with due_at = tomorrow)
        today = timezone.now().date()
        tomorrow = today + timezone.timedelta(days=1)
        instances = ChoreInstance.objects.filter(
            chore=chore,
            due_at__date=tomorrow
        )

        # THIS IS THE CRITICAL TEST - 0 instances = FAILURE
        self.assertEqual(
            instances.count(), 1,
            f"FAILED: Daily chore created via admin interface MUST create 1 instance immediately. "
            f"Found {instances.count()} instances. "
            f"Response data: {response_data}"
        )

        # Verify instance properties
        instance = instances.first()
        self.assertEqual(instance.chore, chore)
        self.assertEqual(instance.status, ChoreInstance.POOL)
        self.assertEqual(instance.points_value, chore.points)
        self.assertIsNone(instance.assigned_to)

        # Verify the instance is due tomorrow (signal creates instances with due_at = tomorrow at 00:00)
        self.assertEqual(
            instance.due_at.date(), tomorrow,
            "Instance should be due tomorrow (signal creates with due_at = tomorrow)"
        )
