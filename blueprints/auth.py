from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from extensions import db, limiter
from models import User
from security import blind_index

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

DUMMY_HASH = generate_password_hash('dummy')


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not email or not password:
            flash('Email and password are required.')
            return render_template('auth/register.html')
        if User.query.filter_by(email_hash=blind_index(email)).first():
            flash('An account with that email already exists.')
            return render_template('auth/register.html')
        user = User()
        user.set_email(email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Welcome to Astronode!')
        return redirect(url_for('main.dashboard'))
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email_hash=blind_index(email)).first()
        if user:
            valid = user.check_password(password)
        else:
            from werkzeug.security import check_password_hash
            check_password_hash(DUMMY_HASH, password)
            valid = False
        if valid and user.active:
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))
        flash('Invalid email or password.')
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('public.landing'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("3 per hour")
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user  = User.query.filter_by(email_hash=blind_index(email)).first()
        if user:
            from emails import queue_password_reset
            queue_password_reset(user)
        flash('If that address has an account, a reset link is on its way.')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from emails import read_token
    user = read_token(token, salt='reset')
    if not user:
        flash('This reset link is invalid or has expired.')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        if len(password) < 8:
            flash('Password must be at least 8 characters.')
            return render_template('auth/reset_password.html', token=token)
        user.set_password(password)
        db.session.commit()
        flash('Password updated. Please log in.')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token)
