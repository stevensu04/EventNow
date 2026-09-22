import csv
import json
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from rest_framework import viewsets

from . import ai
from .models import Attendee, Event, Notification, Session, Subscription
from .serializers import AttendeeSerializer, NotificationSerializer

# Hardcoded venue constraints to simulate real-world physical capacity limits
BRISBANE_VENUES = {
    "City CBD - LatinHub": {"Open Floor Space": 30},
    "BCEC, South Bank": {"Hall 1": 500, "Plaza Ballroom": 300, "M1 Meeting Room": 50},
    "UQ St Lucia Campus": {"The Atrium": 200, "AEB Auditorium": 150, "Room S302": 40},
    "State Library of QLD": {"Queensland Terrace": 120, "Auditorium 1": 250, "The Edge": 80},
    "Fortitude Valley Hub": {"Main Hall": 100, "Rooftop Garden": 50, "Meeting Room A": 30},
    "Online / Remote": {"Zoom Room A": 500, "Microsoft Teams": 1000, "YouTube Live": 5000},
}

EVENT_STATUSES = {code for code, _ in Event.STATUS_CHOICES}
EVENT_CATEGORIES = {code for code, _ in Event.CATEGORY_CHOICES}
ATTENDEE_STATUSES = {"attended", "cancelled", "confirmed"}
TICKET_SALT = "eventnow.ticket"


# --- REST API (admin only, see REST_FRAMEWORK settings) ----------------------

class AttendeeViewSet(viewsets.ModelViewSet):
    queryset = Attendee.objects.all()
    serializer_class = AttendeeSerializer

    def get_queryset(self):
        event_id = self.request.query_params.get('event_id')
        if event_id:
            return self.queryset.filter(event_id=event_id)
        return self.queryset


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all().order_by('-timestamp')
    serializer_class = NotificationSerializer


# --- Helpers -----------------------------------------------------------------

def venue_limit(location):
    return sum(BRISBANE_VENUES.get(location, {"General": 100}).values())


def get_managed_event(request, event_id):
    """Return the event if the current user may manage it; 404 otherwise (don't leak existence)."""
    event = get_object_or_404(Event, id=event_id, is_deleted=False)
    if not event.is_managed_by(request.user):
        raise Http404
    return event


def managed_events(user):
    events = Event.objects.filter(is_deleted=False)
    return events if user.is_superuser else events.filter(organizer=user)


def get_subscription(user):
    subscription, _ = Subscription.objects.get_or_create(user=user)
    return subscription


def with_registration_counts(queryset):
    return queryset.annotate(
        registered=Count('attendees', filter=~Q(attendees__status='cancelled'), distinct=True)
    )


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def ticket_token(attendee):
    return signing.dumps({'a': attendee.id}, salt=TICKET_SALT)


def attendee_from_token(token):
    try:
        attendee_id = signing.loads(token, salt=TICKET_SALT)['a']
    except (signing.BadSignature, KeyError, TypeError):
        raise Http404
    return get_object_or_404(Attendee.objects.select_related('event'), id=attendee_id)


# --- Public pages ------------------------------------------------------------

def landing_page(request):
    upcoming = with_registration_counts(
        Event.objects.filter(is_deleted=False, status__in=['active', 'full'], date__gte=timezone.localdate())
    ).order_by('date')[:3]
    return render(request, 'landingpage.html', {'upcoming_events': upcoming})


def about_page(request):
    return render(request, 'about.html')


def registration0_page(request):
    """Public discovery page with search, category and venue filters."""
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    location = request.GET.get('location', '')

    events = Event.objects.filter(
        is_deleted=False, status__in=['active', 'full'], date__gte=timezone.localdate()
    )
    if query:
        events = events.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category in EVENT_CATEGORIES:
        events = events.filter(category=category)
    if location in BRISBANE_VENUES:
        events = events.filter(location=location)

    events = with_registration_counts(events).order_by('date')

    return render(request, 'registration0.html', {
        'events': events,
        'query': query,
        'category': category,
        'location': location,
        'categories': Event.CATEGORY_CHOICES,
        'venues': BRISBANE_VENUES.keys(),
    })


def event_detail_1_page(request, event_id):
    """Public detail view: event info, sessions with live seat counts, and the registration form."""
    event = get_object_or_404(with_registration_counts(Event.objects.filter(is_deleted=False)), id=event_id)
    sessions = event.sessions.annotate(
        registered=Count('attendees', filter=~Q(attendees__status='cancelled'))
    ).order_by('start_time', 'track')

    spots_left = max(event.capacity - event.registered, 0)
    is_open = event.status == 'active' and event.date >= timezone.localdate() and spots_left > 0

    return render(request, 'event_detail_1.html', {
        'event': event,
        'sessions': sessions,
        'spots_left': spots_left,
        'is_open': is_open,
        'can_manage': event.is_managed_by(request.user),
    })


@require_POST
def register_event(request, event_id):
    """
    Public endpoint: creates an Attendee and enrols them in the chosen sessions.
    Enforces event capacity, per-session capacity, and one registration per email.
    """
    full_name = request.POST.get('full_name', '').strip()
    email = request.POST.get('email', '').strip().lower()
    session_ids = request.POST.getlist('sessions')

    if not full_name or not email or '@' not in email:
        messages.error(request, "Please enter your name and a valid email address.")
        return redirect('event_detail', event_id=event_id)

    with transaction.atomic():
        # Lock the event row so two people can't grab the last seat at the same time
        event = get_object_or_404(Event.objects.select_for_update(), id=event_id, is_deleted=False)
        active_attendees = event.attendees.exclude(status='cancelled')

        if event.status != 'active' or event.date < timezone.localdate():
            messages.error(request, "Registration for this event is closed.")
            return redirect('event_detail', event_id=event.id)

        if active_attendees.filter(email__iexact=email).exists():
            messages.warning(request, f"{email} is already registered for this event.")
            return redirect('event_detail', event_id=event.id)

        if active_attendees.count() >= event.capacity:
            event.status = 'full'
            event.save(update_fields=['status'])
            messages.error(request, "Sorry — this event just sold out.")
            return redirect('event_detail', event_id=event.id)

        # Only sessions that belong to THIS event, and that still have room
        sessions = list(event.sessions.filter(id__in=session_ids).annotate(
            registered=Count('attendees', filter=~Q(attendees__status='cancelled'))
        ))
        full_sessions = [s.title for s in sessions if s.registered >= s.max_capacity]
        if full_sessions:
            messages.error(request, f"These sessions are full: {', '.join(full_sessions)}. Please pick others.")
            return redirect('event_detail', event_id=event.id)

        attendee = Attendee.objects.create(full_name=full_name, email=email, event=event)
        attendee.selected_sessions.add(*sessions)

        if active_attendees.count() >= event.capacity:
            event.status = 'full'
            event.save(update_fields=['status'])

    return redirect(reverse('ticket', args=[ticket_token(attendee)]) + '?new=1')


def ticket_page(request, token):
    """Registration confirmation / ticket. Reachable only via the signed link issued at sign-up."""
    attendee = attendee_from_token(token)
    return render(request, 'ticket.html', {
        'attendee': attendee,
        'event': attendee.event,
        'sessions': attendee.selected_sessions.order_by('start_time'),
        'token': token,
        'just_registered': 'new' in request.GET,
    })


def ticket_ics(request, token):
    """Add-to-calendar file: one VEVENT per selected session, or an all-day event if none."""
    attendee = attendee_from_token(token)
    event = attendee.event
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')

    def escape(text):
        return text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')

    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//EventNow//Ticket//EN', 'CALSCALE:GREGORIAN']
    sessions = list(attendee.selected_sessions.order_by('start_time'))
    blocks = [(f"{event.title}: {s.title}", s.start_time, s.end_time, s.id) for s in sessions] or [(event.title, None, None, 0)]
    for summary, start, end, uid in blocks:
        lines += ['BEGIN:VEVENT', f'UID:eventnow-{attendee.id}-{uid}@eventnow', f'DTSTAMP:{stamp}']
        if start and end:
            day = event.date.strftime('%Y%m%d')
            lines += [f'DTSTART;TZID=Australia/Brisbane:{day}T{start.strftime("%H%M%S")}',
                      f'DTEND;TZID=Australia/Brisbane:{day}T{end.strftime("%H%M%S")}']
        else:
            lines += [f'DTSTART;VALUE=DATE:{event.date.strftime("%Y%m%d")}',
                      f'DTEND;VALUE=DATE:{(event.date + timedelta(days=1)).strftime("%Y%m%d")}']
        lines += [f'SUMMARY:{escape(summary)}', f'LOCATION:{escape(event.location)}', 'END:VEVENT']
    lines.append('END:VCALENDAR')

    response = HttpResponse('\r\n'.join(lines) + '\r\n', content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="eventnow-ticket.ics"'
    return response


def pricing_view(request):
    subscription = get_subscription(request.user) if request.user.is_authenticated else None
    return render(request, 'pricing.html', {'subscription': subscription})


@login_required
@require_POST
def switch_plan(request):
    """Demo billing: switch plan instantly (no payment is taken on this portfolio deployment)."""
    plan = request.POST.get('plan')
    if plan in ('free', 'pro'):
        subscription = get_subscription(request.user)
        subscription.plan = plan
        subscription.save()
        if plan == 'pro':
            messages.success(request, "You're on Professional (demo) — you can now create events.")
            return redirect('dashboard')
        messages.info(request, "Switched back to the Free plan.")
    return redirect('pricing')


# --- Organiser pages ---------------------------------------------------------

@login_required
def dashboard_page(request):
    today = timezone.localdate()
    events = with_registration_counts(managed_events(request.user)).annotate(
        session_count=Count('sessions', distinct=True),
        status_priority=Case(
            When(status__in=['active', 'full'], then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
    ).order_by('status_priority', 'date')

    live_events = [e for e in events if e.status in ('active', 'full') and e.date >= today]
    for event in events:
        event.hard_limit = venue_limit(event.location)
        event.is_finished = event.date < today or event.status in ('expired', 'cancelled')
        event.fill_percentage = min(round(event.registered / event.capacity * 100), 100) if event.capacity else 0

    next_event = min(live_events, key=lambda e: e.date, default=None)
    recent_attendees = Attendee.objects.filter(
        event__in=managed_events(request.user)
    ).select_related('event').order_by('-registration_date')[:5]

    return render(request, 'dashboard.html', {
        'events': events,
        'active_events_count': len(live_events),
        'total_registrations': sum(e.registered for e in live_events),
        'seats_remaining': sum(max(e.capacity - e.registered, 0) for e in live_events),
        'next_event': next_event,
        'next_event_days': (next_event.date - today).days if next_event else None,
        'recent_attendees': recent_attendees,
        'brisbane_venues': BRISBANE_VENUES,
        'categories': Event.CATEGORY_CHOICES,
        'notifications': Notification.objects.order_by('-timestamp')[:3],
        'subscription': get_subscription(request.user),
        'ai_remaining': ai.remaining_quota(request.user),
    })


@login_required
def create_event_page(request):
    """Event creation. Requires a Pro plan and validates capacity against the venue."""
    if not get_subscription(request.user).can_create_event:
        messages.warning(request, "Creating events is a Professional feature. Upgrade (free in this demo) to continue.")
        return redirect('pricing')

    context = {
        'brisbane_venues': BRISBANE_VENUES,
        'categories': Event.CATEGORY_CHOICES,
        'ai_remaining': ai.remaining_quota(request.user),
        'today': timezone.localdate(),
    }

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        location = request.POST.get('location', '')
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', 'community')
        capacity = parse_int(request.POST.get('capacity'))
        try:
            event_date = date.fromisoformat(request.POST.get('date', ''))
        except ValueError:
            event_date = None

        error = None
        if not title or not description:
            error = "Please give the event a title and description."
        elif location not in BRISBANE_VENUES:
            error = "Please choose a venue from the list."
        elif event_date is None or event_date < timezone.localdate():
            error = "Please choose a date that isn't in the past."
        elif not 1 <= capacity <= venue_limit(location):
            error = f"Capacity must be between 1 and the venue limit ({venue_limit(location)})."

        if error:
            messages.error(request, error)
            context['form_data'] = request.POST
            return render(request, 'create_event.html', context)

        new_event = Event.objects.create(
            title=title,
            date=event_date,
            location=location,
            description=description,
            capacity=capacity,
            category=category if category in EVENT_CATEGORIES else 'community',
            organizer=request.user,
        )
        messages.success(request, f"'{title}' is live! Now add some sessions.")
        return redirect('manage_sessions', event_id=new_event.id)

    return render(request, 'create_event.html', context)


@login_required
@require_POST
def update_event(request, event_id):
    event = get_managed_event(request, event_id)

    try:
        new_date = date.fromisoformat(request.POST.get('date', ''))
    except ValueError:
        messages.error(request, "Please enter a valid date.")
        return redirect('dashboard')
    if new_date < timezone.localdate() and new_date != event.date:
        messages.error(request, "You can't reschedule an event to a past date.")
        return redirect('dashboard')

    location = request.POST.get('location', event.location)
    if location not in BRISBANE_VENUES:
        location = event.location
    capacity = parse_int(request.POST.get('capacity'), event.capacity)
    if not 1 <= capacity <= venue_limit(location):
        messages.error(request, f"Capacity must be between 1 and the venue limit ({venue_limit(location)}).")
        return redirect('dashboard')

    event.title = request.POST.get('title', '').strip() or event.title
    event.description = request.POST.get('description', event.description)
    event.location = location
    event.date = new_date
    event.capacity = capacity
    status = request.POST.get('status')
    if status in EVENT_STATUSES:
        event.status = status
    category = request.POST.get('category')
    if category in EVENT_CATEGORIES:
        event.category = category
    event.save()
    messages.success(request, f"'{event.title}' updated.")
    return redirect('dashboard')


@login_required
@require_POST
def delete_event(request, event_id):
    """Soft delete: hide the event but keep its registrations for the record."""
    event = get_managed_event(request, event_id)
    event.is_deleted = True
    event.save(update_fields=['is_deleted'])
    messages.success(request, f"'{event.title}' was archived.")
    return redirect('dashboard')


@login_required
def sessions_page(request, event_id):
    """Session management. Validates session capacity against the chosen room's limit."""
    event = get_managed_event(request, event_id)
    spaces = BRISBANE_VENUES.get(event.location, {"General Space": 100})

    if request.method == 'POST':
        track = request.POST.get('track', '')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        capacity = parse_int(request.POST.get('max_capacity'))
        hard_limit = spaces.get(track)

        if hard_limit is None:
            messages.error(request, "Please choose a space at this venue.")
        elif not 1 <= capacity <= hard_limit:
            messages.error(request, f"{track} holds up to {hard_limit} people.")
        elif not start_time or not end_time or end_time <= start_time:
            messages.error(request, "End time must be later than the start time.")
        else:
            Session.objects.create(
                event=event,
                title=request.POST.get('title', '').strip() or 'Untitled session',
                speaker=request.POST.get('speaker', '').strip() or 'TBA',
                start_time=start_time, end_time=end_time,
                track=track, max_capacity=capacity,
            )
            messages.success(request, "Session added to the schedule.")
        return redirect('manage_sessions', event_id=event.id)

    sessions = event.sessions.annotate(
        registered=Count('attendees', filter=~Q(attendees__status='cancelled'))
    ).order_by('start_time', 'track')

    return render(request, 'sessions.html', {
        'event': event,
        'sessions': sessions,
        'spaces_info': spaces,
    })


@login_required
@require_POST
def delete_session(request, event_id, session_id):
    event = get_managed_event(request, event_id)
    get_object_or_404(Session, id=session_id, event=event).delete()
    messages.success(request, "Session deleted.")
    return redirect('manage_sessions', event_id=event.id)


@login_required
@require_POST
def edit_session(request, event_id, session_id):
    event = get_managed_event(request, event_id)
    session = get_object_or_404(Session, id=session_id, event=event)
    spaces = BRISBANE_VENUES.get(event.location, {})

    track = request.POST.get('track') or session.track
    capacity = parse_int(request.POST.get('max_capacity'), session.max_capacity)
    hard_limit = spaces.get(track, 999)
    if capacity > hard_limit:
        messages.warning(request, f"Capacity for {track} capped at {hard_limit}.")
        capacity = hard_limit

    start_time = request.POST.get('start_time') or session.start_time.strftime('%H:%M')
    end_time = request.POST.get('end_time') or session.end_time.strftime('%H:%M')
    if end_time <= start_time:
        messages.error(request, "End time must be later than the start time.")
        return redirect('manage_sessions', event_id=event.id)

    session.title = request.POST.get('title', '').strip() or session.title
    session.speaker = request.POST.get('speaker', '').strip() or session.speaker
    session.start_time = start_time
    session.end_time = end_time
    session.track = track
    session.max_capacity = max(capacity, 1)
    session.save()
    messages.success(request, "Session updated.")
    return redirect('manage_sessions', event_id=event.id)


@login_required
@ensure_csrf_cookie
def manage_attendees(request, event_id):
    """Attendee lists per session (plus an 'All' tab), with search and HTMX pagination."""
    event = get_managed_event(request, event_id)
    query = request.GET.get('q', '').strip()

    all_attendees = event.attendees.prefetch_related('selected_sessions').order_by('-registration_date')
    if query:
        all_attendees = all_attendees.filter(Q(full_name__icontains=query) | Q(email__icontains=query))

    groups = [{'key': 'all', 'title': 'All attendees', 'attendees': all_attendees}]
    groups += [
        {'key': str(s.id), 'title': s.title, 'attendees': all_attendees.filter(selected_sessions=s)}
        for s in event.sessions.order_by('start_time')
    ]

    session_data = []
    for group in groups:
        page_var = f"page_{group['key']}"
        page_obj = Paginator(group['attendees'], 10).get_page(request.GET.get(page_var, 1))
        session_data.append({**group, 'page_obj': page_obj, 'page_var': page_var})

    counts = event.attendees.aggregate(
        confirmed=Count('id', filter=Q(status='confirmed')),
        attended=Count('id', filter=Q(status='attended')),
        cancelled=Count('id', filter=Q(status='cancelled')),
    )
    keys = {group['key'] for group in groups}
    active_tab = request.GET.get('tab') if request.GET.get('tab') in keys else 'all'
    context = {
        'event': event, 'session_data': session_data, 'query': query,
        'counts': counts, 'active_tab': active_tab,
    }

    if request.htmx:
        return render(request, 'partials/attendee_session_panels.html', context)
    return render(request, 'manage_attendees.html', context)


@login_required
@require_POST
def update_attendee_status(request, attendee_id):
    attendee = get_object_or_404(Attendee.objects.select_related('event'), id=attendee_id)
    if not attendee.event.is_managed_by(request.user):
        raise Http404

    new_status = request.POST.get('status')
    if new_status in ATTENDEE_STATUSES:
        attendee.status = new_status
        attendee.save(update_fields=['status'])

    return render(request, 'partials/single_attendee_row.html', {'attendee': attendee})


@login_required
def export_attendees_csv(request, event_id):
    event = get_managed_event(request, event_id)
    attendees = event.attendees.prefetch_related('selected_sessions').order_by('registration_date')

    safe_title = ''.join(c if c.isalnum() else '_' for c in event.title)[:50]
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{safe_title}_attendees.csv"'

    writer = csv.writer(response)
    writer.writerow(['Full Name', 'Email Address', 'Sessions', 'Registration Date', 'Status'])
    for a in attendees:
        sessions = ", ".join(s.title for s in a.selected_sessions.all()) or "No sessions selected"
        writer.writerow([
            _csv_safe(a.full_name), _csv_safe(a.email), _csv_safe(sessions),
            timezone.localtime(a.registration_date).strftime('%Y-%m-%d %H:%M'),
            a.status.capitalize(),
        ])
    return response


def _csv_safe(value):
    """Neutralise spreadsheet formula injection from user-supplied fields."""
    return "'" + value if value[:1] in ('=', '+', '-', '@') else value


# --- AI features (organisers only, rate limited) -----------------------------

def _ai_error(request, message):
    return render(request, 'partials/_ai_error.html', {'message': message})


@login_required
@require_POST
def generate_event_description(request, event_id):
    """Rewrite an existing event's description; returns an HTMX partial."""
    event = get_managed_event(request, event_id)
    try:
        text = ai.complete(request.user, [
            {"role": "system", "content": "You are a professional event copywriter. Reply in plain Markdown, max 150 words."},
            {"role": "user", "content": (
                f"Write a compelling description for this event.\n"
                f"Title: {event.title}\nLocation: {event.location}, Brisbane\nDate: {event.date:%A %d %B %Y}\n"
                f"Current description: {event.description or 'None yet.'}"
            )},
        ])
    except ai.AIUnavailable as exc:
        return _ai_error(request, str(exc))

    return render(request, 'partials/_ai_description_result.html', {
        'ai_content': ai.render_markdown(text),
        'ai_plain': text,
        'event': event,
    })


@login_required
@require_POST
def generate_ai_description_simple(request):
    title = request.POST.get('title', '').strip()
    if not title:
        return _ai_error(request, "Type an event title first, then try again.")
    try:
        text = ai.complete(request.user, [
            {"role": "system", "content": "You write short, catchy event blurbs in plain text. No headings."},
            {"role": "user", "content": f"Write a 3-sentence event description for: {title[:200]}"},
        ])
    except ai.AIUnavailable as exc:
        return _ai_error(request, str(exc))
    return render(request, 'partials/_ai_simple_result.html', {'ai_content': ai.render_markdown(text), 'ai_plain': text})


@login_required
@require_POST
def agentic_event_parser(request):
    """Turn a natural-language request into structured event fields (JSON mode)."""
    user_input = request.POST.get('prompt', '').strip()[:1000]
    if not user_input:
        return JsonResponse({'error': 'Describe your event first.'}, status=400)

    venues = list(BRISBANE_VENUES.keys())
    categories = [code for code, _ in Event.CATEGORY_CHOICES]
    try:
        raw = ai.complete(request.user, [
            {"role": "system", "content": (
                f"You are an event scheduling assistant. Today is {datetime.now():%Y-%m-%d (%A)}. "
                "Parse the user's request into a JSON object with keys: "
                "'title', 'date' (YYYY-MM-DD), 'location', 'category', 'capacity' (int), 'description'. "
                f"'location' must be exactly one of: {json.dumps(venues)} — pick the closest match. "
                f"'category' must be one of: {json.dumps(categories)}."
            )},
            {"role": "user", "content": user_input},
        ], json_mode=True)
        result = json.loads(raw)
    except ai.AIUnavailable as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    except json.JSONDecodeError:
        return JsonResponse({'error': "The AI returned something unexpected. Try rephrasing."}, status=502)

    if result.get('location') not in BRISBANE_VENUES:
        result['location'] = ''
    result['remaining'] = ai.remaining_quota(request.user)
    return JsonResponse(result)
