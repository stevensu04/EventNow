from django import template

register = template.Library()

CATEGORY_ICONS = {
    "tech": "bi-cpu",
    "business": "bi-briefcase",
    "food": "bi-cup-hot",
    "music": "bi-music-note-beamed",
    "community": "bi-people",
}


@register.filter
def category_icon(category):
    return CATEGORY_ICONS.get(category, "bi-calendar-event")


@register.filter
def percent_of(part, whole):
    try:
        return min(round(int(part) / int(whole) * 100), 100) if int(whole) else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def spots_left(event):
    return max(event.capacity - getattr(event, "registered", 0), 0)


@register.simple_tag
def seat_state(registered, capacity):
    """'is-full' when sold out, 'is-hot' when ≥ 80% taken, '' otherwise — drives the urgency styling."""
    if not capacity or registered >= capacity:
        return "is-full"
    return "is-hot" if registered / capacity >= 0.8 else ""


@register.filter
def initials(name):
    parts = (name or "?").split()
    return "".join(p[0] for p in parts[:2]).upper()
