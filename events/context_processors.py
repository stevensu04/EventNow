from django.conf import settings


def site_flags(request):
    """Feature flags the templates need on every page."""
    return {
        "GOOGLE_LOGIN_ENABLED": settings.GOOGLE_LOGIN_ENABLED,
        "AI_ENABLED": bool(settings.OPENAI_API_KEY),
    }
