"""
Chore models for ChoreBoard.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Chore(models.Model):
    """Chore template for recurring tasks."""

    # Schedule Types
    DAILY = "daily"
    WEEKLY = "weekly"
    EVERY_N_DAYS = "every_n_days"
    CRON = "cron"
    RRULE = "rrule"
    ONE_TIME = "one_time"
    SCHEDULE_CHOICES = [
        (DAILY, "Daily"),
        (WEEKLY, "Weekly"),
        (EVERY_N_DAYS, "Every N Days"),
        (CRON, "Cron"),
        (RRULE, "RRULE"),
        (ONE_TIME, "One-Time Task"),
    ]

    # Weekdays
    WEEKDAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    # Basic
    name = models.CharField(max_length=255)
    description = models.TextField(max_length=1000, blank=True, default='')
    points = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("999.99"))]
    )

    # Assignment
    is_pool = models.BooleanField(default=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name="fixed_chores"
    )

    # Tags
    is_difficult = models.BooleanField(default=False)
    is_undesirable = models.BooleanField(default=False)
    is_late_chore = models.BooleanField(default=False)

    # Distribution
    distribution_time = models.TimeField(default="17:30")

    # Schedule
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_CHOICES, default=DAILY)
    n_days = models.IntegerField(null=True, blank=True)
    every_n_start_date = models.DateField(null=True, blank=True)
    shift_on_late_completion = models.BooleanField(default=True)
    weekday = models.IntegerField(null=True, blank=True, choices=WEEKDAY_CHOICES)
    cron_expr = models.CharField(max_length=100, blank=True, default='')
    rrule_json = models.JSONField(null=True, blank=True)
    one_time_due_date = models.DateField(
        null=True,
        blank=True,
        help_text="For ONE_TIME tasks: optional due date. If not set, task never becomes overdue."
    )

    # Reschedule (one-time override)
    rescheduled_date = models.DateField(null=True, blank=True, help_text="Next date this chore should appear (overrides normal schedule)")
    reschedule_reason = models.CharField(max_length=255, blank=True, default='', help_text="Why was this chore rescheduled")
    rescheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="rescheduled_chores"
    )
    rescheduled_at = models.DateTimeField(null=True, blank=True, help_text="When was this chore rescheduled")

    # Soft Delete
    is_active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chores"
        ordering = ["name"]

    def __str__(self):
        suffix = " (inactive)" if not self.is_active else ""
        return f"{self.name}{suffix}"

    def clean(self):
        super().clean()
        if self.is_pool and self.assigned_to:
            raise ValidationError("Pool chores cannot have assigned_to user")
        if not self.is_pool and not self.assigned_to:
            raise ValidationError("Non-pool chores must have assigned_to user")

        # One-time task validation
        if self.schedule_type == self.ONE_TIME:
            # ONE_TIME doesn't use cron_expr or rrule_json
            if self.cron_expr:
                raise ValidationError({
                    'cron_expr': 'ONE_TIME tasks should not have cron_expr'
                })
            if self.rrule_json:
                raise ValidationError({
                    'rrule_json': 'ONE_TIME tasks should not have rrule_json'
                })
            # one_time_due_date is optional, no validation needed
        elif self.one_time_due_date:
            # one_time_due_date only for ONE_TIME tasks
            raise ValidationError({
                'one_time_due_date': 'Due date only applicable for ONE_TIME tasks'
            })

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        if self.description:
            self.description = self.description.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def is_child_chore(self):
        """
        Check if this chore is a child chore (has dependencies on other chores).

        Returns:
            bool: True if this chore depends on other chores
        """
        if not self.pk:
            return False
        return self.dependencies_as_child.exists()


class ChoreTemplate(models.Model):
    """Reusable chore template for quick chore creation."""

    template_name = models.CharField(max_length=255, unique=True)
    description = models.TextField(max_length=1000, blank=True, default='')

    # Configuration from Chore model
    points = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("999.99"))]
    )
    is_pool = models.BooleanField(default=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name="template_assignments"
    )
    is_difficult = models.BooleanField(default=False)
    is_undesirable = models.BooleanField(default=False)
    is_late_chore = models.BooleanField(default=False)
    distribution_time = models.TimeField(default="17:30")
    schedule_type = models.CharField(max_length=20, choices=Chore.SCHEDULE_CHOICES, default=Chore.DAILY)
    n_days = models.IntegerField(null=True, blank=True)
    every_n_start_date = models.DateField(null=True, blank=True)
    shift_on_late_completion = models.BooleanField(default=True)
    weekday = models.IntegerField(null=True, blank=True, choices=Chore.WEEKDAY_CHOICES)
    cron_expr = models.CharField(max_length=100, blank=True, default='')
    rrule_json = models.JSONField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="created_templates"
    )

    class Meta:
        db_table = "chore_templates"
        ordering = ["template_name"]

    def __str__(self):
        return self.template_name

    def to_chore_dict(self):
        """Convert template to dictionary suitable for Chore creation."""
        return {
            'points': self.points,
            'is_pool': self.is_pool,
            'assigned_to': self.assigned_to,
            'is_difficult': self.is_difficult,
            'is_undesirable': self.is_undesirable,
            'is_late_chore': self.is_late_chore,
            'distribution_time': self.distribution_time,
            'schedule_type': self.schedule_type,
            'n_days': self.n_days,
            'every_n_start_date': self.every_n_start_date,
            'shift_on_late_completion': self.shift_on_late_completion,
            'weekday': self.weekday,
            'cron_expr': self.cron_expr,
            'rrule_json': self.rrule_json,
        }


class ChoreEligibility(models.Model):
    """Eligible users for undesirable chores."""
    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="eligible_users")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        db_table = "chore_eligibility"
        unique_together = ["chore", "user"]

    def __str__(self):
        return f"{self.user} eligible for {self.chore}"


class ChoreDependency(models.Model):
    """
    Parent-child chore dependencies.

    When a parent chore is completed, child chores are automatically spawned
    and assigned to the person who completed the parent.

    IMPORTANT: Child chores (chores with dependencies) will NOT be scheduled
    independently through the normal scheduling system. They ONLY spawn when
    their parent chore is completed. Any schedule settings on child chores
    are ignored.
    """
    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="dependencies_as_child")
    depends_on = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="dependencies_as_parent")
    offset_hours = models.IntegerField(default=0, help_text="Hours after parent completion to spawn this child chore")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chore_dependencies"
        unique_together = ["chore", "depends_on"]

    def __str__(self):
        return f"{self.chore} depends on {self.depends_on}"

    def clean(self):
        super().clean()
        if self.chore == self.depends_on:
            raise ValidationError("Chore cannot depend on itself")

        # Check for circular dependencies
        if self.depends_on and self.chore:
            if self._would_create_cycle():
                raise ValidationError(
                    f"Creating this dependency would create a circular dependency loop. "
                    f"'{self.depends_on.name}' already depends on '{self.chore.name}' "
                    f"(directly or indirectly)."
                )

    def _would_create_cycle(self):
        """Check if adding this dependency would create a circular dependency."""
        # We're adding: chore depends on depends_on
        # This would create a cycle if depends_on already depends on chore (directly or indirectly)
        visited = set()
        queue = [self.depends_on]

        while queue:
            current = queue.pop(0)

            if current == self.chore:
                # Found a path from depends_on back to chore - this would be a cycle
                return True

            if current.id in visited:
                continue

            visited.add(current.id)

            # Get all chores that current depends on
            for dep in ChoreDependency.objects.filter(chore=current).select_related('depends_on'):
                if dep.depends_on.id not in visited:
                    queue.append(dep.depends_on)

        return False


class ChoreInstance(models.Model):
    """Daily instance of a chore template."""

    # Status choices
    POOL = "pool"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    STATUS_CHOICES = [
        (POOL, "Pool"),
        (ASSIGNED, "Assigned"),
        (COMPLETED, "Completed"),
        (SKIPPED, "Skipped"),
    ]

    # Assignment reasons (for "purple states")
    REASON_CLAIMED = "claimed"
    REASON_FORCE_ASSIGNED = "force_assigned"
    REASON_MANUAL = "manual_assign"
    REASON_NO_ELIGIBLE = "no_eligible_users"
    REASON_ALL_COMPLETED_YESTERDAY = "all_completed_yesterday"
    REASON_PARENT_COMPLETION = "parent_completion"
    ASSIGNMENT_REASON_CHOICES = [
        (REASON_CLAIMED, "User claimed"),
        (REASON_FORCE_ASSIGNED, "Force assigned by system"),
        (REASON_MANUAL, "Manually assigned by admin"),
        (REASON_NO_ELIGIBLE, "No eligible users"),
        (REASON_ALL_COMPLETED_YESTERDAY, "All eligible users completed yesterday"),
        (REASON_PARENT_COMPLETION, "Spawned from parent chore completion"),
    ]

    # Relations
    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="instances")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name="assigned_instances"
    )

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=POOL)
    assignment_reason = models.CharField(
        max_length=50, choices=ASSIGNMENT_REASON_CHOICES, blank=True
    )

    # Points snapshot (copied from Chore at creation)
    points_value = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("999.99"))]
    )

    # Scheduling
    due_at = models.DateTimeField()
    distribution_at = models.DateTimeField()

    # Flags
    is_overdue = models.BooleanField(default=False)
    is_late_completion = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Skip tracking
    skip_reason = models.TextField(blank=True, null=True, help_text="Reason for skipping this chore")
    skipped_at = models.DateTimeField(null=True, blank=True, help_text="When this chore was skipped", db_index=True)
    skipped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="skipped_chores",
        help_text="User who skipped this chore"
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chore_instances"
        ordering = ["due_at", "chore__name"]
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["assigned_to", "status"]),
        ]

    def __str__(self):
        status_display = self.get_status_display()
        if self.assigned_to:
            return f"{self.chore.name} ({status_display} - {self.assigned_to.username})"
        return f"{self.chore.name} ({status_display})"

    def clean(self):
        super().clean()
        if self.status == self.ASSIGNED and not self.assigned_to:
            raise ValidationError("Assigned chores must have assigned_to user")
        if self.status == self.POOL and self.assigned_to:
            raise ValidationError("Pool chores cannot have assigned_to user")

    def save(self, *args, **kwargs):
        # Snapshot points from chore template if not already set
        if not self.pk and self.points_value == 0.00:
            self.points_value = self.chore.points
        self.full_clean()
        super().save(*args, **kwargs)


class Completion(models.Model):
    """Record of a chore instance completion."""

    chore_instance = models.OneToOneField(
        ChoreInstance, on_delete=models.CASCADE, related_name="completion"
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="completions"
    )
    completed_at = models.DateTimeField(auto_now_add=True)
    was_late = models.BooleanField(default=False)

    # Undo tracking
    is_undone = models.BooleanField(default=False)
    undone_at = models.DateTimeField(null=True, blank=True)
    undone_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="undone_completions"
    )

    class Meta:
        db_table = "completions"
        ordering = ["-completed_at"]

    def __str__(self):
        status = " (undone)" if self.is_undone else ""
        return f"{self.chore_instance.chore.name} completed by {self.completed_by}{status}"


class CompletionShare(models.Model):
    """Tracks who helped with a completion and their point share."""

    completion = models.ForeignKey(Completion, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    points_awarded = models.DecimalField(
        max_digits=7, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("99999.99"))]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "completion_shares"
        unique_together = ["completion", "user"]
        ordering = ["-points_awarded"]

    def __str__(self):
        return f"{self.user.username}: {self.points_awarded} pts for {self.completion.chore_instance.chore.name}"


class PointsLedger(models.Model):
    """Immutable audit trail of all point transactions."""

    # Transaction types
    TYPE_COMPLETION = "completion"
    TYPE_UNDO = "undo"
    TYPE_WEEKLY_RESET = "weekly_reset"
    TYPE_ADMIN_ADJUSTMENT = "admin_adjustment"
    TRANSACTION_TYPES = [
        (TYPE_COMPLETION, "Chore Completion"),
        (TYPE_UNDO, "Undo Completion"),
        (TYPE_WEEKLY_RESET, "Weekly Reset"),
        (TYPE_ADMIN_ADJUSTMENT, "Admin Adjustment"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ledger_entries")
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    points_change = models.DecimalField(
        max_digits=7, decimal_places=2,
        help_text="Positive for earning, negative for deduction"
    )
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)

    # Optional references
    completion = models.ForeignKey(
        Completion, on_delete=models.SET_NULL, null=True, blank=True, related_name="ledger_entries"
    )
    weekly_snapshot = models.ForeignKey(
        "core.WeeklySnapshot", on_delete=models.SET_NULL, null=True, blank=True
    )

    # Metadata
    description = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="ledger_entries_created"
    )

    class Meta:
        db_table = "points_ledger"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["transaction_type", "-created_at"]),
        ]

    def __str__(self):
        sign = "+" if self.points_change >= 0 else ""
        return f"{self.user.username}: {sign}{self.points_change} pts ({self.get_transaction_type_display()})"


class ArcadeSession(models.Model):
    """Tracks active and completed arcade mode attempts."""

    STATUS_ACTIVE = 'active'
    STATUS_STOPPED = 'stopped'
    STATUS_APPROVED = 'approved'
    STATUS_DENIED = 'denied'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_STOPPED, 'Stopped - Awaiting Approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_DENIED, 'Denied'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='arcade_sessions')
    chore_instance = models.ForeignKey(ChoreInstance, on_delete=models.CASCADE, related_name='arcade_sessions')
    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='arcade_sessions')  # Denormalized for queries

    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    elapsed_seconds = models.IntegerField(default=0)  # Calculated field

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_active = models.BooleanField(default=True)  # Quick lookup for active sessions

    # Retry tracking
    attempt_number = models.IntegerField(default=1)  # 1st attempt, 2nd attempt, etc.
    cumulative_seconds = models.IntegerField(default=0)  # Total time across all retries

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'arcade_sessions'
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['status']),
            models.Index(fields=['chore']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.chore.name} ({self.get_status_display()})"

    def get_elapsed_time(self):
        """Calculate elapsed time based on start/end times."""
        if self.end_time:
            delta = self.end_time - self.start_time
        else:
            delta = timezone.now() - self.start_time
        return int(delta.total_seconds()) + self.cumulative_seconds

    def format_time(self):
        """Format elapsed time as HH:MM:SS or MM:SS."""
        seconds = self.elapsed_seconds if self.elapsed_seconds else self.get_elapsed_time()
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"


class ArcadeCompletion(models.Model):
    """Records approved arcade mode completions."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='arcade_completions')
    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='arcade_completions')
    arcade_session = models.OneToOneField(ArcadeSession, on_delete=models.CASCADE, related_name='completion')
    chore_instance = models.ForeignKey(ChoreInstance, on_delete=models.CASCADE, related_name='arcade_completion')

    completion_time_seconds = models.IntegerField()
    judge = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='judged_arcades')
    approved = models.BooleanField(default=True)  # Always true for this model (denials don't create records)
    judge_notes = models.TextField(blank=True, default='')

    # Points
    base_points = models.DecimalField(max_digits=5, decimal_places=2)
    bonus_points = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_points = models.DecimalField(max_digits=5, decimal_places=2)

    # High score status at time of completion
    is_high_score = models.BooleanField(default=False)
    rank_at_completion = models.IntegerField(null=True, blank=True)  # 1, 2, 3, or None

    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'arcade_completions'
        indexes = [
            models.Index(fields=['user', 'chore']),
            models.Index(fields=['chore', 'completion_time_seconds']),
            models.Index(fields=['is_high_score']),
        ]
        ordering = ['completion_time_seconds']  # Fastest first

    def __str__(self):
        return f"{self.user.username} - {self.chore.name} - {self.format_time()}"

    def format_time(self):
        """Format completion time as HH:MM:SS or MM:SS."""
        seconds = self.completion_time_seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"


class ArcadeHighScore(models.Model):
    """Maintains top 3 high scores per chore."""

    RANK_CHOICES = [
        (1, '1st Place'),
        (2, '2nd Place'),
        (3, '3rd Place'),
    ]

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='high_scores')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='high_scores')
    arcade_completion = models.ForeignKey(ArcadeCompletion, on_delete=models.CASCADE, related_name='high_score_entry')

    time_seconds = models.IntegerField()
    rank = models.IntegerField(choices=RANK_CHOICES)
    achieved_at = models.DateTimeField()

    class Meta:
        db_table = 'arcade_high_scores'
        unique_together = ['chore', 'rank']  # Only one record per rank per chore
        indexes = [
            models.Index(fields=['chore', 'rank']),
            models.Index(fields=['user']),
        ]
        ordering = ['chore', 'rank']

    def __str__(self):
        rank_emoji = {1: '🥇', 2: '🥈', 3: '🥉'}
        return f"{rank_emoji[self.rank]} {self.chore.name} - {self.user.username} - {self.format_time()}"

    def format_time(self):
        """Format time as HH:MM:SS or MM:SS."""
        seconds = self.time_seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"


class PianoScore(models.Model):
    """Records piano game high scores (separate from arcade)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='piano_scores'
    )
    score = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(999999)],
        help_text="Number of tiles successfully hit"
    )
    hard_mode = models.BooleanField(
        default=False,
        help_text="Was this score achieved in hard mode?"
    )
    achieved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'piano_scores'
        ordering = ['-score', 'achieved_at']
        indexes = [
            models.Index(fields=['-score', 'achieved_at']),
            models.Index(fields=['user', '-score']),
            models.Index(fields=['hard_mode', '-score']),
        ]

    def __str__(self):
        mode = " (Hard)" if self.hard_mode else ""
        return f"{self.user.get_display_name()}: {self.score}{mode}"
