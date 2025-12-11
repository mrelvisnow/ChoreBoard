"""
Signal handlers for chore creation.
"""
import logging
from datetime import datetime, timedelta, date
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from chores.models import Chore, ChoreInstance, ChoreDependency

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Chore)
def create_chore_instance_on_creation(sender, instance, created, **kwargs):
    """
    Create a ChoreInstance immediately when a new Chore is created,
    if today matches the chore's schedule.
    """
    try:
        logger.info(f"Signal fired for chore {instance.name} (created={created}, active={instance.is_active})")

        if not created or not instance.is_active:
            logger.info(f"Skipping instance creation: created={created}, active={instance.is_active}")
            return

        # Skip child chores - they should only spawn from parent completion
        if instance.is_child_chore():
            logger.info(f"Skipping instance creation for child chore {instance.name} - will spawn from parent completion")
            return

        now = timezone.now()
        today = now.date()
        should_create_today = False

        if instance.schedule_type == Chore.DAILY:
            should_create_today = True
        elif instance.schedule_type == Chore.WEEKLY and instance.weekday is not None:
            should_create_today = (today.weekday() == instance.weekday)
        elif instance.schedule_type == Chore.EVERY_N_DAYS and instance.every_n_start_date:
            days_since_start = (today - instance.every_n_start_date).days
            should_create_today = (days_since_start % instance.n_days == 0)
        elif instance.schedule_type == Chore.ONE_TIME:
            # ONE_TIME tasks are ALWAYS created immediately
            should_create_today = True

        logger.info(f"Schedule check: type={instance.schedule_type}, should_create_today={should_create_today}")

        if should_create_today:
            # Calculate due_at based on schedule type
            tomorrow = today + timedelta(days=1)

            if instance.schedule_type == Chore.ONE_TIME:
                # ONE_TIME: use one_time_due_date or sentinel far-future date
                if instance.one_time_due_date:
                    # Due at start of day after due_date (consistent with existing logic)
                    due_day = instance.one_time_due_date + timedelta(days=1)
                    due_at = timezone.make_aware(
                        datetime.combine(due_day, datetime.min.time())
                    )
                else:
                    # No due date = use sentinel far-future date (never overdue)
                    far_future = date(9999, 12, 31)
                    due_at = timezone.make_aware(
                        datetime.combine(far_future, datetime.min.time())
                    )
            else:
                # Regular recurring chores: due at start of tomorrow
                due_at = timezone.make_aware(
                    datetime.combine(tomorrow, datetime.min.time())
                )

            # Check if instance already exists (prevent duplicates)
            # Note: For ONE_TIME, we check ANY due date since there should only ever be one instance
            if instance.schedule_type == Chore.ONE_TIME:
                existing = ChoreInstance.objects.filter(chore=instance).exists()
            else:
                # Regular chores: check for instance with due_at = tomorrow
                existing = ChoreInstance.objects.filter(
                    chore=instance,
                    due_at__date=tomorrow
                ).exists()

            if existing:
                logger.info(f"Instance already exists for chore {instance.name}")
                return

            distribution_at = timezone.make_aware(
                datetime.combine(today, instance.distribution_time)
            )

            # Determine status and assignment based on chore type
            if instance.is_undesirable:
                # Undesirable chores: create as POOL
                # Assignment happens later in admin view after ChoreEligibility records are created
                logger.info(f"Creating undesirable instance for {instance.name} (is_pool={instance.is_pool})")
                new_instance = ChoreInstance.objects.create(
                    chore=instance,
                    status=ChoreInstance.POOL,
                    points_value=instance.points,
                    due_at=due_at,
                    distribution_at=distribution_at
                )
                logger.info(f"Created undesirable instance {new_instance.id} for {instance.name} (will be assigned after ChoreEligibility records are created)")

            elif instance.is_pool:
                # Regular pool chore: create as POOL, users can claim it
                new_instance = ChoreInstance.objects.create(
                    chore=instance,
                    status=ChoreInstance.POOL,
                    points_value=instance.points,
                    due_at=due_at,
                    distribution_at=distribution_at
                )
                logger.info(f"Created pool instance {new_instance.id} for chore {instance.name}")

            else:
                # Pre-assigned chore: create with assignment
                new_instance = ChoreInstance.objects.create(
                    chore=instance,
                    status=ChoreInstance.ASSIGNED,
                    assigned_to=instance.assigned_to,
                    points_value=instance.points,
                    due_at=due_at,
                    distribution_at=distribution_at
                )
                logger.info(f"Created pre-assigned instance {new_instance.id} for {instance.name}")
    except Exception as e:
        logger.error(f"Error in chore signal for {instance.name}: {e}", exc_info=True)


@receiver(post_save, sender=ChoreDependency)
def cleanup_child_chore_instances_on_dependency_creation(sender, instance, created, **kwargs):
    """
    When a dependency is created, delete any ChoreInstance objects that were
    created for the child chore before the dependency existed.

    This handles the case where a chore is created first (triggering an instance
    creation), and then later a dependency is added making it a child chore.
    """
    if not created:
        return

    try:
        child_chore = instance.chore
        logger.info(f"Dependency created: {child_chore.name} now depends on {instance.depends_on.name}")

        # Delete any instances that were created for this chore
        # before it became a child chore
        deleted_count = ChoreInstance.objects.filter(
            chore=child_chore,
            status__in=[ChoreInstance.POOL, ChoreInstance.ASSIGNED]
        ).exclude(
            status=ChoreInstance.COMPLETED
        ).delete()[0]

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} pre-existing instances for child chore {child_chore.name}")

    except Exception as e:
        logger.error(f"Error cleaning up child chore instances: {e}", exc_info=True)
