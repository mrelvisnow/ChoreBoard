"""
Management command to manually mark all past-due chores as overdue.
This is useful for fixing chores that were created before the overdue detection fix.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from chores.models import ChoreInstance


class Command(BaseCommand):
    help = 'Manually mark all past-due chores as overdue'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options['dry_run']

        self.stdout.write(f"Current time: {now}")
        self.stdout.write(f"Timezone: {timezone.get_current_timezone()}")
        self.stdout.write("")

        # Find all chores that should be overdue but aren't marked
        overdue_instances = ChoreInstance.objects.filter(
            status__in=[ChoreInstance.POOL, ChoreInstance.ASSIGNED],
            due_at__lt=now,
            is_overdue=False
        ).select_related('chore')

        count = overdue_instances.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No chores need updating"))
            return

        self.stdout.write(f"Found {count} chores that should be overdue but aren't marked:")
        self.stdout.write("")

        # Show which chores will be updated
        for instance in overdue_instances[:20]:  # Limit display to 20
            self.stdout.write(f"  - {instance.chore.name}")
            self.stdout.write(f"      Due: {instance.due_at}")
            self.stdout.write(f"      Status: {instance.status}")
            self.stdout.write(f"      Assigned to: {instance.assigned_to.username if instance.assigned_to else 'Pool'}")

        if count > 20:
            self.stdout.write(f"  ... and {count - 20} more")

        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes made"))
            self.stdout.write(f"Would mark {count} chores as overdue")
        else:
            self.stdout.write("Marking chores as overdue...")
            updated = overdue_instances.update(is_overdue=True)
            self.stdout.write(self.style.SUCCESS(f"✓ Successfully marked {updated} chores as overdue"))

            # Also send notifications for these newly marked overdue chores
            from core.notifications import NotificationService
            for instance in overdue_instances:
                NotificationService.notify_chore_overdue(instance)

            self.stdout.write(self.style.SUCCESS(f"✓ Sent {count} overdue notifications"))
