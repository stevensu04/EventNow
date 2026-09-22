from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Attendee, Event, Session, Subscription
from .views import ticket_token


def make_event(organizer, **kwargs):
    defaults = dict(
        title="Test Meetup", description="A test event", location="Fortitude Valley Hub",
        date=timezone.localdate() + timedelta(days=7), capacity=3, category="tech",
    )
    defaults.update(kwargs)
    return Event.objects.create(organizer=organizer, **defaults)


class BaseTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw-owner-123")
        self.other = User.objects.create_user("other", password="pw-other-123")
        Subscription.objects.create(user=self.owner, plan="pro")
        self.event = make_event(self.owner)
        self.session = Session.objects.create(
            event=self.event, title="Talk", speaker="Ann", start_time=time(9), end_time=time(10),
            track="Main Hall", max_capacity=2,
        )

    def register(self, email, sessions=(), event=None):
        event = event or self.event
        return self.client.post(reverse("register_event", args=[event.id]), {
            "full_name": "Test Person", "email": email, "sessions": [s.id for s in sessions],
        })


class PublicPagesTests(BaseTestCase):
    def test_public_pages_render(self):
        for name, args in [("index", []), ("event_list", []), ("about", []), ("pricing", []),
                           ("event_detail", [self.event.id]), ("login", []), ("account_signup", [])]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_event_list_filters(self):
        make_event(self.owner, title="Jazz Night", category="music")
        response = self.client.get(reverse("event_list"), {"category": "music"})
        self.assertContains(response, "Jazz Night")
        self.assertNotContains(response, "Test Meetup")

    def test_past_and_deleted_events_hidden(self):
        make_event(self.owner, title="Old One", date=timezone.localdate() - timedelta(days=1))
        make_event(self.owner, title="Archived One", is_deleted=True)
        response = self.client.get(reverse("event_list"))
        self.assertNotContains(response, "Old One")
        self.assertNotContains(response, "Archived One")


class RegistrationTests(BaseTestCase):
    def test_successful_registration_redirects_to_ticket(self):
        response = self.register("a@example.com", sessions=[self.session])
        attendee = Attendee.objects.get(email="a@example.com")
        self.assertRedirects(response, reverse("ticket", args=[ticket_token(attendee)]) + "?new=1")
        self.assertEqual(list(attendee.selected_sessions.all()), [self.session])

    def test_duplicate_email_rejected(self):
        self.register("dup@example.com")
        self.register("DUP@example.com")
        self.assertEqual(Attendee.objects.filter(email="dup@example.com").count(), 1)

    def test_event_capacity_enforced_and_marked_full(self):
        for i in range(3):
            self.register(f"p{i}@example.com")
        self.register("late@example.com")
        self.assertFalse(Attendee.objects.filter(email="late@example.com").exists())
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "full")

    def test_session_capacity_enforced(self):
        self.register("s1@example.com", sessions=[self.session])
        self.register("s2@example.com", sessions=[self.session])
        self.register("s3@example.com", sessions=[self.session])
        self.assertFalse(Attendee.objects.filter(email="s3@example.com").exists())

    def test_cannot_enrol_in_another_events_session(self):
        other_event = make_event(self.other, title="Other")
        foreign = Session.objects.create(
            event=other_event, title="Foreign", speaker="X", start_time=time(9), end_time=time(10),
            track="Main Hall", max_capacity=10,
        )
        self.register("x@example.com", sessions=[foreign])
        attendee = Attendee.objects.get(email="x@example.com")
        self.assertEqual(attendee.selected_sessions.count(), 0)

    def test_closed_event_rejects_registration(self):
        self.event.status = "cancelled"
        self.event.save()
        self.register("c@example.com")
        self.assertFalse(Attendee.objects.exists())

    def test_ticket_requires_valid_signature(self):
        self.assertEqual(self.client.get(reverse("ticket", args=["forged-token"])).status_code, 404)

    def test_calendar_file(self):
        self.register("ics@example.com", sessions=[self.session])
        token = ticket_token(Attendee.objects.get(email="ics@example.com"))
        response = self.client.get(reverse("ticket_ics", args=[token]))
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        self.assertIn(b"BEGIN:VEVENT", response.content)
        self.assertIn(b"SUMMARY:Test Meetup: Talk", response.content)


class OrganiserPermissionTests(BaseTestCase):
    """Every organiser endpoint must require login and ownership (these were open before)."""

    def setUp(self):
        super().setUp()
        self.attendee = Attendee.objects.create(event=self.event, full_name="A", email="a@example.com")

    def organiser_urls(self):
        e, s = self.event.id, self.session.id
        return [
            ("get", reverse("dashboard")),
            ("get", reverse("manage_sessions", args=[e])),
            ("get", reverse("manage_attendees", args=[e])),
            ("get", reverse("export_attendees_csv", args=[e])),
            ("post", reverse("update_event", args=[e])),
            ("post", reverse("delete_event", args=[e])),
            ("post", reverse("edit_session", args=[e, s])),
            ("post", reverse("delete_session", args=[e, s])),
            ("post", reverse("update_attendee_status", args=[self.attendee.id])),
        ]

    def test_anonymous_redirected_to_login(self):
        for method, url in self.organiser_urls():
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_non_owner_gets_404(self):
        self.client.force_login(self.other)
        for method, url in self.organiser_urls()[1:]:  # dashboard is per-user, not per-event
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 404)
        self.assertTrue(Session.objects.filter(id=self.session.id).exists())
        self.attendee.refresh_from_db()
        self.assertEqual(self.attendee.status, "confirmed")

    def test_owner_can_manage(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("manage_attendees", args=[self.event.id])).status_code, 200)
        self.client.post(reverse("update_attendee_status", args=[self.attendee.id]), {"status": "attended"})
        self.attendee.refresh_from_db()
        self.assertEqual(self.attendee.status, "attended")

    def test_dashboard_only_shows_own_events(self):
        make_event(self.other, title="Someone Else's Event")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Test Meetup")
        self.assertNotContains(response, "Someone Else&#x27;s Event")

    def test_csv_export_neutralises_formulas(self):
        Attendee.objects.create(event=self.event, full_name="=HYPERLINK(\"x\")", email="f@example.com")
        self.client.force_login(self.owner)
        content = self.client.get(reverse("export_attendees_csv", args=[self.event.id])).content.decode()
        self.assertIn("'=HYPERLINK", content)

    def test_api_is_admin_only(self):
        self.assertIn(self.client.get("/api/attendees/").status_code, (401, 403))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/attendees/").status_code, 403)


class CreateEventTests(BaseTestCase):
    def post_event(self, **overrides):
        data = dict(title="New", description="Desc", location="City CBD - LatinHub",
                    date=(timezone.localdate() + timedelta(days=3)).isoformat(), capacity=20, category="food")
        data.update(overrides)
        return self.client.post(reverse("create_event"), data)

    def test_free_plan_redirected_to_pricing(self):
        self.client.force_login(self.other)
        self.assertRedirects(self.client.get(reverse("create_event")), reverse("pricing"))

    def test_pro_user_creates_event_as_organiser(self):
        self.client.force_login(self.owner)
        self.post_event()
        event = Event.objects.get(title="New")
        self.assertEqual(event.organizer, self.owner)

    def test_capacity_over_venue_limit_rejected(self):
        self.client.force_login(self.owner)
        self.post_event(capacity=31)  # LatinHub holds 30
        self.assertFalse(Event.objects.filter(title="New").exists())

    def test_past_date_rejected(self):
        self.client.force_login(self.owner)
        self.post_event(date=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertFalse(Event.objects.filter(title="New").exists())

    def test_demo_upgrade(self):
        self.client.force_login(self.other)
        self.client.post(reverse("switch_plan"), {"plan": "pro"})
        self.assertEqual(self.other.subscription.plan, "pro")


@override_settings(OPENAI_API_KEY="")
class AIDisabledTests(BaseTestCase):
    def test_ai_endpoints_degrade_gracefully_without_key(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("generate_ai_description", args=[self.event.id]))
        self.assertContains(response, "not configured")
        response = self.client.post(reverse("agentic_parser"), {"prompt": "a meetup"})
        self.assertEqual(response.status_code, 503)

    def test_ai_requires_login(self):
        response = self.client.post(reverse("agentic_parser"), {"prompt": "a meetup"})
        self.assertEqual(response.status_code, 302)
