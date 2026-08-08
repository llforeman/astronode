from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models import User

main_bp = Blueprint('main', __name__)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    from models import Reading
    readings = Reading.query.filter_by(user_id=current_user.id)\
                            .order_by(Reading.created_at.desc()).limit(5).all()
    return render_template('main/dashboard.html', readings=readings)


@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        from datetime import date, time as dtime
        birth_date  = request.form.get('birth_date')
        birth_time  = request.form.get('birth_time')
        birth_place = request.form.get('birth_place', '').strip()
        if birth_date:
            try:
                current_user.birth_date = date.fromisoformat(birth_date)
            except ValueError:
                flash('Invalid birth date.')
                return render_template('main/profile.html')
        if birth_time:
            try:
                h, m = birth_time.split(':')
                current_user.birth_time = dtime(int(h), int(m))
            except (ValueError, AttributeError):
                flash('Invalid birth time.')
                return render_template('main/profile.html')
        current_user.birth_place = birth_place or None
        db.session.commit()
        flash('Profile updated.')
        return redirect(url_for('main.profile'))
    return render_template('main/profile.html')


@main_bp.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    from models import Notification
    from datetime import datetime
    Notification.query.filter_by(user_id=current_user.id, read_at=None)\
                      .update({'read_at': datetime.utcnow()})
    db.session.commit()
    return redirect(request.referrer or url_for('main.dashboard'))
