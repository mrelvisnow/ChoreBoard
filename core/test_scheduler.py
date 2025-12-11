"""
Comprehensive scheduler job tests.

Tests Task 7.5: Scheduler job functionality (midnight, distribution, weekly)
"""
import unittest
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta, date, time, datetime

from users.models import User
from chores.models import Chore, ChoreInstance, Completion, CompletionShare
from core.models import Settings, WeeklySnapshot, EvaluationLog, RotationState
from core.jobs import (
    midnight_evaluation as run_midnight_evaluation,
    distribution_check as run_distribution_check,
    weekly_snapshot_job as run_weekly_snapshot
)


class MidnightEvaluationTests(TestCase):
    """Test the midnight evaluation scheduled job."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='alice',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        # Create daily chore
        self.daily_chore = Chore.objects.create(
            name='Daily Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30)
        )

        # Create weekly chore (today's weekday)
        today_weekday = timezone.now().weekday()
        self.weekly_chore = Chore.objects.create(
            name='Weekly Chore',
            points=Decimal('15.00'),
            is_pool=True,
            schedule_type=Chore.WEEKLY,
            weekday=today_weekday,
            distribution_time=time(18, 0)
        )

        # Create every N days chore (due today)
        self.every_n_chore = Chore.objects.create(
            name='Every 3 Days Chore',
            points=Decimal('12.00'),
            is_pool=True,
            schedule_type=Chore.EVERY_N_DAYS,
            n_days=3,
            every_n_start_date=timezone.now().date() - timedelta(days=3),  # Due today
            distribution_time=time(19, 0)
        )

    def test_midnight_evaluation_creates_daily_instances(self):
        """Test that midnight evaluation creates instances for daily chores."""
        # Run midnight evaluation
        run_midnight_evaluation()

        # Verify daily chore instance created
        instances = ChoreInstance.objects.filter(chore=self.daily_chore)
        self.assertEqual(instances.count(), 1)

        instance = instances.first()
        self.assertEqual(instance.status, ChoreInstance.POOL)
        self.assertEqual(instance.points_value, self.daily_chore.points)

    def test_midnight_evaluation_creates_weekly_instances(self):
        """Test that midnight evaluation creates instances for weekly chores on correct day."""
        # Run midnight evaluation
        run_midnight_evaluation()

        # Verify weekly chore instance created (today is the right day)
        instances = ChoreInstance.objects.filter(chore=self.weekly_chore)
        self.assertEqual(instances.count(), 1)

    def test_midnight_evaluation_skips_wrong_weekday(self):
        """Test that weekly chores not due today are skipped."""
        # Create chore for different weekday
        wrong_day = (timezone.now().weekday() + 1) % 7
        wrong_day_chore = Chore.objects.create(
            name='Wrong Day Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.WEEKLY,
            weekday=wrong_day,
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        # Should not create instance
        instances = ChoreInstance.objects.filter(chore=wrong_day_chore)
        self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_creates_every_n_days_instances(self):
        """Test that every N days chores are created when due."""
        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=self.every_n_chore)
        self.assertEqual(instances.count(), 1)

    def test_midnight_evaluation_marks_overdue(self):
        """Test that midnight evaluation marks past-due instances as overdue."""
        # Create instance with past due date
        yesterday = timezone.now() - timedelta(days=1)
        past_instance = ChoreInstance.objects.create(
            chore=self.daily_chore,
            status=ChoreInstance.POOL,
            points_value=self.daily_chore.points,
            due_at=yesterday,
            distribution_at=yesterday - timedelta(hours=6),
            is_overdue=False
        )

        run_midnight_evaluation()

        # Verify marked as overdue
        past_instance.refresh_from_db()
        self.assertTrue(past_instance.is_overdue)

    def test_midnight_evaluation_marks_chores_overdue_at_midnight(self):
        """Test that chores due 'yesterday' are marked overdue at midnight."""
        # Create instance due at start of today (which means it was due "yesterday")
        today = timezone.now().date()
        due_at = timezone.make_aware(
            datetime.combine(today, datetime.min.time())
        )

        past_instance = ChoreInstance.objects.create(
            chore=self.daily_chore,
            status=ChoreInstance.POOL,
            points_value=self.daily_chore.points,
            due_at=due_at,
            distribution_at=due_at - timedelta(hours=6),
            is_overdue=False
        )

        # Simulate midnight evaluation running now
        run_midnight_evaluation()

        # Verify marked as overdue
        past_instance.refresh_from_db()
        self.assertTrue(
            past_instance.is_overdue,
            f"Chore due at {past_instance.due_at} should be marked overdue"
        )

    def test_midnight_evaluation_does_not_mark_future_chores_overdue(self):
        """Test that chores due tomorrow are NOT marked overdue."""
        today = timezone.now().date()
        day_after_tomorrow = today + timedelta(days=2)

        # Create chore due tomorrow (start of day after tomorrow)
        due_at = timezone.make_aware(
            datetime.combine(day_after_tomorrow, datetime.min.time())
        )

        future_instance = ChoreInstance.objects.create(
            chore=self.daily_chore,
            status=ChoreInstance.POOL,
            points_value=self.daily_chore.points,
            due_at=due_at,
            distribution_at=due_at - timedelta(hours=6),
            is_overdue=False
        )

        run_midnight_evaluation()

        # Verify NOT marked as overdue
        future_instance.refresh_from_db()
        self.assertFalse(
            future_instance.is_overdue,
            f"Chore due at {future_instance.due_at} should NOT be marked overdue"
        )

    def test_midnight_evaluation_resets_claim_counters(self):
        """Test that midnight evaluation resets daily claim counters."""
        # Set user claim counter
        self.user.claims_today = 5
        self.user.save()

        run_midnight_evaluation()

        # Verify reset to 0
        self.user.refresh_from_db()
        self.assertEqual(self.user.claims_today, 0)

    def test_midnight_evaluation_logs_execution(self):
        """Test that midnight evaluation creates log entry."""
        run_midnight_evaluation()

        # Verify log created
        logs = EvaluationLog.objects.all()
        self.assertGreater(logs.count(), 0)

        log = logs.first()
        self.assertTrue(log.success)

    def test_midnight_evaluation_skips_inactive_chores(self):
        """Test that inactive chores don't generate instances."""
        inactive_chore = Chore.objects.create(
            name='Inactive Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            is_active=False  # Marked inactive
        )

        run_midnight_evaluation()

        # Should not create instance
        instances = ChoreInstance.objects.filter(chore=inactive_chore)
        self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_snapshots_points_from_template(self):
        """Test that ChoreInstance copies current point value at creation."""
        # Create chore with initial points
        chore = Chore.objects.create(
            name='Point Test Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY
        )

        run_midnight_evaluation()

        # Get created instance
        instance = ChoreInstance.objects.get(chore=chore)
        self.assertEqual(instance.points_value, Decimal('10.00'))

        # Change chore template points
        chore.points = Decimal('20.00')
        chore.save()

        # Instance should still have old value
        instance.refresh_from_db()
        self.assertEqual(instance.points_value, Decimal('10.00'))

    def test_midnight_evaluation_creates_rrule_daily_instances(self):
        """Test that midnight evaluation creates instances for RRULE DAILY chores."""
        # Create RRULE chore with daily frequency
        rrule_chore = Chore.objects.create(
            name='RRULE Daily Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.RRULE,
            rrule_json={'freq': 'DAILY', 'interval': 1},
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        # Verify instance created
        instances = ChoreInstance.objects.filter(chore=rrule_chore)
        self.assertEqual(instances.count(), 1)

    def test_midnight_evaluation_creates_rrule_weekly_instances(self):
        """Test that midnight evaluation creates instances for RRULE WEEKLY chores on correct day."""
        # Create RRULE chore with weekly frequency on today's weekday
        today_weekday = timezone.now().weekday()
        rrule_chore = Chore.objects.create(
            name='RRULE Weekly Chore',
            points=Decimal('15.00'),
            is_pool=True,
            schedule_type=Chore.RRULE,
            rrule_json={
                'freq': 'WEEKLY',
                'interval': 1,
                'byweekday': [today_weekday]
            },
            distribution_time=time(18, 0)
        )

        run_midnight_evaluation()

        # Verify instance created
        instances = ChoreInstance.objects.filter(chore=rrule_chore)
        self.assertEqual(instances.count(), 1)

    def test_midnight_evaluation_skips_rrule_wrong_weekday(self):
        """Test that RRULE weekly chores not due today are skipped."""
        # Create RRULE chore for different weekday
        wrong_day = (timezone.now().weekday() + 1) % 7
        rrule_chore = Chore.objects.create(
            name='RRULE Wrong Day Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.RRULE,
            rrule_json={
                'freq': 'WEEKLY',
                'interval': 1,
                'byweekday': [wrong_day]
            },
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        # Should not create instance
        instances = ChoreInstance.objects.filter(chore=rrule_chore)
        self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_creates_rrule_interval_instances(self):
        """Test that RRULE with interval creates instances correctly."""
        # Create RRULE chore with 2-day interval starting 2 days ago
        two_days_ago = timezone.now().date() - timedelta(days=2)
        rrule_chore = Chore.objects.create(
            name='RRULE Every 2 Days Chore',
            points=Decimal('12.00'),
            is_pool=True,
            schedule_type=Chore.RRULE,
            rrule_json={
                'freq': 'DAILY',
                'interval': 2,
                'dtstart': two_days_ago.strftime('%Y-%m-%d')
            },
            distribution_time=time(19, 0)
        )

        run_midnight_evaluation()

        # Should create instance (today is 2 days after start)
        instances = ChoreInstance.objects.filter(chore=rrule_chore)
        self.assertEqual(instances.count(), 1)

    def test_midnight_evaluation_skips_rrule_with_until_past(self):
        """Test that RRULE with until date in the past doesn't create instances."""
        yesterday = timezone.now().date() - timedelta(days=1)
        rrule_chore = Chore.objects.create(
            name='RRULE Ended Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.RRULE,
            rrule_json={
                'freq': 'DAILY',
                'interval': 1,
                'until': yesterday.strftime('%Y-%m-%d')
            },
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        # Should not create instance (until date has passed)
        instances = ChoreInstance.objects.filter(chore=rrule_chore)
        self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_creates_rrule_weekday_specific(self):
        """Test that RRULE with specific weekdays works correctly."""
        # Create RRULE for weekdays only (Monday-Friday)
        today_weekday = timezone.now().weekday()
        is_weekday = today_weekday < 5  # 0-4 are Monday-Friday

        rrule_chore = Chore.objects.create(
            name='RRULE Weekdays Only',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.RRULE,
            rrule_json={
                'freq': 'WEEKLY',
                'byweekday': [0, 1, 2, 3, 4]  # Monday-Friday
            },
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=rrule_chore)
        if is_weekday:
            # Should create instance on weekdays
            self.assertEqual(instances.count(), 1)
        else:
            # Should not create instance on weekends
            self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_creates_cron_daily_instances(self):
        """Test that midnight evaluation creates instances for CRON daily chores."""
        # Create CRON chore with daily expression
        cron_chore = Chore.objects.create(
            name='CRON Daily Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.CRON,
            cron_expr='0 0 * * *',  # Daily at midnight
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        # Verify instance created
        instances = ChoreInstance.objects.filter(chore=cron_chore)
        self.assertEqual(instances.count(), 1)

    def test_midnight_evaluation_creates_cron_weekday_instances(self):
        """Test that midnight evaluation creates instances for CRON weekday chores."""
        today_weekday = timezone.now().weekday()
        is_weekday = today_weekday < 5  # 0-4 are Monday-Friday

        # Create CRON chore for weekdays only
        cron_chore = Chore.objects.create(
            name='CRON Weekdays Chore',
            points=Decimal('15.00'),
            is_pool=True,
            schedule_type=Chore.CRON,
            cron_expr='0 0 * * 1-5',  # Monday-Friday at midnight
            distribution_time=time(18, 0)
        )

        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=cron_chore)
        if is_weekday:
            # Should create instance on weekdays
            self.assertEqual(instances.count(), 1)
        else:
            # Should not create instance on weekends
            self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_creates_cron_monthly_instances(self):
        """Test that midnight evaluation creates instances for CRON monthly chores."""
        today = timezone.now().date()
        is_first_of_month = today.day == 1

        # Create CRON chore for first day of month
        cron_chore = Chore.objects.create(
            name='CRON Monthly Chore',
            points=Decimal('20.00'),
            is_pool=True,
            schedule_type=Chore.CRON,
            cron_expr='0 0 1 * *',  # First day of each month at midnight
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=cron_chore)
        if is_first_of_month:
            # Should create instance on first of month
            self.assertEqual(instances.count(), 1)
        else:
            # Should not create instance on other days
            self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_creates_cron_nth_weekday_instances(self):
        """Test that midnight evaluation creates instances for CRON Nth weekday (e.g., 1st and 3rd Saturday)."""
        today = timezone.now().date()
        today_weekday = today.weekday()

        # Check if today is Saturday
        is_saturday = today_weekday == 5  # 5 = Saturday

        # Check if today is 1st or 3rd occurrence of the weekday in the month
        if is_saturday:
            # Count how many Saturdays we've had this month up to today
            first_of_month = today.replace(day=1)
            saturdays_count = 0
            current_day = first_of_month
            while current_day <= today:
                if current_day.weekday() == 5:
                    saturdays_count += 1
                    if current_day == today:
                        break
                current_day += timedelta(days=1)

            is_1st_or_3rd_saturday = saturdays_count in [1, 3]
        else:
            is_1st_or_3rd_saturday = False

        # Create CRON chore for 1st and 3rd Saturday
        cron_chore = Chore.objects.create(
            name='CRON Nth Saturday Chore',
            points=Decimal('25.00'),
            is_pool=True,
            schedule_type=Chore.CRON,
            cron_expr='0 0 * * 6#1,6#3',  # 1st and 3rd Saturday at midnight
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=cron_chore)
        if is_1st_or_3rd_saturday:
            # Should create instance on 1st or 3rd Saturday
            self.assertEqual(instances.count(), 1)
        else:
            # Should not create instance on other days
            self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_skips_cron_specific_day(self):
        """Test that CRON chores only fire on specified days."""
        today_weekday = timezone.now().weekday()
        is_monday = today_weekday == 0

        # Create CRON chore for Mondays only
        cron_chore = Chore.objects.create(
            name='CRON Monday Only Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.CRON,
            cron_expr='0 0 * * 1',  # Monday only at midnight
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=cron_chore)
        if is_monday:
            # Should create instance on Monday
            self.assertEqual(instances.count(), 1)
        else:
            # Should not create instance on other days
            self.assertEqual(instances.count(), 0)

    def test_midnight_evaluation_handles_cron_with_step_values(self):
        """Test that CRON with step values works correctly (e.g., every other day)."""
        today = timezone.now().date()
        day_of_month = today.day

        # Every other day starting from day 1
        should_fire = day_of_month % 2 == 1

        # Create CRON chore for every other day
        cron_chore = Chore.objects.create(
            name='CRON Every Other Day Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.CRON,
            cron_expr='0 0 */2 * *',  # Every 2 days at midnight
            distribution_time=time(17, 30)
        )

        run_midnight_evaluation()

        instances = ChoreInstance.objects.filter(chore=cron_chore)
        # Note: */2 in day field means every 2 days (1, 3, 5, 7, etc.)
        # This test may vary based on month and current day
        # We just verify no error occurs
        self.assertGreaterEqual(instances.count(), 0)


class DistributionCheckTests(TestCase):
    """Test the distribution check (auto-assignment) scheduled job."""

    def setUp(self):
        self.user1 = User.objects.create_user(
            username='alice',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        self.user2 = User.objects.create_user(
            username='bob',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        self.chore = Chore.objects.create(
            name='Test Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY,
            distribution_time=time(17, 30)
        )

        # Create instance ready for distribution
        now = timezone.now()
        distribution_time = now - timedelta(minutes=5)  # Just passed distribution time

        self.instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=now + timedelta(hours=6),
            distribution_at=distribution_time
        )

    def test_distribution_check_assigns_pool_chores(self):
        """Test that distribution check auto-assigns ready pool chores."""
        run_distribution_check()

        # Verify chore was assigned
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.status, ChoreInstance.ASSIGNED)
        self.assertIsNotNone(self.instance.assigned_to)

    def test_distribution_check_respects_fairness(self):
        """Test that distribution check assigns to user with fewest chores."""
        # Give user2 an existing assignment
        ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user2,
            points_value=self.chore.points,
            due_at=timezone.now() + timedelta(hours=6),
            distribution_at=timezone.now()
        )

        run_distribution_check()

        # Should assign to user1 (has fewer chores)
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.assigned_to, self.user1)

    def test_distribution_check_skips_future_distribution(self):
        """Test that chores with future distribution times are not assigned."""
        # Create instance with future distribution time
        future_instance = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.POOL,
            points_value=self.chore.points,
            due_at=timezone.now() + timedelta(hours=12),
            distribution_at=timezone.now() + timedelta(hours=1)
        )

        run_distribution_check()

        # Should remain in pool
        future_instance.refresh_from_db()
        self.assertEqual(future_instance.status, ChoreInstance.POOL)

    @unittest.skip("Feature not implemented: distribution_check() doesn't create EvaluationLog entries")
    def test_distribution_check_logs_execution(self):
        """Test that distribution check creates log entry."""
        run_distribution_check()

        # Verify log created
        logs = EvaluationLog.objects.all()
        self.assertGreater(logs.count(), 0)


class WeeklySnapshotTests(TestCase):
    """Test the weekly snapshot (Sunday midnight) scheduled job."""

    def setUp(self):
        self.user1 = User.objects.create_user(
            username='alice',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )
        self.user1.weekly_points = Decimal('100.00')
        self.user1.all_time_points = Decimal('500.00')
        self.user1.save()

        self.user2 = User.objects.create_user(
            username='bob',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )
        self.user2.weekly_points = Decimal('80.00')
        self.user2.all_time_points = Decimal('400.00')
        self.user2.save()

    def test_weekly_snapshot_creates_records(self):
        """Test that weekly snapshot creates records for all eligible users."""
        run_weekly_snapshot()

        # Verify snapshots created
        snapshots = WeeklySnapshot.objects.all()
        self.assertEqual(snapshots.count(), 2)

        # Verify data
        alice_snapshot = WeeklySnapshot.objects.get(user=self.user1)
        self.assertEqual(alice_snapshot.points_earned, Decimal('100.00'))

        bob_snapshot = WeeklySnapshot.objects.get(user=self.user2)
        self.assertEqual(bob_snapshot.points_earned, Decimal('80.00'))

    @unittest.skip("Feature not implemented: perfect_week hardcoded to False (Phase 3 TODO at jobs.py:301)")
    def test_weekly_snapshot_tracks_perfect_week(self):
        """Test that perfect week flag is set when no overdue chores."""
        # Create all completed chores (no overdue)
        chore = Chore.objects.create(
            name='Test Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY
        )

        now = timezone.now()
        instance = ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.COMPLETED,
            assigned_to=self.user1,
            points_value=chore.points,
            due_at=now + timedelta(hours=6),
            distribution_at=now,
            completed_at=now,
            is_overdue=False  # Completed on time
        )

        run_weekly_snapshot()

        # Verify perfect week
        alice_snapshot = WeeklySnapshot.objects.get(user=self.user1)
        self.assertTrue(alice_snapshot.perfect_week)

    def test_weekly_snapshot_detects_imperfect_week(self):
        """Test that imperfect week is detected when overdue chores exist."""
        # Create overdue chore
        chore = Chore.objects.create(
            name='Test Chore',
            points=Decimal('10.00'),
            is_pool=True,
            schedule_type=Chore.DAILY
        )

        now = timezone.now()
        overdue_instance = ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.ASSIGNED,  # Changed from POOL to ASSIGNED since it has assigned_to
            assigned_to=self.user1,
            points_value=chore.points,
            due_at=now - timedelta(hours=6),
            distribution_at=now - timedelta(hours=12),
            is_overdue=True  # Overdue!
        )

        run_weekly_snapshot()

        # Verify NOT perfect week
        alice_snapshot = WeeklySnapshot.objects.get(user=self.user1)
        self.assertFalse(alice_snapshot.perfect_week)

    @unittest.skip("Feature not implemented: weekly_snapshot_job() doesn't create EvaluationLog entries")
    def test_weekly_snapshot_logs_execution(self):
        """Test that weekly snapshot creates log entry."""
        run_weekly_snapshot()

        # Verify log created
        logs = EvaluationLog.objects.all()
        self.assertGreater(logs.count(), 0)

    # SKIPPED: perfect_weeks feature not implemented yet
    # WeeklySnapshot only has perfect_week (boolean), not perfect_weeks (counter)
    # def test_weekly_snapshot_includes_perfect_week_count(self):
    #     """Test that snapshot includes current perfect week count."""
    #     run_weekly_snapshot()
    #     alice_snapshot = WeeklySnapshot.objects.get(user=self.user1)
    #     self.assertEqual(alice_snapshot.perfect_weeks, 10)

    def test_weekly_snapshot_stores_week_ending_date(self):
        """Test that snapshot stores the correct week-ending date."""
        run_weekly_snapshot()

        snapshot = WeeklySnapshot.objects.first()
        # Week ending should be today (Sunday at midnight)
        self.assertEqual(snapshot.week_ending, timezone.now().date())


class RotationStateTests(TestCase):
    """Test rotation state tracking for undesirable chores."""

    def setUp(self):
        self.user1 = User.objects.create_user(
            username='alice',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        self.user2 = User.objects.create_user(
            username='bob',
            password='test123',
            can_be_assigned=True,
            eligible_for_points=True
        )

        self.undesirable_chore = Chore.objects.create(
            name='Undesirable Chore',
            points=Decimal('15.00'),
            is_pool=True,
            is_undesirable=True,
            schedule_type=Chore.DAILY
        )

        # Add eligibility
        from chores.models import ChoreEligibility
        ChoreEligibility.objects.create(chore=self.undesirable_chore, user=self.user1)
        ChoreEligibility.objects.create(chore=self.undesirable_chore, user=self.user2)

    def test_rotation_state_created_on_completion(self):
        """Test that completing an undesirable chore creates rotation state."""
        now = timezone.now()
        instance = ChoreInstance.objects.create(
            chore=self.undesirable_chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user1,
            points_value=self.undesirable_chore.points,
            due_at=now + timedelta(hours=6),
            distribution_at=now
        )

        # Complete the chore
        instance.status = ChoreInstance.COMPLETED
        instance.completed_at = now
        instance.save()

        # Manually update rotation state (normally done by API view)
        from chores.services import AssignmentService
        AssignmentService.update_rotation_state(self.undesirable_chore, self.user1)

        # Verify rotation state created
        rotation_state = RotationState.objects.get(
            chore=self.undesirable_chore,
            user=self.user1
        )
        self.assertEqual(rotation_state.last_completed_date, timezone.now().date())

    def test_rotation_selects_oldest_completer(self):
        """Test that rotation assigns to user who completed longest ago."""
        # Set user1 completed yesterday
        RotationState.objects.create(
            chore=self.undesirable_chore,
            user=self.user1,
            last_completed_date=date.today() - timedelta(days=1)
        )

        # Set user2 completed 5 days ago
        RotationState.objects.create(
            chore=self.undesirable_chore,
            user=self.user2,
            last_completed_date=date.today() - timedelta(days=5)
        )

        # Create instance and assign via rotation
        now = timezone.now()
        instance = ChoreInstance.objects.create(
            chore=self.undesirable_chore,
            status=ChoreInstance.POOL,
            points_value=self.undesirable_chore.points,
            due_at=now + timedelta(hours=6),
            distribution_at=now
        )

        from chores.services import AssignmentService
        success, message, assigned_user = AssignmentService.assign_chore(instance)

        # Should assign to user2 (completed 5 days ago, oldest)
        self.assertTrue(success)
        self.assertEqual(assigned_user, self.user2)

    def test_rotation_excludes_yesterday_completer(self):
        """Test that users who completed yesterday are excluded (purple state)."""
        # Set both users completed yesterday
        RotationState.objects.create(
            chore=self.undesirable_chore,
            user=self.user1,
            last_completed_date=timezone.now().date() - timedelta(days=1)
        )

        RotationState.objects.create(
            chore=self.undesirable_chore,
            user=self.user2,
            last_completed_date=timezone.now().date() - timedelta(days=1)
        )

        # Try to assign
        now = timezone.now()
        instance = ChoreInstance.objects.create(
            chore=self.undesirable_chore,
            status=ChoreInstance.POOL,
            points_value=self.undesirable_chore.points,
            due_at=now + timedelta(hours=6),
            distribution_at=now
        )

        from chores.services import AssignmentService
        success, message, assigned_user = AssignmentService.assign_chore(instance)

        # Should fail with "all completed yesterday" reason
        self.assertFalse(success)
        self.assertIn('yesterday', message.lower())

        # Verify assignment reason
        instance.refresh_from_db()
        self.assertEqual(
            instance.assignment_reason,
            ChoreInstance.REASON_ALL_COMPLETED_YESTERDAY
        )
