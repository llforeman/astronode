import json
import logging
import secrets
from datetime import datetime

import stripe
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from extensions import db, csrf
from models import Payment, Subscription, Reading, ReadingType

log = logging.getLogger(__name__)

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

# ── One-time products ────────────────────────────────────────────────────────
# amount_cents is the fallback when the Payment Link has no `product` metadata.
PRODUCTS = {
    'natal':    {'amount_cents': 799,  'link_setting': 'STRIPE_LINK_NATAL'},
    'complete': {'amount_cents': 1799, 'link_setting': 'STRIPE_LINK_COMPLETE'},
}

# Legacy monthly links (basic/vip subscriptions) — kept so existing live
# subscribers keep working and get demoted correctly when their sub ends.
_LEGACY_VIP_MIN_CENTS = 900
_LEGACY_ACTIVE_STATUSES = ('active', 'trialing', 'past_due')


def _stripe():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    return stripe


# ── Public pages ─────────────────────────────────────────────────────────────

@billing_bp.route('/pricing')
def pricing():
    credits = {'natal': 0, 'complete': 0}
    if current_user.is_authenticated:
        from models import Entitlement
        for e in Entitlement.query.filter_by(user_id=current_user.id,
                                             profile_a_id=None).all():
            credits[e.product] = credits.get(e.product, 0) + 1
    return render_template('billing/pricing.html', credits=credits)


# ── Checkout redirects (Stripe Payment Links — no API call at checkout) ─────

@billing_bp.route('/checkout/<product>', methods=['POST'])
@login_required
def checkout(product):
    info = PRODUCTS.get(product)
    if not info:
        abort(404)
    link = current_app.config.get(info['link_setting'], '')
    if not link:
        flash('Los pagos aún no están configurados.')
        return redirect(url_for('billing.pricing'))

    from urllib.parse import urlencode
    params = urlencode({
        'client_reference_id': current_user.id,
        'prefilled_email': current_user.email or '',
    })
    sep = '&' if '?' in link else '?'
    return redirect(f"{link}{sep}{params}", code=303)


@billing_bp.route('/success')
def success():
    flash('¡Pago confirmado! Recibirás tu lectura por email en unos minutos.')
    return redirect(url_for('main.dashboard') if current_user.is_authenticated else url_for('public.landing'))


@billing_bp.route('/cancelled')
def cancelled():
    flash('Pago cancelado.')
    return redirect(url_for('billing.pricing'))


# ── Webhook ──────────────────────────────────────────────────────────────────
# Single source of truth for entitlements. Signed events only.
# Handlers let DB errors raise -> 500 -> Stripe retries. Never swallow them.

@billing_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    s = _stripe()
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    secret     = current_app.config['STRIPE_WEBHOOK_SECRET']
    if not secret:
        abort(400)

    # Verify the signature with Stripe, then parse the payload as a plain
    # dict. (construct_event() returns a StripeObject which does not support
    # .get() — dict-style handlers would raise on every event.)
    try:
        s.WebhookSignature.verify_header(payload.decode('utf-8'), sig_header, secret, tolerance=300)
    except (ValueError, stripe.error.SignatureVerificationError):
        abort(400)
    event = json.loads(payload)

    etype = event.get('type')
    obj   = (event.get('data') or {}).get('object') or {}

    if etype == 'checkout.session.completed':
        _handle_checkout_completed(obj)
    elif etype in ('customer.subscription.created', 'customer.subscription.updated'):
        _sync_legacy_subscription(obj)
    elif etype == 'customer.subscription.deleted':
        _cancel_legacy_subscription(obj)

    return '', 200


# ── Resolution helpers ───────────────────────────────────────────────────────

def _resolve_user(session):
    """Resolve/derive the buyer from a completed checkout session.

    Order: client_reference_id (logged-in buyer) -> existing email ->
    auto-created account with a random password they can claim via reset.
    """
    from models import User
    from security import blind_index

    ref = session.get('client_reference_id')
    if ref:
        try:
            user = User.query.get(int(ref))
        except (ValueError, TypeError):
            user = None
        if user:
            return user

    email = (session.get('customer_details') or {}).get('email') \
            or session.get('customer_email') or ''
    if email:
        existing = User.query.filter_by(email_hash=blind_index(email)).first()
        if existing:
            return existing
        user = User()
        user.set_email(email)
        user.set_password(secrets.token_hex(16))  # they claim it via password reset
        db.session.add(user)
        db.session.flush()
    return user


def _product_for_session(session):
    """Product slug for a one-time checkout.

    Prefers `product` metadata set on the Payment Link in the Stripe
    Dashboard; falls back to the amount paid.
    """
    meta = session.get('metadata') or {}
    slug = (meta.get('product') or '').strip().lower()
    if slug in PRODUCTS:
        return slug
    amount = session.get('amount_total') or 0
    if amount >= PRODUCTS['complete']['amount_cents']:
        return 'complete'
    return 'natal'


def _demote_user(user):
    """Demote a legacy subscriber to free when their subscription ends —
    unless a one-time purchase independently backs their current tier."""
    from models import User, Payment

    if not user or user.tier == 'free':
        return
    rank = {'free': 0, 'natal': 1, 'complete': 2}
    owned = Payment.query.filter_by(user_id=user.id, payment_type='one_time',
                                    status='completed').all()
    owns_rank = max((rank.get(p.product, 0) for p in owned), default=0)
    if rank.get(user.tier, 0) > owns_rank:
        user.tier = 'free'


# ── Webhook handlers ─────────────────────────────────────────────────────────

def _handle_checkout_completed(session):
    from models import Entitlement, Notification, Profile

    # Idempotency: unique stripe_session_id — webhook replays are no-ops.
    if Payment.query.filter_by(stripe_session_id=session.get('id', '')).first():
        return

    user = _resolve_user(session)
    if not user:
        log.error('checkout.session.completed: could not resolve user %s',
                  session.get('id'))
        return

    mode      = session.get('mode')   # 'payment' (one-time) or 'subscription' (legacy)
    payment   = Payment(
        user_id=user.id,
        stripe_session_id=session['id'],
        stripe_payment_id=session.get('payment_intent'),
        amount_cents=session.get('amount_total', 0),
        currency=session.get('currency', 'usd'),
        payment_type='subscription' if mode == 'subscription' else 'one_time',
        status='completed',
    )
    db.session.add(payment)
    db.session.flush()   # assign payment.id before entitlement references it

    if mode == 'subscription':
        # Legacy monthly links — map amount to the old tier names (display only).
        amount = session.get('amount_total', 0)
        tier   = 'complete' if amount >= _LEGACY_VIP_MIN_CENTS else 'natal'
        user.tier       = tier
        payment.product = tier
        db.session.add(Subscription(
            user_id=user.id,
            stripe_subscription_id=session.get('subscription'),
            tier=tier,
        ))
        db.session.commit()
        db.session.add(Notification(user_id=user.id,
                                    message=f'Welcome to Astronode {tier.upper()}!',
                                    link='/readings/'))
        db.session.commit()
        _send_welcome_email(user, tier)
        return

    product = _product_for_session(session)
    payment.product = product

    # Every one-time purchase becomes an unassigned credit the user binds to
    # people from their dashboard: natal = 1 person, complete = 2 people.
    entitlement = Entitlement(user_id=user.id, payment_id=payment.id,
                              product=product)
    db.session.add(entitlement)

    if product == 'natal':
        # Nice default: buying for yourself delivers immediately.
        self_profile = Profile.query.filter_by(user_id=user.id, is_self=True).first()
        if self_profile and self_profile.birth_date and self_profile.birth_place:
            entitlement.profile_a_id = self_profile.id
            entitlement.assigned_at  = datetime.utcnow()
            db.session.commit()
            _deliver_natal(user, self_profile, payment)
            return

        db.session.commit()
        _send_complete_profile_email(user)
        db.session.add(Notification(
            user_id=user.id,
            message='¡Pago confirmado! Tienes 1 lectura natal lista para asignar a cualquier persona desde tu panel.',
            link='/dashboard'))
        db.session.commit()
        return

    # complete pack — needs two people, always assigned from the dashboard.
    db.session.commit()
    _send_welcome_email(user, 'complete')
    db.session.add(Notification(
        user_id=user.id,
        message='¡Pago confirmado! Tienes 1 pack completo para asignar a dos personas desde tu panel.',
        link='/dashboard'))
    db.session.commit()


def _deliver_natal(user, profile, payment):
    """Create + enqueue the natal reading for an assigned natal credit."""
    from models import Notification, Reading, ReadingType

    rtype = ReadingType.query.filter_by(slug='natal', active=True).first() \
            or ReadingType.query.filter_by(active=True).first()
    if not rtype:
        db.session.commit()
        return

    reading = Reading(user_id=user.id, reading_type_id=rtype.id,
                      profile_id=profile.id)
    db.session.add(reading)
    db.session.flush()
    payment.reading_id = reading.id
    db.session.commit()

    from worker import enqueue_reading
    enqueue_reading(reading.id)

    db.session.add(Notification(user_id=user.id,
                                message='¡Pago confirmado! Tu lectura natal está en camino.',
                                link=f'/readings/{reading.id}'))
    db.session.commit()


def _sync_legacy_subscription(sub_obj):
    from models import User

    sub = Subscription.query.filter_by(stripe_subscription_id=sub_obj['id']).first()
    if not sub:
        return
    sub.status = sub_obj.get('status') or sub.status
    period_end = sub_obj.get('current_period_end')
    if period_end:
        sub.current_period_end = datetime.utcfromtimestamp(period_end)
    if sub_obj.get('status') not in _LEGACY_ACTIVE_STATUSES:
        _demote_user(User.query.get(sub.user_id))
    db.session.commit()


def _cancel_legacy_subscription(sub_obj):
    from models import User

    sub = Subscription.query.filter_by(stripe_subscription_id=sub_obj['id']).first()
    if not sub:
        return
    sub.status       = 'cancelled'
    sub.cancelled_at = datetime.utcnow()
    _demote_user(User.query.get(sub.user_id))
    db.session.commit()


# ── Email helpers ────────────────────────────────────────────────────────────
# Fire after commit — a failure must never 500 the webhook, or Stripe's retry
# would hit the idempotency guard and skip the work that already succeeded.

def _send_welcome_email(user, tier):
    try:
        from emails import _send
        _send(
            user.email,
            f'Welcome to Astronode {tier.upper()}!',
            'welcome_subscription',
            user=user,
            tier=tier,
            link=url_for('main.dashboard', _external=True),
        )
    except Exception as e:
        current_app.logger.error('Failed to send welcome email: %s', e)


def _send_complete_profile_email(user):
    try:
        from emails import _send
        _send(
            user.email,
            'Completa tu perfil para recibir tu lectura',
            'complete_profile',
            user=user,
            link=url_for('main.profile', _external=True),
        )
    except Exception as e:
        current_app.logger.error('Failed to send complete_profile email: %s', e)
