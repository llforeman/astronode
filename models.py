from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from security import EncryptedField, blind_index


class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(EncryptedField, nullable=False)
    email_hash    = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default='user')  # user | superadmin
    tier          = db.Column(db.String(20), nullable=False, default='free')  # free | basic | vip

    # Birth data for horoscope generation
    birth_date    = db.Column(db.Date, nullable=True)
    birth_time    = db.Column(db.Time, nullable=True)
    birth_place   = db.Column(db.String(255), nullable=True)

    # Stripe
    stripe_customer_id = db.Column(db.String(255), nullable=True, index=True)

    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    readings      = db.relationship('Reading', backref='user', lazy='dynamic')
    payments      = db.relationship('Payment', backref='user', lazy='dynamic')

    def set_email(self, email):
        self.email      = email
        self.email_hash = blind_index(email)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_tier(self, *tiers):
        return self.tier in tiers


class ReadingType(db.Model):
    __tablename__ = 'reading_type'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price_cents = db.Column(db.Integer, nullable=True)    # None = subscription-only
    min_tier    = db.Column(db.String(20), default='free')
    active      = db.Column(db.Boolean, default=True)

    readings    = db.relationship('Reading', backref='reading_type', lazy='dynamic')


class Reading(db.Model):
    __tablename__ = 'reading'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    reading_type_id = db.Column(db.Integer, db.ForeignKey('reading_type.id'), nullable=False)
    status          = db.Column(db.String(20), default='pending')  # pending | generating | completed | failed
    content         = db.Column(db.Text, nullable=True)            # generated horoscope text
    chart_image     = db.Column(db.MediumText, nullable=True)     # base64 encoded PNG
    sent_by_email   = db.Column(db.Boolean, default=False)
    job_id          = db.Column(db.String(255), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at    = db.Column(db.DateTime, nullable=True)


class Payment(db.Model):
    __tablename__ = 'payment'

    id                  = db.Column(db.Integer, primary_key=True)
    user_id             = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    stripe_payment_id   = db.Column(db.String(255), nullable=True, index=True)
    stripe_session_id   = db.Column(db.String(255), nullable=True, index=True)
    amount_cents        = db.Column(db.Integer, nullable=False)
    currency            = db.Column(db.String(10), default='eur')
    payment_type        = db.Column(db.String(20), nullable=False)  # one_time | subscription
    status              = db.Column(db.String(20), default='pending')  # pending | completed | failed | refunded
    reading_id          = db.Column(db.Integer, db.ForeignKey('reading.id'), nullable=True)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)


class Subscription(db.Model):
    __tablename__ = 'subscription'

    id                       = db.Column(db.Integer, primary_key=True)
    user_id                  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    stripe_subscription_id   = db.Column(db.String(255), nullable=True, unique=True, index=True)
    tier                     = db.Column(db.String(20), nullable=False)  # basic | vip
    status                   = db.Column(db.String(20), default='active')  # active | cancelled | past_due
    current_period_end       = db.Column(db.DateTime, nullable=True)
    created_at               = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_at             = db.Column(db.DateTime, nullable=True)


class Notification(db.Model):
    __tablename__ = 'notification'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    message    = db.Column(db.String(500), nullable=False)
    link       = db.Column(db.String(255), nullable=True)
    read_at    = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
