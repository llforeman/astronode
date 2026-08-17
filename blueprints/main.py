import datetime as dt
import logging

from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user
from extensions import db

log = logging.getLogger(__name__)

main_bp = Blueprint('main', __name__)

MAX_PROFILES = 25


@main_bp.route('/dashboard')
@login_required
def dashboard():
    from models import Reading, Profile
    readings = Reading.query.filter_by(user_id=current_user.id)\
                            .order_by(Reading.created_at.desc()).limit(5).all()
    profiles = Profile.query.filter_by(user_id=current_user.id)\
                            .order_by(Profile.is_self.desc(), Profile.created_at.asc()).all()
    return render_template('main/dashboard.html', readings=readings, profiles=profiles)


# ── Profiles ──────────────────────────────────────────────────────────────────

@main_bp.route('/profiles')
@login_required
def profiles():
    from models import Profile, ReadingType
    all_profiles  = Profile.query.filter_by(user_id=current_user.id)\
                                 .order_by(Profile.is_self.desc(), Profile.created_at.asc()).all()
    reading_types = ReadingType.query.filter_by(active=True).all()
    prefill       = session.pop('chart_prefill', None)
    import datetime as _dt
    return render_template('main/profiles.html',
                           profiles=all_profiles,
                           reading_types=reading_types,
                           prefill=prefill,
                           max_profiles=MAX_PROFILES,
                           now=_dt.date.today())


@main_bp.route('/profiles/add', methods=['POST'])
@login_required
def profile_add():
    from models import Profile
    count = Profile.query.filter_by(user_id=current_user.id).count()
    if count >= MAX_PROFILES:
        flash(f'Puedes tener como máximo {MAX_PROFILES} perfiles.')
        return redirect(url_for('main.profiles'))

    name        = request.form.get('name', '').strip()
    birth_date  = request.form.get('birth_date', '').strip()
    birth_time  = request.form.get('birth_time', '').strip()
    birth_place = request.form.get('birth_place', '').strip()
    birth_lat   = request.form.get('birth_lat', '').strip()
    birth_lng   = request.form.get('birth_lng', '').strip()
    gender      = request.form.get('gender', '').strip()
    is_self_req = request.form.get('is_self') == '1'

    if not name:
        flash('El nombre es obligatorio.')
        return redirect(url_for('main.profiles'))

    # Only one is_self per user
    if is_self_req:
        existing_self = Profile.query.filter_by(user_id=current_user.id, is_self=True).first()
        if existing_self:
            flash('Ya tienes un perfil marcado como tú mismo.')
            return redirect(url_for('main.profiles'))

    p = Profile(user_id=current_user.id, is_self=is_self_req)
    p.name = name
    if birth_date:
        try:
            p.birth_date = dt.date.fromisoformat(birth_date)
        except ValueError:
            flash('Invalid birth date.')
            return redirect(url_for('main.profiles'))
    if birth_time:
        try:
            h, m = birth_time.split(':')
            p.birth_time = dt.time(int(h), int(m))
        except (ValueError, AttributeError):
            flash('Invalid birth time.')
            return redirect(url_for('main.profiles'))
    p.birth_place = birth_place or None
    try:
        p.birth_lat = float(birth_lat) if birth_lat else None
        p.birth_lng = float(birth_lng) if birth_lng else None
    except ValueError:
        p.birth_lat = p.birth_lng = None
    p.gender = gender if gender in ('masculino', 'femenino') else None

    db.session.add(p)
    db.session.commit()
    flash(f'Perfil "{p.name}" añadido.')
    return redirect(url_for('main.profiles'))


@main_bp.route('/profiles/<int:profile_id>/edit', methods=['GET', 'POST'])
@login_required
def profile_edit(profile_id):
    from models import Profile
    p = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        birth_date  = request.form.get('birth_date', '').strip()
        birth_time  = request.form.get('birth_time', '').strip()
        birth_place = request.form.get('birth_place', '').strip()
        birth_lat   = request.form.get('birth_lat', '').strip()
        birth_lng   = request.form.get('birth_lng', '').strip()
        gender      = request.form.get('gender', '').strip()

        if not name:
            flash('El nombre es obligatorio.')
            return render_template('main/profile_edit.html', p=p)

        p.name = name
        if birth_date:
            try:
                p.birth_date = dt.date.fromisoformat(birth_date)
            except ValueError:
                flash('Fecha de nacimiento no válida.')
                return render_template('main/profile_edit.html', p=p)
        else:
            p.birth_date = None
        if birth_time:
            try:
                h, m = birth_time.split(':')
                p.birth_time = dt.time(int(h), int(m))
            except (ValueError, AttributeError):
                flash('Hora de nacimiento no válida.')
                return render_template('main/profile_edit.html', p=p)
        else:
            p.birth_time = None
        p.birth_place = birth_place or None
        try:
            p.birth_lat = float(birth_lat) if birth_lat else None
            p.birth_lng = float(birth_lng) if birth_lng else None
        except ValueError:
            p.birth_lat = p.birth_lng = None
        p.gender = gender if gender in ('masculino', 'femenino') else None

        db.session.commit()
        flash(f'"{p.name}" actualizado.')
        return redirect(url_for('main.profiles'))

    return render_template('main/profile_edit.html', p=p)


@main_bp.route('/profiles/<int:profile_id>/delete', methods=['POST'])
@login_required
def profile_delete(profile_id):
    from models import Profile
    p = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()
    name = p.name
    db.session.delete(p)
    db.session.commit()
    flash(f'"{name}" eliminado.')
    return redirect(url_for('main.profiles'))


@main_bp.route('/profiles/<int:profile_id>/chart')
@login_required
def profile_chart(profile_id):
    from models import Profile
    p = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()

    result    = None
    error     = None
    age_point = None
    if p.birth_date and p.birth_place:
        try:
            from ai import compute_chart, compute_age_point
            result = compute_chart(
                p.birth_date,
                p.birth_time or dt.time(12, 0),
                p.birth_place,
                lat=p.birth_lat,
                lng=p.birth_lng,
            )
            result['birth_place'] = p.birth_place
            result['birth_date']  = p.birth_date
            result['birth_time']  = p.birth_time

            try:
                age_point = compute_age_point(
                    result['house_cusps'],
                    p.birth_date,
                    positions=result['positions'],
                )
            except Exception as e:
                log.warning('compute_age_point failed: %s', e)

        except Exception as e:
            error = f'No se pudo calcular la carta: {str(e)}'
    else:
        error = 'Este perfil necesita fecha y lugar de nacimiento para calcular la carta.'

    from models import ReadingType
    import datetime as _dt
    reading_types = ReadingType.query.filter_by(active=True).all()
    return render_template('main/profile_chart.html', p=p, result=result, error=error,
                           age_point=age_point,
                           reading_types=reading_types, now=_dt.date.today())


# ── Compatibilidad ────────────────────────────────────────────────────────────

@main_bp.route('/compatibilidad')
@login_required
def compatibility():
    from models import Profile, ReadingType
    profiles = Profile.query.filter_by(user_id=current_user.id)\
                            .order_by(Profile.is_self.desc(), Profile.created_at.asc()).all()
    reading_types = ReadingType.query.filter(
        ReadingType.active == True,
        ReadingType.slug.in_(['synastry', 'davison'])
    ).all()
    return render_template('main/compatibility.html',
                           profiles=profiles,
                           reading_types=reading_types)


# ── Legacy redirect ───────────────────────────────────────────────────────────

@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    return redirect(url_for('main.profiles'))


# ── Notifications ─────────────────────────────────────────────────────────────

@main_bp.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    from models import Notification
    Notification.query.filter_by(user_id=current_user.id, read_at=None)\
                      .update({'read_at': dt.datetime.utcnow()})
    db.session.commit()
    return redirect(request.referrer or url_for('main.dashboard'))
