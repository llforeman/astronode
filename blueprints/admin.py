from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from extensions import db
from models import User, Reading, Payment, Subscription

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def superadmin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'superadmin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@login_required
@superadmin_required
def index():
    users_count    = User.query.count()
    readings_count = Reading.query.count()
    payments_count = Payment.query.filter_by(status='completed').count()
    return render_template('admin/index.html',
                           users_count=users_count,
                           readings_count=readings_count,
                           payments_count=payments_count)


@admin_bp.route('/users')
@login_required
@superadmin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/readings')
@login_required
@superadmin_required
def readings():
    all_readings = Reading.query.order_by(Reading.created_at.desc()).limit(100).all()
    return render_template('admin/readings.html', readings=all_readings)


@admin_bp.route('/users/<int:user_id>/set-tier', methods=['POST'])
@login_required
@superadmin_required
def set_tier(user_id):
    user = User.query.get_or_404(user_id)
    tier = request.form.get('tier')
    if tier in ('free', 'basic', 'vip'):
        user.tier = tier
        db.session.commit()
        flash(f'User tier updated to {tier}.')
    return redirect(url_for('admin.users'))
