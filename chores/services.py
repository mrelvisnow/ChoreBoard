"""
Service layer for chore assignment and rotation logic.
"""
from django.db import transaction
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta
import logging

from chores.models import Chore, ChoreInstance, ChoreEligibility
from core.models import RotationState, Settings, ActionLog
from users.models import User

logger = logging.getLogger(__name__)


class AssignmentService:
    """Service for assigning chores to users with fairness and eligibility rules."""

    @staticmethod
    def assign_chore(instance, force_assign=False, assigned_by=None):
        """
        Assign a pool chore to a user based on assignment algorithm.

        Args:
            instance: ChoreInstance to assign
            force_assign: If True, assign even if normally blocked
            assigned_by: User performing the assignment (for logging)

        Returns:
            tuple: (success: bool, message: str, assigned_user: User or None)
        """
        if instance.status != ChoreInstance.POOL:
            return False, "Chore is not in pool", None

        chore = instance.chore

        # Get eligible users
        eligible_users = AssignmentService._get_eligible_users(chore)

        if not eligible_users:
            # No eligible users - purple state
            instance.assignment_reason = ChoreInstance.REASON_NO_ELIGIBLE
            instance.save()
            logger.warning(f"No eligible users for chore: {chore.name}")
            return False, "No eligible users for this chore", None

        # Check if chore is undesirable - use rotation
        if chore.is_undesirable:
            selected_user = AssignmentService._select_via_rotation(
                chore, eligible_users, instance
            )
        else:
            # Regular chore - select user with least assigned today
            selected_user = AssignmentService._select_by_fairness(
                eligible_users, chore.is_difficult
            )

        if selected_user is None:
            # All eligible users blocked (e.g., all completed yesterday for undesirable)
            instance.assignment_reason = ChoreInstance.REASON_ALL_COMPLETED_YESTERDAY
            instance.save()
            return False, "All eligible users completed this chore yesterday", None

        # Check difficult chore constraint
        if chore.is_difficult and not force_assign:
            # Check if user already has a difficult chore assigned today
            has_difficult = ChoreInstance.objects.filter(
                assigned_to=selected_user,
                status=ChoreInstance.ASSIGNED,
                chore__is_difficult=True,
                due_at__date=timezone.now().date()
            ).exclude(id=instance.id).exists()

            if has_difficult:
                logger.info(
                    f"User {selected_user.username} already has difficult chore, "
                    f"cannot assign {chore.name}"
                )
                instance.assignment_reason = ChoreInstance.REASON_NO_ELIGIBLE
                instance.save()
                return False, "User already has a difficult chore assigned", None

        # Perform assignment
        instance.status = ChoreInstance.ASSIGNED
        instance.assigned_to = selected_user
        instance.assigned_at = timezone.now()
        # This method is used for automatic system distribution
        instance.assignment_reason = ChoreInstance.REASON_FORCE_ASSIGNED
        instance.save()

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_FORCE_ASSIGN,
            user=assigned_by,
            target_user=selected_user,
            description=f"Assigned {chore.name} to {selected_user.username}",
            metadata={
                "chore_id": chore.id,
                "instance_id": instance.id,
                "force": force_assign
            }
        )

        logger.info(f"Assigned {chore.name} to {selected_user.username}")
        return True, f"Assigned to {selected_user.username}", selected_user

    @staticmethod
    def _get_eligible_users(chore):
        """
        Get list of users eligible for a chore.

        Args:
            chore: Chore instance

        Returns:
            QuerySet of eligible users
        """
        # Start with users who can be assigned
        eligible = User.objects.filter(
            can_be_assigned=True,
            is_active=True,
            exclude_from_auto_assignment=False  # Exclude users who opt out of auto-assignment
        )

        # If chore is undesirable, filter by explicit eligibility
        if chore.is_undesirable:
            eligible_user_ids = ChoreEligibility.objects.filter(
                chore=chore
            ).values_list('user_id', flat=True)

            eligible = eligible.filter(id__in=eligible_user_ids)

        return eligible

    @staticmethod
    def _select_via_rotation(chore, eligible_users, instance):
        """
        Select user for undesirable chore via rotation.

        Algorithm:
        1. Exclude users who completed this chore yesterday (purple state)
        2. Select user with oldest last_completed_date (or never completed)
        3. Update RotationState when assigned

        Args:
            chore: Chore instance
            eligible_users: QuerySet of eligible users
            instance: ChoreInstance being assigned

        Returns:
            User or None
        """
        yesterday = timezone.now().date() - timedelta(days=1)

        # Get rotation state for all eligible users
        rotation_states = RotationState.objects.filter(
            chore=chore,
            user__in=eligible_users
        ).select_related('user')

        # Create map of user_id -> last_completed_date
        state_map = {
            state.user_id: state.last_completed_date
            for state in rotation_states
        }

        # Filter out users who completed yesterday
        available_users = []
        for user in eligible_users:
            last_date = state_map.get(user.id)
            if last_date is None or last_date != yesterday:
                available_users.append((user, last_date))

        if not available_users:
            # All users completed yesterday - purple state
            return None

        # Sort by last_completed_date (None first, then oldest)
        available_users.sort(key=lambda x: (x[1] is not None, x[1] or timezone.now().date()))

        selected_user = available_users[0][0]

        logger.info(
            f"Rotation selected {selected_user.username} for {chore.name} "
            f"(last completed: {state_map.get(selected_user.id, 'never')})"
        )

        return selected_user

    @staticmethod
    def _select_by_fairness(eligible_users, is_difficult=False):
        """
        Select user by fairness - least assigned chores today.

        Args:
            eligible_users: QuerySet of eligible users
            is_difficult: If True, consider difficult chore constraint

        Returns:
            User or None
        """
        today = timezone.now().date()
        logger.info(f"Fairness selection: is_difficult={is_difficult}, eligible_users_count={eligible_users.count()}")

        # Annotate users with count of assigned chores today
        users_with_counts = eligible_users.annotate(
            assigned_today=Count(
                'assigned_instances',
                filter=Q(
                    assigned_instances__status=ChoreInstance.ASSIGNED,
                    assigned_instances__due_at__date=today
                )
            )
        ).order_by('assigned_today', '?')  # Secondary random for tiebreak

        if is_difficult:
            # Exclude users with difficult chores already assigned
            before_filter_count = users_with_counts.count()
            users_with_counts = users_with_counts.exclude(
                assigned_instances__chore__is_difficult=True,
                assigned_instances__status=ChoreInstance.ASSIGNED,
                assigned_instances__due_at__date=today
            )
            after_filter_count = users_with_counts.count()
            logger.info(
                f"Difficult chore filter: {before_filter_count} users before, "
                f"{after_filter_count} users after"
            )

        selected = users_with_counts.first()

        if selected:
            logger.info(
                f"Fairness selected {selected.username} "
                f"({selected.assigned_today} chores assigned today)"
            )

        return selected

    @staticmethod
    def update_rotation_state(chore, user):
        """
        Update rotation state when undesirable chore is completed.

        Args:
            chore: Chore instance
            user: User who completed the chore
        """
        if not chore.is_undesirable:
            return

        today = timezone.now().date()

        RotationState.objects.update_or_create(
            chore=chore,
            user=user,
            defaults={
                'last_completed_date': today
            }
        )

        logger.info(f"Updated rotation state: {user.username} completed {chore.name} on {today}")


class DependencyService:
    """Service for handling chore dependencies."""

    @staticmethod
    def spawn_dependent_chores(parent_instance, completion_time):
        """
        Spawn child chores when parent is completed.

        Args:
            parent_instance: ChoreInstance that was completed
            completion_time: datetime when parent was completed

        Returns:
            list of created ChoreInstance objects
        """
        from chores.models import ChoreDependency, Completion

        # Get who completed the parent chore
        try:
            completion = Completion.objects.get(chore_instance=parent_instance)
            completed_by = completion.completed_by
        except Completion.DoesNotExist:
            # Fallback: If no completion record (shouldn't happen), use assigned_to
            completed_by = parent_instance.assigned_to
            logger.warning(
                f"No completion record found for parent instance {parent_instance.id}. "
                f"Using assigned_to as fallback."
            )

        # Get all chores that depend on this chore
        dependencies = ChoreDependency.objects.filter(
            depends_on=parent_instance.chore
        ).select_related('chore')

        spawned = []

        for dep in dependencies:
            child_chore = dep.chore

            # Check if child chore is active
            if not child_chore.is_active:
                logger.info(f"Skipping inactive dependent chore: {child_chore.name}")
                continue

            # Calculate due time with offset
            due_at = completion_time + timedelta(hours=dep.offset_hours)

            # Calculate distribution time (use child's distribution time on due date)
            due_date = due_at.date()
            distribution_at = timezone.make_aware(
                timezone.datetime.combine(due_date, child_chore.distribution_time)
            )

            # Create child instance - ALWAYS assign to user who completed parent
            # This overrides the child_chore's is_pool or assigned_to settings
            child_instance = ChoreInstance.objects.create(
                chore=child_chore,
                status=ChoreInstance.ASSIGNED,
                assigned_to=completed_by,
                points_value=child_chore.points,
                due_at=due_at,
                distribution_at=distribution_at,
                assignment_reason=ChoreInstance.REASON_PARENT_COMPLETION
            )

            spawned.append(child_instance)
            logger.info(
                f"Spawned dependent chore: {child_chore.name} "
                f"assigned to {completed_by.username} who completed parent "
                f"(due in {dep.offset_hours}h, at {due_at})"
            )

        return spawned

    @staticmethod
    def check_circular_dependency(chore, depends_on):
        """
        Check if adding a dependency would create a circular reference.

        Args:
            chore: Child chore
            depends_on: Parent chore

        Returns:
            bool: True if circular dependency detected, False otherwise
        """
        from chores.models import ChoreDependency

        # Check if depends_on depends on chore (direct circle)
        if ChoreDependency.objects.filter(
            chore=depends_on,
            depends_on=chore
        ).exists():
            return True

        # Check for indirect circles (BFS)
        visited = set()
        queue = [depends_on]

        while queue:
            current = queue.pop(0)

            if current.id in visited:
                continue

            visited.add(current.id)

            # Get chores that current depends on
            parents = ChoreDependency.objects.filter(
                chore=current
            ).values_list('depends_on_id', flat=True)

            for parent_id in parents:
                if parent_id == chore.id:
                    # Found a circle
                    return True
                queue.append(Chore.objects.get(id=parent_id))

        return False


class SkipService:
    """Service for skipping and unskipping chore instances."""

    @staticmethod
    def skip_chore(instance_id, user, reason=None):
        """
        Skip a chore instance (admin only).

        Args:
            instance_id: ChoreInstance ID to skip
            user: User performing the skip (admin)
            reason: Optional reason for skipping

        Returns:
            tuple: (success: bool, message: str, instance: ChoreInstance or None)
        """
        with transaction.atomic():
            try:
                instance = ChoreInstance.objects.select_for_update().get(id=instance_id)
            except ChoreInstance.DoesNotExist:
                return False, "Chore instance not found", None

            # Validation: Cannot skip completed chores
            if instance.status == ChoreInstance.COMPLETED:
                return False, "Cannot skip a completed chore", None

            # Validation: Cannot skip already skipped chores
            if instance.status == ChoreInstance.SKIPPED:
                return False, "This chore is already skipped", None

            # Store previous state for logging
            previous_status = instance.status
            previous_assigned_to = instance.assigned_to

            # Update instance to skipped status
            instance.status = ChoreInstance.SKIPPED
            instance.skip_reason = reason or ""
            instance.skipped_at = timezone.now()
            instance.skipped_by = user
            instance.save()

            # Log action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_SKIP,
                user=user,
                target_user=previous_assigned_to,
                description=f"Skipped {instance.chore.name}" + (f": {reason}" if reason else ""),
                metadata={
                    "chore_id": instance.chore.id,
                    "instance_id": instance.id,
                    "previous_status": previous_status,
                    "previous_assigned_to": previous_assigned_to.id if previous_assigned_to else None,
                    "reason": reason
                }
            )

            logger.info(
                f"Admin {user.username} skipped chore {instance.chore.name} "
                f"(instance {instance.id}, previous status: {previous_status})"
            )

            return True, f"Chore '{instance.chore.name}' has been skipped", instance

    @staticmethod
    def unskip_chore(instance_id, user):
        """
        Restore a skipped chore instance within 24 hours (admin only).

        Args:
            instance_id: ChoreInstance ID to unskip
            user: User performing the unskip (admin)

        Returns:
            tuple: (success: bool, message: str, instance: ChoreInstance or None)
        """
        with transaction.atomic():
            try:
                instance = ChoreInstance.objects.select_for_update().get(id=instance_id)
            except ChoreInstance.DoesNotExist:
                return False, "Chore instance not found", None

            # Validation: Must be skipped status
            if instance.status != ChoreInstance.SKIPPED:
                return False, "This chore is not skipped", None

            # Validation: Check 24-hour window
            settings = Settings.get_settings()
            undo_limit_hours = settings.undo_time_limit_hours
            time_limit = timedelta(hours=undo_limit_hours)

            if timezone.now() - instance.skipped_at > time_limit:
                return False, f"Cannot unskip after {undo_limit_hours} hours", None

            # Restore to appropriate state based on chore type and assignment
            now = timezone.now()
            is_overdue = now > instance.due_at

            # Determine restore state based on chore's is_pool setting and assignment
            if instance.chore.is_pool or not instance.assigned_to:
                # Pool chores or unassigned chores go back to pool
                instance.status = ChoreInstance.POOL
                instance.assigned_to = None
                instance.is_overdue = is_overdue
                if is_overdue:
                    restored_state = "pool (overdue)"
                else:
                    restored_state = "pool"
            else:
                # Assigned chores (is_pool=False) stay assigned to original user
                instance.status = ChoreInstance.ASSIGNED
                instance.is_overdue = is_overdue
                if is_overdue:
                    restored_state = f"assigned to {instance.assigned_to.username} (overdue)"
                else:
                    restored_state = f"assigned to {instance.assigned_to.username}"

            # Clear skip tracking fields
            instance.skip_reason = None
            instance.skipped_at = None
            instance.skipped_by = None
            instance.save()

            # Log action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_UNSKIP,
                user=user,
                target_user=instance.assigned_to,
                description=f"Unskipped {instance.chore.name} (restored to {restored_state})",
                metadata={
                    "chore_id": instance.chore.id,
                    "instance_id": instance.id,
                    "restored_status": instance.status,
                    "restored_assigned_to": instance.assigned_to.id if instance.assigned_to else None
                }
            )

            logger.info(
                f"Admin {user.username} unskipped chore {instance.chore.name} "
                f"(instance {instance.id}, restored to {restored_state})"
            )

            return True, f"Chore '{instance.chore.name}' has been restored to {restored_state}", instance


class RescheduleService:
    """Service for rescheduling chores (admin only)."""

    @staticmethod
    def reschedule_chore(chore_id, new_date, user, reason=None):
        """
        Reschedule a chore to a specific date (overrides normal schedule).

        Args:
            chore_id: ID of the chore to reschedule
            new_date: date object for when chore should next appear
            user: User performing the reschedule (must be admin)
            reason: Optional reason for rescheduling

        Returns:
            tuple: (success: bool, message: str, chore: Chore or None)
        """
        try:
            chore = Chore.objects.get(id=chore_id, is_active=True)
        except Chore.DoesNotExist:
            return False, "Chore not found or is inactive", None

        # Validate date is in the future
        today = timezone.now().date()
        if new_date < today:
            return False, "Cannot reschedule to a past date", None

        # Update reschedule fields
        chore.rescheduled_date = new_date
        chore.reschedule_reason = reason or ""
        chore.rescheduled_by = user
        chore.rescheduled_at = timezone.now()
        chore.save()

        # Log the action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_RESCHEDULE,
            user=user,
            description=f"Rescheduled '{chore.name}' to {new_date.strftime('%Y-%m-%d')}" +
                       (f": {reason}" if reason else ""),
            metadata={
                "chore_id": chore.id,
                "new_date": new_date.isoformat(),
                "reason": reason or ""
            }
        )

        logger.info(
            f"Admin {user.username} rescheduled chore '{chore.name}' "
            f"to {new_date.strftime('%Y-%m-%d')}"
        )

        return True, f"Chore '{chore.name}' rescheduled to {new_date.strftime('%B %d, %Y')}", chore

    @staticmethod
    def clear_reschedule(chore_id, user):
        """
        Clear reschedule and resume normal schedule.

        Args:
            chore_id: ID of the chore
            user: User clearing the reschedule (must be admin)

        Returns:
            tuple: (success: bool, message: str, chore: Chore or None)
        """
        try:
            chore = Chore.objects.get(id=chore_id, is_active=True)
        except Chore.DoesNotExist:
            return False, "Chore not found or is inactive", None

        if not chore.rescheduled_date:
            return False, "Chore is not currently rescheduled", None

        # Clear reschedule fields
        chore.rescheduled_date = None
        chore.reschedule_reason = ""
        chore.rescheduled_by = None
        chore.rescheduled_at = None
        chore.save()

        # Log the action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_CLEAR_RESCHEDULE,
            user=user,
            description=f"Cleared reschedule for '{chore.name}' (resumed normal schedule)",
            metadata={
                "chore_id": chore.id
            }
        )

        logger.info(
            f"Admin {user.username} cleared reschedule for chore '{chore.name}'"
        )

        return True, f"Reschedule cleared for '{chore.name}' - resumed normal schedule", chore


class UnclaimService:
    """Service for unclaiming chores (kiosk mode)."""

    @staticmethod
    def unclaim_chore(instance_id):
        """
        Unclaim a chore instance and return it to the pool.

        This allows the assigned user to release a chore back to the pool
        for someone else to claim or complete.

        Args:
            instance_id: ID of the ChoreInstance to unclaim

        Returns:
            tuple: (success: bool, message: str, instance: ChoreInstance or None)
        """
        try:
            instance = ChoreInstance.objects.select_for_update().get(id=instance_id)
        except ChoreInstance.DoesNotExist:
            return False, "Chore instance not found", None

        # Validate the instance is eligible for unclaim
        if instance.status != ChoreInstance.ASSIGNED:
            return False, "This chore is not assigned and cannot be unclaimed", None

        if not instance.chore.is_pool:
            return False, "Only pool chores can be unclaimed", None

        # Prevent unclaiming force-assigned or manually-assigned chores
        if instance.assignment_reason in [ChoreInstance.REASON_FORCE_ASSIGNED, ChoreInstance.REASON_MANUAL]:
            return False, "Cannot unclaim force-assigned or manually-assigned chores", None

        if instance.status == ChoreInstance.COMPLETED:
            return False, "This chore has already been completed", None

        # Store the assigned user for logging
        previously_assigned_to = instance.assigned_to

        # Return the chore to the pool
        instance.status = ChoreInstance.POOL
        instance.assigned_to = None
        instance.assigned_at = None
        instance.assignment_reason = ""  # Empty string, not None (field has blank=True but not null=True)
        instance.save()

        # Restore the user's claim allowance if they had claimed it
        if previously_assigned_to:
            previously_assigned_to.claims_today = max(0, previously_assigned_to.claims_today - 1)
            previously_assigned_to.save()

        # Log the action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_UNCLAIM,
            user=previously_assigned_to,
            target_user=previously_assigned_to,
            description=f"Unclaimed '{instance.chore.name}' (returned to pool)",
            metadata={
                "instance_id": instance.id,
                "chore_id": instance.chore.id,
                "chore_name": instance.chore.name,
                "previously_assigned_to": previously_assigned_to.id if previously_assigned_to else None
            }
        )

        return True, f"Chore '{instance.chore.name}' returned to pool", instance
