"""
Populate the database with demo events so a fresh deployment isn't empty.

    python manage.py seed_demo                 # add demo data (skips if it already exists)
    python manage.py seed_demo --reset         # wipe and recreate the demo organiser's events
    python manage.py seed_demo --demo-password <pw>   # also enable a public "demo" login
"""

import random
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from events.models import Attendee, Event, Notification, Session, Subscription

EVENTS = [
    {
        "title": "Brisbane Web Dev Meetup",
        "category": "tech",
        "location": "Fortitude Valley Hub",
        "capacity": 120,
        "days": 9,
        "description": "Lightning talks on modern web tooling, followed by pizza and networking. "
                       "This month: HTMX in production, edge deployments, and accessible design systems.",
        "sessions": [
            ("HTMX in Production", "Mia Chen", "18:00", "18:40", "Main Hall", 100),
            ("Deploying Django to the Edge", "Liam Nguyen", "18:45", "19:25", "Main Hall", 100),
            ("Design Systems Workshop", "Ava Patel", "18:00", "19:30", "Meeting Room A", 30),
        ],
        "attendees": 64,
    },
    {
        "title": "Startup Pitch Night",
        "category": "business",
        "location": "State Library of QLD",
        "capacity": 150,
        "days": 16,
        "description": "Ten early-stage Queensland founders pitch to a panel of investors. "
                       "Stay for the panel Q&A and drinks on the terrace.",
        "sessions": [
            ("Founder Pitches", "Hosted by Noah Williams", "17:30", "19:00", "Auditorium 1", 150),
            ("Investor Panel", "QLD Angels", "19:00", "19:45", "Auditorium 1", 150),
            ("Networking Drinks", "EventNow", "19:45", "21:00", "Queensland Terrace", 120),
        ],
        "attendees": 138,
    },
    {
        "title": "Street Food Lab",
        "category": "food",
        "location": "City CBD - LatinHub",
        "capacity": 30,
        "days": 5,
        "description": "A hands-on tasting session exploring Latin American street food, "
                       "led by local chefs. Small group — seats go fast.",
        "sessions": [
            ("Arepas from Scratch", "Chef Sofia Ramirez", "12:00", "13:30", "Open Floor Space", 30),
        ],
        "attendees": 27,
    },
    {
        "title": "AI for Good Symposium",
        "category": "tech",
        "location": "UQ St Lucia Campus",
        "capacity": 350,
        "days": 23,
        "description": "Researchers and practitioners share how machine learning is being applied to "
                       "climate, health and accessibility challenges across Queensland.",
        "sessions": [
            ("Keynote: Responsible AI", "Prof. Grace Liu", "09:00", "10:00", "The Atrium", 200),
            ("Climate Modelling with ML", "Dr. Oliver Smith", "10:15", "11:15", "AEB Auditorium", 150),
            ("Accessible AI Interfaces", "Isla Brown", "10:15", "11:15", "Room S302", 40),
            ("Panel: AI & Public Health", "Various", "11:30", "12:30", "The Atrium", 200),
        ],
        "attendees": 212,
    },
    {
        "title": "Riverside Jazz Evening",
        "category": "music",
        "location": "BCEC, South Bank",
        "capacity": 300,
        "days": 30,
        "description": "An evening of live jazz from Brisbane's best ensembles, with river views "
                       "and a pop-up bar in the Plaza Ballroom.",
        "sessions": [
            ("The Southbank Quartet", "Live", "19:00", "20:00", "Plaza Ballroom", 300),
            ("Late Set: Blue Note Revival", "Live", "20:30", "22:00", "Plaza Ballroom", 300),
        ],
        "attendees": 96,
    },
    {
        "title": "Community Coding Day",
        "category": "community",
        "location": "Online / Remote",
        "capacity": 500,
        "days": 12,
        "description": "A free, beginner-friendly day of pair programming and mentoring. "
                       "Bring a laptop and a project idea — or pick one of ours.",
        "sessions": [
            ("Kick-off & Team Matching", "Mentors", "10:00", "10:30", "Zoom Room A", 500),
            ("Build Sprint", "Everyone", "10:30", "15:00", "Zoom Room A", 500),
            ("Demo Showcase", "Everyone", "15:00", "16:00", "YouTube Live", 5000),
        ],
        "attendees": 41,
    },
]

FIRST = ["Olivia", "Jack", "Charlotte", "William", "Amelia", "Henry", "Mia", "Leo", "Ella", "Lucas",
         "Grace", "Thomas", "Chloe", "James", "Zoe", "Ethan", "Ruby", "Oscar", "Sophie", "Max"]
LAST = ["Smith", "Nguyen", "Chen", "Brown", "Wilson", "Taylor", "Lee", "Martin", "Patel", "Walker"]


class Command(BaseCommand):
    help = "Seed demo events, sessions and attendees."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo events first.")
        parser.add_argument("--demo-password", help="Create/refresh a public 'demo' organiser login.")

    @transaction.atomic
    def handle(self, *args, reset=False, demo_password=None, **options):
        rng = random.Random(7202)
        organiser, _ = User.objects.get_or_create(
            username="eventnow", defaults={"email": "hello@eventnow.example", "first_name": "EventNow"}
        )
        if not organiser.has_usable_password():
            organiser.set_unusable_password()
            organiser.save()
        Subscription.objects.update_or_create(user=organiser, defaults={"plan": "pro"})

        if demo_password:
            demo, _ = User.objects.get_or_create(username="demo", defaults={"email": "demo@eventnow.example"})
            demo.set_password(demo_password)
            demo.save()
            Subscription.objects.update_or_create(user=demo, defaults={"plan": "pro"})
            organiser = demo  # demo visitors can manage the seeded events
            self.stdout.write(self.style.SUCCESS("Demo login ready: username 'demo'"))

        if reset:
            deleted, _ = Event.objects.filter(organizer__username__in=["eventnow", "demo"]).delete()
            self.stdout.write(f"Removed {deleted} existing demo rows.")
        elif Event.objects.filter(organizer=organiser).exists():
            self.stdout.write("Demo events already exist — use --reset to recreate them.")
            return

        today = timezone.localdate()
        for spec in EVENTS:
            event = Event.objects.create(
                organizer=organiser,
                title=spec["title"],
                category=spec["category"],
                location=spec["location"],
                capacity=spec["capacity"],
                date=today + timedelta(days=spec["days"]),
                description=spec["description"],
            )
            sessions = [
                Session.objects.create(
                    event=event, title=title, speaker=speaker,
                    start_time=time.fromisoformat(start), end_time=time.fromisoformat(end),
                    track=track, max_capacity=cap,
                )
                for title, speaker, start, end, track, cap in spec["sessions"]
            ]
            seats = {s.id: s.max_capacity for s in sessions}
            for i in range(spec["attendees"]):
                first, last = rng.choice(FIRST), rng.choice(LAST)
                attendee = Attendee.objects.create(
                    event=event,
                    full_name=f"{first} {last}",
                    email=f"{first}.{last}{i}@example.com".lower(),
                    status=rng.choices(["confirmed", "attended", "cancelled"], [85, 10, 5])[0],
                )
                picks = [s for s in rng.sample(sessions, k=rng.randint(1, len(sessions))) if seats[s.id] > 0]
                for s in picks:
                    seats[s.id] -= 1
                attendee.selected_sessions.add(*picks)

        if not Notification.objects.exists():
            Notification.objects.create(
                title="Welcome to EventNow",
                message="Create an event, add sessions, and share the link — registrations appear here in real time.",
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(EVENTS)} demo events."))
