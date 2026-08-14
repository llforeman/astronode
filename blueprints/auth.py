from flask import Blueprint, render_template, redirect, url_for, request, flash, session
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
            flash('El email y la contraseña son obligatorios.')
            return render_template('auth/register.html')
        if User.query.filter_by(email_hash=blind_index(email)).first():
            flash('Ya existe una cuenta con ese email.')
            return render_template('auth/register.html')
        user = User()
        user.set_email(email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)

        # If user came from the free chart tool, send them to profiles to save it
        if session.get('chart_prefill'):
            flash('¡Bienvenido/a a Astronode! Guarda tu carta como perfil abajo.')
            return redirect(url_for('main.profiles'))

        flash('¡Bienvenido/a a Astronode!')
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
        flash('Email o contraseña incorrectos.')
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
        flash('Si esa dirección tiene cuenta, te enviamos un enlace de restablecimiento.')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from emails import read_token
    user = read_token(token, salt='reset')
    if not user:
        flash('Este enlace de restablecimiento no es válido o ha caducado.')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.')
            return render_template('auth/reset_password.html', token=token)
        user.set_password(password)
        db.session.commit()
        flash('Contraseña actualizada. Por favor, inicia sesión.')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token)
