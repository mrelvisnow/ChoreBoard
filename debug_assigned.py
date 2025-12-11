"""
Quick debug script to check assigned chores in database
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ChoreBoard.settings')
django.setup()

from django.utils import timezone
from django.db.models import Q
from chores.models import ChoreInstance

now = timezone.now()
today = now.date()

print(f"Current time: {now}")
print(f"Today's date: {today}")
print(f"Timezone: {timezone.get_current_timezone()}")
print("=" * 80)

# Check for assigned chores using OLD logic (only today)
old_query = ChoreInstance.objects.filter(
    status=ChoreInstance.ASSIGNED,
    due_at__date=today,
    chore__is_active=True
).exclude(status=ChoreInstance.SKIPPED).select_related('chore', 'assigned_to')

print(f"\nOLD QUERY (due_at__date=today only): {old_query.count()} chores")
for chore in old_query:
    print(f"  - {chore.chore.name} assigned to {chore.assigned_to}, due at {chore.due_at}, overdue={chore.is_overdue}")

# Check for assigned chores using NEW logic (today OR overdue)
new_query = ChoreInstance.objects.filter(
    status=ChoreInstance.ASSIGNED,
    chore__is_active=True
).filter(
    Q(due_at__date=today) | Q(due_at__lt=now)
).exclude(status=ChoreInstance.SKIPPED).select_related('chore', 'assigned_to')

print(f"\nNEW QUERY (today OR overdue): {new_query.count()} chores")
for chore in new_query:
    print(f"  - {chore.chore.name} assigned to {chore.assigned_to}, due at {chore.due_at}, overdue={chore.is_overdue}")

# Check ALL assigned chores regardless of due date
all_assigned = ChoreInstance.objects.filter(
    status=ChoreInstance.ASSIGNED,
    chore__is_active=True
).select_related('chore', 'assigned_to').order_by('-due_at')

print(f"\nALL ASSIGNED CHORES (no date filter): {all_assigned.count()} chores")
for chore in all_assigned[:10]:  # Show first 10
    print(f"  - {chore.chore.name} assigned to {chore.assigned_to}, due at {chore.due_at}, overdue={chore.is_overdue}")

# Check pool chores
pool_chores = ChoreInstance.objects.filter(
    status=ChoreInstance.POOL,
    due_at__date=today,
    chore__is_active=True
).exclude(status=ChoreInstance.SKIPPED).select_related('chore')

print(f"\nPOOL CHORES (due today): {pool_chores.count()} chores")
for chore in pool_chores:
    print(f"  - {chore.chore.name}, due at {chore.due_at}, overdue={chore.is_overdue}")
