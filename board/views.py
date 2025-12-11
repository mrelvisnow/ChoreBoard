"""
Views for ChoreBoard frontend.
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
from chores.models import ChoreInstance, Completion, CompletionShare, PointsLedger, Chore
from chores.services import AssignmentService, DependencyService
from chores.arcade_service import ArcadeService
from users.models import User
from core.models import Settings, ActionLog, WeeklySnapshot
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


def main_board(request):
    """
    Main board view showing all chores (pool + assigned) with color coding.
    """
    now = timezone.now()
    today = now.date()

    # Get all active chore instances for today (excluding skipped)
    # Bug #6 Fix: Filter out instances of inactive chores
    # Include: due today, overdue from past, OR no due date (sentinel date)
    # Note: Use year > 3000 instead of >= 9999 to avoid overflow errors
    # Note: Chores "for today" are created with due_at = start of tomorrow, so include tomorrow too
    from datetime import datetime, timedelta
    far_future = timezone.make_aware(datetime(3000, 1, 1))
    tomorrow = today + timedelta(days=1)

    pool_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.POOL,
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__date=tomorrow) |  # Due tomorrow (chores created "for today")
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date beyond year 3000)
    ).select_related('chore').order_by('due_at')

    # Get assigned chores: include chores due today, overdue, OR no due date
    # Only include chores assigned to users who are eligible for points (to match what's displayed)
    assigned_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.ASSIGNED,
        chore__is_active=True,
        assigned_to__eligible_for_points=True,  # Only count chores for eligible users
        assigned_to__isnull=False  # Exclude unassigned chores
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__date=tomorrow) |  # Due tomorrow (chores created "for today")
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date beyond year 3000)
    ).select_related('chore', 'assigned_to').order_by('due_at')

    # Feature #8: Group assigned chores by user
    from collections import defaultdict
    chores_by_user = defaultdict(lambda: {'overdue': [], 'ontime': []})

    # Also collect stats during iteration
    overdue_assigned = []
    ontime_assigned = []

    for chore in assigned_chores:
        user = chore.assigned_to
        if chore.is_overdue:
            chores_by_user[user]['overdue'].append(chore)
            overdue_assigned.append(chore)
        else:
            chores_by_user[user]['ontime'].append(chore)
            ontime_assigned.append(chore)

    # Convert to list of dicts for template
    assigned_by_user = [
        {
            'user': user,
            'overdue': chores['overdue'],
            'ontime': chores['ontime'],
            'total': len(chores['overdue']) + len(chores['ontime'])
        }
        for user, chores in chores_by_user.items()
    ]

    # Sort by user name
    assigned_by_user.sort(key=lambda x: x['user'].first_name or x['user'].username)

    # Calculate total assigned (for stat card)
    total_assigned_count = len(overdue_assigned) + len(ontime_assigned)

    # Get all users for the user selector (only those eligible for points)
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    # Get admin users only for reschedule function
    admin_users = User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True)
    ).filter(
        is_active=True
    ).order_by('first_name', 'username')

    # Get active arcade session (kiosk-mode compatible)
    # Check if ANY user has an active arcade session
    from chores.models import ArcadeSession
    active_arcade_session = ArcadeSession.objects.filter(
        status=ArcadeSession.STATUS_ACTIVE
    ).select_related('chore', 'user').first()

    context = {
        'pool_chores': pool_chores,
        'assigned_by_user': assigned_by_user,  # NEW: Grouped by user
        'overdue_assigned': overdue_assigned,  # For stats
        'ontime_assigned': ontime_assigned,    # For stats
        'total_assigned_count': total_assigned_count,  # Total assigned (on-time + overdue)
        'users': users,
        'admin_users': admin_users,
        'today': today,
        'now': now,
        'active_arcade_session': active_arcade_session,  # Arcade mode
    }

    return render(request, 'board/main.html', context)


def pool_only(request):
    """
    Pool-only view showing only unclaimed chores.
    """
    now = timezone.now()
    today = now.date()

    # Use year > 3000 to avoid overflow errors with year >= 9999
    from datetime import datetime, timedelta
    far_future = timezone.make_aware(datetime(3000, 1, 1))
    tomorrow = today + timedelta(days=1)

    pool_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.POOL,
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__date=tomorrow) |  # Due tomorrow (chores created "for today")
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date beyond year 3000)
    ).select_related('chore').order_by('due_at')

    # Get all users for the user selector (only those eligible for points)
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    context = {
        'pool_chores': pool_chores,
        'users': users,
        'today': today,
    }

    return render(request, 'board/pool.html', context)


def user_board(request, username):
    """
    User-specific board showing chores assigned to a specific user.
    """
    user = get_object_or_404(User, username=username, is_active=True)
    now = timezone.now()
    today = now.date()

    # Use year > 3000 to avoid overflow errors with year >= 9999
    from datetime import datetime, timedelta
    far_future = timezone.make_aware(datetime(3000, 1, 1))
    tomorrow = today + timedelta(days=1)

    # Get chores assigned to this user: include chores due today, overdue, OR no due date
    assigned_chores = ChoreInstance.objects.filter(
        assigned_to=user,
        status__in=[ChoreInstance.ASSIGNED, ChoreInstance.POOL],
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__date=tomorrow) |  # Due tomorrow (chores created "for today")
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date beyond year 3000)
    ).select_related('chore').order_by('due_at')

    # Separate overdue from on-time
    overdue_chores = assigned_chores.filter(is_overdue=True)
    ontime_chores = assigned_chores.filter(is_overdue=False)

    # Get user's current points
    weekly_points = user.weekly_points
    all_time_points = user.all_time_points

    # Get all users for switching (only those eligible for points)
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    # Check for active arcade session for THIS user only (kiosk-mode compatible)
    from chores.models import ArcadeSession
    active_arcade_session = ArcadeSession.objects.filter(
        status=ArcadeSession.STATUS_ACTIVE,
        user=user  # Only show arcade banner if this user is playing
    ).select_related('chore', 'user').first()

    context = {
        'selected_user': user,
        'overdue_chores': overdue_chores,
        'ontime_chores': ontime_chores,
        'weekly_points': weekly_points,
        'all_time_points': all_time_points,
        'users': users,
        'today': today,
        'active_arcade_session': active_arcade_session,
    }

    return render(request, 'board/user.html', context)


def user_board_minimal(request, username):
    """
    Minimal user board showing ONLY chores assigned to user.
    No points, no user selector, no stats - just the chores.

    Kiosk-mode compatible: Uses username from URL, not logged-in user.
    """
    from chores.models import ArcadeSession
    from datetime import timedelta

    # Get user from URL parameter (kiosk-mode compatible, no login required)
    user = get_object_or_404(User, username=username, is_active=True)
    now = timezone.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)

    # Get chores assigned to this user: include chores due today OR overdue from previous days
    assigned_chores = ChoreInstance.objects.filter(
        assigned_to=user,
        status__in=[ChoreInstance.ASSIGNED, ChoreInstance.POOL],
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) | Q(due_at__date=tomorrow) | Q(due_at__lt=now)  # Due today/tomorrow OR past due
    ).select_related('chore').order_by('is_overdue', 'due_at')

    # Check for active arcade session for THIS user only (from URL username)
    # This ensures Alice's arcade session only shows on /user/alice/minimal/
    # and not on /user/bob/minimal/ (kiosk-mode friendly)
    active_arcade_session = ArcadeSession.objects.filter(
        status=ArcadeSession.STATUS_ACTIVE,
        user=user  # Filter by user from URL, not request.user
    ).select_related('chore', 'user').first()

    # Get all users for arcade mode selection (only those eligible for points)
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    context = {
        'user': user,
        'assigned_chores': assigned_chores,
        'today': today,
        'active_arcade_session': active_arcade_session,
        'users': users,
    }

    return render(request, 'board/user_minimal.html', context)


def pool_minimal(request):
    """
    Minimal pool view showing ONLY unclaimed chores.
    No navigation, no header, no user selector - just the pool chores.
    Kiosk-mode compatible.
    """
    from chores.models import ArcadeSession

    now = timezone.now()
    today = now.date()

    # Get all pool chores for today
    # Use year > 3000 to avoid overflow errors with year >= 9999
    from datetime import datetime, timedelta
    far_future = timezone.make_aware(datetime(3000, 1, 1))
    tomorrow = today + timedelta(days=1)

    pool_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.POOL,
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__date=tomorrow) |  # Due tomorrow (chores created "for today")
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date beyond year 3000)
    ).select_related('chore').order_by('due_at')

    # Check for any active arcade session (kiosk-mode compatible)
    active_arcade_session = ArcadeSession.objects.filter(
        status=ArcadeSession.STATUS_ACTIVE
    ).select_related('chore', 'user').first()

    # Get all users for arcade mode and claiming (only those eligible for points)
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    context = {
        'pool_chores': pool_chores,
        'today': today,
        'active_arcade_session': active_arcade_session,
        'users': users,
    }

    return render(request, 'board/pool_minimal.html', context)


def assigned_minimal(request):
    """
    Minimal view showing all assigned chores grouped by user.
    No navigation, no header - just the assigned chores by user.
    Kiosk-mode compatible.
    """
    from collections import defaultdict
    from chores.models import ArcadeSession

    now = timezone.now()
    today = now.date()

    # Use year > 3000 to avoid overflow errors with year >= 9999
    from datetime import datetime, timedelta
    far_future = timezone.make_aware(datetime(3000, 1, 1))
    tomorrow = today + timedelta(days=1)

    # Get all assigned chores: include chores due today, overdue, OR no due date
    assigned_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.ASSIGNED,
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__date=tomorrow) |  # Due tomorrow (chores created "for today")
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date beyond year 3000)
    ).exclude(status=ChoreInstance.SKIPPED).select_related('chore', 'assigned_to').order_by('due_at')

    # Group assigned chores by user
    chores_by_user = defaultdict(lambda: {'overdue': [], 'ontime': []})

    for chore in assigned_chores:
        user = chore.assigned_to
        if chore.is_overdue:
            chores_by_user[user]['overdue'].append(chore)
        else:
            chores_by_user[user]['ontime'].append(chore)

    # Convert to list of dicts for template
    # Filter out users not eligible for points (and None users from unassigned chores)
    assigned_by_user = [
        {
            'user': user,
            'overdue': chores['overdue'],
            'ontime': chores['ontime'],
            'total': len(chores['overdue']) + len(chores['ontime'])
        }
        for user, chores in chores_by_user.items()
        if user is not None and user.eligible_for_points
    ]

    # Sort by user name
    assigned_by_user.sort(key=lambda x: x['user'].first_name or x['user'].username)

    # Check for any active arcade session (kiosk-mode compatible)
    active_arcade_session = ArcadeSession.objects.filter(
        status=ArcadeSession.STATUS_ACTIVE
    ).select_related('chore', 'user').first()

    # Get all users for completing chores (only those eligible for points)
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    context = {
        'assigned_by_user': assigned_by_user,
        'today': today,
        'active_arcade_session': active_arcade_session,
        'users': users,
    }

    return render(request, 'board/assigned_minimal.html', context)


def users_minimal(request):
    """
    Minimal view showing all users as cards.
    No navigation, no header - just user cards with their weekly and all-time points.
    Kiosk-mode compatible.
    """
    from chores.models import ArcadeSession
    from datetime import timedelta

    now = timezone.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)

    # Get all users eligible for points
    users = User.objects.filter(
        is_active=True,
        can_be_assigned=True,
        eligible_for_points=True
    ).order_by('first_name', 'username')

    # Get chore counts per user: include chores due today OR overdue from previous days
    assigned_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.ASSIGNED,
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) | Q(due_at__date=tomorrow) | Q(due_at__lt=now)  # Due today/tomorrow OR past due
    ).exclude(status=ChoreInstance.SKIPPED).select_related('assigned_to')

    # Count chores per user
    chore_counts = {}
    for chore in assigned_chores:
        if chore.assigned_to and chore.assigned_to.eligible_for_points:
            user_id = chore.assigned_to.id
            chore_counts[user_id] = chore_counts.get(user_id, 0) + 1

    # Attach chore counts to users
    users_with_counts = []
    for user in users:
        users_with_counts.append({
            'user': user,
            'chore_count': chore_counts.get(user.id, 0)
        })

    # Check for any active arcade session (kiosk-mode compatible)
    active_arcade_session = ArcadeSession.objects.filter(
        status=ArcadeSession.STATUS_ACTIVE
    ).select_related('chore', 'user').first()

    context = {
        'users_with_counts': users_with_counts,
        'today': today,
        'active_arcade_session': active_arcade_session,
    }

    return render(request, 'board/users_minimal.html', context)


def leaderboard(request):
    """
    Leaderboard view showing weekly and all-time rankings.
    """
    # Get leaderboard type from query param (default: weekly)
    board_type = request.GET.get('type', 'weekly')

    if board_type == 'alltime':
        # All-time points
        ranked_users = User.objects.filter(
            eligible_for_points=True,
            is_active=True
        ).order_by('-all_time_points')
        points_field = 'all_time_points'
        title = 'All-Time Leaderboard'
    else:
        # Weekly points
        ranked_users = User.objects.filter(
            eligible_for_points=True,
            is_active=True
        ).order_by('-weekly_points')
        points_field = 'weekly_points'
        title = 'Weekly Leaderboard'

    # Add rank to each user
    ranked_list = []
    for idx, user in enumerate(ranked_users, start=1):
        points = getattr(user, points_field)
        ranked_list.append({
            'rank': idx,
            'user': user,
            'points': points,
        })

    context = {
        'board_type': board_type,
        'title': title,
        'ranked_list': ranked_list,
    }

    return render(request, 'board/leaderboard.html', context)


def leaderboard_minimal(request):
    """
    Minimal leaderboard view showing weekly and all-time rankings.
    No navigation, no header - just the leaderboard.
    Kiosk-mode compatible.
    """
    # Get leaderboard type from query param (default: weekly)
    board_type = request.GET.get('type', 'weekly')

    if board_type == 'alltime':
        # All-time points
        ranked_users = User.objects.filter(
            eligible_for_points=True,
            is_active=True
        ).order_by('-all_time_points')
        points_field = 'all_time_points'
        title = 'All-Time Leaderboard'
    else:
        # Weekly points
        ranked_users = User.objects.filter(
            eligible_for_points=True,
            is_active=True
        ).order_by('-weekly_points')
        points_field = 'weekly_points'
        title = 'Weekly Leaderboard'

    # Add rank to each user
    ranked_list = []
    for idx, user in enumerate(ranked_users, start=1):
        points = getattr(user, points_field)
        ranked_list.append({
            'rank': idx,
            'user': user,
            'points': points,
        })

    context = {
        'board_type': board_type,
        'title': title,
        'ranked_list': ranked_list,
    }

    return render(request, 'board/leaderboard_minimal.html', context)


@login_required
def quick_add_task(request):
    """
    Quick-add interface for creating one-time tasks.
    Available to any logged-in user.
    """
    if request.method == 'GET':
        # Get all users for assignment dropdown
        users = User.objects.filter(
            is_active=True,
            can_be_assigned=True,
            eligible_for_points=True
        ).order_by('first_name', 'username')

        return render(request, 'board/quick_add_task.html', {'users': users})

    elif request.method == 'POST':
        # Create one-time task
        try:
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            points = request.POST.get('points', '10')
            is_difficult = request.POST.get('is_difficult') == 'true'

            # Security: Non-admin users can only create 0-point tasks to prevent abuse
            if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
                points = Decimal('0.00')
            else:
                # Validate points for admin users
                try:
                    points = Decimal(points)
                    if points < 0 or points > 999.99:
                        return JsonResponse({'error': 'Points must be between 0 and 999.99'}, status=400)
                except (ValueError, TypeError):
                    return JsonResponse({'error': 'Invalid points value'}, status=400)

            # Assignment
            assignment_type = request.POST.get('assignment_type', 'pool')
            assigned_to_id = request.POST.get('assigned_to')

            # Due date (optional)
            from datetime import datetime
            due_date_str = request.POST.get('due_date', '').strip()
            one_time_due_date = None
            if due_date_str:
                try:
                    one_time_due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return JsonResponse({'error': 'Invalid due date format'}, status=400)

            # Validate
            if not name:
                return JsonResponse({'error': 'Name is required'}, status=400)

            # Create chore
            with transaction.atomic():
                chore = Chore.objects.create(
                    name=name,
                    description=description,
                    schedule_type=Chore.ONE_TIME,
                    one_time_due_date=one_time_due_date,
                    points=points,
                    is_difficult=is_difficult,
                    is_active=True,
                    is_pool=(assignment_type == 'pool')
                )

                # If directly assigned, assign the instance
                if assignment_type == 'assigned' and assigned_to_id:
                    try:
                        assigned_user = User.objects.get(id=assigned_to_id, is_active=True, can_be_assigned=True)
                        instance = ChoreInstance.objects.filter(chore=chore).first()
                        if instance:
                            instance.status = ChoreInstance.ASSIGNED
                            instance.assigned_to = assigned_user
                            instance.assigned_at = timezone.now()
                            instance.assignment_reason = ChoreInstance.REASON_FIXED
                            instance.save(update_fields=['status', 'assigned_to', 'assigned_at', 'assignment_reason'])

                            ActionLog.objects.create(
                                action_type=ActionLog.ACTION_ADMIN,
                                user=request.user if request.user.is_authenticated else assigned_user,
                                description=f"Created and assigned one-time task: {chore.name} to {assigned_user.get_display_name()}",
                                metadata={'chore_id': chore.id, 'instance_id': instance.id}
                            )
                    except User.DoesNotExist:
                        return JsonResponse({'error': 'Invalid user selected for assignment'}, status=400)
                else:
                    # Log pool task creation
                    ActionLog.objects.create(
                        action_type=ActionLog.ACTION_ADMIN,
                        user=request.user if request.user.is_authenticated else None,
                        description=f"Created one-time task: {chore.name}",
                        metadata={'chore_id': chore.id}
                    )

                logger.info(f"Created one-time task: {chore.name} (ID: {chore.id})")

            return JsonResponse({
                'success': True,
                'message': 'Task created successfully',
                'chore_id': chore.id
            })

        except Exception as e:
            logger.exception("Error creating quick-add task")
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=400)


@require_http_methods(["POST"])
def claim_chore_view(request):
    """Handle chore claim from frontend (kiosk mode with user selection)."""
    try:
        instance_id = request.POST.get('instance_id')
        user_id = request.POST.get('user_id')

        if not instance_id:
            return JsonResponse({'error': 'Missing instance_id'}, status=400)
        if not user_id:
            return JsonResponse({'error': 'Please select who is claiming this chore'}, status=400)

        with transaction.atomic():
            instance = ChoreInstance.objects.select_for_update().get(id=instance_id)

            if instance.status != ChoreInstance.POOL:
                return JsonResponse({'error': 'This chore is not in the pool'}, status=400)

            # Get the selected user
            try:
                user = User.objects.get(id=user_id, can_be_assigned=True, is_active=True)
            except User.DoesNotExist:
                return JsonResponse({'error': 'Invalid user selected'}, status=400)

            # Check daily claim limit
            settings = Settings.get_settings()
            if user.claims_today >= settings.max_claims_per_day:
                return JsonResponse({
                    'error': f'Daily claim limit reached ({settings.max_claims_per_day})'
                }, status=400)

            # Claim the chore
            instance.status = ChoreInstance.ASSIGNED
            instance.assigned_to = user
            instance.assigned_at = timezone.now()
            instance.assignment_reason = ChoreInstance.REASON_CLAIMED
            instance.save()

            user.claims_today += 1
            user.save()

            ActionLog.objects.create(
                action_type=ActionLog.ACTION_CLAIM,
                user=user,
                description=f"Claimed {instance.chore.name}",
                metadata={'instance_id': instance.id}
            )

            logger.info(f"User {user.username} claimed chore {instance.chore.name}")

            return JsonResponse({'message': 'Chore claimed successfully!'})

    except ChoreInstance.DoesNotExist:
        return JsonResponse({'error': 'Chore not found'}, status=404)
    except Exception as e:
        logger.error(f"Error claiming chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def complete_chore_view(request):
    """Handle chore completion from frontend (kiosk mode with user selection)."""
    try:
        instance_id = request.POST.get('instance_id')
        user_id = request.POST.get('user_id')
        helper_ids = request.POST.getlist('helper_ids')

        if not instance_id:
            return JsonResponse({'error': 'Missing instance_id'}, status=400)
        if not user_id:
            return JsonResponse({'error': 'Please select who is completing this chore'}, status=400)

        with transaction.atomic():
            instance = ChoreInstance.objects.select_for_update().get(id=instance_id)

            if instance.status == ChoreInstance.COMPLETED:
                return JsonResponse({'error': 'Already completed'}, status=400)

            # Determine completion time and late status
            now = timezone.now()
            was_late = now > instance.due_at

            # Get the selected user
            try:
                user = User.objects.get(id=user_id, can_be_assigned=True, is_active=True)
            except User.DoesNotExist:
                return JsonResponse({'error': 'Invalid user selected'}, status=400)

            # Update instance
            instance.status = ChoreInstance.COMPLETED
            instance.completed_at = now
            instance.is_late_completion = was_late
            instance.save()

            # Create completion record
            completion = Completion.objects.create(
                chore_instance=instance,
                completed_by=user,
                was_late=was_late
            )

            # Determine who gets points
            if helper_ids:
                helpers_list = list(User.objects.filter(
                    id__in=helper_ids,
                    eligible_for_points=True
                ))
            else:
                if instance.chore.is_undesirable:
                    from chores.models import ChoreEligibility
                    eligible_ids = ChoreEligibility.objects.filter(
                        chore=instance.chore
                    ).values_list('user_id', flat=True)
                    helpers_list = list(User.objects.filter(
                        id__in=eligible_ids,
                        eligible_for_points=True
                    ))
                else:
                    # Check if completing user is eligible for points
                    if user.eligible_for_points:
                        helpers_list = [user]
                    else:
                        # User is not eligible - redistribute to ALL eligible users
                        helpers_list = list(User.objects.filter(
                            eligible_for_points=True,
                            can_be_assigned=True,
                            is_active=True
                        ))
                        logger.info(
                            f"User {user.username} not eligible for points. "
                            f"Redistributing {instance.points_value} pts to {len(helpers_list)} eligible users"
                        )

            # Split points
            if helpers_list:
                points_per_person = instance.points_value / len(helpers_list)
                points_per_person = Decimal(str(round(float(points_per_person), 2)))

                for helper in helpers_list:
                    CompletionShare.objects.create(
                        completion=completion,
                        user=helper,
                        points_awarded=points_per_person
                    )
                    helper.add_points(points_per_person)
                    PointsLedger.objects.create(
                        user=helper,
                        transaction_type=PointsLedger.TYPE_COMPLETION,
                        points_change=points_per_person,
                        balance_after=helper.weekly_points,
                        completion=completion,
                        description=f"Completed {instance.chore.name}",
                        created_by=user
                    )

            # Update rotation state
            if instance.chore.is_undesirable and instance.assigned_to:
                AssignmentService.update_rotation_state(
                    instance.chore,
                    instance.assigned_to
                )

            # Spawn dependent chores
            spawned = DependencyService.spawn_dependent_chores(instance, now)

            ActionLog.objects.create(
                action_type=ActionLog.ACTION_COMPLETE,
                user=user,
                description=f"Completed {instance.chore.name}",
                metadata={
                    'instance_id': instance.id,
                    'helpers': len(helpers_list),
                    'spawned_children': len(spawned)
                }
            )

            logger.info(f"User {user.username} completed chore {instance.chore.name}")

            return JsonResponse({'message': 'Chore completed successfully!'})

    except ChoreInstance.DoesNotExist:
        return JsonResponse({'error': 'Chore not found'}, status=404)
    except Exception as e:
        logger.error(f"Error completing chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def unclaim_chore_view(request):
    """Handle unclaiming a chore (returning it to the pool)."""
    try:
        instance_id = request.POST.get('instance_id')

        if not instance_id:
            return JsonResponse({'error': 'Missing instance_id'}, status=400)

        # Call the UnclaimService - it will automatically use the assigned user
        from chores.services import UnclaimService
        success, message, instance = UnclaimService.unclaim_chore(instance_id)

        if success:
            return JsonResponse({'message': message})
        else:
            return JsonResponse({'error': message}, status=400)

    except ChoreInstance.DoesNotExist:
        return JsonResponse({'error': 'Chore not found'}, status=404)
    except Exception as e:
        logger.error(f"Error unclaiming chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def skip_chore_view(request):
    """Handle skipping a chore from frontend (kiosk mode with user selection)."""
    try:
        instance_id = request.POST.get('instance_id')
        user_id = request.POST.get('user_id')
        skip_reason = request.POST.get('skip_reason', '').strip()

        if not instance_id:
            return JsonResponse({'error': 'Missing instance_id'}, status=400)
        if not user_id:
            return JsonResponse({'error': 'Please select who is skipping this chore'}, status=400)

        # Get the selected user
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            return JsonResponse({'error': 'Invalid user selected'}, status=400)

        # Check if user is admin
        if not (user.is_staff or user.is_superuser):
            return JsonResponse({'error': 'Only administrators can skip chores'}, status=403)

        # Call the SkipService
        from chores.services import SkipService
        success, message, instance = SkipService.skip_chore(
            instance_id=instance_id,
            user=user,
            reason=skip_reason if skip_reason else None
        )

        if success:
            return JsonResponse({'message': message or 'Chore skipped successfully!'})
        else:
            return JsonResponse({'error': message}, status=400)

    except ChoreInstance.DoesNotExist:
        return JsonResponse({'error': 'Chore not found'}, status=404)
    except Exception as e:
        logger.error(f"Error skipping chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def reschedule_chore_view(request):
    """Handle rescheduling a chore instance from frontend (kiosk mode with user selection)."""
    try:
        instance_id = request.POST.get('instance_id')
        user_id = request.POST.get('user_id')
        new_due_datetime = request.POST.get('new_due_datetime', '').strip()
        reschedule_reason = request.POST.get('reschedule_reason', '').strip()

        if not instance_id:
            return JsonResponse({'error': 'Missing instance_id'}, status=400)
        if not user_id:
            return JsonResponse({'error': 'Please select who is rescheduling this chore'}, status=400)
        if not new_due_datetime:
            return JsonResponse({'error': 'Please provide a new due date and time'}, status=400)

        # Get the selected user
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            return JsonResponse({'error': 'Invalid user selected'}, status=400)

        # Check if user is admin
        if not (user.is_staff or user.is_superuser):
            return JsonResponse({'error': 'Only administrators can reschedule chores'}, status=403)

        # Parse the datetime
        from datetime import datetime
        from django.utils.dateparse import parse_datetime

        try:
            # Try parsing ISO format datetime
            new_due_at = parse_datetime(new_due_datetime)
            if not new_due_at:
                # Try parsing as datetime string
                new_due_at = timezone.datetime.fromisoformat(new_due_datetime.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            return JsonResponse({'error': f'Invalid datetime format: {str(e)}'}, status=400)

        with transaction.atomic():
            instance = ChoreInstance.objects.select_for_update().get(id=instance_id)

            if instance.status == ChoreInstance.COMPLETED:
                return JsonResponse({'error': 'Cannot reschedule a completed chore'}, status=400)

            old_due_at = instance.due_at
            instance.due_at = new_due_at
            instance.save()

            # Log the reschedule action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_RESCHEDULE,
                user=user,
                description=f"Rescheduled {instance.chore.name} from {old_due_at.strftime('%Y-%m-%d %H:%M')} to {new_due_at.strftime('%Y-%m-%d %H:%M')}",
                metadata={
                    'instance_id': instance.id,
                    'old_due_at': old_due_at.isoformat(),
                    'new_due_at': new_due_at.isoformat(),
                    'reason': reschedule_reason if reschedule_reason else None
                }
            )

            logger.info(f"User {user.username} rescheduled chore {instance.chore.name} from {old_due_at} to {new_due_at}")

            return JsonResponse({'message': f'Chore rescheduled to {new_due_at.strftime("%B %d at %I:%M %p")}'})

    except ChoreInstance.DoesNotExist:
        return JsonResponse({'error': 'Chore not found'}, status=404)
    except Exception as e:
        logger.error(f"Error rescheduling chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def health_check(request):
    """
    Health check endpoint for monitoring.
    Returns JSON with system status and database connectivity.
    """
    from django.db import connection
    from django.conf import settings

    health_data = {
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'checks': {}
    }

    # Check database connectivity
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_data['checks']['database'] = 'ok'
    except Exception as e:
        health_data['status'] = 'unhealthy'
        health_data['checks']['database'] = f'error: {str(e)}'
        logger.error(f"Health check database error: {str(e)}")

    # Check scheduler (if accessible)
    try:
        from core.scheduler import scheduler
        if scheduler and scheduler.running:
            health_data['checks']['scheduler'] = 'running'
        else:
            health_data['checks']['scheduler'] = 'stopped'
    except Exception as e:
        health_data['checks']['scheduler'] = f'unknown: {str(e)}'

    # Basic system info
    health_data['info'] = {
        'debug_mode': settings.DEBUG,
        'allowed_hosts': settings.ALLOWED_HOSTS,
    }

    # Return appropriate status code
    status_code = 200 if health_data['status'] == 'healthy' else 503

    return JsonResponse(health_data, status=status_code)


def get_updates(request):
    """
    API endpoint for real-time updates.
    Returns changes since the given timestamp.
    """
    try:
        # Get 'since' parameter (ISO format timestamp)
        since_str = request.GET.get('since')
        if not since_str:
            return JsonResponse({'error': 'Missing since parameter'}, status=400)

        # Parse timestamp (ISO 8601 format)
        from datetime import datetime
        from django.utils.dateparse import parse_datetime
        try:
            # Use Django's parse_datetime which handles timezone-aware datetimes
            since = parse_datetime(since_str)
            if since is None:
                return JsonResponse({'error': 'Invalid timestamp format'}, status=400)
            # If naive, make it timezone-aware using Django's timezone
            if timezone.is_naive(since):
                since = timezone.make_aware(since)
        except ValueError:
            return JsonResponse({'error': 'Invalid timestamp format'}, status=400)

        # Get current time for response
        from datetime import timedelta
        now = timezone.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        updates = {
            'timestamp': now.isoformat(),
            'changes': []
        }

        # Get updated chore instances: include chores due today OR overdue from previous days
        updated_instances = ChoreInstance.objects.filter(
            updated_at__gt=since,
            chore__is_active=True
        ).filter(
            Q(due_at__date=today) | Q(due_at__date=tomorrow) | Q(due_at__lt=now)  # Due today/tomorrow OR past due
        ).exclude(
            status=ChoreInstance.SKIPPED
        ).select_related('chore', 'assigned_to')

        for instance in updated_instances:
            change_data = {
                'type': 'chore_instance',
                'id': instance.id,
                'action': 'updated',
                'data': {
                    'status': instance.status,
                    'chore_name': instance.chore.name,
                    'points': str(instance.chore.points),
                    'assigned_to': instance.assigned_to.get_display_name() if instance.assigned_to else None,
                    'assigned_to_id': instance.assigned_to.id if instance.assigned_to else None,
                }
            }
            updates['changes'].append(change_data)

        # Get updated user points
        updated_users = User.objects.filter(
            is_active=True,
            eligible_for_points=True,
            updated_at__gt=since
        )

        for user in updated_users:
            change_data = {
                'type': 'user_points',
                'id': user.id,
                'action': 'updated',
                'data': {
                    'username': user.username,
                    'display_name': user.get_display_name(),
                    'weekly_points': str(user.weekly_points),
                    'all_time_points': str(user.all_time_points),
                }
            }
            updates['changes'].append(change_data)

        return JsonResponse(updates)

    except Exception as e:
        logger.error(f"Error in get_updates: {str(e)}")
        return JsonResponse({'error': 'Internal server error'}, status=500)
