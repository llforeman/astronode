import os
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_migrate import Migrate
import redis

db            = SQLAlchemy()
login_manager = LoginManager()
csrf          = CSRFProtect()
limiter       = Limiter(key_func=get_remote_address)
mail          = Mail()
migrate       = Migrate()


def get_redis_client():
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    return redis.from_url(url)
