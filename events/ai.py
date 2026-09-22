"""
Thin wrapper around the OpenAI API.

- The client is created lazily, so the site still boots without an API key.
- Each user gets AI_DAILY_LIMIT calls per day (tracked in the AIUsage table),
  which keeps a public demo from running up the OpenAI bill.
- Model output is rendered from Markdown and sanitised before it reaches a template.
"""

import logging

import markdown
import nh3
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import AIUsage

logger = logging.getLogger(__name__)

_client = None


class AIUnavailable(Exception):
    """Raised with a user-facing message when an AI call can't be made."""


def is_enabled():
    return bool(settings.OPENAI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=25)
    return _client


def remaining_quota(user):
    usage = AIUsage.objects.filter(user=user, day=timezone.localdate()).first()
    return max(settings.AI_DAILY_LIMIT - (usage.count if usage else 0), 0)


def _consume_quota(user):
    with transaction.atomic():
        usage, _ = AIUsage.objects.select_for_update().get_or_create(user=user, day=timezone.localdate())
        if usage.count >= settings.AI_DAILY_LIMIT:
            return False
        AIUsage.objects.filter(pk=usage.pk).update(count=F("count") + 1)
    return True


def complete(user, messages, json_mode=False):
    """Run a chat completion for `user`, enforcing availability and the daily quota."""
    if not is_enabled():
        raise AIUnavailable("AI features are not configured on this deployment.")
    if not _consume_quota(user):
        raise AIUnavailable(f"You've used all {settings.AI_DAILY_LIMIT} AI requests for today. Try again tomorrow.")

    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    try:
        response = _get_client().chat.completions.create(
            model=settings.OPENAI_MODEL, messages=messages, **kwargs
        )
    except Exception:
        logger.exception("OpenAI request failed")
        raise AIUnavailable("The AI service didn't respond. Please try again in a moment.")
    return response.choices[0].message.content or ""


def render_markdown(text):
    """Markdown → sanitised HTML, safe to inject into the page."""
    return mark_safe(nh3.clean(markdown.markdown(text)))
