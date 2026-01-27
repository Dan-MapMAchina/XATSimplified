"""
Django settings for XATSimplified project.

Simplified performance monitoring backend for multi-server workload evaluation.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Sentry Error Tracking
# ---------------------------------------------------------------------------
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
        profiles_sample_rate=float(os.environ.get('SENTRY_PROFILES_SAMPLE_RATE', '0.1')),
        send_default_pii=False,
        environment=os.environ.get('SENTRY_ENVIRONMENT', 'development'),
    )

# ---------------------------------------------------------------------------
# Azure Key Vault Integration (optional - for Azure deployments)
# ---------------------------------------------------------------------------
AZURE_KEY_VAULT_URL = os.environ.get('AZURE_KEY_VAULT_URL', '')

def get_secret_from_keyvault(secret_name, default=None):
    """Retrieve a secret from Azure Key Vault if configured, otherwise return default."""
    if not AZURE_KEY_VAULT_URL:
        return default
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=AZURE_KEY_VAULT_URL, credential=credential)
        secret = client.get_secret(secret_name)
        return secret.value
    except Exception:
        return default

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# Try Azure Key Vault first, then environment variable, then default
SECRET_KEY = get_secret_from_keyvault('django-secret-key') or os.environ.get('SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
SHARED_APPS = [
    'django_tenants',
    'collectors.apps.CollectorsConfig',  # Contains tenant model

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'allauth',
    'allauth.account',

    # Local apps
    'core',
    'authentication',
    'cloud_providers',
]

TENANT_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',

    # Tenant-specific apps
    'collectors.apps.CollectorsConfig',
    'authentication',
]

# Build INSTALLED_APPS avoiding duplicates
INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS
    if app not in SHARED_APPS and app + '.apps.CollectorsConfig' not in SHARED_APPS
]

# Multi-tenancy configuration
TENANT_MODEL = "collectors.Tenant"
TENANT_DOMAIN_MODEL = "collectors.Domain"
PUBLIC_SCHEMA_NAME = 'public'

MIDDLEWARE = [
    'django_tenants.middleware.main.TenantMainMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'core.middleware.CSRFExemptAPIMiddleware',  # Must be before CSRF middleware
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# Database - PostgreSQL with django-tenants
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/xatsimplified')

DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL)
}

DATABASES['default']['ENGINE'] = 'django_tenants.postgresql_backend'

DATABASE_ROUTERS = (
    'django_tenants.routers.TenantSyncRouter',
)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files (uploads)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Site ID for allauth
SITE_ID = 1

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# JWT Configuration
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# CORS Configuration - Allow all origins for development
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Allauth configuration
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = True
ACCOUNT_AUTHENTICATION_METHOD = 'username_email'
ACCOUNT_EMAIL_VERIFICATION = 'optional'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100MB

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}

# ---------------------------------------------------------------------------
# Rate Limiting Configuration (django-ratelimit)
# ---------------------------------------------------------------------------
# Cache backend for rate limiting (uses default cache)
RATELIMIT_USE_CACHE = 'default'

# Enable rate limiting (can be disabled for testing)
RATELIMIT_ENABLE = os.environ.get('RATELIMIT_ENABLE', 'True').lower() == 'true'

# Default rate limits (requests/period)
RATELIMIT_DEFAULT_RATE = os.environ.get('RATELIMIT_DEFAULT_RATE', '100/m')  # 100 requests per minute

# Rate limit configuration by endpoint type
RATELIMIT_AUTH = os.environ.get('RATELIMIT_AUTH', '5/m')        # Login/register: 5 per minute
RATELIMIT_API = os.environ.get('RATELIMIT_API', '60/m')         # General API: 60 per minute
RATELIMIT_UPLOAD = os.environ.get('RATELIMIT_UPLOAD', '10/m')   # Upload endpoints: 10 per minute
RATELIMIT_TRICKLE = os.environ.get('RATELIMIT_TRICKLE', '120/m')  # Trickle data: 120 per minute

# Add cache backend for rate limiting
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Use Redis if available (recommended for production)
REDIS_URL = os.environ.get('REDIS_URL', '')
if REDIS_URL:
    CACHES['default'] = {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
    }
