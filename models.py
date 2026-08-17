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

    # Legacy birth data columns kept for backward compat (not used by new code)
    birth_date    = db.Column(db.Date, nullable=True)
    birth_time    = db.Column(db.Time, nullable=True)
    birth_place   = db.Column(db.String(255), nullable=True)
    gender        = db.Column(db.String(20), nullable=True)

    # Stripe
    stripe_customer_id = db.Column(db.String(255), nullable=True, index=True)

    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    readings      = db.relationship('Reading', backref='user', lazy='dynamic',
                                    foreign_keys='Reading.user_id')
    payments      = db.relationship('Payment', backref='user', lazy='dynamic')
    profiles      = db.relationship('Profile', lazy='dynamic',
                                    foreign_keys='Profile.user_id')

    def set_email(self, email):
        self.email      = email
        self.email_hash = blind_index(email)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_tier(self, *tiers):
        return self.tier in tiers

    def self_profile(self):
        return Profile.query.filter_by(user_id=self.id, is_self=True).first()


class Profile(db.Model):
    __tablename__ = 'profile'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name        = db.Column(db.String(100), nullable=False, default='Me')
    birth_date  = db.Column(db.Date, nullable=True)
    birth_time  = db.Column(db.Time, nullable=True)
    birth_place = db.Column(db.String(255), nullable=True)
    birth_lat   = db.Column(db.Float, nullable=True)
    birth_lng   = db.Column(db.Float, nullable=True)
    gender      = db.Column(db.String(20), nullable=True)
    is_self     = db.Column(db.Boolean, default=False, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    readings    = db.relationship('Reading', backref='profile', lazy='dynamic',
                                  foreign_keys='Reading.profile_id')

    @property
    def sun_sign(self):
        if not self.birth_date:
            return None
        m, d = self.birth_date.month, self.birth_date.day
        signs = [
            (1, 20, 'Capricorn'), (2, 19, 'Aquarius'), (3, 20, 'Pisces'),
            (4, 20, 'Aries'), (5, 21, 'Taurus'), (6, 21, 'Gemini'),
            (7, 22, 'Cancer'), (8, 23, 'Leo'), (9, 23, 'Virgo'),
            (10, 23, 'Libra'), (11, 22, 'Scorpio'), (12, 22, 'Sagittarius'),
            (12, 31, 'Capricorn'),
        ]
        for month, day, sign in signs:
            if m < month or (m == month and d <= day):
                return sign
        return 'Capricorn'


class ReadingType(db.Model):
    __tablename__ = 'reading_type'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    slug        = db.Column(db.String(50), nullable=True)   # natal|karmic|synastry|davison|solar_return|lunar_return
    description = db.Column(db.Text, nullable=True)
    price_cents = db.Column(db.Integer, nullable=True)    # None = subscription-only
    min_tier    = db.Column(db.String(20), default='free')
    active      = db.Column(db.Boolean, default=True)

    readings    = db.relationship('Reading', backref='reading_type', lazy='dynamic')


class Reading(db.Model):
    __tablename__ = 'reading'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    profile_id      = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=True, index=True)
    reading_type_id = db.Column(db.Integer, db.ForeignKey('reading_type.id'), nullable=False)
    status          = db.Column(db.String(20), default='pending')  # pending | generating | completed | failed
    content         = db.Column(db.Text(16777215), nullable=True)  # generated horoscope text (MEDIUMTEXT)
    chart_image     = db.Column(db.Text(16777215), nullable=True)  # base64 encoded PNG (MEDIUMTEXT)
    params          = db.Column(db.JSON, nullable=True)             # extra data per reading type
    sent_by_email   = db.Column(db.Boolean, default=False)
    job_id          = db.Column(db.String(255), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at    = db.Column(db.DateTime, nullable=True)

    @property
    def profile_name(self):
        if self.profile:
            return self.profile.name
        return 'Unknown'


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


class PlacementContent(db.Model):
    __tablename__ = 'placement_content'

    id           = db.Column(db.Integer, primary_key=True)
    body         = db.Column(db.String(10), nullable=False)   # sun / moon / rising
    sign         = db.Column(db.String(20), nullable=False)   # English: Aries, Taurus...
    seo_body     = db.Column(db.Text, nullable=True)          # 800-1200 words, HTML
    preview_text = db.Column(db.Text, nullable=True)          # 200-300 words, ends mid-thought
    meta_title   = db.Column(db.String(100), nullable=True)
    meta_desc    = db.Column(db.String(200), nullable=True)
    lang         = db.Column(db.String(5), default='es', nullable=False)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('body', 'sign', 'lang', name='uq_placement_lang'),)


class SunMoonInteraction(db.Model):
    __tablename__ = 'sun_moon_interaction'

    id     = db.Column(db.Integer, primary_key=True)
    sign_a = db.Column(db.String(20), nullable=False)  # alphabetically first of the pair
    sign_b = db.Column(db.String(20), nullable=False)  # alphabetically second (or same)
    text   = db.Column(db.Text, nullable=True)          # 1-2 sentences
    lang   = db.Column(db.String(5), default='es', nullable=False)

    __table_args__ = (db.UniqueConstraint('sign_a', 'sign_b', 'lang', name='uq_sunmoon_lang'),)


class Notification(db.Model):
    __tablename__ = 'notification'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    message    = db.Column(db.String(500), nullable=False)
    link       = db.Column(db.String(255), nullable=True)
    read_at    = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
