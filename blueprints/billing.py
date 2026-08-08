import stripe
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from extensions import db, csrf
from models import Payment, Subscription, Reading, ReadingType

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

# Prices in cents — used to determine tier from subscription amount
VIP_MIN_CENTS = 900  # anything >= €9.00/mo is VIP


def _stripe():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    return stripe


# ── Public pages ─────────────────────────────────────────────────────────────

@billing_bp.route('/pricing')
def pricing():
    return render_template('billing/pricing.html')


# ── Checkout redirects ────────────────────────────────────────────────────────

@billing_bp.route('/checkout/reading/<int:reading_type_id>', methods=['POST'])
@login_required
def checkout_reading(reading_type_id):
    ReadingType.query.filter_by(id=reading_type_id, active=True).first_or_404()
    link = current_app.config.get('STRIPE_LINK_READING', '')
    if not link:
        flash('Payments are not yet configured.')
        return redirect(url_for('billing.pricing'))
    return redirect(
        f"{link}?client_reference_id={current_user.id}"
        f"&prefilled_email={current_user.email}",
        code=303,
    )


@billing_bp.route('/checkout/subscribe/<tier>', methods=['POST'])
@login_required
def checkout_subscribe(tier):
    link_map = {
        'basic': current_app.config.get('STRIPE_LINK_BASIC', ''),
        'vip':   current_app.config.get('STRIPE_LINK_VIP', ''),
    }
    link = link_map.get(tier, '')
    if not link:
        flash('This plan is not yet available.')
        return redirect(url_for('billing.pricing'))
    return redirect(
        f"{link}?client_reference_id={current_user.id}"
        f"&prefilled_email={current_user.email}",
        code=303,
    )


@billing_bp.route('/success')
def success():
    flash('Payment confirmed! Check your email shortly.')
    return redirect(url_for('main.dashboard') if current_user.is_authenticated else url_for('public.landing'))


@billing_bp.route('/cancelled')
def cancelled():
    flash('Payment cancelled.')
    return redirect(url_for('billing.pricing'))


# ── Webhook ───────────────────────────────────────────────────────────────────

@billing_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    s = _stripe()
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    secret     = current_app.config['STRIPE_WEBHOOK_SECRET']

    try:
        event = s.Webhook.construct_event(payload, sig_header, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        abort(400)

    obj = event['data']['object']
    try:
        if event['type'] == 'checkout.session.completed':
            _handle_checkout_completed(obj)
        elif event['type'] == 'customer.subscription.updated':
            _handle_subscription_updated(obj)
        elif event['type'] == 'customer.subscription.deleted':
            _handle_subscription_deleted(obj)
    except Exception as e:
        current_app.logger.error('Webhook handler error [%s]: %s', event['type'], e)

    return '', 200


# ── Webhook handlers ──────────────────────────────────────────────────────────

def _get_or_create_user(email):
    """Find user by email or create a new account for them."""
    from models import User
    from security import blind_index
    import secrets

    user = User.query.filter_by(email_hash=blind_index(email)).first()
    if not user:
        user = User()
        user.set_email(email)
        user.set_password(secrets.token_hex(16))  # random password — they reset it to log in
        db.session.add(user)
        db.session.flush()
    return user


def _handle_checkout_completed(session):
    from datetime import datetime
    from models import Notification

    email   = (session.get('customer_details') or {}).get('email', '')
    mode    = session.get('mode')   # 'payment' or 'subscription'
    user_id = session.get('client_reference_id')

    # Resolve user — prefer client_reference_id (logged-in buyer), fall back to email
    from models import User
    if user_id:
        user = User.query.get(int(user_id))
    elif email:
        user = _get_or_create_user(email)
    else:
        current_app.logger.error('Webhook: no user_id or email in session %s', session['id'])
        return

    if not user:
        return

    # Record payment
    payment = Payment(
        user_id=user.id,
        stripe_session_id=session['id'],
        stripe_payment_id=session.get('payment_intent'),
        amount_cents=session.get('amount_total', 0),
        currency=session.get('currency', 'eur'),
        payment_type='one_time' if mode == 'payment' else 'subscription',
        status='completed',
    )
    db.session.add(payment)

    if mode == 'payment':
        # One-time reading — use first active reading type
        rtype = ReadingType.query.filter_by(active=True).first()
        if rtype and user.birth_date and user.birth_place:
            reading = Reading(user_id=user.id, reading_type_id=rtype.id)
            db.session.add(reading)
            db.session.flush()
            payment.reading_id = reading.id
            db.session.commit()
            from worker import enqueue_reading
            enqueue_reading(reading.id)
        else:
            # No birth data yet — notify them to complete profile
            db.session.commit()
            _send_complete_profile_email(user)

    elif mode == 'subscription':
        amount = session.get('amount_total', 0)
        tier   = 'vip' if amount >= VIP_MIN_CENTS else 'basic'
        user.tier = tier
        sub = Subscription(
            user_id=user.id,
            stripe_subscription_id=session.get('subscription'),
            tier=tier,
        )
        db.session.add(sub)
        db.session.commit()
        _send_welcome_subscription_email(user, tier)

    notif = Notification(
        user_id=user.id,
        message='Payment confirmed! Your reading is on its way.' if mode == 'payment' else f'Welcome to {user.tier.upper()}!',
        link='/readings/',
    )
    db.session.add(notif)
    db.session.commit()


def _handle_subscription_updated(sub_obj):
    from models import User
    from datetime import datetime

    sub = Subscription.query.filter_by(stripe_subscription_id=sub_obj['id']).first()
    if not sub:
        return
    sub.status = sub_obj['status']
    sub.current_period_end = datetime.utcfromtimestamp(sub_obj['current_period_end'])
    if sub_obj['status'] != 'active':
        user = User.query.get(sub.user_id)
        if user:
            user.tier = 'free'
    db.session.commit()


def _handle_subscription_deleted(sub_obj):
    from models import User
    from datetime import datetime

    sub = Subscription.query.filter_by(stripe_subscription_id=sub_obj['id']).first()
    if not sub:
        return
    sub.status     = 'cancelled'
    sub.cancelled_at = datetime.utcnow()
    user = User.query.get(sub.user_id)
    if user:
        user.tier = 'free'
    db.session.commit()


# ── Email helpers ─────────────────────────────────────────────────────────────

def _send_complete_profile_email(user):
    try:
        from emails import _send
        _send(
            user.email,
            'Complete your Astronode profile to get your reading',
            'complete_profile',
            user=user,
            link=url_for('main.profile', _external=True),
        )
    except Exception as e:
        current_app.logger.error('Failed to send complete_profile email: %s', e)


def _send_welcome_subscription_email(user, tier):
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
        current_app.logger.error('Failed to send welcome_subscription email: %s', e)
