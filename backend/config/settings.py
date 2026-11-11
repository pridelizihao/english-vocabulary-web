import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DEBUG=0 时必须设置 DJANGO_SECRET_KEY')
    SECRET_KEY = 'dev-only-change-me'
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
    if host.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'corsheaders', 'rest_framework', 'vocabulary',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', 'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': os.environ.get('DJANGO_DB_PATH', BASE_DIR / 'db.sqlite3'),
}}
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
# Cached example-sentence audio (edge-tts); keep it outside the code directory.
AUDIO_CACHE_DIR = os.environ.get('DJANGO_AUDIO_DIR', BASE_DIR / 'audio-cache')
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Uploads are read fully into memory while parsing, so keep a hard ceiling.
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# --- auth ------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.environ.get('DJANGO_SECURE_COOKIES', '0') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
if os.environ.get('DJANGO_USE_X_FORWARDED_PROTO') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = DEBUG  # 生产环境请显式配置 CORS_ALLOWED_ORIGINS
if not DEBUG:
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.environ.get('DJANGO_CORS_ALLOWED_ORIGINS', '').split(',')
        if origin.strip()
    ]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'DJANGO_CSRF_TRUSTED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080',
    ).split(',')
    if origin.strip()
]

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_THROTTLE_RATES': {
        'auth': os.environ.get('DJANGO_AUTH_THROTTLE_RATE', '10/min'),
        'email_code': os.environ.get('DJANGO_EMAIL_CODE_RATE', '3/min'),
    },
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ],
}

# --- email (verification codes / password reset) ---------------------------
# 开发环境默认把邮件打到控制台，不用配 SMTP 也能走完整流程；生产用环境变量
# 设置 DJANGO_EMAIL_BACKEND=...smtp.EmailBackend 与下面的 HOST/PORT 等。
_EMAIL_BACKEND_DEFAULT = (
    'django.core.mail.backends.console.EmailBackend'
    if DEBUG else
    'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_BACKEND = os.environ.get('DJANGO_EMAIL_BACKEND', _EMAIL_BACKEND_DEFAULT)
EMAIL_HOST = os.environ.get('DJANGO_EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('DJANGO_EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('DJANGO_EMAIL_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('DJANGO_EMAIL_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('DJANGO_EMAIL_USE_TLS', '1') == '1'
EMAIL_USE_SSL = os.environ.get('DJANGO_EMAIL_USE_SSL', '0') == '1'
EMAIL_TIMEOUT = int(os.environ.get('DJANGO_EMAIL_TIMEOUT', '10'))
DEFAULT_FROM_EMAIL = os.environ.get(
    'DJANGO_DEFAULT_FROM_EMAIL', '英语单词记忆 <no-reply@localhost>',
)

# 验证码有效期 / 冷却 / 频率上限（秒与次数）。
EMAIL_CODE_TTL_MINUTES = int(os.environ.get('DJANGO_EMAIL_CODE_TTL', '10'))
EMAIL_CODE_COOLDOWN_SECONDS = int(os.environ.get('DJANGO_EMAIL_CODE_COOLDOWN', '60'))
EMAIL_CODE_MAX_ATTEMPTS = int(os.environ.get('DJANGO_EMAIL_CODE_MAX_ATTEMPTS', '5'))
EMAIL_CODE_EMAIL_HOURLY_LIMIT = int(os.environ.get('DJANGO_EMAIL_CODE_EMAIL_HOURLY_LIMIT', '5'))
EMAIL_CODE_IP_HOURLY_LIMIT = int(os.environ.get('DJANGO_EMAIL_CODE_IP_HOURLY_LIMIT', '20'))
