"""
Management command to preview what midnight evaluation would create.
"""
from django.core.management.base import BaseCommand
from chores.models import Chore, ChoreInstance
from django.utils import timezone
from datetime import timedelta
from core.jobs import should_create_instance_today


class Command(BaseCommand):
    help = 'Preview what chores would be created by midnight evaluation'

    def handle(self, *args, **options):
        now = timezone.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS(f'Midnight Evaluation Preview for {today}'))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write('')

        # Get active chores (excluding child chores)
        from django.db.models import Exists, OuterRef
        from chores.models import ChoreDependency

        has_dependencies = ChoreDependency.objects.filter(chore=OuterRef('pk'))
        active_chores = Chore.objects.filter(
            is_active=True
        ).exclude(
            Exists(has_dependencies)
        ).order_by('name')

        will_create = []
        will_skip = []
        already_exists = []

        for chore in active_chores:
            # Check if instance already exists
            existing = ChoreInstance.objects.filter(
                chore=chore,
                due_at__date=tomorrow
            ).exists()

            if existing:
                already_exists.append(chore)
                continue

            # Check if it should be created
            should_create = should_create_instance_today(chore, today)

            if should_create:
                will_create.append(chore)
            else:
                will_skip.append(chore)

        # Display results
        self.stdout.write(self.style.SUCCESS(f'✓ WILL CREATE ({len(will_create)} chores):'))
        if will_create:
            for chore in will_create:
                status = "POOL" if chore.is_pool else f"ASSIGNED to {chore.assigned_to.username if chore.assigned_to else 'nobody'}"
                self.stdout.write(f'  • {chore.name} ({status})')
        else:
            self.stdout.write('    (none)')
        self.stdout.write('')

        if already_exists:
            self.stdout.write(self.style.WARNING(f'⚠ ALREADY EXISTS ({len(already_exists)} chores):'))
            for chore in already_exists:
                self.stdout.write(f'  • {chore.name}')
            self.stdout.write('')

        self.stdout.write(f'SKIPPED ({len(will_skip)} chores - not scheduled for today):')
        if len(will_skip) <= 10:
            for chore in will_skip:
                schedule_info = chore.get_schedule_display() if hasattr(chore, 'get_schedule_display') else chore.schedule_type
                self.stdout.write(f'  • {chore.name} ({schedule_info})')
        else:
            self.stdout.write(f'    (showing first 10 of {len(will_skip)})')
            for chore in will_skip[:10]:
                schedule_info = chore.get_schedule_display() if hasattr(chore, 'get_schedule_display') else chore.schedule_type
                self.stdout.write(f'  • {chore.name} ({schedule_info})')
        self.stdout.write('')

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(f'Total active chores: {active_chores.count()}')
        self.stdout.write(f'Will create: {len(will_create)}')
        self.stdout.write(f'Already exist: {len(already_exists)}')
        self.stdout.write(f'Not scheduled today: {len(will_skip)}')
