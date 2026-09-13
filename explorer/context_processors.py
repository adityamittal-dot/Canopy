from django.conf import settings


def github_oauth(request):
    """Whether "sign in with GitHub" should render at all - same off-by-
    default-until-configured posture as GEMINI_API_KEY gating the AI chat
    panel. A context processor (not a per-view context key) because the
    sign-in link needs to appear in every page's header, not just one view.
    """
    return {'github_oauth_enabled': bool(settings.GITHUB_OAUTH_CLIENT_ID)}
