import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    return int(os.getenv(name, str(default)))


def parse_csv_env(raw_value):
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def parse_opensearch_hosts(raw_hosts):
    hosts = []
    for item in raw_hosts.split(","):
        host_item = item.strip()
        if not host_item:
            continue
        if ":" in host_item:
            host, port = host_item.split(":", 1)
            hosts.append({"host": host.strip(), "port": int(port.strip())})
        else:
            hosts.append({"host": host_item, "port": 9200})
    return hosts


def build_databases_config(base_dir):
    engine = os.getenv("DJANGO_DB_ENGINE", "django.db.backends.mysql")

    if engine == "django.db.backends.sqlite3":
        return {
            "default": {
                "ENGINE": engine,
                "NAME": os.getenv("DJANGO_DB_NAME", str(base_dir / "db.sqlite3")),
            }
        }

    return {
        "default": {
            "ENGINE": engine,
            "NAME": os.getenv("DJANGO_DB_NAME", "online"),
            "USER": os.getenv("DJANGO_DB_USER", "root"),
            "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", "MyPass123!"),
            "HOST": os.getenv("DJANGO_DB_HOST", "192.168.23.204"),
            "PORT": os.getenv("DJANGO_DB_PORT", "3306"),
            "OPTIONS": {
                "charset": os.getenv("DJANGO_DB_CHARSET", "utf8mb4"),
            },
        }
    }

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "C0d3x_9vK2!mQ7@tLp4#sX8$wRn5%yH1^bF6&jD3*zUa0_PqWeRtYuIo",
)
DEBUG = env_bool("DJANGO_DEBUG", True)
FORCE_HTTPS = env_bool("DJANGO_FORCE_HTTPS", False)
FORCE_SCRIPT_NAME = os.getenv("DJANGO_FORCE_SCRIPT_NAME", "").rstrip("/") or None
EMBED_API_BASE_URL = os.getenv("DJANGO_EMBED_API_BASE_URL", "http://192.168.23.201:8000").rstrip("/")
CORS_ALLOWED_ORIGINS = parse_csv_env(
    os.getenv(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "http://192.168.23.201:8080,http://127.0.0.1:8080,http://localhost:8080",
    )
)

ALLOWED_HOSTS = ['192.168.23.201', 'localhost', '127.0.0.1', '192.168.23.204']

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'db_display',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'data_viewer.middleware.SimpleCORSMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'data_viewer.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'data_viewer.wsgi.application'

DATABASES = build_databases_config(BASE_DIR)

OPENSEARCH_CONFIG = {
    'hosts': parse_opensearch_hosts(os.getenv("OPENSEARCH_HOSTS", "192.168.23.204:9200")),
    'http_auth': (
        os.getenv("OPENSEARCH_USERNAME", "admin"),
        os.getenv("OPENSEARCH_PASSWORD", "MyStrongPass123!"),
    ),
    'use_ssl': env_bool("OPENSEARCH_USE_SSL", True),
    'verify_certs': env_bool("OPENSEARCH_VERIFY_CERTS", False),
    'ssl_show_warn': env_bool("OPENSEARCH_SSL_SHOW_WARN", False),
    'timeout': env_int("OPENSEARCH_TIMEOUT", 60),
    'max_retries': env_int("OPENSEARCH_MAX_RETRIES", 2),
    'retry_on_timeout': env_bool("OPENSEARCH_RETRY_ON_TIMEOUT", True),
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

STATIC_URL = os.getenv(
    "DJANGO_STATIC_URL",
    f"{FORCE_SCRIPT_NAME}/static/" if FORCE_SCRIPT_NAME else "/static/",
)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECURE_HSTS_SECONDS = 31536000 if FORCE_HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = FORCE_HTTPS
SECURE_HSTS_PRELOAD = FORCE_HTTPS
SECURE_SSL_REDIRECT = FORCE_HTTPS
SESSION_COOKIE_SECURE = FORCE_HTTPS
CSRF_COOKIE_SECURE = FORCE_HTTPS

X_FRAME_OPTIONS = 'DENY'
