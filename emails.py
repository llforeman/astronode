import logging
from flask import current_app, render_template, url_for
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from extensions import mail

log = logging.getLogger(__name__)


def make_token(user, salt):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)
    return s.dumps({'uid': user.id, 'pw': (user.password_hash or '')[-16:]})


def read_token(token, salt, max_age=3600):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)
    try:
        data = s.loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None
    from models import User
    user = User.query.get(data['uid'])
    if not user or (user.password_hash or '')[-16:] != data['pw']:
        return None
    return user


def _send(to, subject, template, **ctx):
    msg = Message(
        subject,
        recipients=[to],
        html=render_template(f'emails/{template}.html', **ctx),
    )
    mail.send(msg)


def queue_password_reset(user):
    from extensions import get_redis_client
    from rq import Queue
    token = make_token(user, salt='reset')
    link  = url_for('auth.reset_password', token=token, _external=True)
    q = Queue('mail', connection=get_redis_client())
    q.enqueue(_send_password_reset_task, user.email, link, job_timeout='2m')


def _send_password_reset_task(email, link):
    from app import create_app
    app = create_app()
    with app.app_context():
        _send(email, 'Reset your Astronode password', 'password_reset', link=link)


def send_reading_email(user, reading):
    base_url = current_app.config.get('BASE_URL', 'http://localhost:5000').rstrip('/')
    link = f"{base_url}/readings/{reading.id}"
    _send(
        user.email,
        'Your Astronode Horoscope Reading is Ready',
        'reading_ready',
        user=user,
        reading=reading,
        link=link,
    )
