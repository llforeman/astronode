import os
import sys
from datetime import timedelta

is_debug = os.getenv('FLASK_ENV', 'production').lower() == 'development'

def _require_env(name):
    value = os.getenv(name)
    if not value:
        if not is_debug:
            sys.exit(f"[FATAL] {name} not set")
        return f'MISSING_{name}'
    return value


class Config:
    SECRET_KEY = _require_env('SECRET_KEY')

    SQLALCHEMY_DATABASE_URI = _require_env('DATABASE_URL')
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_timeout': 30,
        'max_overflow': 10,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    _redis = os.environ.get('REDIS_URL', '')
    RATELIMIT_STORAGE_URI = f"{_redis}/1" if _redis else 'memory://'

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = not is_debug
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)

    MAIL_SERVER   = os.getenv('MAIL_SERVER', 'smtp.hostinger.com')
    MAIL_PORT     = int(os.getenv('MAIL_PORT', 465))
    MAIL_USE_SSL  = True
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', os.getenv('MAIL_USERNAME', ''))
    MAIL_SUPPRESS_SEND = is_debug

    AI_API_KEY = _require_env('AI_API_KEY')
    AI_API_URL = os.getenv('AI_API_URL', 'https://openrouter.ai/api/v1')
    AI_MODEL   = os.getenv('AI_MODEL', 'meta-llama/llama-3.3-70b-instruct')

    STRIPE_SECRET_KEY      = _require_env('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = _require_env('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET  = _require_env('STRIPE_WEBHOOK_SECRET')

    STRIPE_LINK_READING = os.getenv('STRIPE_LINK_READING', '')
    STRIPE_LINK_BASIC   = os.getenv('STRIPE_LINK_BASIC', '')
    STRIPE_LINK_VIP     = os.getenv('STRIPE_LINK_VIP', '')
