# EventNow

**Brisbane events, beautifully run.** Attendees discover events and register in under a minute. Organisers publish events, schedule parallel sessions, enforce room capacity and check people in.

[![CI](https://github.com/stevensu04/EventNow/actions/workflows/ci.yml/badge.svg)](https://github.com/stevensu04/EventNow/actions/workflows/ci.yml)

**Live demo:** https://event-now-eight.vercel.app

---

## Features

**For attendees**
- Browse upcoming events with search plus category and venue filters
- See live seat counts, with "only N left" warnings as events fill up
- Pick sessions across parallel tracks; each room enforces its own limit
- No account needed. Registering gives you a shareable ticket link and a calendar (`.ics`) download

**For organisers**
- **AI event drafting**: describe an event in one sentence and the form fills itself (OpenAI, JSON mode)
- **AI description rewrite**, reviewed before saving, with a per-user daily quota to cap API spend
- Session scheduler that checks capacity against each venue's rooms
- Live check-in with HTMX: search, paginate and mark attendance without page reloads
- CSV export (with spreadsheet formula-injection protection)
- Dashboard with live events, registrations, remaining seats and latest sign-ups
- Demo subscription tiers: Free and Professional (upgrading is instant and free in the demo)

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Django 6, Django REST Framework, django-allauth (username + Google sign-in) |
| Frontend | Server-rendered templates, HTMX, Bootstrap 5 with a custom design system |
| Data | PostgreSQL on [Neon](https://neon.tech) in production, SQLite locally |
| AI | OpenAI Chat Completions API |
| Hosting | [Vercel](https://vercel.com) (zero-config Django, static files on the CDN) |
| CI | GitHub Actions: checks, migration drift, tests |

## Security notes

- All secrets come from environment variables; none are committed.
- Organisers can only see and change their own events. Every management endpoint checks ownership and returns 404 otherwise.
- The REST API is admin-only.
- Registration runs in a transaction with a row lock, so the last seat can't be double-booked.
- Tickets are signed tokens: a ticket URL can't be guessed from an attendee ID.
- AI output is rendered from Markdown and sanitised with `nh3`.

## Run locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # DEBUG=True is enough to start
python manage.py migrate
python manage.py seed_demo      # six sample Brisbane events
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000. Sign up, click **Upgrade** on the Pricing page, and you can create events.

Run the tests:

```bash
python manage.py test events
```

## Deploy (Vercel + Neon, free tiers)

1. Create a Neon project and copy its connection string.
2. Import this repo in Vercel. Django is detected automatically.
3. Set these environment variables in Vercel:

   | Variable | Value |
   |---|---|
   | `SECRET_KEY` | a long random string |
   | `DATABASE_URL` | the Neon connection string |
   | `ALLOWED_HOSTS` | your custom domain, if any (`*.vercel.app` hosts are added automatically) |
   | `OPENAI_API_KEY` | optional; AI features hide themselves without it |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | optional; Google sign-in appears only when both are set |

4. Run migrations and seed data against Neon from your machine:

   ```bash
   DATABASE_URL="postgresql://..." python manage.py migrate
   DATABASE_URL="postgresql://..." python manage.py seed_demo
   DATABASE_URL="postgresql://..." python manage.py createsuperuser
   ```

## Project structure

```
EventNow/            Django project (settings, urls, wsgi)
events/
  models.py          Event, Session, Attendee, Subscription, AIUsage
  views.py           public pages, registration, organiser tools, AI endpoints
  ai.py              OpenAI wrapper: lazy client, daily quota, safe Markdown
  templates/         pages + HTMX partials
  static/css/        design system (eventnow.css)
  management/commands/seed_demo.py
  tests.py           permission, registration and capacity tests
```

## Background

EventNow started as the final project for INFS7202 (Web Information Systems) at the University of Queensland. It was later rebuilt with a new design system, hardened security, organiser-scoped permissions and serverless deployment.
