"""
Management command to check recent midnight evaluation logs.
"""
from django.core.management.base import BaseCommand
from core.models import EvaluationLog
from django.utils import timezone


class Command(BaseCommand):
    help = 'Check recent midnight evaluation logs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=10,
            help='Number of recent evaluations to show (default: 10)'
        )

    def handle(self, *args, **options):
        count = options['count']

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS(f'Recent Midnight Evaluations (last {count})'))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write('')

        logs = EvaluationLog.objects.order_by('-started_at')[:count]

        if not logs.exists():
            self.stdout.write(self.style.WARNING('No evaluation logs found.'))
            self.stdout.write('')
            self.stdout.write('This means midnight evaluation has never run.')
            self.stdout.write('Try running: python manage.py run_midnight_evaluation')
            return

        for i, log in enumerate(logs, 1):
            now = timezone.now()
            time_ago = now - log.started_at
            hours_ago = time_ago.total_seconds() / 3600

            if hours_ago < 1:
                time_str = f"{int(time_ago.total_seconds() / 60)} minutes ago"
            elif hours_ago < 24:
                time_str = f"{int(hours_ago)} hours ago"
            else:
                time_str = f"{int(hours_ago / 24)} days ago"

            # Color based on success
            if log.success:
                status_style = self.style.SUCCESS
                status = "✓ SUCCESS"
            else:
                status_style = self.style.ERROR
                status = "✗ FAILED"

            self.stdout.write(f"{i}. {status_style(status)} - {time_str}")
            self.stdout.write(f"   Started: {log.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
            self.stdout.write(f"   Chores created: {log.chores_created}")
            self.stdout.write(f"   Chores marked overdue: {log.chores_marked_overdue}")
            self.stdout.write(f"   Execution time: {log.execution_time_seconds}s")

            if log.errors_count > 0:
                self.stdout.write(self.style.WARNING(f"   Errors: {log.errors_count}"))
                if log.error_details:
                    for line in log.error_details.split('\n')[:3]:  # Show first 3 error lines
                        self.stdout.write(self.style.ERROR(f"     {line}"))

            self.stdout.write('')

        # Show scheduler status
        from core.scheduler import scheduler
        self.stdout.write(self.style.SUCCESS('Scheduler Status:'))
        if scheduler.running:
            self.stdout.write(self.style.SUCCESS('  ✓ Scheduler is running'))
            jobs = scheduler.get_jobs()
            for job in jobs:
                if job.id == 'midnight_evaluation':
                    self.stdout.write(f"  Next run: {job.next_run_time}")
        else:
            self.stdout.write(self.style.ERROR('  ✗ Scheduler is NOT running'))
