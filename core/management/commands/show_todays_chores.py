"""
Management command to show all chore instances created today.
"""
from django.core.management.base import BaseCommand
from chores.models import ChoreInstance
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Show all chore instances created for today'

    def handle(self, *args, **options):
        now = timezone.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS(f"Chore Instances for Today ({today})"))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write('')

        # Find instances "for today" - they have due_at = start of tomorrow
        instances = ChoreInstance.objects.filter(
            due_at__date=tomorrow
        ).select_related('chore', 'assigned_to').order_by('status', 'chore__name')

        if not instances.exists():
            self.stdout.write(self.style.WARNING('No chore instances found for today.'))
            self.stdout.write('')
            self.stdout.write('This means:')
            self.stdout.write('  1. Midnight evaluation hasn\'t run yet today, OR')
            self.stdout.write('  2. No chores are scheduled for today, OR')
            self.stdout.write('  3. All today\'s chores have already been completed/skipped')
            self.stdout.write('')
            self.stdout.write('Try running: python manage.py run_midnight_evaluation')
            return

        # Group by status
        status_counts = {
            ChoreInstance.POOL: 0,
            ChoreInstance.ASSIGNED: 0,
            ChoreInstance.COMPLETED: 0,
            ChoreInstance.SKIPPED: 0,
        }

        self.stdout.write(f"Found {instances.count()} chore instances for today:\n")

        for instance in instances:
            status_counts[instance.status] += 1

            # Color based on status
            if instance.status == ChoreInstance.POOL:
                status_color = self.style.SUCCESS
                status_text = "POOL"
            elif instance.status == ChoreInstance.ASSIGNED:
                status_color = self.style.WARNING
                status_text = "ASSIGNED"
            elif instance.status == ChoreInstance.COMPLETED:
                status_color = self.style.SUCCESS
                status_text = "COMPLETED"
            elif instance.status == ChoreInstance.SKIPPED:
                status_color = self.style.ERROR
                status_text = "SKIPPED"
            else:
                status_color = self.style.NOTICE
                status_text = instance.status

            # Build status line
            line = f"  [{status_color(status_text)}] {instance.chore.name}"

            if instance.assigned_to:
                line += f" -> {instance.assigned_to.get_display_name()}"

            if instance.is_overdue:
                line += self.style.ERROR(" (OVERDUE)")

            self.stdout.write(line)

            # Show distribution time if in pool
            if instance.status == ChoreInstance.POOL:
                self.stdout.write(f"      Distribution at: {instance.distribution_at.strftime('%H:%M')}")

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Summary:'))
        self.stdout.write(f"  Pool: {status_counts[ChoreInstance.POOL]}")
        self.stdout.write(f"  Assigned: {status_counts[ChoreInstance.ASSIGNED]}")
        self.stdout.write(f"  Completed: {status_counts[ChoreInstance.COMPLETED]}")
        self.stdout.write(f"  Skipped: {status_counts[ChoreInstance.SKIPPED]}")
        self.stdout.write('')

        # Show distribution info
        current_time = now.time()
        undistributed = instances.filter(
            status=ChoreInstance.POOL,
            distribution_at__gt=now
        ).count()

        if undistributed > 0:
            self.stdout.write(self.style.WARNING(
                f"WARNING: {undistributed} chores are in POOL waiting for distribution time"
            ))
            self.stdout.write('')
            self.stdout.write('These chores will be automatically assigned when their distribution time arrives.')
            self.stdout.write(f'Current time: {now.strftime("%H:%M")}')
