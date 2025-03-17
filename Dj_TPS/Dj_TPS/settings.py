import os.path
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from django.utils.log import RequireDebugFalse
import logging

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
# bool(os.getenv('DEBUG'))

# 'ALLOWED_HOSTS' should be a single string of hosts with a space between each.
# For example: 'ALLOWED_HOSTS=localhost 127.0.0.1 [::1]'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS').split(' ')

# SSH settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Security
SESSION_COOKIE_HTTPONLY = True # Значение по умолчанию, можно и не писать
CSRF_COOKIE_HTTPONLY = True  # Значение по умолчанию, можно и не писать
SESSION_COOKIE_SAMESITE = 'Lax'  # или 'Strict' Lax - Значение по умолчанию, можно и не писать
CSRF_COOKIE_SAMESITE = 'Lax'     # или 'Strict' Lax - Значение по умолчанию, можно и не писать
# Подробнее - https://docs.djangoproject.com/en/5.0/ref/settings/

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_filters',
    'background_task',
    'tph_system.apps.TphSystemConfig',
    'users.apps.UsersConfig',
    'axes',
    'debug_toolbar',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'tph_system.middleware.CurrentUserMiddleware',
    'tph_system.middleware.ErrorLoggingMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',

    # AxesMiddleware should be the last middleware in the MIDDLEWARE list.
    # It only formats user lockout messages and renders Axes lockout responses
    # on failed user authentication attempts from login views.
    # If you do not want Axes to override the authentication response
    # you can skip installing the middleware and use your own views.
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'Dj_TPS.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'Dj_TPS.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.getenv('POSTGRES_DB'),
        'USER': os.getenv('POSTGRES_USER'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD'),
        'HOST': os.getenv('POSTGRES_HOST'),
        'PORT': os.getenv('POSTGRES_PORT'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

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

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    )
}

SIMPLE_JWT = {
    'SIGNING_KEY': os.getenv('SECRET_KEY'),
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
}

AUTHENTICATION_BACKENDS = [
    # AxesStandaloneBackend should be the first backend in the AUTHENTICATION_BACKENDS list.
    'axes.backends.AxesStandaloneBackend',

    # Django ModelBackend is the default authentication backend.
    'django.contrib.auth.backends.ModelBackend',
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'ru'

TIME_ZONE = 'Europe/Moscow'

DATETIME_FORMAT = 'd.m.Y - H:i:s'

USE_I18N = True
USE_L10N = False
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATICFILES_DIRS = []

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'main_page'
LOGOUT_REDIRECT_URL = 'users:login'
LOGIN_URL = 'users:login'

SESSION_COOKIE_AGE = 60 * 60 * 4    # 4 часа
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# Настройки для background tasks (необязательно)
MAX_ATTEMPTS = 3  # Максимальное число попыток выполнения задачи

# Axes settings
AXES_FAILURE_LIMIT = 10
AXES_LOCK_OUT_AT_FAILURE = True
AXES_COOLOFF_TIME = 0.083   # lockout 5 mins
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
# Блокировка только по username. Если хотим по пользаку или ip, то ["username", "ip_address"]
# А если хотим по комбинации username и ip, то [["username", "ip_address"]]
AXES_LOCKOUT_PARAMETERS = ["username"]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_CALLABLE = 'users.views.user_lockout'

# For django-debug
INTERNAL_IPS = [
    "127.0.0.1",
]


class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        # Очищаем чувствительные данные из записи лога
        if hasattr(record, 'request'):
            request = record.request
            # Удаляем куки
            if hasattr(request, 'COOKIES'):
                request.COOKIES = '<<COOKIES BLURRED>>'
            # Удаляем заголовки с авторизацией
            if 'HTTP_AUTHORIZATION' in request.META:
                request.META['HTTP_AUTHORIZATION'] = '<<AUTH BLURRED>>'
            # Очищаем POST-данные
            if request.method == 'POST':
                request.POST = '<<POST DATA BLURRED>>'
        return True


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': RequireDebugFalse,
        },
        'sensitive_data': {
            '()': SensitiveDataFilter,
        }
    },
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'C:/Users/alexi/PycharmProjects/TPS/Dj_TPS/django_errors.log',
            'maxBytes': 1024*1024*5,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'filters': ['require_debug_false', 'sensitive_data'],
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'filters': ['require_debug_false', 'sensitive_data'],
            'include_html': False,  # Не отправлять HTML-отчеты
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['error_file', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
    }
}