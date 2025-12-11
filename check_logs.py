import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ChoreBoard.settings')
django.setup()

from core.models import EvaluationLog
from chores.models import ChoreInstance
from django.utils import timezone

print("=" * 80)
print("EVALUATION LOGS")
print("=" * 80)

logs = EvaluationLog.objects.order_by('-started_at')[:5]
for i, log in enumerate(logs, 1):
    print(f"\n{i}. {log.started_at}")
    print(f"   Success: {log.success}")
    print(f"   Chores created: {log.chores_created}")
    print(f"   Chores marked overdue: {log.chores_marked_overdue}")
    print(f"   Errors: {log.errors_count}")
    if log.error_details:
        print(f"   Error details: {log.error_details[:200]}")

print("\n" + "=" * 80)
print("CHORE INSTANCES CREATED TODAY")
print("=" * 80)

now = timezone.now()
today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

instances_today = ChoreInstance.objects.filter(
    created_at__gte=today_start
).order_by('-created_at')

print(f"\nFound {instances_today.count()} instances created today (since {today_start})")

for inst in instances_today[:10]:
    print(f"  - {inst.chore.name} ({inst.status}) - created at {inst.created_at}")
