"""
Service layer for Arcade Mode logic.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
import logging

from chores.models import (
    Chore, ChoreInstance, ArcadeSession, ArcadeCompletion,
    ArcadeHighScore, PointsLedger, Completion, CompletionShare
)
from core.models import ActionLog
from users.models import User
from core.notifications import NotificationService

logger = logging.getLogger(__name__)


class ArcadeService:
    """Service for managing arcade mode challenges and competitions."""

    @staticmethod
    @transaction.atomic
    def start_arcade(user, chore_instance):
        """
        Start arcade mode for a user on a chore instance.

        Args:
            user: User starting arcade
            chore_instance: ChoreInstance to arcade

        Returns:
            tuple: (success: bool, message: str, arcade_session: ArcadeSession or None)
        """
        # Check if user already has an active arcade session
        active_session = ArcadeSession.objects.filter(
            user=user,
            is_active=True,
            status=ArcadeSession.STATUS_ACTIVE
        ).first()

        if active_session:
            return False, f"You already have an active arcade session for '{active_session.chore.name}'. Please complete or cancel it first.", None

        # If it's a pool chore, claim it to the user
        if chore_instance.status == ChoreInstance.POOL:
            chore_instance.status = ChoreInstance.ASSIGNED
            chore_instance.assigned_to = user
            chore_instance.assigned_at = timezone.now()
            chore_instance.assignment_reason = ChoreInstance.REASON_CLAIMED
            chore_instance.save()
        # If it's already assigned, verify it's assigned to this user
        elif chore_instance.status == ChoreInstance.ASSIGNED:
            if chore_instance.assigned_to != user:
                return False, "This chore is assigned to someone else", None
            # Already assigned to this user, just start arcade
        else:
            return False, f"Cannot start arcade on chore with status: {chore_instance.get_status_display()}", None

        # Create arcade session
        arcade_session = ArcadeSession.objects.create(
            user=user,
            chore_instance=chore_instance,
            chore=chore_instance.chore,
            status=ArcadeSession.STATUS_ACTIVE,
            is_active=True,
            attempt_number=1,
            cumulative_seconds=0
        )

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,  # We'll use ADMIN type for now
            user=user,
            description=f"Started arcade mode for '{chore_instance.chore.name}'",
            metadata={
                'session_id': arcade_session.id,
                'chore_id': chore_instance.chore.id,
            }
        )

        logger.info(f"User {user.username} started arcade for {chore_instance.chore.name}")

        return True, "Arcade mode started! Timer is running.", arcade_session

    @staticmethod
    @transaction.atomic
    def stop_arcade(arcade_session):
        """
        Stop arcade timer and prepare for judge approval.

        Args:
            arcade_session: ArcadeSession to stop

        Returns:
            tuple: (success: bool, message: str, elapsed_seconds: int)
        """
        if arcade_session.status != ArcadeSession.STATUS_ACTIVE:
            return False, "Arcade session is not active", 0

        # Calculate elapsed time
        arcade_session.end_time = timezone.now()
        arcade_session.elapsed_seconds = arcade_session.get_elapsed_time()
        arcade_session.status = ArcadeSession.STATUS_STOPPED
        arcade_session.is_active = False
        arcade_session.save()

        logger.info(
            f"User {arcade_session.user.username} stopped arcade for "
            f"{arcade_session.chore.name} at {arcade_session.format_time()}"
        )

        return True, "Timer stopped. Please select a judge for approval.", arcade_session.elapsed_seconds

    @staticmethod
    @transaction.atomic
    def approve_arcade(arcade_session, judge, notes=''):
        """
        Judge approves arcade completion, award points, update leaderboard.

        Args:
            arcade_session: ArcadeSession to approve
            judge: User who is judging
            notes: Optional judge notes

        Returns:
            tuple: (success: bool, message: str, arcade_completion: ArcadeCompletion or None)
        """
        if arcade_session.status != ArcadeSession.STATUS_STOPPED:
            return False, "Arcade session must be stopped first", None

        if judge == arcade_session.user:
            return False, "You cannot judge your own arcade completion", None

        # Update session status
        arcade_session.status = ArcadeSession.STATUS_APPROVED
        arcade_session.save()

        # Create arcade completion record
        base_points = arcade_session.chore_instance.points_value

        # Create completion record
        arcade_completion = ArcadeCompletion.objects.create(
            user=arcade_session.user,
            chore=arcade_session.chore,
            arcade_session=arcade_session,
            chore_instance=arcade_session.chore_instance,
            completion_time_seconds=arcade_session.elapsed_seconds,
            judge=judge,
            approved=True,
            judge_notes=notes,
            base_points=base_points,
            bonus_points=Decimal('0.00'),  # Will be calculated by update_high_scores
            total_points=base_points  # Will be updated after bonus calculation
        )

        # Update high scores and calculate bonus
        ArcadeService.update_high_scores(arcade_completion)

        # Award points to user
        arcade_completion.refresh_from_db()  # Get updated bonus_points
        user = arcade_session.user
        user.add_points(arcade_completion.total_points, weekly=True, all_time=True)
        user.save()

        # Create points ledger entry
        PointsLedger.objects.create(
            user=user,
            transaction_type=PointsLedger.TYPE_COMPLETION,
            points_change=arcade_completion.total_points,
            balance_after=user.all_time_points,
            description=f"Arcade completion: {arcade_session.chore.name} ({arcade_completion.format_time()})",
            created_by=judge
        )

        # Mark chore instance as completed
        chore_instance = arcade_session.chore_instance
        completion_time = timezone.now()
        chore_instance.status = ChoreInstance.COMPLETED
        chore_instance.completed_at = completion_time
        chore_instance.save()

        # Create standard Completion record (for compatibility with existing system)
        completion = Completion.objects.create(
            chore_instance=chore_instance,
            completed_by=user,
            was_late=chore_instance.is_overdue
        )

        # Spawn dependent chores (if any)
        from chores.services import DependencyService, AssignmentService
        spawned_children = DependencyService.spawn_dependent_chores(chore_instance, completion_time)

        # Update rotation state for undesirable chores
        AssignmentService.update_rotation_state(arcade_session.chore, user)

        # Create completion share (no helpers in arcade mode)
        CompletionShare.objects.create(
            completion=completion,
            user=user,
            points_awarded=arcade_completion.total_points
        )

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=judge,
            target_user=user,
            description=f"Approved arcade completion for '{arcade_session.chore.name}' - {arcade_completion.format_time()}",
            metadata={
                'session_id': arcade_session.id,
                'completion_id': arcade_completion.id,
                'time': arcade_completion.completion_time_seconds,
                'points': str(arcade_completion.total_points),
                'is_high_score': arcade_completion.is_high_score,
                'rank': arcade_completion.rank_at_completion,
                'spawned_children': len(spawned_children),
            }
        )

        # Send Home Assistant webhook if this is a new record
        if arcade_completion.rank_at_completion == 1:
            NotificationService.send_arcade_new_record(
                user=user,
                chore_name=arcade_session.chore.name,
                time_seconds=arcade_completion.completion_time_seconds,
                points=arcade_completion.total_points
            )

        logger.info(
            f"Judge {judge.username} approved arcade for {user.username} - "
            f"{arcade_session.chore.name} in {arcade_completion.format_time()}"
        )

        return True, f"Approved! +{arcade_completion.total_points} points awarded.", arcade_completion

    @staticmethod
    @transaction.atomic
    def deny_arcade(arcade_session, judge, notes=''):
        """
        Judge denies arcade completion, offer retry.

        Args:
            arcade_session: ArcadeSession to deny
            judge: User who is judging
            notes: Optional judge notes

        Returns:
            tuple: (success: bool, message: str)
        """
        if arcade_session.status != ArcadeSession.STATUS_STOPPED:
            return False, "Arcade session must be stopped first"

        if judge == arcade_session.user:
            return False, "You cannot judge your own arcade completion"

        # Update session status
        arcade_session.status = ArcadeSession.STATUS_DENIED
        arcade_session.save()

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=judge,
            target_user=arcade_session.user,
            description=f"Denied arcade completion for '{arcade_session.chore.name}'",
            metadata={
                'session_id': arcade_session.id,
                'reason': notes,
                'time': arcade_session.elapsed_seconds,
            }
        )

        logger.info(
            f"Judge {judge.username} denied arcade for {arcade_session.user.username} - "
            f"{arcade_session.chore.name}"
        )

        return True, f"Judge {judge.get_display_name()} denied the completion. You can continue arcade or complete normally."

    @staticmethod
    @transaction.atomic
    def continue_arcade(arcade_session):
        """
        Resume arcade timer after denial.

        Args:
            arcade_session: ArcadeSession to continue

        Returns:
            tuple: (success: bool, message: str)
        """
        if arcade_session.status != ArcadeSession.STATUS_DENIED:
            return False, "Can only continue denied arcade sessions"

        # Resume timer with cumulative time
        arcade_session.cumulative_seconds = arcade_session.elapsed_seconds
        arcade_session.start_time = timezone.now()
        arcade_session.end_time = None
        arcade_session.status = ArcadeSession.STATUS_ACTIVE
        arcade_session.is_active = True
        arcade_session.attempt_number += 1
        arcade_session.save()

        logger.info(
            f"User {arcade_session.user.username} resumed arcade for "
            f"{arcade_session.chore.name} (attempt #{arcade_session.attempt_number})"
        )

        return True, "Arcade resumed! Timer is running again."

    @staticmethod
    @transaction.atomic
    def cancel_arcade(arcade_session):
        """
        Cancel arcade mode, return chore to pool.

        Args:
            arcade_session: ArcadeSession to cancel

        Returns:
            tuple: (success: bool, message: str)
        """
        if arcade_session.status == ArcadeSession.STATUS_APPROVED:
            return False, "Cannot cancel approved arcade session"

        # Mark session as cancelled
        arcade_session.status = ArcadeSession.STATUS_CANCELLED
        arcade_session.is_active = False
        if not arcade_session.end_time:
            arcade_session.end_time = timezone.now()
            arcade_session.elapsed_seconds = arcade_session.get_elapsed_time()
        arcade_session.save()

        # Return chore to pool
        chore_instance = arcade_session.chore_instance
        chore_instance.status = ChoreInstance.POOL
        chore_instance.assigned_to = None
        chore_instance.assigned_at = None
        chore_instance.assignment_reason = ''
        chore_instance.save()

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=arcade_session.user,
            description=f"Cancelled arcade mode for '{arcade_session.chore.name}'",
            metadata={
                'session_id': arcade_session.id,
            }
        )

        logger.info(
            f"User {arcade_session.user.username} cancelled arcade for "
            f"{arcade_session.chore.name}"
        )

        return True, "Arcade cancelled. Chore returned to pool."

    @staticmethod
    @transaction.atomic
    def update_high_scores(arcade_completion):
        """
        Update leaderboard after new completion.
        Calculates bonus points and updates high score rankings.

        Args:
            arcade_completion: ArcadeCompletion to process
        """
        chore = arcade_completion.chore
        time_seconds = arcade_completion.completion_time_seconds

        # Get current top 3 high scores
        existing_scores = list(
            ArcadeHighScore.objects.filter(chore=chore).order_by('rank')
        )

        # Determine if this beats any existing scores
        new_rank = None
        is_new_record = False

        if not existing_scores:
            # First score for this chore
            new_rank = 1
            is_new_record = True
        else:
            # Check if faster than existing scores
            for score in existing_scores:
                if time_seconds < score.time_seconds:
                    new_rank = score.rank
                    is_new_record = (new_rank == 1)
                    break

            # If not faster than any existing, check if we have room for more
            if new_rank is None and len(existing_scores) < 3:
                new_rank = len(existing_scores) + 1

        # Calculate bonus points
        bonus_points = ArcadeService.calculate_bonus_points(
            arcade_completion.base_points,
            new_rank,
            is_new_record
        )

        # Update completion record
        arcade_completion.bonus_points = bonus_points
        arcade_completion.total_points = arcade_completion.base_points + bonus_points
        arcade_completion.is_high_score = (new_rank is not None)
        arcade_completion.rank_at_completion = new_rank
        arcade_completion.save()

        # Update high scores table if needed
        if new_rank is not None:
            # Shift existing ranks down
            for score in existing_scores:
                if score.rank >= new_rank:
                    if score.rank < 3:
                        score.rank += 1
                        score.save()
                    else:
                        # 3rd place being displaced - delete it
                        score.delete()

            # Create new high score entry
            ArcadeHighScore.objects.create(
                chore=chore,
                user=arcade_completion.user,
                arcade_completion=arcade_completion,
                time_seconds=time_seconds,
                rank=new_rank,
                achieved_at=arcade_completion.completed_at
            )

            logger.info(
                f"New high score! {arcade_completion.user.username} ranked #{new_rank} "
                f"for {chore.name} with {arcade_completion.format_time()}"
            )

    @staticmethod
    def calculate_bonus_points(base_points, rank, is_new_record):
        """
        Calculate bonus points based on ranking.

        Args:
            base_points: Base points for the chore
            rank: Ranking achieved (1, 2, 3, or None)
            is_new_record: Whether this beats the current #1

        Returns:
            Decimal: Bonus points
        """
        if rank is None:
            return Decimal('0.00')

        if is_new_record:
            # +50% bonus for new record
            return base_points * Decimal('0.50')
        elif rank in [1, 2, 3]:
            # +25% bonus for top 3
            return base_points * Decimal('0.25')

        return Decimal('0.00')

    @staticmethod
    def get_active_session(user):
        """
        Get user's active arcade session if any.

        Args:
            user: User to check

        Returns:
            ArcadeSession or None
        """
        return ArcadeSession.objects.filter(
            user=user,
            is_active=True,
            status=ArcadeSession.STATUS_ACTIVE
        ).select_related('chore', 'chore_instance').first()

    @staticmethod
    def get_high_score(chore):
        """
        Get the #1 high score for a chore.

        Args:
            chore: Chore to get high score for

        Returns:
            ArcadeHighScore or None
        """
        return ArcadeHighScore.objects.filter(
            chore=chore,
            rank=1
        ).select_related('user').first()

    @staticmethod
    def get_top_scores(chore):
        """
        Get top 3 high scores for a chore.

        Args:
            chore: Chore to get scores for

        Returns:
            QuerySet of ArcadeHighScore
        """
        return ArcadeHighScore.objects.filter(
            chore=chore
        ).select_related('user', 'arcade_completion').order_by('rank')

    @staticmethod
    def get_user_stats(user):
        """
        Get arcade statistics for a user.

        Args:
            user: User to get stats for

        Returns:
            dict: Statistics dictionary
        """
        total_attempts = ArcadeSession.objects.filter(user=user).count()
        total_completions = ArcadeCompletion.objects.filter(user=user).count()
        high_scores_held = ArcadeHighScore.objects.filter(user=user).count()
        total_arcade_points = sum(
            completion.total_points
            for completion in ArcadeCompletion.objects.filter(user=user)
        ) or Decimal('0.00')

        success_rate = 0
        if total_attempts > 0:
            success_rate = int((total_completions / total_attempts) * 100)

        return {
            'total_attempts': total_attempts,
            'total_completions': total_completions,
            'success_rate': success_rate,
            'high_scores_held': high_scores_held,
            'total_arcade_points': total_arcade_points,
        }

    @staticmethod
    def get_pending_approvals():
        """
        Get all arcade sessions waiting for judge approval.

        Returns:
            QuerySet of ArcadeSession
        """
        return ArcadeSession.objects.filter(
            status=ArcadeSession.STATUS_STOPPED
        ).select_related('user', 'chore', 'chore_instance').order_by('-end_time')
