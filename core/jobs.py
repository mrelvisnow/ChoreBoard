"""
Scheduled job implementations for ChoreBoard.
"""
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import datetime, timedelta
import logging
import json
from dateutil import rrule
from croniter import croniter

from chores.models import Chore, ChoreInstance
from users.models import User
from core.models import EvaluationLog, WeeklySnapshot, Settings
from core.notifications import NotificationService

logger = logging.getLogger(__name__)


def midnight_evaluation():
    """
    Midnight evaluation job (runs at 00:00 daily).

    Tasks:
    1. Create new ChoreInstances for active chores based on schedule
    2. Mark overdue ChoreInstances
    3. Reset users' claims_today counter
    4. Log execution results
    """
    started_at = timezone.now()
    logger.info(f"Starting midnight evaluation at {started_at}")

    chores_created = 0
    chores_marked_overdue = 0
    errors = []

    try:
        with transaction.atomic():
            # Reset daily claim counters
            User.objects.filter(can_be_assigned=True).update(claims_today=0)
            logger.info("Reset daily claim counters for all users")

            # Mark overdue chores
            now = timezone.now()
            overdue_instances = ChoreInstance.objects.filter(
                status__in=[ChoreInstance.POOL, ChoreInstance.ASSIGNED],
                due_at__lt=now,
                is_overdue=False
            ).select_related('chore', 'assigned_to')

            # Collect instances before updating (can't iterate after update)
            overdue_list = list(overdue_instances)
            overdue_count = overdue_instances.update(is_overdue=True)
            chores_marked_overdue = overdue_count
            logger.info(f"Marked {overdue_count} chore instances as overdue")

            # Send webhook notifications for overdue chores
            for instance in overdue_list:
                NotificationService.notify_chore_overdue(instance)

            # Cleanup completed one-time tasks (archive after undo window)
            try:
                cleanup_completed_one_time_tasks()
            except Exception as e:
                error_msg = f"Error cleaning up one-time tasks: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

            # Get active chores, excluding child chores (those with dependencies)
            from django.db.models import Exists, OuterRef
            from chores.models import ChoreDependency

            # Subquery to check if chore is a child (has dependencies_as_child)
            has_dependencies = ChoreDependency.objects.filter(chore=OuterRef('pk'))

            active_chores = Chore.objects.filter(
                is_active=True
            ).exclude(
                # Exclude chores that are children (have parent dependencies)
                Exists(has_dependencies)
            )
            logger.info(f"Found {active_chores.count()} active chores (excluding child chores)")

            # Create instances for each chore based on schedule
            today = now.date()

            for chore in active_chores:
                try:
                    should_create = should_create_instance_today(chore, today)

                    if should_create:
                        # Calculate due time (start of next day - clearer and DST-safe)
                        tomorrow = today + timedelta(days=1)
                        due_at = timezone.make_aware(
                            datetime.combine(tomorrow, datetime.min.time())
                        )

                        # Distribution time
                        distribution_at = timezone.make_aware(
                            datetime.combine(today, chore.distribution_time)
                        )

                        # Create instance
                        instance = ChoreInstance.objects.create(
                            chore=chore,
                            status=ChoreInstance.POOL if chore.is_pool else ChoreInstance.ASSIGNED,
                            assigned_to=chore.assigned_to if not chore.is_pool else None,
                            points_value=chore.points,
                            due_at=due_at,
                            distribution_at=distribution_at
                        )

                        chores_created += 1
                        logger.info(f"Created instance for chore: {chore.name}")

                        # If chore is undesirable and in pool, assign immediately
                        if chore.is_undesirable and chore.is_pool:
                            from chores.services import AssignmentService
                            success, message, assigned_user = AssignmentService.assign_chore(
                                instance,
                                force_assign=False,
                                assigned_by=None
                            )
                            if success:
                                logger.info(
                                    f"Auto-assigned undesirable chore '{chore.name}' to "
                                    f"{assigned_user.username} at midnight"
                                )
                            else:
                                logger.warning(
                                    f"Could not assign undesirable chore '{chore.name}': {message}"
                                )

                except Exception as e:
                    error_msg = f"Error creating instance for chore {chore.name}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Log execution
            completed_at = timezone.now()
            execution_time = (completed_at - started_at).total_seconds()

            eval_log = EvaluationLog.objects.create(
                started_at=started_at,
                completed_at=completed_at,
                success=len(errors) == 0,
                chores_created=chores_created,
                chores_marked_overdue=chores_marked_overdue,
                errors_count=len(errors),
                error_details="\n".join(errors) if errors else "",
                execution_time_seconds=Decimal(str(execution_time))
            )

            logger.info(f"Midnight evaluation completed in {execution_time:.2f}s")
            logger.info(f"Created {chores_created} instances, marked {chores_marked_overdue} overdue")

            return eval_log

    except Exception as e:
        error_msg = f"Critical error in midnight evaluation: {str(e)}"
        logger.error(error_msg)
        errors.append(error_msg)

        # Still log the execution
        completed_at = timezone.now()
        execution_time = (completed_at - started_at).total_seconds()

        eval_log = EvaluationLog.objects.create(
            started_at=started_at,
            completed_at=completed_at,
            success=False,
            chores_created=chores_created,
            chores_marked_overdue=chores_marked_overdue,
            errors_count=len(errors),
            error_details="\n".join(errors),
            execution_time_seconds=Decimal(str(execution_time))
        )

        raise


def evaluate_rrule(rrule_json, check_date, chore_created_date):
    """
    Evaluate if a date matches an RRULE schedule.

    Args:
        rrule_json: Dictionary containing RRULE parameters
        check_date: date object to check
        chore_created_date: date when the chore was created (used as default dtstart)

    Returns:
        bool: True if check_date matches the RRULE

    Supported RRULE parameters:
        - freq: DAILY, WEEKLY, MONTHLY, YEARLY (required)
        - interval: int (default: 1)
        - dtstart: date string or date object (default: chore_created_date)
        - until: date string or date object (optional)
        - count: int (optional)
        - byweekday: list of weekday indices 0-6 (0=Monday) (optional)
        - bymonthday: list of month day numbers (optional)
        - bymonth: list of month numbers (optional)
    """
    # Map string frequency to rrule constants
    freq_map = {
        'DAILY': rrule.DAILY,
        'WEEKLY': rrule.WEEKLY,
        'MONTHLY': rrule.MONTHLY,
        'YEARLY': rrule.YEARLY,
    }

    # Get frequency
    freq_str = rrule_json.get('freq', '').upper()
    if freq_str not in freq_map:
        raise ValueError(f"Invalid or missing frequency: {freq_str}")

    freq = freq_map[freq_str]

    # Get interval (default 1)
    interval = rrule_json.get('interval', 1)

    # Get dtstart (start date for the rule)
    dtstart = rrule_json.get('dtstart')
    if dtstart:
        if isinstance(dtstart, str):
            dtstart = datetime.strptime(dtstart, '%Y-%m-%d').date()
    else:
        # Default to when the chore was created
        dtstart = chore_created_date

    # Convert date to datetime for rrule (rrule requires datetime)
    dtstart_dt = datetime.combine(dtstart, datetime.min.time())
    check_dt = datetime.combine(check_date, datetime.min.time())

    # Build rrule parameters
    rule_params = {
        'freq': freq,
        'interval': interval,
        'dtstart': dtstart_dt,
    }

    # Optional: until (end date)
    if 'until' in rrule_json:
        until = rrule_json['until']
        if isinstance(until, str):
            until = datetime.strptime(until, '%Y-%m-%d').date()
        rule_params['until'] = datetime.combine(until, datetime.max.time())

    # Optional: count (number of occurrences)
    if 'count' in rrule_json:
        rule_params['count'] = rrule_json['count']

    # Optional: byweekday (specific weekdays)
    if 'byweekday' in rrule_json:
        # Map indices or string codes to rrule weekday constants
        weekday_map_by_index = [
            rrule.MO, rrule.TU, rrule.WE, rrule.TH,
            rrule.FR, rrule.SA, rrule.SU
        ]
        weekday_map_by_name = {
            'MO': rrule.MO, 'TU': rrule.TU, 'WE': rrule.WE, 'TH': rrule.TH,
            'FR': rrule.FR, 'SA': rrule.SA, 'SU': rrule.SU
        }

        byweekday = []
        for item in rrule_json['byweekday']:
            if isinstance(item, int):
                # Integer index (0-6)
                byweekday.append(weekday_map_by_index[item])
            elif isinstance(item, str):
                # String code ('MO', 'TU', etc.)
                if item in weekday_map_by_name:
                    byweekday.append(weekday_map_by_name[item])
                else:
                    logger.warning(f"Unknown weekday code: {item}")
            else:
                logger.warning(f"Invalid weekday format: {item} (type: {type(item)})")

        if byweekday:
            rule_params['byweekday'] = byweekday

    # Optional: bymonthday (specific days of month)
    if 'bymonthday' in rrule_json:
        rule_params['bymonthday'] = rrule_json['bymonthday']

    # Optional: bymonth (specific months)
    if 'bymonth' in rrule_json:
        rule_params['bymonth'] = rrule_json['bymonth']

    # Create the rrule
    rule = rrule.rrule(**rule_params)

    # Check if check_date is in the rule's occurrences
    # We check from dtstart to check_date + 1 day to include check_date
    occurrences = rule.between(
        dtstart_dt,
        check_dt + timedelta(days=1),
        inc=True  # Include boundaries
    )

    # Check if any occurrence falls on check_date
    for occurrence in occurrences:
        if occurrence.date() == check_date:
            return True

    return False


def evaluate_cron(cron_expr, check_date):
    """
    Evaluate if a date matches a CRON expression.

    Args:
        cron_expr: CRON expression string (e.g., "0 0 * * 1-5" for weekdays at midnight)
        check_date: date object to check

    Returns:
        bool: True if check_date matches the CRON expression

    CRON Format: minute hour day_of_month month day_of_week
    - minute: 0-59
    - hour: 0-23
    - day_of_month: 1-31
    - month: 1-12
    - day_of_week: 0-7 (0 and 7 are Sunday)

    Special characters:
    - *: Any value
    - ,: Value list separator
    - -: Range of values
    - /: Step values
    - #: Nth occurrence (e.g., 6#1 = first Saturday)

    Examples:
    - "0 0 * * *": Daily at midnight
    - "0 0 * * 1-5": Weekdays at midnight
    - "0 0 1 * *": First day of each month at midnight
    - "0 0 * * 6#1,6#3": First and third Saturday at midnight
    """
    if not cron_expr or not cron_expr.strip():
        raise ValueError("CRON expression cannot be empty")

    try:
        # Create a datetime at the start of check_date
        check_dt = datetime.combine(check_date, datetime.min.time())

        # Create croniter instance with the cron expression
        cron = croniter(cron_expr, check_dt)

        # Get the previous occurrence before check_dt
        prev_occurrence = cron.get_prev(datetime)

        # Get the next occurrence after the previous one
        cron_from_prev = croniter(cron_expr, prev_occurrence)
        next_occurrence = cron_from_prev.get_next(datetime)

        # Check if next_occurrence falls on check_date
        if next_occurrence.date() == check_date:
            return True

        # Also check if check_dt itself matches the cron expression
        # This handles the case where check_date is the start date
        cron_check = croniter(cron_expr, check_dt)
        next_from_check = cron_check.get_next(datetime)

        # If the next occurrence from check_dt is still on the same day, it matches
        if next_from_check.date() == check_date:
            return True

        return False

    except Exception as e:
        logger.error(f"Error evaluating CRON expression '{cron_expr}': {e}")
        raise ValueError(f"Invalid CRON expression: {cron_expr}") from e


def should_create_instance_today(chore, today):
    """
    Determine if a chore instance should be created today based on schedule.

    Args:
        chore: Chore model instance
        today: date object for today

    Returns:
        bool: True if instance should be created
    """
    # Check if instance already exists for today
    # Note: With our due_at logic, instances "for today" have due_at = start of tomorrow
    tomorrow = today + timedelta(days=1)
    existing = ChoreInstance.objects.filter(
        chore=chore,
        due_at__date=tomorrow
    ).exists()

    if existing:
        return False

    # Check for rescheduled date (overrides normal schedule)
    if chore.rescheduled_date:
        if chore.rescheduled_date == today:
            # Clear reschedule and create instance today
            chore.rescheduled_date = None
            chore.reschedule_reason = ""
            chore.rescheduled_by = None
            chore.rescheduled_at = None
            chore.save()
            logger.info(f"Chore '{chore.name}' rescheduled date reached, cleared reschedule and creating instance")
            return True
        else:
            # Skip normal schedule - chore is rescheduled for a different day
            logger.debug(f"Chore '{chore.name}' is rescheduled to {chore.rescheduled_date}, skipping today")
            return False

    # ONE_TIME chores are created immediately via signal, not by midnight evaluation
    if chore.schedule_type == Chore.ONE_TIME:
        return False

    # Daily chores
    if chore.schedule_type == Chore.DAILY:
        return True

    # Weekly chores
    if chore.schedule_type == Chore.WEEKLY:
        if chore.weekday is not None:
            return today.weekday() == chore.weekday
        return False

    # Every N days
    if chore.schedule_type == Chore.EVERY_N_DAYS:
        if chore.every_n_start_date and chore.n_days:
            days_since_start = (today - chore.every_n_start_date).days
            return days_since_start % chore.n_days == 0
        return False

    # RRULE schedule
    if chore.schedule_type == Chore.RRULE:
        if not chore.rrule_json:
            logger.warning(f"Chore '{chore.name}' has RRULE schedule but no rrule_json data")
            return False

        try:
            # Parse RRULE JSON and check if today matches
            return evaluate_rrule(chore.rrule_json, today, chore.created_at.date())
        except Exception as e:
            logger.error(f"Error evaluating RRULE for chore '{chore.name}': {e}")
            return False

    # CRON schedule
    if chore.schedule_type == Chore.CRON:
        if not chore.cron_expr:
            logger.warning(f"Chore '{chore.name}' has CRON schedule but no cron_expr data")
            return False

        try:
            # Parse CRON expression and check if today matches
            return evaluate_cron(chore.cron_expr, today)
        except Exception as e:
            logger.error(f"Error evaluating CRON for chore '{chore.name}': {e}")
            return False

    return False


def cleanup_completed_one_time_tasks():
    """
    Archive (deactivate) completed ONE_TIME tasks after undo window expires.

    Runs at midnight. Checks for ONE_TIME chore instances that:
    - Status is COMPLETED
    - Completed more than UNDO_WINDOW (2 hours) ago

    Then deactivates the parent Chore (is_active=False).

    Returns:
        int: Number of chores archived
    """
    now = timezone.now()
    undo_window = timedelta(hours=2)
    cutoff_time = now - undo_window

    logger.info(f"[CLEANUP] Starting cleanup of completed ONE_TIME tasks (cutoff: {cutoff_time})")

    # Find completed ONE_TIME instances
    completed_instances = ChoreInstance.objects.filter(
        chore__schedule_type=Chore.ONE_TIME,
        chore__is_active=True,  # Only active chores
        status=ChoreInstance.COMPLETED
    ).select_related('chore')

    archived_count = 0

    for instance in completed_instances:
        # Check if instance was completed before cutoff
        if instance.completed_at and instance.completed_at <= cutoff_time:
            # Undo window has passed - archive the chore
            chore = instance.chore
            chore.is_active = False
            chore.save(update_fields=['is_active'])

            archived_count += 1
            logger.info(f"[CLEANUP] Archived ONE_TIME task: {chore.name} (ID: {chore.id})")

    logger.info(f"[CLEANUP] Archived {archived_count} completed ONE_TIME tasks")
    return archived_count


def distribution_check():
    """
    Distribution check job (runs at 17:30 daily).

    Tasks:
    1. Find ChoreInstances with distribution_time that has passed
    2. Auto-assign based on assignment algorithm
    3. Send notifications for assigned chores
    """
    from chores.services import AssignmentService

    logger.info("Starting distribution check")

    now = timezone.now()
    current_tz = timezone.get_current_timezone()
    logger.info(f"Distribution check running at {now} (timezone: {current_tz})")

    # Find pool chores that need distribution
    instances_to_distribute = ChoreInstance.objects.filter(
        status=ChoreInstance.POOL,
        distribution_at__lte=now,
        due_at__gt=now  # Not yet due
    )

    logger.info(f"Found {instances_to_distribute.count()} instances to distribute")
    for instance in instances_to_distribute:
        logger.info(
            f"  - {instance.chore.name}: distribution_at={instance.distribution_at}, "
            f"now={now}, status={instance.status}"
        )

    assigned_count = 0
    failed_count = 0

    for instance in instances_to_distribute:
        try:
            success, message, user = AssignmentService.assign_chore(
                instance,
                force_assign=False,
                assigned_by=None  # System assignment
            )

            if success:
                assigned_count += 1
                logger.info(f"Auto-assigned {instance.chore.name} to {user.username}")
                # Send webhook notification
                NotificationService.notify_chore_assigned(instance, user, reason="auto")
            else:
                failed_count += 1
                logger.warning(f"Could not assign {instance.chore.name}: {message}")

        except Exception as e:
            failed_count += 1
            logger.error(f"Error distributing chore {instance.chore.name}: {str(e)}")

    logger.info(
        f"Distribution check complete. "
        f"Assigned: {assigned_count}, Failed: {failed_count}"
    )
    return assigned_count


def weekly_snapshot_job():
    """
    Weekly snapshot job (runs Sunday at 00:00).

    Tasks:
    1. Create WeeklySnapshot for each eligible user
    2. Calculate points earned this week
    3. Check for perfect week (no overdue chores)
    4. Update streak records
    """
    logger.info("Starting weekly snapshot job")

    now = timezone.now()
    week_ending = now.date()

    # Get all users eligible for points
    eligible_users = User.objects.filter(eligible_for_points=True)

    snapshots_created = 0

    for user in eligible_users:
        try:
            with transaction.atomic():
                # Check if snapshot already exists
                if WeeklySnapshot.objects.filter(
                    user=user,
                    week_ending=week_ending
                ).exists():
                    logger.info(f"Snapshot already exists for {user.username}")
                    continue

                # Get settings for conversion rate
                settings = Settings.get_settings()

                # Calculate cash value
                points = user.weekly_points
                cash_value = points * settings.points_to_dollar_rate

                # Check for perfect week (no overdue assigned chores)
                # TODO: Implement perfect week check in Phase 3
                perfect_week = False

                # Create snapshot
                snapshot = WeeklySnapshot.objects.create(
                    user=user,
                    week_ending=week_ending,
                    points_earned=points,
                    cash_value=cash_value,
                    perfect_week=perfect_week
                )

                snapshots_created += 1
                logger.info(f"Created snapshot for {user.username}: {points} pts = ${cash_value}")

        except Exception as e:
            logger.error(f"Error creating snapshot for {user.username}: {str(e)}")

    # Calculate total points for weekly reset notification
    total_users = eligible_users.count()
    total_points = sum(u.weekly_points for u in eligible_users)

    # Send weekly reset notification
    NotificationService.notify_weekly_reset(total_users, total_points)

    logger.info(f"Weekly snapshot job complete. Created {snapshots_created} snapshots")
    return snapshots_created
