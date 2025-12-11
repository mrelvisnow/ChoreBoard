"""
URL routing for ChoreBoard frontend.
"""
from django.urls import path
from board import views
from board import views_weekly
from board import views_admin
from board import views_auth
from board import views_arcade
from board import views_piano

app_name = 'board'

urlpatterns = [
    path('', views.main_board, name='main'),
    path('pool/', views.pool_only, name='pool'),
    path('pool/minimal/', views.pool_minimal, name='pool_minimal'),
    path('user/<str:username>/', views.user_board, name='user'),
    path('user/<str:username>/minimal/', views.user_board_minimal, name='user_minimal'),
    path('assigned/minimal/', views.assigned_minimal, name='assigned_minimal'),
    path('users/minimal/', views.users_minimal, name='users_minimal'),
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('leaderboard/minimal/', views.leaderboard_minimal, name='leaderboard_minimal'),
    # Quick Add Task
    path('quick-add-task/', views.quick_add_task, name='quick_add_task'),
    # Health Check
    path('health/', views.health_check, name='health_check'),
    # Real-time Updates API
    path('api/updates/', views.get_updates, name='get_updates'),
    # Auth
    path('login/', views_auth.login_view, name='login'),
    path('logout/', views_auth.logout_view, name='logout'),
    # Actions
    path('action/claim/', views.claim_chore_view, name='claim_action'),
    path('action/complete/', views.complete_chore_view, name='complete_action'),
    path('action/unclaim/', views.unclaim_chore_view, name='unclaim_action'),
    path('action/skip/', views.skip_chore_view, name='skip_action'),
    path('action/reschedule/', views.reschedule_chore_view, name='reschedule_action'),
    # Weekly Reset
    path('weekly-reset/', views_weekly.weekly_reset, name='weekly_reset'),
    path('weekly-reset/convert/', views_weekly.weekly_reset_convert, name='weekly_reset_convert'),
    path('weekly-reset/undo/', views_weekly.weekly_reset_undo, name='weekly_reset_undo'),
    # Admin Panel
    path('admin-panel/', views_admin.admin_dashboard, name='admin_dashboard'),
    path('admin-panel/chores/', views_admin.admin_chores, name='admin_chores'),
    path('admin-panel/chores/list/', views_admin.admin_chores_list, name='admin_chores_list'),
    path('admin-panel/users/', views_admin.admin_users, name='admin_users'),
    path('admin-panel/users/list/', views_admin.admin_users_list, name='admin_users_list'),
    path('admin-panel/settings/', views_admin.admin_settings, name='admin_settings'),
    path('admin-panel/logs/', views_admin.admin_logs, name='admin_logs'),
    path('admin-panel/backups/', views_admin.admin_backups, name='admin_backups'),
    path('admin-panel/backup/create/', views_admin.admin_backup_create, name='admin_backup_create'),
    path('admin-panel/backup/download/<int:backup_id>/', views_admin.admin_backup_download, name='admin_backup_download'),
    path('admin-panel/backup/upload/', views_admin.admin_backup_upload, name='admin_backup_upload'),
    path('admin-panel/backup/restore/', views_admin.admin_backup_restore, name='admin_backup_restore'),
    path('admin-panel/force-assign/', views_admin.admin_force_assign, name='admin_force_assign'),
    path('admin-panel/force-assign/<int:instance_id>/', views_admin.admin_force_assign_action, name='admin_force_assign_action'),
    path('admin-panel/streaks/', views_admin.admin_streaks, name='admin_streaks'),
    path('admin-panel/streak/<int:user_id>/increment/', views_admin.admin_streak_increment, name='admin_streak_increment'),
    path('admin-panel/streak/<int:user_id>/reset/', views_admin.admin_streak_reset, name='admin_streak_reset'),
    path('admin-panel/undo-completions/', views_admin.admin_undo_completions, name='admin_undo_completions'),
    path('admin-panel/undo-completion/<int:completion_id>/', views_admin.admin_undo_completion, name='admin_undo_completion'),
    # Chore CRUD
    path('admin-panel/chore/get/<int:chore_id>/', views_admin.admin_chore_get, name='admin_chore_get'),
    path('admin-panel/chore/create/', views_admin.admin_chore_create, name='admin_chore_create'),
    path('admin-panel/chore/update/<int:chore_id>/', views_admin.admin_chore_update, name='admin_chore_update'),
    path('admin-panel/chore/toggle/<int:chore_id>/', views_admin.admin_chore_toggle_active, name='admin_chore_toggle'),
    # Skip/Unskip Chore
    path('admin-panel/skip-chores/', views_admin.admin_skip_chores, name='admin_skip_chores'),
    path('admin-panel/chore/skip/<int:instance_id>/', views_admin.admin_skip_chore, name='admin_chore_skip'),
    path('admin-panel/chore/unskip/<int:instance_id>/', views_admin.admin_unskip_chore, name='admin_chore_unskip'),
    # Reschedule Chore
    path('admin-panel/reschedule-chores/', views_admin.admin_reschedule_chores, name='admin_reschedule_chores'),
    path('admin-panel/chore/reschedule/<int:chore_id>/', views_admin.admin_reschedule_chore, name='admin_chore_reschedule'),
    path('admin-panel/chore/clear-reschedule/<int:chore_id>/', views_admin.admin_clear_reschedule, name='admin_chore_clear_reschedule'),
    # Chore Templates
    path('admin-panel/templates/list/', views_admin.admin_templates_list, name='admin_templates_list'),
    path('admin-panel/template/get/<int:template_id>/', views_admin.admin_template_get, name='admin_template_get'),
    path('admin-panel/template/save/', views_admin.admin_template_save, name='admin_template_save'),
    path('admin-panel/template/delete/<int:template_id>/', views_admin.admin_template_delete, name='admin_template_delete'),
    # User CRUD
    path('admin-panel/user/get/<int:user_id>/', views_admin.admin_user_get, name='admin_user_get'),
    path('admin-panel/user/create/', views_admin.admin_user_create, name='admin_user_create'),
    path('admin-panel/user/update/<int:user_id>/', views_admin.admin_user_update, name='admin_user_update'),
    path('admin-panel/user/toggle/<int:user_id>/', views_admin.admin_user_toggle_active, name='admin_user_toggle'),
    # Manual Points Adjustment
    path('admin-panel/adjust-points/', views_admin.admin_adjust_points, name='admin_adjust_points'),
    path('admin-panel/adjust-points/submit/', views_admin.admin_adjust_points_submit, name='admin_adjust_points_submit'),
    # Arcade Mode
    path('action/arcade/start/', views_arcade.start_arcade, name='arcade_start'),
    path('action/arcade/stop/', views_arcade.stop_arcade, name='arcade_stop'),
    path('action/arcade/cancel/', views_arcade.cancel_arcade, name='arcade_cancel'),
    path('action/arcade/status/', views_arcade.get_arcade_status, name='arcade_status'),
    path('arcade/submitted/<int:session_id>/', views_arcade.arcade_submitted, name='arcade_submitted'),
    path('arcade/judge-select/<int:session_id>/', views_arcade.judge_select, name='arcade_judge_select'),
    path('arcade/submit-approval/<int:session_id>/', views_arcade.submit_for_approval, name='arcade_submit_approval'),
    path('arcade/pending/<int:session_id>/', views_arcade.pending_approval, name='arcade_pending_approval'),
    path('arcade/judge-approval/', views_arcade.judge_approval, name='arcade_judge_approval'),
    path('arcade/approve/<int:session_id>/', views_arcade.approve_submission, name='arcade_approve'),
    path('arcade/deny/<int:session_id>/', views_arcade.deny_submission, name='arcade_deny'),
    path('arcade/continue/<int:session_id>/', views_arcade.continue_after_denial, name='arcade_continue'),
    path('arcade/leaderboard/', views_arcade.arcade_leaderboard, name='arcade_leaderboard'),
    path('arcade/leaderboard/minimal/', views_arcade.arcade_leaderboard_minimal, name='arcade_leaderboard_minimal'),
    path('arcade/judge-approval/minimal/', views_arcade.judge_approval_minimal, name='arcade_judge_approval_minimal'),
    path('user-profile/<str:username>/', views_arcade.user_profile, name='user_profile'),
    path('api/arcade/high-score/<int:chore_id>/', views_arcade.get_high_score, name='arcade_high_score'),
    # Piano Game Easter Egg
    path('piano/play/', views_piano.piano_game, name='piano_game'),
    path('piano/leaderboard/', views_piano.piano_leaderboard, name='piano_leaderboard'),
    path('piano/submit/', views_piano.submit_piano_score, name='piano_submit_score'),
]
