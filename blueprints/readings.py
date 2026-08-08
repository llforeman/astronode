from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, abort
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Reading, ReadingType

readings_bp = Blueprint('readings', __name__, url_prefix='/readings')


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
