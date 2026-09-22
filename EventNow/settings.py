"""
Django settings for EventNow.

All secrets and environment-specific values are read from environment
variables (see `.env.example`). Nothing sensitive is hardcoded here.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env in development; on Vercel the variables come from the dashboard
load_dotenv(BASE_DIR / ".env")


def env(name, default=""):
    """Like os.getenv, but an empty value (e.g. a blank Vercel variable) counts as unset."""
    return os.getenv(name, "").strip() or default


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# --- Core security -----------------------------------------------------------

DEBUG = env_bool("DEBUG", False)

SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise RuntimeError(
            "SECRET_KEY is not set. Add it in Vercel → Project → Settings → Environment Variables."
        )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Vercel exposes the deployment host; allow it automatically (production + previews)
if os.getenv("VERCEL_URL"):
    ALLOWED_HOSTS.append(os.environ["VERCEL_URL"])
if os.getenv("VERCEL_PROJECT_PRODUCTION_URL"):
    ALLOWED_HOSTS.append(os.environ["VERCEL_PROJECT_PRODUCTION_URL"])

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
CSRF_TRUSTED_ORIGINS += [f"https://{host}" for host in ALLOWED_HOSTS if host not in ("localhost", "127.0.0.1")]

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "events",
    "django_htmx",
    "rest_framework",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "crispy_forms",
    "crispy_bootstrap5",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "EventNow.urls"
WSGI_APPLICATION = "EventNow.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "events.context_processors.site_flags",
            ],
        },
    },
]


# --- Database ----------------------------------------------------------------
# Neon Postgres in production via DATABASE_URL; local SQLite otherwise.

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0,  # serverless: don't hold connections between invocations
        ssl_require=env("DATABASE_URL").startswith("postgres"),
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Authentication ----------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SITE_ID = 1

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "index"

ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"
ACCOUNT_MESSAGES = False
SOCIALACCOUNT_AUTO_SIGNUP = True

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_LOGIN_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET},
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "METHOD": "oauth2",
        "VERIFIED_EMAIL": True,
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# --- UI ----------------------------------------------------------------------

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"


# --- API ---------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
}


# --- Internationalization ----------------------------------------------------

LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Brisbane"
USE_I18N = True
USE_TZ = True


# --- Static files ------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "events" / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Hashed, compressed files in production; plain files in development and tests
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG and "test" not in sys.argv
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


# --- AI features -------------------------------------------------------------

OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-5.4-mini")
AI_DAILY_LIMIT = int(env("AI_DAILY_LIMIT", "10"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
