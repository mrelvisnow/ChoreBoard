"""
Admin panel views for ChoreBoard.
"""
import os
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.conf import settings
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from users.models import User
from core.models import Settings, ActionLog, WeeklySnapshot, Backup
from chores.models import Chore, ChoreInstance, Completion, CompletionShare, PointsLedger, ChoreTemplate
from chores.services import SkipService, RescheduleService

logger = logging.getLogger(__name__)


def is_staff_user(user):
    """Check if user is authenticated and staff."""
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(is_staff_user)
def admin_dashboard(request):
    """
    Admin dashboard showing key metrics and recent activity.
    """
    from datetime import datetime
    from django.db.models import Q

    now = timezone.now()
    today = now.date()

    # Use year > 3000 to avoid overflow errors with year >= 9999
    far_future = timezone.make_aware(datetime(3000, 1, 1))

    # Key metrics
    active_chores = Chore.objects.filter(is_active=True).count()
    active_users = User.objects.filter(is_active=True, eligible_for_points=True).count()

    # Chore instance counts (matching main page logic: today + overdue + no due date)
    # Pool chores (any user)
    pool_count = ChoreInstance.objects.filter(
        status=ChoreInstance.POOL,
        chore__is_active=True
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date)
    ).count()

    # Assigned chores (eligible users only, matching main page)
    assigned_count = ChoreInstance.objects.filter(
        status=ChoreInstance.ASSIGNED,
        chore__is_active=True,
        assigned_to__eligible_for_points=True,  # Only count eligible users
        assigned_to__isnull=False
    ).filter(
        Q(due_at__date=today) |  # Due today
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (sentinel date)
    ).count()

    # Completed chores (today only is fine)
    completed_count = ChoreInstance.objects.filter(
        status=ChoreInstance.COMPLETED,
        chore__is_active=True,
        due_at__date=today
    ).count()

    # Overdue chores (eligible users only)
    overdue_count = ChoreInstance.objects.filter(
        status=ChoreInstance.ASSIGNED,
        chore__is_active=True,
        assigned_to__eligible_for_points=True,
        assigned_to__isnull=False,
        is_overdue=True
    ).filter(
        Q(due_at__date=today) |  # Due today but overdue
        Q(due_at__lt=now) |  # Overdue from previous days
        Q(due_at__gte=far_future)  # No due date (can't be overdue but include for consistency)
    ).count()

    # Skipped chores count (today only is fine)
    skipped_count = ChoreInstance.objects.filter(due_at__date=today, status=ChoreInstance.SKIPPED).count()

    # Points this week
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weekly_points = User.objects.filter(
        is_active=True,
        eligible_for_points=True
    ).aggregate(total=Sum('weekly_points'))['total'] or 0

    # Recent completions (last 24 hours)
    recent_completions = Completion.objects.filter(
        completed_at__gte=now - timedelta(hours=24)
    ).select_related('chore_instance__chore', 'completed_by').order_by('-completed_at')[:10]

    # Recent actions
    recent_actions = ActionLog.objects.select_related('user').order_by('-created_at')[:15]

    # Get settings
    settings = Settings.get_settings()

    context = {
        'active_chores': active_chores,
        'active_users': active_users,
        'pool_count': pool_count,
        'assigned_count': assigned_count,
        'completed_count': completed_count,
        'overdue_count': overdue_count,
        'skipped_count': skipped_count,
        'weekly_points': weekly_points,
        'conversion_rate': settings.points_to_dollar_rate,
        'weekly_cash_value': weekly_points * settings.points_to_dollar_rate,
        'recent_completions': recent_completions,
        'recent_actions': recent_actions,
    }

    return render(request, 'board/admin/dashboard.html', context)


@login_required
@user_passes_test(is_staff_user)
def admin_chores(request):
    """
    Chore management page - list all chores.
    """
    chores = Chore.objects.all().order_by('-is_active', 'name')

    context = {
        'chores': chores,
    }

    return render(request, 'board/admin/chores.html', context)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["GET"])
def admin_chores_list(request):
    """
    Get list of all chores for dropdowns.
    """
    try:
        chores = Chore.objects.filter(is_active=True).order_by('name')
        chores_list = [{'id': c.id, 'name': c.name} for c in chores]
        return JsonResponse({'chores': chores_list})
    except Exception as e:
        logger.error(f"Error fetching chores list: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_users(request):
    """
    User management page - list all users.
    """
    users = User.objects.all().order_by('-is_active', 'username')

    context = {
        'users': users,
    }

    return render(request, 'board/admin/users.html', context)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["GET"])
def admin_users_list(request):
    """
    Get list of all active users for dropdowns/selectors.
    Returns JSON array of user objects.
    """
    try:
        users = User.objects.filter(
            is_active=True,
            can_be_assigned=True
        ).order_by('first_name', 'username')

        users_list = [
            {
                'id': u.id,
                'username': u.username,
                'first_name': u.first_name,
                'display_name': u.get_display_name()
            }
            for u in users
        ]

        return JsonResponse({'users': users_list})
    except Exception as e:
        logger.error(f"Error fetching users list: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_settings(request):
    """
    Settings management page.
    """
    settings = Settings.get_settings()

    if request.method == 'POST':
        try:
            # Update settings from form
            settings.points_to_dollar_rate = request.POST.get('points_to_dollar_rate')
            settings.max_claims_per_day = request.POST.get('max_claims_per_day')
            settings.undo_time_limit_hours = request.POST.get('undo_time_limit_hours')
            settings.weekly_reset_undo_hours = request.POST.get('weekly_reset_undo_hours')
            settings.enable_notifications = request.POST.get('enable_notifications') == 'on'
            settings.home_assistant_webhook_url = request.POST.get('home_assistant_webhook_url', '')
            settings.arcade_submission_redirect_seconds = request.POST.get('arcade_submission_redirect_seconds', 5)
            settings.updated_by = request.user

            # Handle SiteSettings for point labels
            from board.models import SiteSettings
            site_settings = SiteSettings.get_settings()
            site_settings.points_label = request.POST.get('points_label', 'points').strip()
            site_settings.points_label_short = request.POST.get('points_label_short', 'pts').strip()
            site_settings.save()

            settings.save()

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_SETTINGS_CHANGE,
                user=request.user,
                description=f"Updated settings",
                metadata={
                    'conversion_rate': float(settings.points_to_dollar_rate),
                    'max_claims': settings.max_claims_per_day,
                }
            )

            return JsonResponse({'message': 'Settings updated successfully'})
        except Exception as e:
            logger.error(f"Error updating settings: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)

    from board.models import SiteSettings

    context = {
        'settings': settings,
        'site_settings': SiteSettings.get_settings(),
    }

    return render(request, 'board/admin/settings.html', context)


@login_required
@user_passes_test(is_staff_user)
def admin_logs(request):
    """
    Action logs viewer with filtering.
    """
    # Get filter parameters
    action_type = request.GET.get('type', '')
    user_id = request.GET.get('user', '')
    days = int(request.GET.get('days', 7))

    # Build query
    logs = ActionLog.objects.select_related('user')

    if action_type:
        logs = logs.filter(action_type=action_type)

    if user_id:
        logs = logs.filter(user_id=user_id)

    # Filter by date range
    cutoff = timezone.now() - timedelta(days=days)
    logs = logs.filter(created_at__gte=cutoff)

    logs = logs.order_by('-created_at')[:100]

    # Get filter options
    action_types = ActionLog.ACTION_TYPES
    users = User.objects.filter(is_active=True).order_by('username')

    context = {
        'logs': logs,
        'action_types': action_types,
        'users': users,
        'selected_type': action_type,
        'selected_user': user_id,
        'selected_days': days,
    }

    return render(request, 'board/admin/logs.html', context)


@login_required
@user_passes_test(is_staff_user)
def admin_undo_completions(request):
    """
    List recent completions that can be undone (within 24 hours).
    """
    now = timezone.now()
    settings = Settings.get_settings()
    cutoff = now - timedelta(hours=settings.undo_time_limit_hours)

    # Get recent completions (excluding undone ones)
    recent_completions = Completion.objects.filter(
        completed_at__gte=cutoff,
        is_undone=False
    ).select_related(
        'chore_instance__chore',
        'completed_by'
    ).prefetch_related(
        'shares__user'
    ).order_by('-completed_at')

    context = {
        'completions': recent_completions,
        'undo_time_limit': settings.undo_time_limit_hours,
    }

    return render(request, 'board/admin/undo_completions.html', context)


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_staff_user)
def admin_undo_completion(request, completion_id):
    """
    Undo a completion (reverse points and reset instance status).
    """
    try:
        now = timezone.now()
        settings = Settings.get_settings()
        cutoff = now - timedelta(hours=settings.undo_time_limit_hours)

        with transaction.atomic():
            completion = get_object_or_404(
                Completion.objects.select_related('chore_instance'),
                id=completion_id
            )

            # Check if within undo window
            if completion.completed_at < cutoff:
                return JsonResponse({
                    'error': f'Too old to undo (>{settings.undo_time_limit_hours}h)'
                }, status=400)

            instance = completion.chore_instance

            # Reverse points for all users who received them
            from chores.models import CompletionShare, PointsLedger
            shares = CompletionShare.objects.filter(completion=completion)

            for share in shares:
                # Subtract points (can go negative, then floored to 0)
                share.user.add_points(-share.points_awarded)

                # Create ledger entry for the reversal
                PointsLedger.objects.create(
                    user=share.user,
                    transaction_type=PointsLedger.TYPE_UNDO,
                    points_change=-share.points_awarded,
                    balance_after=share.user.weekly_points,
                    completion=completion,
                    description=f"Undid completion of {instance.chore.name}",
                    created_by=request.user
                )

            # Reset instance status to assigned (or pool if it wasn't assigned)
            if instance.assigned_to:
                instance.status = ChoreInstance.ASSIGNED
            else:
                instance.status = ChoreInstance.POOL

            instance.completed_at = None
            instance.is_late_completion = False
            instance.save()

            # Mark completion as undone
            completion.is_undone = True
            completion.undone_at = now
            completion.undone_by = request.user
            completion.save()

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_UNDO,
                user=request.user,
                description=f"Undid completion of {instance.chore.name}",
                metadata={
                    'instance_id': instance.id,
                    'completion_id': completion.id,
                    'points_reversed': float(sum(s.points_awarded for s in shares))
                }
            )

            logger.info(f"Admin {request.user.username} undid completion {completion.id}")

            return JsonResponse({
                'message': f'Completion undone. Points reversed for {shares.count()} user(s).'
            })

    except Exception as e:
        logger.error(f"Error undoing completion: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# CHORE CRUD ENDPOINTS
# ============================================================================

@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["GET"])
def admin_chore_get(request, chore_id):
    """
    Get chore data for editing.
    """
    try:
        from chores.models import ChoreDependency

        chore = get_object_or_404(Chore, id=chore_id)

        # Get all assignable users
        assignable_users = User.objects.filter(is_active=True, can_be_assigned=True)

        # Get dependency info
        dependency = ChoreDependency.objects.filter(chore=chore).first()
        depends_on_id = dependency.depends_on.id if dependency else None
        offset_hours = dependency.offset_hours if dependency else 0

        # Get eligible users for undesirable chores
        from chores.models import ChoreEligibility
        eligible_user_ids = list(ChoreEligibility.objects.filter(chore=chore).values_list('user_id', flat=True))

        data = {
            'id': chore.id,
            'name': chore.name,
            'description': chore.description,
            'points': str(chore.points),
            'is_pool': chore.is_pool,
            'assigned_to': chore.assigned_to.id if chore.assigned_to else None,
            'is_undesirable': chore.is_undesirable,
            'eligible_user_ids': eligible_user_ids,
            'distribution_time': chore.distribution_time.strftime('%H:%M'),
            'schedule_type': chore.schedule_type,
            'weekday': chore.weekday,
            'n_days': chore.n_days,
            'every_n_start_date': chore.every_n_start_date.isoformat() if chore.every_n_start_date else None,
            'cron_expr': chore.cron_expr or '',
            'rrule_json': chore.rrule_json or '',
            'one_time_due_date': chore.one_time_due_date.isoformat() if chore.one_time_due_date else '',
            'depends_on': depends_on_id,
            'offset_hours': offset_hours,
            'is_active': chore.is_active,
            'assignable_users': [
                {'id': u.id, 'name': u.get_display_name()}
                for u in assignable_users
            ]
        }

        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error fetching chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_chore_create(request):
    """
    Create a new chore.
    """
    logger.info("=== admin_chore_create called ===")
    try:
        from chores.models import ChoreDependency
        import json

        # Get form data
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        points = Decimal(request.POST.get('points', '0.00'))
        logger.info(f"Creating chore: {name}, points={points}")
        is_pool = request.POST.get('is_pool') == 'true'
        assigned_to_id = request.POST.get('assigned_to')
        is_undesirable = request.POST.get('is_undesirable') == 'true'
        is_difficult = request.POST.get('is_difficult') == 'true'
        distribution_time = request.POST.get('distribution_time', '17:30')
        schedule_type = request.POST.get('schedule_type', Chore.DAILY)

        # Schedule-specific fields
        weekday = request.POST.get('weekday')
        n_days = request.POST.get('n_days')
        every_n_start_date = request.POST.get('every_n_start_date')
        cron_expr = request.POST.get('cron_expr', '').strip()
        rrule_json_str = request.POST.get('rrule_json', '').strip()
        one_time_due_date = request.POST.get('one_time_due_date', '').strip()

        # Dependency fields
        depends_on_id = request.POST.get('depends_on')
        offset_hours = request.POST.get('offset_hours', '0')

        # Validation
        if not name:
            return JsonResponse({'error': 'Chore name is required'}, status=400)

        if len(name) > 255:
            return JsonResponse({'error': 'Chore name cannot exceed 255 characters'}, status=400)

        if points < 0 or points > Decimal('999.99'):
            return JsonResponse({'error': 'Points must be between 0.00 and 999.99'}, status=400)

        if not is_pool and not assigned_to_id:
            return JsonResponse({'error': 'Non-pool chores must have an assigned user'}, status=400)

        # Parse rrule JSON if provided
        rrule_json = None
        if rrule_json_str:
            try:
                rrule_json = json.loads(rrule_json_str)
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Invalid RRULE JSON format'}, status=400)

        with transaction.atomic():
            # Create chore
            chore = Chore.objects.create(
                name=name,
                description=description,
                points=points,
                is_pool=is_pool,
                assigned_to_id=assigned_to_id if not is_pool else None,
                is_undesirable=is_undesirable,
                is_difficult=is_difficult,
                distribution_time=distribution_time,
                schedule_type=schedule_type,
                weekday=int(weekday) if weekday else None,
                n_days=int(n_days) if n_days else None,
                every_n_start_date=every_n_start_date if every_n_start_date else None,
                cron_expr=cron_expr,
                rrule_json=rrule_json,
                one_time_due_date=one_time_due_date if one_time_due_date else None,
                is_active=True
            )
            logger.info(f"Created chore {chore.id}: {chore.name}, is_undesirable={chore.is_undesirable}")

            # Create dependency if specified
            if depends_on_id:
                parent_chore = Chore.objects.get(id=int(depends_on_id))
                ChoreDependency.objects.create(
                    chore=chore,
                    depends_on=parent_chore,
                    offset_hours=int(offset_hours) if offset_hours else 0
                )

            # Handle eligible users for undesirable chores
            if is_undesirable:
                eligible_users_json = request.POST.get('eligible_users', '[]')
                try:
                    eligible_user_ids = json.loads(eligible_users_json)
                    from chores.models import ChoreEligibility, ChoreInstance
                    from chores.services import AssignmentService

                    # Create ChoreEligibility records
                    for user_id in eligible_user_ids:
                        ChoreEligibility.objects.create(
                            chore=chore,
                            user_id=int(user_id)
                        )
                    logger.info(f"Created {len(eligible_user_ids)} ChoreEligibility records for {chore.name}")

                    # NOW that ChoreEligibility records exist, try to assign any pool instances created by the signal
                    pool_instances = ChoreInstance.objects.filter(
                        chore=chore,
                        status=ChoreInstance.POOL,
                        assigned_to__isnull=True
                    )

                    for instance in pool_instances:
                        success, message, assigned_user = AssignmentService.assign_chore(instance)
                        if success:
                            logger.info(f"✓ Assigned undesirable chore {chore.name} to {assigned_user.username}")
                        else:
                            logger.warning(f"✗ Could not assign undesirable chore {chore.name}: {message}")

                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Error parsing eligible users: {str(e)}")

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                description=f"Created chore: {chore.name}",
                metadata={'chore_id': chore.id}
            )

            logger.info(f"Admin {request.user.username} created chore {chore.id}: {chore.name}")

            # Store chore_id for response
            chore_id = chore.id
            chore_name = chore.name

        # Transaction has committed, signal should have fired
        # Note: ChoreInstance creation is handled automatically by the post_save signal
        # in chores/signals.py which fires within the transaction

        return JsonResponse({
            'message': f'Chore "{chore_name}" created successfully',
            'chore_id': chore_id
        })

    except ValueError as e:
        return JsonResponse({'error': f'Invalid input: {str(e)}'}, status=400)
    except Exception as e:
        logger.error(f"Error creating chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_chore_update(request, chore_id):
    """
    Update an existing chore.
    """
    try:
        from chores.models import ChoreDependency
        import json

        chore = get_object_or_404(Chore, id=chore_id)

        # Get form data
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        points = Decimal(request.POST.get('points', '0.00'))
        is_pool = request.POST.get('is_pool') == 'true'
        assigned_to_id = request.POST.get('assigned_to')
        is_undesirable = request.POST.get('is_undesirable') == 'true'
        is_difficult = request.POST.get('is_difficult') == 'true'
        distribution_time = request.POST.get('distribution_time', '17:30')
        schedule_type = request.POST.get('schedule_type', Chore.DAILY)

        # Schedule-specific fields
        weekday = request.POST.get('weekday')
        n_days = request.POST.get('n_days')
        every_n_start_date = request.POST.get('every_n_start_date')
        cron_expr = request.POST.get('cron_expr', '').strip()
        rrule_json_str = request.POST.get('rrule_json', '').strip()
        one_time_due_date = request.POST.get('one_time_due_date', '').strip()

        # Dependency fields
        depends_on_id = request.POST.get('depends_on')
        offset_hours = request.POST.get('offset_hours', '0')

        # Validation
        if not name:
            return JsonResponse({'error': 'Chore name is required'}, status=400)

        if len(name) > 255:
            return JsonResponse({'error': 'Chore name cannot exceed 255 characters'}, status=400)

        if points < 0 or points > Decimal('999.99'):
            return JsonResponse({'error': 'Points must be between 0.00 and 999.99'}, status=400)

        if not is_pool and not assigned_to_id:
            return JsonResponse({'error': 'Non-pool chores must have an assigned user'}, status=400)

        # Parse rrule JSON if provided
        rrule_json = None
        if rrule_json_str:
            try:
                rrule_json = json.loads(rrule_json_str)
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Invalid RRULE JSON format'}, status=400)

        with transaction.atomic():
            # Update chore
            chore.name = name
            chore.description = description
            chore.points = points
            chore.is_pool = is_pool
            chore.assigned_to_id = assigned_to_id if not is_pool else None
            chore.is_undesirable = is_undesirable
            chore.is_difficult = is_difficult
            chore.distribution_time = distribution_time
            chore.schedule_type = schedule_type
            chore.weekday = int(weekday) if weekday else None
            chore.n_days = int(n_days) if n_days else None
            chore.every_n_start_date = every_n_start_date if every_n_start_date else None
            chore.cron_expr = cron_expr
            chore.rrule_json = rrule_json
            chore.one_time_due_date = one_time_due_date if one_time_due_date else None
            chore.save()

            # Update dependencies
            # Delete existing dependency
            ChoreDependency.objects.filter(chore=chore).delete()

            # Create new dependency if specified
            if depends_on_id:
                parent_chore = Chore.objects.get(id=int(depends_on_id))
                ChoreDependency.objects.create(
                    chore=chore,
                    depends_on=parent_chore,
                    offset_hours=int(offset_hours) if offset_hours else 0
                )

            # Handle eligible users for undesirable chores
            # Delete existing eligible users
            from chores.models import ChoreEligibility
            ChoreEligibility.objects.filter(chore=chore).delete()

            # Create new eligible users if undesirable
            if is_undesirable:
                eligible_users_json = request.POST.get('eligible_users', '[]')
                try:
                    eligible_user_ids = json.loads(eligible_users_json)
                    for user_id in eligible_user_ids:
                        ChoreEligibility.objects.create(
                            chore=chore,
                            user_id=int(user_id)
                        )
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Error parsing eligible users: {str(e)}")

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                description=f"Updated chore: {chore.name}",
                metadata={'chore_id': chore.id}
            )

            logger.info(f"Admin {request.user.username} updated chore {chore.id}: {chore.name}")

            return JsonResponse({
                'message': f'Chore "{chore.name}" updated successfully'
            })

    except ValueError as e:
        return JsonResponse({'error': f'Invalid input: {str(e)}'}, status=400)
    except Exception as e:
        logger.error(f"Error updating chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_chore_toggle_active(request, chore_id):
    """
    Toggle chore active status (soft delete).
    """
    try:
        chore = get_object_or_404(Chore, id=chore_id)

        with transaction.atomic():
            # Toggle active status
            chore.is_active = not chore.is_active
            chore.save()

            status = "activated" if chore.is_active else "deactivated"

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                description=f"{status.capitalize()} chore: {chore.name}",
                metadata={'chore_id': chore.id, 'is_active': chore.is_active}
            )

            logger.info(f"Admin {request.user.username} {status} chore {chore.id}: {chore.name}")

            return JsonResponse({
                'message': f'Chore "{chore.name}" {status} successfully',
                'is_active': chore.is_active
            })

    except Exception as e:
        logger.error(f"Error toggling chore status: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# CHORE TEMPLATE ENDPOINTS
# ============================================================================

@login_required
@user_passes_test(is_staff_user)
def admin_templates_list(request):
    """Get list of all chore templates."""
    try:
        templates = ChoreTemplate.objects.all().order_by('template_name')
        template_list = [
            {
                'id': t.id,
                'template_name': t.template_name,
                'description': t.description,
                'points': str(t.points),
                'schedule_type': t.schedule_type,
                'created_at': t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ]
        return JsonResponse({'templates': template_list})
    except Exception as e:
        logger.error(f"Error fetching templates: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_template_get(request, template_id):
    """Get a specific template's details."""
    try:
        template = ChoreTemplate.objects.get(id=template_id)
        data = {
            'id': template.id,
            'template_name': template.template_name,
            'description': template.description,
            'points': str(template.points),
            'is_pool': template.is_pool,
            'assigned_to': template.assigned_to.id if template.assigned_to else None,
            'is_undesirable': template.is_undesirable,
            'is_difficult': template.is_difficult,
            'is_late_chore': template.is_late_chore,
            'distribution_time': template.distribution_time.strftime('%H:%M'),
            'schedule_type': template.schedule_type,
            'weekday': template.weekday,
            'n_days': template.n_days,
            'every_n_start_date': template.every_n_start_date.isoformat() if template.every_n_start_date else None,
            'cron_expr': template.cron_expr or '',
            'rrule_json': template.rrule_json or '',
            'shift_on_late_completion': template.shift_on_late_completion,
        }
        return JsonResponse(data)
    except ChoreTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)
    except Exception as e:
        logger.error(f"Error fetching template: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_template_save(request):
    """Save a new template or update existing one."""
    try:
        import json

        template_name = request.POST.get('template_name', '').strip()
        description = request.POST.get('description', '').strip()
        points = Decimal(request.POST.get('points', '0.00'))
        is_pool = request.POST.get('is_pool') == 'true'
        assigned_to_id = request.POST.get('assigned_to')
        is_undesirable = request.POST.get('is_undesirable') == 'true'
        is_difficult = request.POST.get('is_difficult') == 'true'
        is_late_chore = request.POST.get('is_late_chore') == 'true'
        distribution_time = request.POST.get('distribution_time', '17:30')
        schedule_type = request.POST.get('schedule_type', Chore.DAILY)
        weekday = request.POST.get('weekday')
        n_days = request.POST.get('n_days')
        every_n_start_date = request.POST.get('every_n_start_date')
        cron_expr = request.POST.get('cron_expr', '').strip()
        rrule_json_str = request.POST.get('rrule_json', '').strip()
        shift_on_late_completion = request.POST.get('shift_on_late_completion') != 'false'

        # Validation
        if not template_name:
            return JsonResponse({'error': 'Template name is required'}, status=400)

        # Parse rrule JSON if provided
        rrule_json = None
        if rrule_json_str:
            try:
                rrule_json = json.loads(rrule_json_str)
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Invalid RRULE JSON format'}, status=400)

        # Check if template already exists
        existing_template = ChoreTemplate.objects.filter(template_name=template_name).first()

        if existing_template:
            # Update existing template
            existing_template.description = description
            existing_template.points = points
            existing_template.is_pool = is_pool
            existing_template.assigned_to_id = assigned_to_id if not is_pool else None
            existing_template.is_undesirable = is_undesirable
            existing_template.is_difficult = is_difficult
            existing_template.is_late_chore = is_late_chore
            existing_template.distribution_time = distribution_time
            existing_template.schedule_type = schedule_type
            existing_template.weekday = int(weekday) if weekday else None
            existing_template.n_days = int(n_days) if n_days else None
            existing_template.every_n_start_date = every_n_start_date if every_n_start_date else None
            existing_template.cron_expr = cron_expr
            existing_template.rrule_json = rrule_json
            existing_template.shift_on_late_completion = shift_on_late_completion
            existing_template.save()

            message = f'Template "{template_name}" updated successfully'
        else:
            # Create new template
            template = ChoreTemplate.objects.create(
                template_name=template_name,
                description=description,
                points=points,
                is_pool=is_pool,
                assigned_to_id=assigned_to_id if not is_pool else None,
                is_undesirable=is_undesirable,
                is_difficult=is_difficult,
                is_late_chore=is_late_chore,
                distribution_time=distribution_time,
                schedule_type=schedule_type,
                weekday=int(weekday) if weekday else None,
                n_days=int(n_days) if n_days else None,
                every_n_start_date=every_n_start_date if every_n_start_date else None,
                cron_expr=cron_expr,
                rrule_json=rrule_json,
                shift_on_late_completion=shift_on_late_completion,
                created_by=request.user
            )

            message = f'Template "{template_name}" saved successfully'

        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=request.user,
            description=f"Saved chore template: {template_name}",
            metadata={'template_name': template_name}
        )

        logger.info(f"Admin {request.user.username} saved template: {template_name}")
        return JsonResponse({'message': message})

    except Exception as e:
        logger.error(f"Error saving template: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_template_delete(request, template_id):
    """Delete a template."""
    try:
        template = ChoreTemplate.objects.get(id=template_id)
        template_name = template.template_name
        template.delete()

        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=request.user,
            description=f"Deleted chore template: {template_name}",
            metadata={'template_id': template_id}
        )

        logger.info(f"Admin {request.user.username} deleted template: {template_name}")
        return JsonResponse({'message': f'Template "{template_name}" deleted successfully'})

    except ChoreTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting template: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# USER CRUD ENDPOINTS
# ============================================================================

@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["GET"])
def admin_user_get(request, user_id):
    """
    Get user data for editing.
    """
    try:
        user = get_object_or_404(User, id=user_id)

        data = {
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'can_be_assigned': user.can_be_assigned,
            'exclude_from_auto_assignment': user.exclude_from_auto_assignment,
            'eligible_for_points': user.eligible_for_points,
            'is_staff': user.is_staff,
            'is_active': user.is_active,
        }

        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error fetching user: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_user_create(request):
    """
    Create a new user.
    """
    try:
        # Get form data
        username = request.POST.get('username', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        password = request.POST.get('password', '').strip()
        can_be_assigned = request.POST.get('can_be_assigned') == 'true'
        exclude_from_auto_assignment = request.POST.get('exclude_from_auto_assignment') == 'true'
        eligible_for_points = request.POST.get('eligible_for_points') == 'true'
        is_staff = request.POST.get('is_staff') == 'true'

        # Validation
        if not username:
            return JsonResponse({'error': 'Username is required'}, status=400)

        if len(username) < 3:
            return JsonResponse({'error': 'Username must be at least 3 characters'}, status=400)

        if len(username) > 150:
            return JsonResponse({'error': 'Username cannot exceed 150 characters'}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({'error': 'Username already exists'}, status=400)

        if not password:
            return JsonResponse({'error': 'Password is required'}, status=400)

        if len(password) < 4:
            return JsonResponse({'error': 'Password must be at least 4 characters'}, status=400)

        with transaction.atomic():
            # Create user
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=first_name,
                can_be_assigned=can_be_assigned,
                exclude_from_auto_assignment=exclude_from_auto_assignment,
                eligible_for_points=eligible_for_points,
                is_staff=is_staff,
                is_active=True
            )

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                description=f"Created user: {user.username}",
                metadata={'user_id': user.id}
            )

            logger.info(f"Admin {request.user.username} created user {user.id}: {user.username}")

            return JsonResponse({
                'message': f'User "{user.username}" created successfully',
                'user_id': user.id
            })

    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_user_update(request, user_id):
    """
    Update an existing user.
    """
    try:
        user = get_object_or_404(User, id=user_id)

        # Get form data
        first_name = request.POST.get('first_name', '').strip()
        password = request.POST.get('password', '').strip()
        can_be_assigned = request.POST.get('can_be_assigned') == 'true'
        exclude_from_auto_assignment = request.POST.get('exclude_from_auto_assignment') == 'true'
        eligible_for_points = request.POST.get('eligible_for_points') == 'true'
        is_staff = request.POST.get('is_staff') == 'true'

        with transaction.atomic():
            # Update user
            user.first_name = first_name
            user.can_be_assigned = can_be_assigned
            user.exclude_from_auto_assignment = exclude_from_auto_assignment
            user.eligible_for_points = eligible_for_points
            user.is_staff = is_staff

            # Update password if provided
            if password:
                if len(password) < 4:
                    return JsonResponse({'error': 'Password must be at least 4 characters'}, status=400)
                user.set_password(password)

            user.save()

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                description=f"Updated user: {user.username}",
                metadata={'user_id': user.id}
            )

            logger.info(f"Admin {request.user.username} updated user {user.id}: {user.username}")

            return JsonResponse({
                'message': f'User "{user.username}" updated successfully'
            })

    except Exception as e:
        logger.error(f"Error updating user: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_user_toggle_active(request, user_id):
    """
    Toggle user active status (soft delete).
    """
    try:
        user = get_object_or_404(User, id=user_id)

        # Prevent deactivating self
        if user.id == request.user.id:
            return JsonResponse({'error': 'You cannot deactivate your own account'}, status=400)

        with transaction.atomic():
            # Toggle active status
            user.is_active = not user.is_active
            user.save()

            status = "activated" if user.is_active else "deactivated"

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                description=f"{status.capitalize()} user: {user.username}",
                metadata={'user_id': user.id, 'is_active': user.is_active}
            )

            logger.info(f"Admin {request.user.username} {status} user {user.id}: {user.username}")

            return JsonResponse({
                'message': f'User "{user.username}" {status} successfully',
                'is_active': user.is_active
            })

    except Exception as e:
        logger.error(f"Error toggling user status: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_backups(request):
    """
    View and manage database backups.
    """
    backups = Backup.objects.all().order_by('-created_at')

    # Calculate total backup size
    total_size = sum(b.file_size_bytes for b in backups)

    context = {
        'backups': backups,
        'total_backups': backups.count(),
        'total_size_bytes': total_size,
    }

    return render(request, 'board/admin/backups.html', context)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_backup_create(request):
    """
    Create a new manual backup.
    """
    try:
        from django.core.management import call_command
        from io import StringIO

        # Capture command output
        out = StringIO()
        notes = request.POST.get('notes', 'Manual backup from admin panel')

        # Call the backup management command
        call_command('create_backup', notes=notes, stdout=out)

        output = out.getvalue()
        logger.info(f"Admin {request.user.username} created manual backup")

        return JsonResponse({
            'message': 'Backup created successfully',
            'output': output
        })

    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["GET"])
def admin_backup_download(request, backup_id):
    """
    Download a backup file.
    """
    try:
        from django.http import FileResponse
        import os

        backup = get_object_or_404(Backup, id=backup_id)

        if not os.path.exists(backup.file_path):
            logger.error(f"Backup file not found: {backup.file_path}")
            return JsonResponse({'error': 'Backup file not found'}, status=404)

        # Log the download action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=request.user,
            description=f"Downloaded backup: {backup.filename}",
            metadata={
                'backup_id': backup.id,
                'filename': backup.filename,
                'file_size': backup.file_size_bytes
            }
        )

        logger.info(f"Admin {request.user.username} downloading backup {backup.filename}")

        # Return file as download
        response = FileResponse(
            open(backup.file_path, 'rb'),
            as_attachment=True,
            filename=backup.filename
        )
        response['Content-Length'] = backup.file_size_bytes
        return response

    except Exception as e:
        logger.error(f"Error downloading backup: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_backup_upload(request):
    """
    Upload a backup file.
    Validates that it's a SQLite database with required tables.
    """
    try:
        import sqlite3
        from pathlib import Path

        uploaded_file = request.FILES.get('backup_file')
        if not uploaded_file:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        notes = request.POST.get('notes', 'Uploaded backup')

        # Validate file extension
        if not uploaded_file.name.endswith('.sqlite3'):
            return JsonResponse({'error': 'File must be a .sqlite3 file'}, status=400)

        # Validate file size (max 500MB)
        max_size = 500 * 1024 * 1024  # 500MB in bytes
        if uploaded_file.size > max_size:
            return JsonResponse({'error': f'File too large. Maximum size is 500MB'}, status=400)

        # Save to temporary location
        temp_path = Path(settings.BASE_DIR) / 'data' / 'backups' / f'temp_{uploaded_file.name}'
        with open(temp_path, 'wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        # Validate it's a SQLite database
        try:
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()

            # Check for required tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            required_tables = {'users', 'chores', 'chore_instances', 'settings'}
            missing_tables = required_tables - tables

            if missing_tables:
                conn.close()
                os.remove(temp_path)
                return JsonResponse({
                    'error': f'Invalid ChoreBoard backup. Missing tables: {", ".join(missing_tables)}'
                }, status=400)

            conn.close()

        except sqlite3.Error as e:
            if temp_path.exists():
                os.remove(temp_path)
            return JsonResponse({'error': f'Invalid SQLite database: {str(e)}'}, status=400)

        # Generate proper filename
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'db_backup_uploaded_{timestamp}.sqlite3'
        final_path = Path(settings.BASE_DIR) / 'data' / 'backups' / filename

        # Move to final location
        os.rename(temp_path, final_path)

        # Create Backup record
        backup = Backup.objects.create(
            filename=filename,
            file_path=str(final_path),
            file_size_bytes=uploaded_file.size,
            created_by=request.user,
            notes=notes,
            is_manual=True
        )

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=request.user,
            description=f"Uploaded backup: {filename}",
            metadata={'backup_id': backup.id, 'filename': filename, 'size': uploaded_file.size}
        )

        logger.info(f"Admin {request.user.username} uploaded backup {filename}")

        return JsonResponse({
            'success': True,
            'message': f'Backup uploaded successfully: {filename}',
            'backup_id': backup.id
        })

    except Exception as e:
        logger.error(f"Error uploading backup: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_backup_restore(request):
    """
    Queue a backup for restore on next server restart.
    """
    try:
        backup_id = request.POST.get('backup_id')
        create_safety_backup = request.POST.get('create_safety_backup') == 'true'

        if not backup_id:
            return JsonResponse({'error': 'Backup ID required'}, status=400)

        backup = get_object_or_404(Backup, id=backup_id)

        # Verify backup file exists
        if not os.path.exists(backup.file_path):
            return JsonResponse({'error': 'Backup file not found on disk'}, status=404)

        # Queue the restore
        from core.restore_queue import RestoreQueue
        RestoreQueue.queue_restore(
            backup_id=backup.id,
            backup_filepath=backup.file_path,
            create_safety_backup=create_safety_backup
        )

        # Log action
        ActionLog.objects.create(
            action_type=ActionLog.ACTION_ADMIN,
            user=request.user,
            description=f"Queued restore: {backup.filename}",
            metadata={
                'backup_id': backup.id,
                'filename': backup.filename,
                'create_safety_backup': create_safety_backup
            }
        )

        logger.info(f"Admin {request.user.username} queued restore of {backup.filename}")

        return JsonResponse({
            'success': True,
            'message': f'Restore queued. Restart the server to apply.',
            'requires_restart': True
        })

    except Exception as e:
        logger.error(f"Error queuing restore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_force_assign(request):
    """
    Manual force-assign interface for pool chores.
    """
    # Get all pool chores (not completed, in pool status)
    pool_chores = ChoreInstance.objects.filter(
        status=ChoreInstance.POOL
    ).select_related('chore').order_by('due_at')

    # Get all eligible users
    users = User.objects.filter(is_active=True, can_be_assigned=True).order_by('username')

    context = {
        'pool_chores': pool_chores,
        'users': users,
    }

    return render(request, 'board/admin/force_assign.html', context)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_force_assign_action(request, instance_id):
    """
    Execute force assignment of a chore to a user.
    """
    try:
        user_id = request.POST.get('user_id')

        if not user_id:
            return JsonResponse({'error': 'User ID required'}, status=400)

        instance = get_object_or_404(ChoreInstance, id=instance_id)
        user = get_object_or_404(User, id=user_id)

        if instance.status != ChoreInstance.POOL:
            return JsonResponse({'error': 'Chore is not in pool'}, status=400)

        with transaction.atomic():
            # Assign to user
            instance.status = ChoreInstance.ASSIGNED
            instance.assigned_to = user
            instance.assigned_at = timezone.now()
            instance.assignment_reason = ChoreInstance.REASON_MANUAL
            instance.save()

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_MANUAL_ASSIGN,
                user=request.user,
                target_user=user,
                description=f"Manually assigned '{instance.chore.name}' to {user.get_display_name()}",
                metadata={
                    'chore_instance_id': instance.id,
                    'chore_name': instance.chore.name,
                }
            )

            logger.info(f"Admin {request.user.username} force-assigned chore {instance.id} to {user.username}")

            return JsonResponse({
                'message': f'Successfully assigned "{instance.chore.name}" to {user.get_display_name()}',
            })

    except Exception as e:
        logger.error(f"Error force-assigning chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_streaks(request):
    """
    Streak management interface.
    """
    from core.models import Streak

    # Get all users with their streaks
    users = User.objects.filter(is_active=True).order_by('username')

    # Get or create streak for each user
    streaks = []
    for user in users:
        streak, _ = Streak.objects.get_or_create(user=user)
        streaks.append({
            'user': user,
            'streak': streak,
        })

    context = {
        'streaks': streaks,
    }

    return render(request, 'board/admin/streaks.html', context)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_streak_increment(request, user_id):
    """
    Increment a user's streak manually.
    """
    try:
        from core.models import Streak

        user = get_object_or_404(User, id=user_id)
        streak, _ = Streak.objects.get_or_create(user=user)

        with transaction.atomic():
            streak.current_streak += 1
            if streak.current_streak > streak.longest_streak:
                streak.longest_streak = streak.current_streak
            streak.last_perfect_week = timezone.now().date()
            streak.save()

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_SETTINGS_CHANGE,
                user=request.user,
                target_user=user,
                description=f"Incremented {user.get_display_name()}'s streak to {streak.current_streak}",
                metadata={
                    'user_id': user.id,
                    'new_current_streak': streak.current_streak,
                    'new_longest_streak': streak.longest_streak,
                }
            )

            logger.info(f"Admin {request.user.username} incremented streak for {user.username}")

            return JsonResponse({
                'message': f"Incremented {user.get_display_name()}'s streak to {streak.current_streak}",
                'current_streak': streak.current_streak,
                'longest_streak': streak.longest_streak,
            })

    except Exception as e:
        logger.error(f"Error incrementing streak: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_streak_reset(request, user_id):
    """
    Reset a user's current streak to 0.
    """
    try:
        from core.models import Streak

        user = get_object_or_404(User, id=user_id)
        streak, _ = Streak.objects.get_or_create(user=user)

        with transaction.atomic():
            old_streak = streak.current_streak
            streak.current_streak = 0
            streak.save()

            # Log the action
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_SETTINGS_CHANGE,
                user=request.user,
                target_user=user,
                description=f"Reset {user.get_display_name()}'s streak from {old_streak} to 0",
                metadata={
                    'user_id': user.id,
                    'old_streak': old_streak,
                    'longest_streak': streak.longest_streak,
                }
            )

            logger.info(f"Admin {request.user.username} reset streak for {user.username}")

            return JsonResponse({
                'message': f"Reset {user.get_display_name()}'s streak to 0",
                'current_streak': 0,
                'longest_streak': streak.longest_streak,
            })

    except Exception as e:
        logger.error(f"Error resetting streak: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_skip_chore(request, instance_id):
    """
    Skip a chore instance (admin only).
    """
    try:
        reason = request.POST.get('reason', '').strip()

        success, message, instance = SkipService.skip_chore(
            instance_id=instance_id,
            user=request.user,
            reason=reason if reason else None
        )

        if success:
            logger.info(f"Admin {request.user.username} skipped chore instance {instance_id}")
            return JsonResponse({
                'message': message,
                'instance_id': instance.id,
                'chore_name': instance.chore.name,
                'status': instance.status
            })
        else:
            logger.warning(f"Failed to skip chore {instance_id}: {message}")
            return JsonResponse({'error': message}, status=400)

    except Exception as e:
        logger.error(f"Error skipping chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_unskip_chore(request, instance_id):
    """
    Unskip (restore) a skipped chore instance (admin only).
    """
    try:
        success, message, instance = SkipService.unskip_chore(
            instance_id=instance_id,
            user=request.user
        )

        if success:
            logger.info(f"Admin {request.user.username} unskipped chore instance {instance_id}")
            return JsonResponse({
                'message': message,
                'instance_id': instance.id,
                'chore_name': instance.chore.name,
                'status': instance.status,
                'assigned_to': instance.assigned_to.username if instance.assigned_to else None
            })
        else:
            logger.warning(f"Failed to unskip chore {instance_id}: {message}")
            return JsonResponse({'error': message}, status=400)

    except Exception as e:
        logger.error(f"Error unskipping chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_reschedule_chore(request, chore_id):
    """
    Reschedule a chore to a specific date (admin only).
    """
    try:
        from datetime import datetime

        new_date_str = request.POST.get('new_date')
        reason = request.POST.get('reason', '').strip()

        if not new_date_str:
            return JsonResponse({'error': 'New date is required'}, status=400)

        # Parse the date
        try:
            new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        success, message, chore = RescheduleService.reschedule_chore(
            chore_id=chore_id,
            new_date=new_date,
            user=request.user,
            reason=reason if reason else None
        )

        if success:
            logger.info(f"Admin {request.user.username} rescheduled chore {chore_id} to {new_date}")
            return JsonResponse({
                'message': message,
                'chore_id': chore.id,
                'chore_name': chore.name,
                'rescheduled_date': chore.rescheduled_date.isoformat() if chore.rescheduled_date else None
            })
        else:
            logger.warning(f"Failed to reschedule chore {chore_id}: {message}")
            return JsonResponse({'error': message}, status=400)

    except Exception as e:
        logger.error(f"Error rescheduling chore: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_clear_reschedule(request, chore_id):
    """
    Clear reschedule and resume normal schedule (admin only).
    """
    try:
        success, message, chore = RescheduleService.clear_reschedule(
            chore_id=chore_id,
            user=request.user
        )

        if success:
            logger.info(f"Admin {request.user.username} cleared reschedule for chore {chore_id}")
            return JsonResponse({
                'message': message,
                'chore_id': chore.id,
                'chore_name': chore.name
            })
        else:
            logger.warning(f"Failed to clear reschedule for chore {chore_id}: {message}")
            return JsonResponse({'error': message}, status=400)

    except Exception as e:
        logger.error(f"Error clearing reschedule: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff_user)
def admin_skip_chores(request):
    """
    Admin page for skipping chores and viewing skipped chores history.
    """
    today = timezone.now().date()
    now = timezone.now()
    settings = Settings.get_settings()
    undo_limit_hours = settings.undo_time_limit_hours
    undo_cutoff = now - timedelta(hours=undo_limit_hours)

    # Get active chores (pool + assigned) that can be skipped
    # Include all instances due today OR overdue from previous days
    active_chores = ChoreInstance.objects.filter(
        Q(due_at__date=today) | Q(due_at__lt=now),
        status__in=[ChoreInstance.POOL, ChoreInstance.ASSIGNED],
        chore__is_active=True
    ).select_related('chore', 'assigned_to').order_by('due_at', 'status')

    # Get recently skipped chores (within undo window)
    skipped_chores_recent = ChoreInstance.objects.filter(
        status=ChoreInstance.SKIPPED,
        skipped_at__gte=undo_cutoff
    ).select_related('chore', 'assigned_to', 'skipped_by').order_by('-skipped_at')

    # Get older skipped chores (beyond undo window)
    skipped_chores_old = ChoreInstance.objects.filter(
        status=ChoreInstance.SKIPPED,
        skipped_at__lt=undo_cutoff
    ).select_related('chore', 'assigned_to', 'skipped_by').order_by('-skipped_at')[:20]

    context = {
        'active_chores': active_chores,
        'skipped_chores_recent': skipped_chores_recent,
        'skipped_chores_old': skipped_chores_old,
        'undo_limit_hours': undo_limit_hours,
        'today': today,
    }

    return render(request, 'board/admin/skip_chores.html', context)


@login_required
@user_passes_test(is_staff_user)
def admin_reschedule_chores(request):
    """
    Admin page for rescheduling chores.
    """
    today = timezone.now().date()

    # Get all active chores
    active_chores = Chore.objects.filter(
        is_active=True
    ).prefetch_related('eligible_users').order_by('name')

    # Separate rescheduled and normal chores
    rescheduled_chores = []
    normal_chores = []

    for chore in active_chores:
        if chore.rescheduled_date:
            rescheduled_chores.append(chore)
        else:
            normal_chores.append(chore)

    context = {
        'rescheduled_chores': rescheduled_chores,
        'normal_chores': normal_chores,
        'today': today,
    }

    return render(request, 'board/admin/reschedule_chores.html', context)


# ============================================================================
# MANUAL POINTS ADJUSTMENT
# ============================================================================

@login_required
@user_passes_test(is_staff_user)
def admin_adjust_points(request):
    """
    Manual points adjustment interface for admins.
    """
    # Get all active users ordered by username
    users = User.objects.filter(is_active=True).order_by('username')

    # Get recent manual adjustments (last 20)
    recent_adjustments = PointsLedger.objects.filter(
        transaction_type=PointsLedger.TYPE_ADMIN_ADJUSTMENT
    ).select_related('user', 'created_by').order_by('-created_at')[:20]

    context = {
        'users': users,
        'recent_adjustments': recent_adjustments,
    }

    return render(request, 'board/admin/adjust_points.html', context)


@login_required
@user_passes_test(is_staff_user)
@require_http_methods(["POST"])
def admin_adjust_points_submit(request):
    """
    Process manual points adjustment.
    """
    try:
        user_id = request.POST.get('user_id')
        points_str = request.POST.get('points', '').strip()
        reason = request.POST.get('reason', '').strip()

        # Validation
        if not user_id:
            return JsonResponse({'error': 'User is required'}, status=400)

        if not points_str:
            return JsonResponse({'error': 'Points amount is required'}, status=400)

        if not reason:
            return JsonResponse({'error': 'Reason is required'}, status=400)

        if len(reason) < 10:
            return JsonResponse({'error': 'Reason must be at least 10 characters'}, status=400)

        # Parse points
        try:
            points = Decimal(points_str)
        except (ValueError, TypeError, InvalidOperation):
            return JsonResponse({'error': 'Invalid points amount'}, status=400)

        # Validate points amount
        if points == 0:
            return JsonResponse({'error': 'Points amount cannot be zero'}, status=400)

        if abs(points) > Decimal('999.99'):
            return JsonResponse({'error': 'Points adjustment cannot exceed ±999.99'}, status=400)

        # Get user
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found or inactive'}, status=404)

        # Prevent self-adjustment
        if user.id == request.user.id:
            return JsonResponse({'error': 'You cannot adjust your own points'}, status=403)

        with transaction.atomic():
            # Get current balance
            current_balance = user.all_time_points
            new_balance = current_balance + points

            # Update user's points
            user.add_points(points, weekly=True, all_time=True)

            # Create PointsLedger entry
            ledger_entry = PointsLedger.objects.create(
                user=user,
                transaction_type=PointsLedger.TYPE_ADMIN_ADJUSTMENT,
                points_change=points,
                balance_after=new_balance,
                description=f"Manual adjustment by {request.user.get_display_name()}: {reason}",
                created_by=request.user
            )

            # Create ActionLog entry
            ActionLog.objects.create(
                action_type=ActionLog.ACTION_ADMIN,
                user=request.user,
                target_user=user,
                description=f"Adjusted points for {user.get_display_name()}: {points:+.2f} ({reason})",
                metadata={
                    'user_id': user.id,
                    'points_change': str(points),
                    'old_balance': str(current_balance),
                    'new_balance': str(new_balance),
                    'reason': reason
                }
            )

            logger.info(
                f"Admin {request.user.username} adjusted points for {user.username}: "
                f"{points:+.2f} (reason: {reason})"
            )

            return JsonResponse({
                'message': f'Successfully adjusted {user.get_display_name()}\'s points by {points:+.2f}',
                'old_balance': str(current_balance),
                'new_balance': str(new_balance),
                'ledger_id': ledger_entry.id
            })

    except Exception as e:
        logger.error(f"Error adjusting points: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
