"""Django admin configuration for Chore models."""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    Chore, ChoreEligibility, ChoreDependency, ChoreInstance,
    Completion, CompletionShare, PointsLedger, PianoScore
)


class ChoreEligibilityInline(admin.TabularInline):
    """Inline admin for eligible users (undesirable chores)."""
    model = ChoreEligibility
    extra = 1
    autocomplete_fields = ['user']


class ChoreDependencyAsChildInline(admin.TabularInline):
    """Inline admin for chores that depend on this chore."""
    model = ChoreDependency
    fk_name = 'depends_on'
    extra = 0
    verbose_name = "Chore that depends on this"
    verbose_name_plural = "Child Chores (these spawn when this chore completes)"
    autocomplete_fields = ['chore']


class ChoreDependencyAsParentInline(admin.TabularInline):
    """Inline admin for chores this chore depends on."""
    model = ChoreDependency
    fk_name = 'chore'
    extra = 0
    verbose_name = "Depends on"
    verbose_name_plural = "Parent Chores (this spawns after these complete)"
    autocomplete_fields = ['depends_on']


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    """Admin interface for Chore model."""
    list_display = ["name", "points", "colored_status", "assigned_to", "schedule_type", "has_dependencies", "is_difficult"]
    list_filter = ["is_active", "is_pool", "is_difficult", "is_undesirable", "is_late_chore", "schedule_type"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at", "dependency_info"]
    list_editable = ["points"]
    list_per_page = 50
    inlines = [ChoreEligibilityInline, ChoreDependencyAsParentInline, ChoreDependencyAsChildInline]

    actions = ['activate_chores', 'deactivate_chores', 'mark_as_pool', 'mark_as_difficult']

    fieldsets = (
        ("Basic Info", {
            "fields": ("name", "description", "points")
        }),
        ("Assignment", {
            "fields": ("is_pool", "assigned_to")
        }),
        ("Tags", {
            "fields": ("is_difficult", "is_undesirable", "is_late_chore")
        }),
        ("Schedule", {
            "fields": ("schedule_type", "distribution_time", "n_days", "every_n_start_date",
                      "shift_on_late_completion", "weekday", "cron_expr", "rrule_json")
        }),
        ("Dependencies", {
            "fields": ("dependency_info",),
            "classes": ("collapse",)
        }),
        ("Status", {
            "fields": ("is_active",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def colored_status(self, obj):
        """Display status with color coding."""
        if not obj.is_active:
            return format_html('<span style="color: #999;">⚫ Inactive</span>')
        elif obj.is_pool:
            return format_html('<span style="color: #3b82f6;">🔵 Pool</span>')
        else:
            return format_html('<span style="color: #10b981;">🟢 Assigned</span>')
    colored_status.short_description = "Status"

    def has_dependencies(self, obj):
        """Show if chore has parent/child relationships."""
        as_child = obj.dependencies_as_child.count()
        as_parent = obj.dependencies_as_parent.count()
        if as_child > 0 and as_parent > 0:
            return format_html('<span title="Has both parent and child chores">↕️ Both</span>')
        elif as_child > 0:
            return format_html('<span title="Has parent chore(s)">⬆️ Child</span>')
        elif as_parent > 0:
            return format_html('<span title="Has child chore(s)">⬇️ Parent</span>')
        return "-"
    has_dependencies.short_description = "Dependencies"

    def dependency_info(self, obj):
        """Display dependency relationships."""
        if not obj.pk:
            return "Save chore first to add dependencies"

        html = []

        # Parent dependencies
        parents = obj.dependencies_as_child.all()
        if parents:
            html.append("<strong>This chore spawns after:</strong><ul>")
            for dep in parents:
                html.append(f"<li>{dep.depends_on.name} (offset: {dep.offset_hours}h)</li>")
            html.append("</ul>")

            # Warning if child chore has its own schedule
            html.append('<div style="background-color: #fff3cd; border: 1px solid #ffc107; padding: 10px; margin-top: 10px; border-radius: 4px;">')
            html.append('<strong>⚠️ Note:</strong> This is a child chore - it will ONLY spawn when its parent chore(s) are completed. ')
            html.append('The schedule settings above are ignored for child chores.')
            html.append('</div>')

        # Child dependencies
        children = obj.dependencies_as_parent.all()
        if children:
            html.append("<strong>When this completes, it spawns:</strong><ul>")
            for dep in children:
                html.append(f"<li>{dep.chore.name} (offset: {dep.offset_hours}h)</li>")
            html.append("</ul>")

        if not html:
            return "No dependencies configured"

        return mark_safe("".join(html))
    dependency_info.short_description = "Dependency Relationships"

    @admin.action(description="✅ Activate selected chores")
    def activate_chores(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} chore(s) activated successfully.")

    @admin.action(description="❌ Deactivate selected chores")
    def deactivate_chores(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} chore(s) deactivated successfully.")

    @admin.action(description="🔵 Mark as pool chores")
    def mark_as_pool(self, request, queryset):
        updated = queryset.update(is_pool=True, assigned_to=None)
        self.message_user(request, f"{updated} chore(s) marked as pool.")

    @admin.action(description="⚠️ Mark as difficult")
    def mark_as_difficult(self, request, queryset):
        updated = queryset.update(is_difficult=True)
        self.message_user(request, f"{updated} chore(s) marked as difficult.")


@admin.register(ChoreEligibility)
class ChoreEligibilityAdmin(admin.ModelAdmin):
    """Admin interface for ChoreEligibility model."""
    list_display = ["chore", "user"]
    list_filter = ["chore"]
    search_fields = ["chore__name", "user__username"]


@admin.register(ChoreDependency)
class ChoreDependencyAdmin(admin.ModelAdmin):
    """Admin interface for ChoreDependency model."""
    list_display = ["chore", "depends_on", "offset_hours", "created_at"]
    list_filter = ["offset_hours"]
    search_fields = ["chore__name", "depends_on__name"]
    readonly_fields = ["created_at"]


@admin.register(ChoreInstance)
class ChoreInstanceAdmin(admin.ModelAdmin):
    """Admin interface for ChoreInstance model."""
    list_display = ["chore_name", "colored_status", "assigned_to", "points_value", "due_date", "overdue_indicator"]
    list_filter = ["status", "is_overdue", "is_late_completion", "due_at", "assignment_reason"]
    search_fields = ["chore__name", "assigned_to__username"]
    readonly_fields = ["created_at", "assigned_at", "completed_at", "updated_at", "time_until_due"]
    date_hierarchy = "due_at"
    list_per_page = 100
    autocomplete_fields = ["chore", "assigned_to"]

    actions = ['force_assign_to_user', 'mark_as_overdue', 'reset_to_pool']

    fieldsets = (
        ("Chore Info", {
            "fields": ("chore", "points_value")
        }),
        ("Assignment", {
            "fields": ("status", "assigned_to", "assignment_reason")
        }),
        ("Schedule", {
            "fields": ("distribution_at", "due_at", "time_until_due")
        }),
        ("Flags", {
            "fields": ("is_overdue", "is_late_completion")
        }),
        ("Timestamps", {
            "fields": ("created_at", "assigned_at", "completed_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def chore_name(self, obj):
        """Display chore name with link."""
        url = reverse('admin:chores_chore_change', args=[obj.chore.id])
        return format_html('<a href="{}">{}</a>', url, obj.chore.name)
    chore_name.short_description = "Chore"
    chore_name.admin_order_field = "chore__name"

    def colored_status(self, obj):
        """Display status with color coding."""
        colors = {
            ChoreInstance.POOL: ('#3b82f6', '🔵'),
            ChoreInstance.ASSIGNED: ('#10b981', '🟢'),
            ChoreInstance.COMPLETED: ('#6b7280', '✅'),
        }
        color, emoji = colors.get(obj.status, ('#999', '❓'))

        if obj.assignment_reason in [ChoreInstance.REASON_NO_ELIGIBLE, ChoreInstance.REASON_ALL_COMPLETED_YESTERDAY]:
            # Purple state
            return format_html(
                '<span style="color: #a855f7;" title="{}">{} {} (blocked)</span>',
                obj.get_assignment_reason_display(), emoji, obj.get_status_display()
            )

        return format_html('<span style="color: {};">{} {}</span>', color, emoji, obj.get_status_display())
    colored_status.short_description = "Status"
    colored_status.admin_order_field = "status"

    def overdue_indicator(self, obj):
        """Show overdue status with visual indicator."""
        if obj.is_overdue:
            from django.utils import timezone
            hours_overdue = (timezone.now() - obj.due_at).total_seconds() / 3600
            return format_html('<span style="color: #ef4444; font-weight: bold;">🔴 {}h late</span>', int(hours_overdue))
        return format_html('<span style="color: #10b981;">✅ On time</span>')
    overdue_indicator.short_description = "Overdue?"

    def due_date(self, obj):
        """Display due date in friendly format."""
        from django.utils import timezone
        now = timezone.now()
        if obj.due_at < now:
            return format_html('<span style="color: #ef4444;">{}</span>', obj.due_at.strftime('%Y-%m-%d %H:%M'))
        return obj.due_at.strftime('%Y-%m-%d %H:%M')
    due_date.short_description = "Due"
    due_date.admin_order_field = "due_at"

    def time_until_due(self, obj):
        """Calculate and display time until due."""
        from django.utils import timezone
        now = timezone.now()
        delta = obj.due_at - now

        if delta.total_seconds() < 0:
            hours = abs(int(delta.total_seconds() / 3600))
            return format_html('<span style="color: #ef4444;">⚠️ {} hours overdue</span>', hours)

        hours = int(delta.total_seconds() / 3600)
        return format_html('<span style="color: #10b981;">⏱️ {} hours remaining</span>', hours)
    time_until_due.short_description = "Time Until Due"

    @admin.action(description="👤 Force assign to user (select user in next step)")
    def force_assign_to_user(self, request, queryset):
        """Force assign selected instances to a specific user."""
        from django.contrib import messages
        from django.shortcuts import render, redirect
        from django.utils import timezone
        from users.models import User
        from core.models import ActionLog

        # Filter to only pool instances
        pool_instances = queryset.filter(status=ChoreInstance.POOL)

        if not pool_instances.exists():
            messages.error(request, "No pool chores selected. Only pool chores can be force-assigned.")
            return

        # If user is selected, perform the assignment
        if 'target_user_id' in request.POST:
            target_user_id = request.POST.get('target_user_id')

            if not target_user_id:
                messages.error(request, "Please select a user to assign chores to.")
                return

            try:
                target_user = User.objects.get(id=target_user_id)
            except User.DoesNotExist:
                messages.error(request, "Selected user does not exist.")
                return

            # Check if user can be assigned
            if not target_user.can_be_assigned:
                messages.error(request, f"{target_user.username} cannot be assigned chores (can_be_assigned=False).")
                return

            # Assign chores
            assigned_count = 0
            for instance in pool_instances:
                instance.status = ChoreInstance.ASSIGNED
                instance.assigned_to = target_user
                instance.assigned_at = timezone.now()
                instance.assignment_reason = ChoreInstance.REASON_MANUAL_ASSIGN
                instance.save()

                # Increment user's claims_today counter
                target_user.claims_today += 1
                target_user.save()

                # Log the action
                ActionLog.objects.create(
                    action_type=ActionLog.ACTION_MANUAL_ASSIGN,
                    user=request.user,
                    target_user=target_user,
                    description=f"Admin {request.user.username} manually assigned '{instance.chore.name}' to {target_user.username}",
                    metadata={
                        'instance_id': instance.id,
                        'chore_name': instance.chore.name,
                        'points': str(instance.points_value)
                    }
                )

                assigned_count += 1

            messages.success(
                request,
                f"Successfully assigned {assigned_count} chore(s) to {target_user.username}. "
                f"Their daily claim count increased from {target_user.claims_today - assigned_count} to {target_user.claims_today}."
            )
            return

        # Show intermediate page to select user
        eligible_users = User.objects.filter(can_be_assigned=True, is_active=True).order_by('username')

        context = {
            'title': f'Force Assign {pool_instances.count()} Chore(s)',
            'instances': pool_instances,
            'eligible_users': eligible_users,
            'action_url': request.get_full_path(),
            'opts': self.model._meta,
        }

        return render(request, 'admin/chores/force_assign_intermediate.html', context)

    @admin.action(description="🔴 Mark as overdue")
    def mark_as_overdue(self, request, queryset):
        updated = queryset.update(is_overdue=True)
        self.message_user(request, f"{updated} instance(s) marked as overdue.")

    @admin.action(description="🔵 Reset to pool (unassign)")
    def reset_to_pool(self, request, queryset):
        from django.db.models import Q
        # Only allow for non-completed instances
        eligible = queryset.filter(~Q(status=ChoreInstance.COMPLETED))
        updated = eligible.update(
            status=ChoreInstance.POOL,
            assigned_to=None,
            assignment_reason=''
        )
        self.message_user(request, f"{updated} instance(s) reset to pool.")


@admin.register(Completion)
class CompletionAdmin(admin.ModelAdmin):
    """Admin interface for Completion model."""
    list_display = ["chore_instance", "completed_by", "completed_at_display", "was_late", "undo_status", "time_until_undo_expires"]
    list_filter = ["is_undone", "was_late", "completed_at"]
    search_fields = ["chore_instance__chore__name", "completed_by__username"]
    readonly_fields = ["completed_at", "undone_at", "undo_window_info"]
    actions = ['undo_completions']

    fieldsets = (
        ("Completion Info", {
            "fields": ("chore_instance", "completed_by", "completed_at")
        }),
        ("Status", {
            "fields": ("was_late", "is_undone", "undone_at")
        }),
        ("Undo Window", {
            "fields": ("undo_window_info",),
            "description": "Completions can be undone within the configured time limit"
        }),
    )

    def completed_at_display(self, obj):
        """Display completion time with relative time."""
        from django.utils import timezone
        from django.utils.html import format_html
        delta = timezone.now() - obj.completed_at
        if delta.days > 0:
            relative = f"{delta.days} days ago"
        elif delta.seconds > 3600:
            relative = f"{delta.seconds // 3600} hours ago"
        else:
            relative = f"{delta.seconds // 60} minutes ago"
        return format_html(
            '{}<br><span style="color: #666; font-size: 0.9em;">({})</span>',
            obj.completed_at.strftime('%Y-%m-%d %H:%M'),
            relative
        )
    completed_at_display.short_description = "Completed At"

    def undo_status(self, obj):
        """Display undo status with visual indicator."""
        from django.utils.html import format_html
        if obj.is_undone:
            return format_html('<span style="color: #dc3545;">✗ Undone</span>')
        return format_html('<span style="color: #28a745;">✓ Active</span>')
    undo_status.short_description = "Status"

    def time_until_undo_expires(self, obj):
        """Display time remaining to undo."""
        from django.utils import timezone
        from django.utils.html import format_html
        from core.models import Settings

        if obj.is_undone:
            return format_html('<span style="color: #999;">N/A (already undone)</span>')

        settings = Settings.get_settings()
        undo_deadline = obj.completed_at + timezone.timedelta(hours=settings.undo_time_limit_hours)
        delta = undo_deadline - timezone.now()

        if delta.total_seconds() <= 0:
            return format_html('<span style="color: #dc3545;">⚠️ Expired</span>')

        hours_remaining = int(delta.total_seconds() / 3600)
        if hours_remaining > 1:
            return format_html('<span style="color: #28a745;">{} hours</span>', hours_remaining)
        else:
            minutes_remaining = int(delta.total_seconds() / 60)
            return format_html('<span style="color: #ffc107;">{}  min</span>', minutes_remaining)
    time_until_undo_expires.short_description = "Undo Window"

    def undo_window_info(self, obj):
        """Display detailed undo window information."""
        from django.utils import timezone
        from django.utils.html import format_html
        from core.models import Settings

        settings = Settings.get_settings()
        undo_deadline = obj.completed_at + timezone.timedelta(hours=settings.undo_time_limit_hours)
        delta = undo_deadline - timezone.now()

        if obj.is_undone:
            return format_html(
                '<p style="color: #dc3545;"><strong>This completion has been undone.</strong></p>'
                '<p>Undone at: {}</p>',
                obj.undone_at.strftime('%Y-%m-%d %H:%M') if obj.undone_at else 'Unknown'
            )

        if delta.total_seconds() <= 0:
            return format_html(
                '<p style="color: #dc3545;"><strong>Undo window expired.</strong></p>'
                '<p>Completed: {}</p>'
                '<p>Undo deadline: {} ({} hour window)</p>',
                obj.completed_at.strftime('%Y-%m-%d %H:%M'),
                undo_deadline.strftime('%Y-%m-%d %H:%M'),
                settings.undo_time_limit_hours
            )

        hours_remaining = int(delta.total_seconds() / 3600)
        return format_html(
            '<p style="color: #28a745;"><strong>Undo available for {} more hours.</strong></p>'
            '<p>Completed: {}</p>'
            '<p>Undo deadline: {}</p>',
            hours_remaining,
            obj.completed_at.strftime('%Y-%m-%d %H:%M'),
            undo_deadline.strftime('%Y-%m-%d %H:%M')
        )
    undo_window_info.short_description = "Undo Window Details"

    @admin.action(description="🔙 Undo selected completions")
    def undo_completions(self, request, queryset):
        """Undo selected completions if within time limit."""
        from django.contrib import messages
        from django.utils import timezone
        from core.models import Settings, ActionLog
        from chores.models import CompletionShare, PointsLedger
        from decimal import Decimal

        settings = Settings.get_settings()
        undo_limit_hours = settings.undo_time_limit_hours

        success_count = 0
        error_count = 0
        errors = []

        for completion in queryset:
            # Check if already undone
            if completion.is_undone:
                errors.append(f"'{completion.chore_instance.chore.name}' - Already undone")
                error_count += 1
                continue

            # Check time limit
            time_since_completion = timezone.now() - completion.completed_at
            if time_since_completion.total_seconds() > (undo_limit_hours * 3600):
                hours_ago = int(time_since_completion.total_seconds() / 3600)
                errors.append(f"'{completion.chore_instance.chore.name}' - Too old ({hours_ago}h ago, limit: {undo_limit_hours}h)")
                error_count += 1
                continue

            try:
                # Get all point shares for this completion
                shares = CompletionShare.objects.filter(completion=completion)

                # Reverse points for each user
                for share in shares:
                    user = share.user
                    points_to_deduct = share.points_awarded

                    # Deduct from weekly_points (floor at 0)
                    user.weekly_points = max(Decimal('0.00'), user.weekly_points - points_to_deduct)
                    user.save()

                    # Create reversing ledger entry
                    PointsLedger.objects.create(
                        user=user,
                        transaction_type=PointsLedger.UNDO_COMPLETION,
                        points_change=-points_to_deduct,
                        balance_after=user.weekly_points,
                        description=f"Undid completion of '{completion.chore_instance.chore.name}' (originally completed by {completion.completed_by.username})"
                    )

                # Restore ChoreInstance to previous state
                instance = completion.chore_instance
                # If was forced/manual assignment, restore to assigned
                # Otherwise restore to pool
                if instance.assignment_reason in [ChoreInstance.REASON_MANUAL_ASSIGN, ChoreInstance.REASON_FORCED]:
                    instance.status = ChoreInstance.ASSIGNED
                    # Keep assigned_to as-is
                else:
                    instance.status = ChoreInstance.POOL
                    instance.assigned_to = None

                instance.completed_at = None
                instance.is_late_completion = False
                instance.save()

                # Mark completion as undone
                completion.is_undone = True
                completion.undone_at = timezone.now()
                completion.save()

                # Log the undo action
                ActionLog.objects.create(
                    action_type=ActionLog.ACTION_UNDO,
                    user=request.user,
                    target_user=completion.completed_by,
                    description=f"Admin {request.user.username} undid completion of '{instance.chore.name}' by {completion.completed_by.username}",
                    metadata={
                        'completion_id': completion.id,
                        'instance_id': instance.id,
                        'chore_name': instance.chore.name,
                        'original_completer': completion.completed_by.username,
                        'num_shares': shares.count(),
                        'total_points_reversed': str(sum(s.points_awarded for s in shares))
                    }
                )

                success_count += 1

            except Exception as e:
                errors.append(f"'{completion.chore_instance.chore.name}' - Error: {str(e)}")
                error_count += 1

        # Show results
        if success_count > 0:
            messages.success(
                request,
                f"Successfully undid {success_count} completion(s). Points have been reversed and chore instances restored."
            )

        if error_count > 0:
            messages.warning(
                request,
                f"Could not undo {error_count} completion(s):<br>" + "<br>".join(errors)
            )


class CompletionShareInline(admin.TabularInline):
    """Inline admin for CompletionShare."""
    model = CompletionShare
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(CompletionShare)
class CompletionShareAdmin(admin.ModelAdmin):
    """Admin interface for CompletionShare model."""
    list_display = ["completion", "user", "points_awarded", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["completion__chore_instance__chore__name", "user__username"]
    readonly_fields = ["created_at"]


@admin.register(PointsLedger)
class PointsLedgerAdmin(admin.ModelAdmin):
    """Admin interface for PointsLedger model."""
    list_display = ["user", "transaction_type", "points_change", "balance_after", "created_at"]
    list_filter = ["transaction_type", "created_at"]
    search_fields = ["user__username", "description"]
    readonly_fields = ["created_at"]

    def has_add_permission(self, request):
        """Ledger entries should only be created by the system."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Ledger entries are immutable and cannot be deleted."""
        return False


@admin.register(PianoScore)
class PianoScoreAdmin(admin.ModelAdmin):
    """Admin interface for PianoScore model."""
    list_display = ('user', 'score', 'hard_mode', 'achieved_at')
    list_filter = ('hard_mode', 'achieved_at')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    readonly_fields = ('achieved_at',)
    date_hierarchy = 'achieved_at'
