"""Piano Tiles game views for ChoreBoard easter egg."""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from chores.models import PianoScore
from users.models import User
from core.models import Settings
import logging

logger = logging.getLogger(__name__)


def piano_game(request):
    """
    Piano Tiles game page (kiosk mode compatible).
    No authentication required.
    """
    # Get active users for user selection after game over
    active_users = User.objects.filter(is_active=True).order_by('first_name', 'username')

    context = {
        'active_users': active_users,
    }
    return render(request, 'board/piano/game.html', context)


def piano_leaderboard(request):
    """
    Piano leaderboard page showing top 10 scores (kiosk mode compatible).

    Query params:
    - hard_mode: 'true', 'false', or omit for all modes
    - highlight: score_id to highlight
    """
    # Get filter from query params
    hard_mode_filter = request.GET.get('hard_mode')

    # Base query - top 10 all-time scores
    base_query = PianoScore.objects.select_related('user')

    if hard_mode_filter == 'true':
        top_scores = base_query.filter(hard_mode=True)[:10]
        mode_label = "Hard Mode"
    elif hard_mode_filter == 'false':
        top_scores = base_query.filter(hard_mode=False)[:10]
        mode_label = "Normal Mode"
    else:
        top_scores = base_query[:10]
        mode_label = "All Modes"

    # Get highlighted score if provided
    highlight_id = request.GET.get('highlight')

    # Get redirect settings
    settings = Settings.get_settings()
    redirect_seconds = settings.arcade_submission_redirect_seconds

    context = {
        'top_scores': top_scores,
        'mode_label': mode_label,
        'hard_mode_filter': hard_mode_filter,
        'highlight_id': highlight_id,
        'redirect_seconds': redirect_seconds,
        'redirect_url': '/arcade/leaderboard/',
    }

    return render(request, 'board/piano/leaderboard.html', context)


@require_POST
def submit_piano_score(request):
    """
    Submit piano score (kiosk mode compatible).

    POST params:
    - user_id: Required - ID of user who played
    - score: Required - Integer score (tiles hit)
    - hard_mode: Optional - 'true' or 'false' (default: false)

    Returns JSON with redirect URL to leaderboard with highlight.
    """
    try:
        # Validate user_id
        user_id = request.POST.get('user_id')
        if not user_id:
            return JsonResponse({
                'success': False,
                'message': 'User ID is required'
            }, status=400)

        user = get_object_or_404(User, id=user_id, is_active=True)

        # Validate score
        score = request.POST.get('score')
        if not score:
            return JsonResponse({
                'success': False,
                'message': 'Score is required'
            }, status=400)

        try:
            score = int(score)
            if score < 0:
                raise ValueError("Score cannot be negative")
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'message': 'Invalid score value'
            }, status=400)

        # Parse hard mode
        hard_mode = request.POST.get('hard_mode', 'false').lower() == 'true'

        # Create piano score record
        piano_score = PianoScore.objects.create(
            user=user,
            score=score,
            hard_mode=hard_mode
        )

        # Build redirect URL with highlight
        redirect_url = f'/piano/leaderboard/?highlight={piano_score.id}'
        if hard_mode:
            redirect_url += '&hard_mode=true'

        return JsonResponse({
            'success': True,
            'message': f'Score saved: {score} points!',
            'score_id': piano_score.id,
            'redirect': redirect_url
        })

    except Exception as e:
        logger.exception("Error submitting piano score")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)
