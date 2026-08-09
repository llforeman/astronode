import os
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, abort
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Reading, ReadingType

readings_bp = Blueprint('readings', __name__, url_prefix='/readings')

_DEV = os.environ.get('DEV_SKIP_PAYMENT', '').lower() in ('1', 'true', 'yes')


@readings_bp.route('/')
@login_required
def index():
    readings = Reading.query.filter_by(user_id=current_user.id)\
                            .order_by(Reading.created_at.desc()).all()
    return render_template('readings/index.html', readings=readings)


@readings_bp.route('/<int:reading_id>')
@login_required
def view(reading_id):
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id).first_or_404()
    return render_template('readings/view.html', reading=reading)


@readings_bp.route('/request/<int:reading_type_id>', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def request_reading(reading_type_id):
    rtype = ReadingType.query.filter_by(id=reading_type_id, active=True).first_or_404()

    if not current_user.birth_date or not current_user.birth_place:
        flash('Please complete your birth data in your profile first.')
        return redirect(url_for('main.profile'))

    # Check if this type requires payment
    if not _DEV:
        if rtype.price_cents and rtype.min_tier == 'free':
            return redirect(url_for('billing.checkout_reading', reading_type_id=reading_type_id))

        # Check tier access
        tier_order = ['free', 'basic', 'vip']
        user_tier_idx = tier_order.index(current_user.tier) if current_user.tier in tier_order else 0
        min_tier_idx  = tier_order.index(rtype.min_tier) if rtype.min_tier in tier_order else 0
        if user_tier_idx < min_tier_idx:
            return redirect(url_for('billing.pricing'))

    reading = Reading(user_id=current_user.id, reading_type_id=rtype.id)
    db.session.add(reading)
    db.session.commit()

    from worker import enqueue_reading
    enqueue_reading(reading.id)

    flash('Your reading is being generated. We\'ll email you when it\'s ready.')
    return redirect(url_for('readings.view', reading_id=reading.id))


@readings_bp.route('/status/<int:reading_id>')
@login_required
def status(reading_id):
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id).first_or_404()
    return jsonify({'status': reading.status})


@readings_bp.route('/dev-generate', methods=['GET', 'POST'])
@login_required
def dev_generate():
    """Synchronous dev route — no Stripe, no Redis. Only active when DEV_SKIP_PAYMENT=1."""
    if not _DEV:
        abort(404)

    if not current_user.birth_date or not current_user.birth_place:
        flash('Complete your birth data in your profile first.')
        return redirect(url_for('main.profile'))

    if request.method == 'GET':
        return render_template('readings/dev_generate.html')

    # Ensure a reading type exists
    rtype = ReadingType.query.filter_by(active=True).first()
    if not rtype:
        rtype = ReadingType(
            name='Carta Natal Completa',
            description='Interpretación completa de tu carta natal con IA.',
            price_cents=999,
            min_tier='free',
            active=True,
        )
        db.session.add(rtype)
        db.session.commit()

    # Create the reading record
    reading = Reading(user_id=current_user.id, reading_type_id=rtype.id,
                      status='generating')
    db.session.add(reading)
    db.session.commit()

    # Run in a background thread so the browser isn't holding the connection open
    reading_id = reading.id
    user_id    = current_user.id

    def _run(app, rid, uid, rt):
        with app.app_context():
            from ai import generate_horoscope
            from models import Reading, User
            u = User.query.get(uid)
            try:
                result = generate_horoscope(u, rt)
                status = 'completed'
            except Exception as e:
                result = None
                status = 'failed'
                print(f'[dev-generate] generation failed: {e}')

            # Release the stale connection held during LLM generation,
            # then re-fetch the reading with a fresh connection to commit.
            db.session.remove()
            r = Reading.query.get(rid)
            r.status = status
            if result:
                r.content      = result['text']
                r.chart_image  = result.get('chart_image')
                r.completed_at = datetime.utcnow()
            db.session.commit()

    import threading
    from flask import current_app
    t = threading.Thread(target=_run, args=(current_app._get_current_object(), reading_id, user_id, rtype), daemon=True)
    t.start()

    return redirect(url_for('readings.view', reading_id=reading.id))
