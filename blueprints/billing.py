import stripe
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from extensions import db, csrf
from models import Payment, Subscription, ReadingType, Reading

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

TIER_PRICES = {
    'basic': {'price_id': None, 'name': 'Basic'},
    'vip':   {'price_id': None, 'name': 'VIP'},
}


def _stripe():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    return stripe


@billing_bp.route('/pricing')
def pricing():
    return render_template('billing/pricing.html')


@billing_bp.route('/checkout/reading/<int:reading_type_id>', methods=['POST'])
@login_required
def checkout_reading(reading_type_id):
    rtype = ReadingType.query.filter_by(id=reading_type_id, active=True).first_or_404()
    if not rtype.price_cents:
        abort(400)

    s = _stripe()
    session = s.checkout.Session.create(
        payment_method_types=['card'],
        mode='payment',
        customer_email=current_user.email,
        line_items=[{
            'price_data': {
                'currency': 'eur',
                'unit_amount': rtype.price_cents,
                'product_data': {'name': rtype.name},
            },
            'quantity': 1,
        }],
        metadata={
            'user_id': current_user.id,
            'reading_type_id': reading_type_id,
            'payment_type': 'one_time',
        },
        success_url=url_for('billing.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=url_for('billing.cancelled', _external=True),
    )
    return redirect(session.url, code=303)


@billing_bp.route('/checkout/subscribe/<tier>', methods=['POST'])
@login_required
def checkout_subscribe(tier):
    if tier not in TIER_PRICES:
        abort(400)
    price_id = TIER_PRICES[tier]['price_id']
    if not price_id:
        flash('Subscription plans are not yet configured. Check back soon.')
        return redirect(url_for('billing.pricing'))

    s = _stripe()
    session = s.checkout.Session.create(
        payment_method_types=['card'],
        mode='subscription',
        customer_email=current_user.email,
        line_items=[{'price': price_id, 'quantity': 1}],
        metadata={
            'user_id': current_user.id,
            'tier': tier,
            'payment_type': 'subscription',
        },
        success_url=url_for('billing.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=url_for('billing.cancelled', _external=True),
    )
    return redirect(session.url, code=303)


@billing_bp.route('/success')
@login_required
def success():
    flash('Payment successful! Your reading will be generated shortly.')
    return redirect(url_for('main.dashboard'))


@billing_bp.route('/cancelled')
def cancelled():
    flash('Payment cancelled.')
    return redirect(url_for('billing.pricing'))


@billing_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    s = _stripe()
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    try:
        event = s.Webhook.construct_event(
            payload, sig_header, current_app.config['STRIPE_WEBHOOK_SECRET'])
    except (ValueError, stripe.error.SignatureVerificationError):
        abort(400)

    if event['type'] == 'checkout.session.completed':
        _handle_checkout_completed(event['data']['object'])
    elif event['type'] == 'customer.subscription.updated':
        _handle_subscription_updated(event['data']['object'])
    elif event['type'] == 'customer.subscription.deleted':
        _handle_subscription_deleted(event['data']['object'])

    return '', 200


def _handle_checkout_completed(session):
    from models import User, Notification
    from datetime import datetime

    meta     = session.get('metadata', {})
    user_id  = meta.get('user_id')
    pay_type = meta.get('payment_type')
    if not user_id:
        return

    from models import User
    user = User.query.get(int(user_id))
    if not user:
        return

    payment = Payment(
        user_id=int(user_id),
        stripe_session_id=session['id'],
        stripe_payment_id=session.get('payment_intent'),
        amount_cents=session.get('amount_total', 0),
        currency=session.get('currency', 'eur'),
        payment_type=pay_type,
        status='completed',
    )
    db.session.add(payment)

    if pay_type == 'one_time':
        reading_type_id = meta.get('reading_type_id')
        if reading_type_id:
            reading = Reading(
                user_id=int(user_id),
                reading_type_id=int(reading_type_id),
            )
            db.session.add(reading)
            db.session.flush()
            payment.reading_id = reading.id
            from worker import enqueue_reading
            enqueue_reading(reading.id)

    elif pay_type == 'subscription':
        tier = meta.get('tier')
        if tier:
            user.tier = tier
            sub = Subscription(
                user_id=int(user_id),
                stripe_subscription_id=session.get('subscription'),
                tier=tier,
            )
            db.session.add(sub)

    notif = Notification(
        user_id=int(user_id),
        message='Payment confirmed! Your reading is being prepared.',
        link=url_for('readings.index'),
    )
    db.session.add(notif)
    db.session.commit()


def _handle_subscription_updated(sub_obj):
    from models import User
    stripe_sub_id = sub_obj['id']
    sub = Subscription.query.filter_by(stripe_subscription_id=stripe_sub_id).first()
    if not sub:
        return
    sub.status = sub_obj['status']
    from datetime import datetime
    sub.current_period_end = datetime.utcfromtimestamp(sub_obj['current_period_end'])
    if sub_obj['status'] != 'active':
        user = User.query.get(sub.user_id)
        if user:
            user.tier = 'free'
    db.session.commit()


def _handle_subscription_deleted(sub_obj):
    from models import User
    from datetime import datetime
    stripe_sub_id = sub_obj['id']
    sub = Subscription.query.filter_by(stripe_subscription_id=stripe_sub_id).first()
    if not sub:
        return
    sub.status = 'cancelled'
    sub.cancelled_at = datetime.utcnow()
    user = User.query.get(sub.user_id)
    if user:
        user.tier = 'free'
    db.session.commit()


def url_for(endpoint, **kwargs):
    from flask import url_for as _url_for
    return _url_for(endpoint, **kwargs)
