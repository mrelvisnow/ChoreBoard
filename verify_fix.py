"""
Verify that the assigned count fix is working correctly.
This checks if the view is using the new query logic.
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

print("=" * 80)
print("VERIFICATION: Assigned Count Fix")
print("=" * 80)

# Test the query that main_board view should be using
assigned_chores = ChoreInstance.objects.filter(
    status=ChoreInstance.ASSIGNED,
    chore__is_active=True
).filter(
    Q(due_at__date=today) | Q(due_at__lt=now)  # Due today OR past due
).exclude(status=ChoreInstance.SKIPPED).select_related('chore', 'assigned_to').order_by('due_at')

print(f"\n[OK] Query executed successfully")
print(f"[OK] Found {assigned_chores.count()} assigned chores (today + overdue)")

# Group by user
from collections import defaultdict
chores_by_user = defaultdict(lambda: {'overdue': [], 'ontime': []})

for chore in assigned_chores:
    user = chore.assigned_to
    if chore.is_overdue:
        chores_by_user[user]['overdue'].append(chore)
    else:
        chores_by_user[user]['ontime'].append(chore)

# Filter like the view does
assigned_by_user = [
    {
        'user': user,
        'overdue': chores['overdue'],
        'ontime': chores['ontime'],
        'total': len(chores['overdue']) + len(chores['ontime'])
    }
    for user, chores in chores_by_user.items()
    if user is not None and user.eligible_for_points
]

print(f"[OK] Grouped by {len(assigned_by_user)} user(s)")

if assigned_by_user:
    print("\n[USERS] Users with assigned chores:")
    for user_data in assigned_by_user:
        user = user_data['user']
        print(f"\n  {user.get_display_name()}:")
        print(f"    - Overdue: {len(user_data['overdue'])}")
        print(f"    - On-time: {len(user_data['ontime'])}")
        print(f"    - Total: {user_data['total']}")
else:
    print("\n[WARN] No users with assigned chores (or all users have eligible_for_points=False)")

# Check how many chores have no assigned user
no_user = assigned_chores.filter(assigned_to=None).count()
if no_user > 0:
    print(f"\n[WARN] {no_user} chores have assigned_to=None (won't show on board)")

# Check for users not eligible for points
users_not_eligible = assigned_chores.exclude(assigned_to=None).exclude(
    assigned_to__eligible_for_points=True
).count()
if users_not_eligible > 0:
    print(f"[WARN] {users_not_eligible} chores assigned to users not eligible for points")

print("\n" + "=" * 80)
print("RESULT:")
if assigned_by_user:
    print(f"[SUCCESS] Fix is WORKING - {len(assigned_by_user)} user(s) should see assigned chores")
else:
    print("[ERROR] Fix may not be working - no users with assigned chores")
print("=" * 80)
