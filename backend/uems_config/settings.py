"""
Django settings for the Unified Enterprise Management System (HOMS).

Configuration is environment-driven so the same image runs locally, on a
staging host and in production. Development defaults keep the zero-config
SQLite demo working; production refuses to start with insecure defaults.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core security
# ---------------------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-insecure-secret-key-change-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false."
        )

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,0.0.0.0,testserver" if DEBUG else "",
)
# Render supplies the public hostname; custom domains remain environment-driven.
render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must list the public host names in production."
    )

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "/api/v1").rstrip("/")
APP_ENV = os.getenv("APP_ENV", "development")

# Opt-in demo login. When True, /auth/demo-login/ may issue tokens ONLY for
# accounts flagged is_demo=True (seeded by `manage.py seed_demo`). Regular
# accounts can never be accessed through it. Seeding itself is always a
# manual, explicit management command - nothing here runs on deploy.
DEMO_LOGIN = env_bool("DEMO_LOGIN", False)
# Public shared-role access requested for this deployment; no password required.
ROLE_LOGIN = env_bool("ROLE_LOGIN", True)

# Application definition

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
]

LOCAL_APPS = [
    "core",
    "attendance",
    "inventory",
    "fleet",
    "nemt",
    "medicine_delivery",
    "payroll",
    "reports",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "uems_config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "uems_config.wsgi.application"
ASGI_APPLICATION = "uems_config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if os.getenv("RENDER") == "true" and not DEBUG and not DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL must point to the existing persistent database on Render.")


def _database_from_url(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "sqlite":
        name = parsed.path.lstrip("/") or str(BASE_DIR / "db.sqlite3")
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name}
    if scheme in {"postgres", "postgresql", "pgsql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        }
    raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {scheme}")


if DATABASE_URL:
    DATABASES = {"default": _database_from_url(DATABASE_URL)}
elif os.getenv("DB_ENGINE", "sqlite").lower() in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "homs"),
            "USER": os.getenv("DB_USER", "homs"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "db"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }

# Custom user model
AUTH_USER_MODEL = "core.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Kathmandu")
USE_I18N = True
USE_TZ = True

# Static and media storage
STATIC_URL = os.getenv("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = os.getenv("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles"))
MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = os.getenv("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media"))

STORAGES = {
    "default": {
        "BACKEND": os.getenv(
            "DJANGO_STORAGE_BACKEND",
            "django.core.files.storage.FileSystemStorage",
        ),
    },
    "staticfiles": {
        "BACKEND": os.getenv(
            "DJANGO_STATICFILES_STORAGE",
            "django.contrib.staticfiles.storage.StaticFilesStorage",
        ),
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": int(os.getenv("API_PAGE_SIZE", "20")),
    # Reports use ?format=csv|xlsx|pdf themselves; stop DRF from treating it
    # as a renderer override (which raises Http404 for non-renderer formats).
    "URL_FORMAT_OVERRIDE": None,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        *(["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    ],
}

# Simple JWT
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("JWT_ACCESS_MINUTES", "480"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.getenv("JWT_REFRESH_DAYS", "7"))
    ),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# CORS: explicit origins in production, permissive only for local development.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000" if DEBUG else "")
CORS_ALLOW_ALL_ORIGINS = DEBUG and env_bool("CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOW_CREDENTIALS = env_bool("CORS_ALLOW_CREDENTIALS", True)

# HTTPS / proxy hardening (enabled by default outside DEBUG).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# Logging
LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("DJANGO_LOG_FILE", "").strip()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
if LOG_FILE:
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": LOG_FILE,
        "maxBytes": int(os.getenv("DJANGO_LOG_MAX_BYTES", "10485760")),
        "backupCount": int(os.getenv("DJANGO_LOG_BACKUPS", "5")),
        "formatter": "verbose",
    }
    LOGGING["root"]["handlers"].append("file")

# QR Code settings
QR_CODE_IMAGE_DIR = Path(MEDIA_ROOT) / "qrcodes"
QR_CODE_IMAGE_URL = MEDIA_URL + "qrcodes/"
ROTATING_QR_VALIDITY_SECONDS = int(os.getenv("ROTATING_QR_VALIDITY_SECONDS", "30"))
ONE_TIME_QR_DEFAULT_VALIDITY_MINUTES = int(
    os.getenv("ONE_TIME_QR_DEFAULT_VALIDITY_MINUTES", "5")
)

os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(QR_CODE_IMAGE_DIR, exist_ok=True)
os.makedirs(STATIC_ROOT, exist_ok=True)

# WhiteNoise serves collected static files (including Django admin) behind
# gunicorn. Media files still need a reverse proxy or object storage in
# production; see docs/DEPLOYMENT.md.
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = int(os.getenv("WHITENOISE_MAX_AGE", "31536000" if not DEBUG else "0"))
