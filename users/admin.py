"""Django admin configuration for User model."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin interface for User model."""

    # Display fields in list view
    list_display = [
        "username",
        "get_display_name",
        "email",
        "can_be_assigned",
        "exclude_from_auto_assignment",
        "eligible_for_points",
        "weekly_points",
        "all_time_points",
        "is_active",
        "is_staff",
    ]

    # Filters in sidebar
    list_filter = [
        "is_active",
        "is_staff",
        "is_superuser",
        "can_be_assigned",
        "exclude_from_auto_assignment",
        "eligible_for_points",
    ]

    # Search fields
    search_fields = ["username", "first_name", "last_name", "email"]

    # Edit form fieldsets
    fieldsets = BaseUserAdmin.fieldsets + (
        ("ChoreBoard Settings", {
            "fields": (
                "can_be_assigned",
                "exclude_from_auto_assignment",
                "eligible_for_points",
            )
        }),
        ("Points & Claims", {
            "fields": (
                "weekly_points",
                "all_time_points",
                "claims_today",
            )
        }),
        ("Timestamps", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    # Add form fieldsets
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("ChoreBoard Settings", {
            "fields": (
                "can_be_assigned",
                "exclude_from_auto_assignment",
                "eligible_for_points",
            )
        }),
    )

    # Read-only fields
    readonly_fields = ["created_at", "updated_at"]

    # Ordering
    ordering = ["username"]
