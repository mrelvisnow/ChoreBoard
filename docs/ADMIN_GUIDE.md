# ChoreBoard Admin Guide

## Table of Contents
1. [Admin Panel Overview](#admin-panel-overview)
2. [User Management](#user-management)
3. [Chore Management](#chore-management)
4. [Weekly Reset & Points](#weekly-reset--points)
5. [Undo Operations](#undo-operations)
6. [Backups & Recovery](#backups--recovery)
7. [System Settings](#system-settings)
   - [Core Settings](#core-settings)
   - [Site Settings](#site-settings)
   - [Webhook Notifications](#webhook-notifications)
   - [Environment Variables](#environment-variables)
8. [Troubleshooting](#troubleshooting)

---

## Admin Panel Overview

### Accessing Admin Features

**Django Admin Interface:**
- URL: `/admin`
- Full CRUD access to all models
- Bulk actions and filtering
- Direct database access

**ChoreBoard Admin Panel:**
- URL: `/board/admin/`
- User-friendly interfaces for common tasks
- Chore management with visual editors
- Quick access to undo, backups, and settings

### Admin Permissions

To perform admin tasks, your user account must have:
- `is_staff = True` **OR**
- `is_superuser = True`

Set these flags in the Django admin user editor.

---

## User Management

### Creating Users

**Via Django Admin** (`/admin/users/user/`):
1. Click "Add User+"
2. Fill in required fields:
   - Username (unique, lowercase recommended)
   - Display name (how they appear on the board)
   - Email (optional)
3. Set eligibility flags:
   - **Can Be Assigned**: Can receive assigned chores
   - **Eligible for Points**: Earns points for completions
4. Save

**Via Setup Command**:
```bash
python manage.py setup
```
Use this for the initial admin user only.

### User Flags Explained

**Can Be Assigned:**
- If **True**: User appears in auto-assignment pool
- If **False**: User never gets auto-assigned chores (but can still claim from pool)
- Use case: Parents who want to participate but not receive assigned chores

**Eligible for Points:**
- If **True**: User earns points for chore completions
- If **False**: User can still complete chores but gets zero points
- Use case: Guest users or adults who don't want points tracking

**Is Active:**
- If **True**: User can log in and appears on board
- If **False**: Soft deleted (not visible, no assignments)
- Use case: Family member moved out, but keep historical data

### Editing Users

1. Navigate to Django Admin → Users
2. Click on username to edit
3. Update any fields
4. Click "Save"

**Important Fields:**
- **Weekly Points**: Auto-calculated, reset every Sunday midnight
- **All-Time Points**: Auto-calculated from PointsLedger
- **Claims Today**: Auto-reset at midnight
- **Streak**: Perfect week streak counter (managed in ChoreBoard Admin)

### Deleting Users

**Never hard delete users!** Use soft delete instead:
1. Edit user in Django admin
2. Uncheck "Is Active"
3. Save

This preserves all historical data while removing them from active use.

---

## Chore Management

### Creating Chores

**Via ChoreBoard Admin** (`/board/admin/chores/`):
1. Click "Create New Chore"
2. Fill in chore details:
   - **Name**: What needs to be done
   - **Description**: Optional details
   - **Points**: How many points awarded (can be customized to "stars", "coins", etc.)
3. Choose **Schedule Type**:
   - **Daily**: Every day
   - **Weekly**: Specific days of week
   - **Every N Days**: Every X days
   - **Cron**: Advanced cron expression
   - **RRULE**: Recurring rule (visual editor provided)
4. Set additional options:
   - **Undesirable**: Enable rotation (oldest completer gets it next)
   - **Difficult**: Prevent double assignment same day
   - **Fixed User**: Assign to specific person always
   - **Max Active**: How many instances can exist at once
5. Click "Save Chore"

**Chore Templates:**
- Save frequently-used configurations as templates
- Load template when creating new chore
- All fields except name are copied

### Schedule Types

**Daily:**
- Creates instance every day at midnight
- Simple and straightforward
- Example: "Make your bed"

**Weekly:**
- Select specific days: Mon, Tue, Wed, Thu, Fri, Sat, Sun
- Instance created on those days only
- Example: "Take out trash" (Tuesday & Friday)

**Every N Days:**
- Specify interval (e.g., every 3 days)
- Creates instance every N days from start
- Example: "Water plants" (every 3 days)

**CRON:**
- Advanced scheduling using cron syntax (5-field format)
- Full control over timing with minute, hour, day, month, weekday
- **Format**: `minute hour day_of_month month day_of_week`
- **Supports**:
  - Wildcards (`*`): Any value
  - Lists (`,`): Multiple values (e.g., `1,3,5`)
  - Ranges (`-`): Range of values (e.g., `1-5`)
  - Steps (`/`): Step values (e.g., `*/2` = every 2)
  - **Nth occurrence (`#`)**: Specific week of month (e.g., `6#1` = first Saturday)

**CRON Examples:**
```
0 0 * * *           # Daily at midnight
0 0 * * 1-5         # Weekdays (Mon-Fri) at midnight
0 0 1 * *           # First day of each month
0 0 15 * *          # 15th of each month
0 0 * * 0           # Sundays at midnight
0 0 * * 1,3,5       # Monday, Wednesday, Friday
0 0 1,15 * *        # 1st and 15th of each month
0 0 */2 * *         # Every 2 days
0 0 * * 6#1,6#3     # 1st and 3rd Saturday of each month
0 0 * * 5#-1        # Last Friday of each month
0 0 L * *           # Last day of each month
```

**CRON Weekday Reference:**
- 0 or 7 = Sunday
- 1 = Monday
- 2 = Tuesday
- 3 = Wednesday
- 4 = Thursday
- 5 = Friday
- 6 = Saturday

**RRULE:**
- Visual editor for complex recurring patterns (JSON format)
- More human-readable than CRON for complex rules
- Select frequency, interval, specific days
- **Supported Parameters**:
  - `freq`: DAILY, WEEKLY, MONTHLY, YEARLY (required)
  - `interval`: How often to repeat (default: 1)
  - `dtstart`: Start date (default: chore creation date)
  - `until`: End date (optional)
  - `count`: Number of occurrences (optional)
  - `byweekday`: Specific weekdays [0-6] where 0=Monday (optional)
  - `bymonthday`: Specific days of month (optional)
  - `bymonth`: Specific months (optional)
  - `bysetpos`: Nth occurrence (e.g., 1st, 3rd)

**RRULE Examples:**
```json
{
  "freq": "DAILY",
  "interval": 1
}
// Daily

{
  "freq": "WEEKLY",
  "interval": 1,
  "byweekday": [0, 2, 4]
}
// Weekly on Monday, Wednesday, Friday

{
  "freq": "MONTHLY",
  "interval": 1,
  "bymonthday": [1, 15]
}
// 1st and 15th of each month

{
  "freq": "MONTHLY",
  "byweekday": [5],
  "bysetpos": [1, 3]
}
// 1st and 3rd Saturday of each month

{
  "freq": "WEEKLY",
  "byweekday": [0, 1, 2, 3, 4]
}
// Weekdays only (Mon-Fri)

{
  "freq": "DAILY",
  "interval": 2,
  "dtstart": "2025-01-01"
}
// Every 2 days starting Jan 1, 2025

{
  "freq": "WEEKLY",
  "interval": 2,
  "byweekday": [0, 3]
}
// Every 2 weeks on Monday and Thursday

{
  "freq": "MONTHLY",
  "byweekday": [5],
  "bysetpos": [-1]
}
// Last Friday of each month
```

**RRULE Weekday Reference:**
- 0 = Monday
- 1 = Tuesday
- 2 = Wednesday
- 3 = Thursday
- 4 = Friday
- 5 = Saturday
- 6 = Sunday

**Choosing Between CRON and RRULE:**

Use **CRON** when:
- You're familiar with cron syntax
- Need Nth weekday syntax (`6#1,6#3`)
- Want compact, one-line expressions
- Migrating from existing cron-based systems

Use **RRULE** when:
- You prefer JSON/structured format
- Need complex recurring patterns
- Want more readable configuration
- Need features like `until` dates and occurrence counts

### Chore Rotation (Undesirable Flag)

For chores nobody wants to do:
1. Enable "Undesirable" checkbox
2. System tracks last completion date per user
3. At 5:30 PM distribution, assigns to user who completed longest ago
4. If someone completed yesterday, they're skipped (purple state)
5. Rotation is fair and automatic

### Difficult Chores

Enable "Difficult" flag to prevent assigning two difficult chores to same user on same day:
1. Mark chore as "Difficult"
2. System checks existing assignments during distribution
3. If user already has a difficult chore today, skip them
4. Prevents overburdening one person

### Dependencies (Parent-Child Chores)

**Creating Dependencies**:
1. Edit a chore (the "parent")
2. Scroll to "Child Chores" section
3. Click "Add Child Dependency"
4. Select child chore from dropdown
5. Set offset hours (delay before spawning)
6. Save

**How It Works**:
- When parent chore completes, child spawns after offset hours
- Child is auto-assigned to whoever completed parent
- Example: "Clean kitchen" (parent) → "Mop floor" (child, +1 hour)

**Important**:
- Circular dependencies are prevented (validation error)
- Child inherits parent's due date + offset
- Child gets parent's completer automatically assigned

### Editing Chores

1. Navigate to ChoreBoard Admin → Chores
2. Click "Edit" on the chore
3. Make changes
4. **Note**: Changes only affect NEW instances created after edit
5. Existing chore instances keep their original snapshot values
6. Save

### Deactivating Chores

**Soft Delete** (recommended):
1. Edit chore in Django Admin
2. Uncheck "Is Active"
3. Save
4. No new instances created
5. Existing instances remain until completed

**Hard Delete** (not recommended):
- Deletes chore and all instances
- Loses historical data
- Use only for test/mistake chores

### Force Assigning Pool Chores

If a pool chore isn't being claimed:
1. Navigate to ChoreBoard Admin → Force Assign
2. Find the chore in the list
3. Select a user from dropdown
4. Click "Assign"
5. Chore is immediately assigned to that user

---

## Weekly Reset & Points

### How Weekly Reset Works

**Automatic Process (Every Sunday Midnight):**
1. System creates WeeklySnapshot for each user
2. Records weekly points earned
3. Marks users who had "perfect week" (all chores on time)
4. Increments perfect week streaks
5. Resets weekly points counter to zero

**Weekly Snapshot Fields:**
- Week ending date
- Points earned that week
- Whether it was a perfect week
- Cash value (points × conversion rate)

### Viewing Weekly Snapshots

Django Admin → Weekly Snapshots
- Filter by user
- Filter by date range
- See perfect week indicators
- View points and cash conversion

### Perfect Week Streaks

**What is it?**
- User completes ALL assigned chores ON TIME for entire week
- Week = Sunday midnight to Sunday midnight
- Tracked in user's Streak model

**Managing Streaks** (`/board/admin/streaks/`):
1. View all users' streaks
2. **Increment**: Add 1 to current streak (manual adjustment)
3. **Reset**: Set streak back to 0 (with confirmation)
4. Longest streak auto-updates when current exceeds it

**Use Cases:**
- Manually reward exceptional week
- Fix incorrect streak calculation
- Reset after user requests

### Points Conversion

**Setting Conversion Rate** (Django Admin → Settings):
1. Navigate to `/admin/core/settings/`
2. Edit "Points to Dollar Rate"
3. Default: 0.01 (100 points = $1.00)
4. Examples:
   - 0.01 = 100 points = $1
   - 0.05 = 20 points = $1
   - 0.10 = 10 points = $1
5. Save

**Paying Users:**
- Weekly snapshots show cash value
- Use this to calculate weekly allowances
- Export snapshot data if needed
- Payment method is up to you (cash, bank transfer, etc.)

### Manual Points Adjustment

If you need to adjust points manually:

**Via PointsLedger** (Django Admin):
1. Navigate to `/admin/chores/pointsledger/`
2. Click "Add Points Ledger+"
3. Set:
   - User
   - Points amount (positive or negative)
   - Reason: "MANUAL" or "ADJUSTMENT"
   - Description (explain why)
4. Save
5. User's all-time and weekly points update automatically

**Via User Edit:**
- Don't manually edit user.weekly_points or user.all_time_points
- These are auto-calculated from PointsLedger
- Always use PointsLedger for adjustments

---

## Undo Operations

### Undoing Chore Completions

**Via ChoreBoard Admin** (`/board/admin/undo/`):
1. Navigate to Undo Completions page
2. View list of recent completions (last 24 hours)
3. Find the completion to undo
4. Click "Undo"
5. Confirm the action

**What Gets Undone:**
- ChoreInstance restored to previous state (ASSIGNED or POOL)
- Points removed from all participants
- PointsLedger entries marked as undone
- CompletionShares reversed
- Completion marked as undone (not deleted)

**Time Window:**
- Default: 24 hours after completion
- Configurable in Settings → Undo Time Limit
- After window expires, completion cannot be undone
- This prevents accidental undos of old data

**Via Django Admin:**
1. Navigate to `/admin/chores/completion/`
2. Select completion(s) to undo
3. Actions dropdown → "Undo selected completions"
4. Confirm

**Important:**
- Already-undone completions won't appear in list again
- Undoing is logged in ActionLog for audit trail
- Users' weekly/all-time points update immediately

### Undoing Weekly Reset

**Time Window**: 24 hours after reset (Sunday midnight)

**How to Undo:**
Currently not supported in UI. Contact developer for database-level undo.

**Prevention:**
- Test your setup before going live
- Verify conversion rates before reset
- Backup database before Sundays (see Backups section)

---

## Backups & Recovery

### Viewing Backups

**ChoreBoard Admin** (`/board/admin/backups/`):
- Lists all backups with metadata
- Shows filename, size, date
- Indicates manual vs automatic
- Displays total storage usage

### Creating Manual Backups

**Via ChoreBoard Admin:**
1. Navigate to Backups page
2. Click "Create Manual Backup"
3. Optionally add notes (e.g., "Before weekly reset")
4. Click "Create"
5. Backup created instantly

**Via Command Line:**
```bash
python manage.py create_backup
```

Or with notes:
```bash
python manage.py create_backup --notes "Before testing new feature"
```

### Automatic Backups

**Setup** (see task 8.7 in Implementation Tasks):

Add to crontab (Linux/Mac):
```bash
0 2 * * * cd /path/to/ChoreBoard2 && /path/to/.venv/bin/python manage.py create_backup --automatic
```

Or Task Scheduler (Windows):
- Program: `C:\path\to\.venv\Scripts\python.exe`
- Arguments: `C:\path\to\manage.py create_backup --automatic`
- Schedule: Daily at 2:00 AM

**Automatic Retention:**
- Backups older than 7 days are auto-deleted
- Keeps most recent 7 days only
- Saves disk space
- Configurable in code if needed

### Restoring from Backup

**Via Docker:**
```bash
# Stop container
docker-compose down

# Copy backup to container
docker cp ./backup_20251207.sqlite3 choreboard:/app/data/db.sqlite3

# Restart container
docker-compose up -d
```

**Via Local:**
```bash
# Stop Django server

# Copy backup file
cp backups/backup_20251207.sqlite3 db.sqlite3

# Restart Django server
python manage.py runserver
```

**Important:**
- Always backup current database before restoring!
- Restoration overwrites all data since backup
- Verify backup date before restoring
- Test in development first if possible

### Backup Best Practices

1. **Daily automatic backups**: Set up cron/scheduler
2. **Manual backup before risky operations**: Weekly reset, major changes
3. **Keep external copies**: Copy backups to external drive/cloud monthly
4. **Test restores**: Verify backups can actually restore (test environment)
5. **Document recovery procedure**: Write steps specific to your setup

---

## System Settings

### Core Settings

Django Admin → Settings (`/admin/core/settings/`):

**Points to Dollar Rate:**
- Conversion rate for weekly payout
- Default: 0.01 (100 points = $1)

**Max Claims Per Day:**
- How many pool chores each user can claim daily
- Default: 1
- Resets at midnight

**Undo Time Limit:**
- Hours after completion when undo is allowed
- Default: 24

**Weekly Reset Undo:**
- Hours after Sunday reset when undo is allowed
- Default: 24

**Home Assistant Webhook:**
- Optional webhook URL for notifications
- Format: `https://your-ha-instance/api/webhook/choreboard`
- Leave blank to disable

### Site Settings

ChoreBoard Admin → Site Settings (`/admin/board/sitesettings/`):

**Points Label:**
- Full form used throughout site
- Default: "points"
- Examples: "stars", "coins", "experience"

**Points Label Short:**
- Abbreviated form for compact displays
- Default: "pts"
- Examples: "★", "$", "xp"

**Effect:**
- Updates immediately across all pages
- Customize for your family's preference
- Makes the system more engaging for kids

### Webhook Notifications

ChoreBoard can send webhook notifications to Home Assistant or other automation systems when key events occur.

**Configuring Webhooks** (Django Admin → Settings):

1. **Enable Notifications**: Check the "Enable notifications" checkbox
2. **Webhook URL**: Enter your webhook endpoint URL
   - Home Assistant format: `http://your-ha-instance:8123/api/webhook/choreboard`
   - Generic webhook format: Any HTTPS/HTTP endpoint that accepts POST requests

**Events That Trigger Webhooks:**

| Event Type | When It Fires | Payload Includes |
|------------|---------------|------------------|
| `chore_completed` | User completes a chore | Chore name, completer, points earned, helpers, late status |
| `chore_claimed` | User claims a pool chore | Chore name, claimer, points value, due date |
| `chore_overdue` | Midnight evaluation marks chore overdue | Chore name, assigned user, points value, due date |
| `chore_assigned` | System auto-assigns a chore | Chore name, assigned user, assignment reason |
| `perfect_week_achieved` | User completes perfect week | User, streak count, weekly points |
| `weekly_reset` | Sunday midnight reset | Total users, total points |
| `test_notification` | Admin tests webhook config | Test message |

**Payload Structure:**

All webhooks follow this format:
```json
{
  "event_type": "chore_completed",
  "data": {
    "chore_name": "Take out trash",
    "completed_by": "John Doe",
    "username": "john",
    "points_earned": 10.0,
    "was_late": false,
    "due_at": "2025-12-07T23:59:59Z",
    "helpers": ["Jane Doe"],
    "points_split": "2 ways"
  }
}
```

**Home Assistant Integration Example:**

1. Create webhook automation in Home Assistant:
```yaml
automation:
  - alias: "ChoreBoard: Chore Completed"
    trigger:
      platform: webhook
      webhook_id: "choreboard"
    condition:
      - condition: template
        value_template: "{{ trigger.json.event_type == 'chore_completed' }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Chore Completed!"
          message: "{{ trigger.json.data.completed_by }} completed {{ trigger.json.data.chore_name }} for {{ trigger.json.data.points_earned }} points"
```

2. Get your webhook URL:
   - Go to Settings → Automations & Scenes → (Your automation) → Trigger
   - Copy the webhook URL (format: `http://homeassistant.local:8123/api/webhook/choreboard`)

3. Enter the URL in ChoreBoard Settings

4. Test the webhook (see Testing below)

**Testing Webhooks:**

Via Django Shell:
```python
python manage.py shell
>>> from core.notifications import NotificationService
>>> result = NotificationService.send_test_notification()
>>> print(result)
{'success': True, 'message': 'Test notification sent successfully'}
```

Via Admin Interface (future feature):
- Navigate to Settings page
- Click "Test Webhook" button
- Check Home Assistant for received notification

**Webhook Timeout & Retries:**

- Timeout: 5 seconds per request
- No automatic retries (fire-and-forget)
- Failed webhooks are logged but don't block operations
- Check Django logs for webhook errors

**Troubleshooting Webhooks:**

| Problem | Solution |
|---------|----------|
| Webhooks not sending | Check "Enable notifications" is checked and URL is configured |
| 404 errors | Verify webhook URL is correct (include `/api/webhook/` path) |
| Timeout errors | Ensure webhook endpoint responds within 5 seconds |
| SSL errors | Use HTTP for local network or configure valid SSL certificate |
| Not receiving in HA | Check Home Assistant logs, verify webhook_id matches |

**Security Considerations:**

- Use HTTPS for production deployments
- Keep webhook URL private (contains authentication)
- Home Assistant webhook URLs are public but require network access
- Consider firewall rules to restrict webhook endpoint access
- No sensitive data (passwords) is sent in webhooks

**Disabling Webhooks:**

1. Navigate to Django Admin → Settings
2. Uncheck "Enable notifications"
3. Click "Save"

OR

1. Clear the "Home assistant webhook url" field
2. Click "Save"

### Environment Variables

Edit `.env` file:

**SECRET_KEY:**
- Django security key
- Must be kept secret!
- Generate new for production: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

**DEBUG:**
- Set to `False` in production
- Set to `True` only in development

**ALLOWED_HOSTS:**
- Comma-separated list of valid hosts
- Example: `localhost,127.0.0.1,choreboard.example.com`

**DATABASE_PATH:**
- Path to SQLite database file
- Default: `./db.sqlite3`
- For Docker: `/app/data/db.sqlite3`

**ALLOW_IFRAME_EMBEDDING:**
- Allow ChoreBoard to be embedded in iframes
- Set to `True` to allow embedding (default)
- Set to `False` to block iframe embedding for security
- Use case: Enable for kiosk displays, dashboards, or embedded views
- **Security Note**: Enabling this disables clickjacking protection. Only enable if you trust the sites embedding ChoreBoard.

**TZ:**
- Timezone for scheduled jobs
- Default: `America/Chicago`
- Format: IANA timezone (e.g., `America/New_York`, `Europe/London`)

---

## Troubleshooting

### Chores Not Appearing

**Symptoms**: New chore created but doesn't show on board

**Causes & Solutions:**
1. **Not yet midnight**: Wait until midnight for first instance
   - **OR** use immediate creation (already implemented via signals)
2. **Chore inactive**: Check Django Admin → Chore → is_active=True
3. **Schedule misconfigured**: Verify schedule type fields
4. **Date in past**: Check start date is not in future

**Manual Fix**:
Run midnight evaluation manually:
```bash
python manage.py run_midnight_evaluation
```

### Auto-Assignment Not Working

**Symptoms**: Pool chores not being assigned at 5:30 PM

**Causes & Solutions:**
1. **Scheduler not running**: Check server logs for APScheduler
2. **No eligible users**: All users have `can_be_assigned=False`
3. **Rotation block**: All eligible users completed yesterday (purple state)
4. **Difficult chore conflict**: All users already have difficult chore today

**Manual Fix**:
Run distribution check manually:
```bash
python manage.py run_distribution_check
```

### Points Not Updating

**Symptoms**: User completed chore but points don't show

**Causes & Solutions:**
1. **User not eligible**: Check `eligible_for_points=True`
2. **Undo performed**: Completion was undone by admin
3. **Database issue**: Check PointsLedger for transaction

**Manual Fix**:
Recalculate points from PointsLedger:
```python
# In Django shell
from users.models import User
user = User.objects.get(username='john')
user.all_time_points = user.calculate_all_time_points()
user.weekly_points = user.calculate_weekly_points()
user.save()
```

### Perfect Week Streak Not Incrementing

**Symptoms**: User completed all chores on time but streak didn't go up

**Causes & Solutions:**
1. **One chore was late**: Check completion timestamps vs due dates
2. **Streak reset manually**: Check ActionLog for admin resets
3. **Sunday reset failed**: Check evaluation logs for errors

**Manual Fix**:
Manually increment via ChoreBoard Admin → Streaks → Increment button

### Database Locked Errors

**Symptoms**: `database is locked` error during claims/completions

**Causes & Solutions:**
1. **Concurrent access**: Multiple users claiming/completing simultaneously
2. **Long transaction**: A query is taking too long
3. **Backup running**: Backup process has database lock

**Fixes:**
- This should be rare due to `select_for_update()` locking
- Retry the operation
- Check for stuck background jobs
- Restart Django server if persistent

### Scheduled Jobs Not Running

**Symptoms**: Midnight evaluation or weekly reset didn't happen

**Check APScheduler Status**:
```bash
# In Django shell
from apscheduler.schedulers.background import BackgroundScheduler
# Check logs in console/stdout
```

**Or via Health Check**:
Navigate to `/board/health/` and check `apscheduler_running` status.

**Solutions:**
1. Restart Django server
2. Check timezone settings (TZ environment variable)
3. Manually trigger jobs for now:
   ```bash
   python manage.py run_midnight_evaluation
   python manage.py run_weekly_snapshot
   ```

---

## Logs and Monitoring

### Action Log

Django Admin → Action Logs

**Records:**
- All admin actions (force assign, undo, etc.)
- User actions (claim, complete)
- System actions (auto-assign, reset)

**Fields:**
- Actor (who did it)
- Action type
- Affected model and ID
- Timestamp
- Additional details (JSON)

**Use Cases:**
- Audit trail for admin actions
- Troubleshooting user disputes
- Understanding system behavior

### Evaluation Log

Django Admin → Evaluation Logs

**Records:**
- Midnight evaluation runs
- Distribution check runs
- Weekly snapshot runs

**Fields:**
- Job type
- Start and end time
- Execution duration
- Success/failure status
- Error messages (if failed)

**Use Cases:**
- Verify scheduled jobs are running
- Identify performance issues
- Debug job failures

### Health Check

Navigate to `/board/health/` (or via API):
```bash
curl http://localhost:8000/health/
```

**Returns:**
```json
{
  "status": "healthy",
  "timestamp": "2025-12-07T12:00:00Z",
  "database": "connected",
  "apscheduler_running": true,
  "debug_mode": false,
  "allowed_hosts": ["localhost", "127.0.0.1"]
}
```

**Use Cases:**
- External monitoring tools
- Quick system status check
- Verify database connectivity
- Check if scheduled jobs are active

---

## Best Practices

### Weekly Admin Routine

**Monday Morning:**
1. Check EvaluationLog for Sunday midnight reset
2. Verify all users got weekly snapshots
3. Review perfect week streaks
4. Calculate and pay allowances

**Mid-Week:**
1. Monitor overdue chores (red status)
2. Reassign if needed
3. Check for purple blocked chores

**Friday Evening:**
1. Remind users to complete weekend chores
2. Preview who's on track for perfect week
3. Create backup before weekend

**Before Bed:**
1. Quick check of the board
2. Verify no critical errors in logs

### Managing Difficult Users

**User complains chore was too hard:**
1. Review points value - adjust if needed
2. Mark as "difficult" to prevent double assignment
3. Or assign helpers next time

**User never completes chores:**
1. Review their assignments - too many?
2. Adjust auto-assignment eligibility
3. Have a conversation (system can't fix motivation!)

**User disputes points:**
1. Check ActionLog for what happened
2. Review PointsLedger transactions
3. Manually adjust if error confirmed
4. Document in ledger description

### Family Meetings

**Monthly:**
- Review points system fairness
- Adjust difficult/undesirable flags as needed
- Get feedback on chore rotation
- Celebrate perfect week achievements

**Quarterly:**
- Review and adjust points values
- Add new chores for new responsibilities
- Archive/deactivate outgrown chores
- Consider conversion rate adjustment

---

## Advanced Topics

### Custom Chore Types

If you need specialized chore logic:
1. Create new Chore with specific flags
2. Use dependencies for multi-step chores
3. Use RRULE for complex schedules
4. Consider forking and modifying code for extreme customization

### API Integration

ChoreBoard has a full REST API:
- Home automation integration
- Custom dashboards
- Mobile apps
- Notification systems

See README.md → API Documentation section.

### Database Migrations

When updating ChoreBoard:
```bash
# Pull latest code
git pull

# Run migrations
python manage.py migrate

# Restart server
```

Always backup before updating!

---

## Getting Help

**Check Logs First:**
1. Django server console output
2. Django Admin → EvaluationLog
3. Django Admin → ActionLog

**Review Documentation:**
- This guide (ADMIN_GUIDE.md)
- User guide (USER_GUIDE.md)
- README.md
- Planning docs in `/planning`

**GitHub Issues:**
- Check existing issues
- Submit new issue with:
  - Clear description
  - Steps to reproduce
  - Error messages from logs
  - ChoreBoard version

**Community:**
- Family members may have questions
- Create your own FAQ
- Document your specific setup/rules

---

**Happy Administrating! 🎯**
