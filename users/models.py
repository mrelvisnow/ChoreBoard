"""
User models for ChoreBoard.

Defines custom User model with assignment eligibility, points tracking, and claims.
"""
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.text import slugify


class User(AbstractUser):
    """
    Custom user model with chore assignment and points tracking.

    Extends Django's AbstractUser with fields for:
    - Assignment eligibility (can_be_assigned)
    - Points eligibility (eligible_for_points)
    - Points tracking (weekly and all-time)
    - Daily claim limits
    - Soft delete (is_active)
    """

    # Assignment & Points Eligibility
    can_be_assigned = models.BooleanField(
        default=True,
        help_text="Can this user be assigned chores? (Included in rotation/force-assignment pool)"
    )
    exclude_from_auto_assignment = models.BooleanField(
        default=False,
        help_text="If True, user will NOT be auto-assigned chores at distribution time, but can still claim or be manually assigned"
    )
    eligible_for_points = models.BooleanField(
        default=False,
        help_text="Can this user earn points and appear on leaderboard?"
    )

    # Points Tracking
    weekly_points = models.DecimalField(
        max_digits=7,  # Up to 99999.99
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
        help_text="Points earned this week (resets Sunday midnight)"
    )
    all_time_points = models.DecimalField(
        max_digits=10,  # Up to 99999999.99
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
        help_text="Total points earned all time"
    )

    # Claims Tracking
    claims_today = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Number of chores claimed today (resets at midnight)"
    )

    # Soft Delete (override AbstractUser's is_active to use for soft delete)
    # Note: is_active already exists in AbstractUser, we'll use it for soft delete

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        ordering = ["username"]
        indexes = [
            models.Index(fields=["is_active", "eligible_for_points"]),
            models.Index(fields=["is_active", "can_be_assigned"]),
        ]

    def __str__(self):
        """Return display name for this user."""
        return self.get_display_name()

    def get_display_name(self):
        """
        Get the display name for this user.

        Returns first_name if set, otherwise username.
        Appends (inactive) suffix if user is soft-deleted.
        """
        name = self.first_name.strip() if self.first_name else self.username
        if not self.is_active:
            return f"{name} (inactive)"
        return name

    def get_url_slug(self):
        """
        Get URL-safe slug for this user.

        Converts username to lowercase with hyphens for URL routing.
        """
        return slugify(self.username)

    def can_claim_today(self):
        """Check if user can claim another chore today (limit 1/day)."""
        return self.claims_today < 1

    def reset_daily_claims(self):
        """Reset daily claim counter (called at midnight)."""
        self.claims_today = 0
        self.save(update_fields=["claims_today"])

    def add_points(self, points_amount, weekly=True, all_time=True):
        """
        Add points to this user's totals.

        Args:
            points_amount: Decimal amount to add
            weekly: Add to weekly points (default True)
            all_time: Add to all-time points (default True)
        """
        from decimal import Decimal as D

        if weekly:
            self.weekly_points = D(str(self.weekly_points)) + points_amount
            # Floor at 0 (no negative weekly points)
            if self.weekly_points < 0:
                self.weekly_points = 0

        if all_time:
            self.all_time_points = D(str(self.all_time_points)) + points_amount
            # Floor at 0 (no negative all-time points)
            if self.all_time_points < 0:
                self.all_time_points = 0

        self.save(update_fields=["weekly_points", "all_time_points"])

    def reset_weekly_points(self):
        """Reset weekly points to 0 (called during weekly convert & reset)."""
        self.weekly_points = 0
        self.save(update_fields=["weekly_points"])
