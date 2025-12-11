"""
Management command to diagnose overdue chore marking issues.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from chores.models import ChoreInstance


class Command(BaseCommand):
    help = 'Diagnose overdue chore marking issues'

    def handle(self, *args, **options):
        now = timezone.now()
        self.stdout.write(self.style.SUCCESS(f"Current time: {now}"))
        self.stdout.write(f"Timezone: {timezone.get_current_timezone()}")
        self.stdout.write(f"UTC offset: {now.strftime('%z')}")
        self.stdout.write("")

        # Find instances that should be overdue but aren't
        should_be_overdue = ChoreInstance.objects.filter(
            status__in=[ChoreInstance.POOL, ChoreInstance.ASSIGNED],
            due_at__lt=now,
            is_overdue=False
        ).order_by('due_at')

        self.stdout.write(f"Found {should_be_overdue.count()} instances that should be overdue but aren't:")
        self.stdout.write("")

        if should_be_overdue.count() == 0:
            self.stdout.write(self.style.SUCCESS("✓ No mismatches found!"))
        else:
            for instance in should_be_overdue[:20]:
                self.stdout.write(self.style.WARNING(f"⚠ {instance.chore.name}"))
                self.stdout.write(f"    Status: {instance.status}")
                self.stdout.write(f"    Due at: {instance.due_at}")
                self.stdout.write(f"    Due at (UTC): {instance.due_at.astimezone(timezone.utc)}")
                self.stdout.write(f"    Time past due: {now - instance.due_at}")
                self.stdout.write("")

        # Check recent evaluation logs
        from core.models import EvaluationLog
        recent_logs = EvaluationLog.objects.order_by('-started_at')[:5]

        self.stdout.write("\nRecent midnight evaluation logs:")
        for log in recent_logs:
            status = "✓" if log.success else "✗"
            self.stdout.write(
                f"{status} {log.started_at}: "
                f"created={log.chores_created}, marked_overdue={log.chores_marked_overdue}"
            )
