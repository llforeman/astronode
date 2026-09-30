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
    from models import Profile
    from blueprints.readings import _coverage_sets
    profiles = Profile.query.filter_by(user_id=current_user.id)\
                            .order_by(Profile.is_self.desc(), Profile.created_at.asc()).all()
    unassigned = _unassigned_entitlements()
    natal_cov, pack_cov, _ = _coverage_sets(current_user)
    coverage = {}
    for p in profiles:
        if current_user.tier == 'complete' or p.id in pack_cov:
            coverage[p.id] = 'pack'
        elif current_user.tier == 'natal' or p.id in natal_cov:
            coverage[p.id] = 'natal'
        else:
            coverage[p.id] = None
    return render_template('main/dashboard.html', profiles=profiles,
                           unassigned=unassigned, coverage=coverage)


def defer_blobs():
    from sqlalchemy.orm import defer
    from models import Reading
    return (defer(Reading.chart_image), defer(Reading.chart_png),
            defer(Reading.pdf_content), defer(Reading.content))


def _unassigned_entitlements():
    from models import Entitlement
    return Entitlement.query.filter_by(user_id=current_user.id, profile_a_id=None)\
                            .order_by(Entitlement.created_at.asc()).all()


# ── Entitlements (purchase credits) ──────────────────────────────────────────

@main_bp.route('/entitlements/<int:eid>/assign', methods=['GET', 'POST'])
@login_required
def assign_entitlement(eid):
    from models import Entitlement, Profile
    ent = Entitlement.query.filter_by(id=eid, user_id=current_user.id).first_or_404()
    if ent.is_assigned:
        flash('Ese crédito ya está asignado.')
        return redirect(url_for('main.dashboard'))

    profiles = Profile.query.filter_by(user_id=current_user.id)\
                            .order_by(Profile.is_self.desc(), Profile.created_at.asc()).all()

    if request.method == 'POST':
        a_id = request.form.get('profile_a', type=int)
        b_id = request.form.get('profile_b', type=int) if ent.product == 'complete' else None

        pa = Profile.query.filter_by(id=a_id, user_id=current_user.id).first() if a_id else None
        pb = Profile.query.filter_by(id=b_id, user_id=current_user.id).first() if b_id else None

        if not pa or not pa.birth_date or not pa.birth_place:
            flash('Elige una persona con fecha y lugar de nacimiento completos.')
        elif ent.product == 'complete' and (not pb or not pb.birth_date or not pb.birth_place):
            flash('Elige la segunda persona con datos de nacimiento completos.')
        elif ent.product == 'complete' and pa.id == pb.id:
            flash('Elige dos personas distintas para el pack.')
        else:
            ent.profile_a_id = pa.id
            if pb:
                ent.profile_b_id = pb.id
            ent.assigned_at = dt.datetime.utcnow()
            db.session.commit()

            if ent.product == 'natal':
                from blueprints.billing import _deliver_natal
                _deliver_natal(current_user, pa, ent.payment)
                flash(f'¡Listo! La lectura natal de {pa.name} se está generando.')
            else:
                flash(f'Pack asignado a {pa.name} y {pb.name}. Ya puedes generar todas sus lecturas.')
            return redirect(url_for('main.dashboard'))

    pre_a = request.args.get('profile_a', type=int)
    pre_b = request.args.get('profile_b', type=int)
    return render_template('main/assign_entitlement.html', ent=ent, profiles=profiles,
                           pre_a=pre_a, pre_b=pre_b)


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


def _refresh_profile_signs(profile):
    """Best-effort cache of Sun/Moon/Ascendant signs (fast swisseph path)."""
    if not (profile.birth_date and profile.birth_place):
        return
    try:
        from ai import compute_key_signs
        signs = compute_key_signs(
            profile.birth_date,
            profile.birth_time or dt.time(12, 0),
            profile.birth_place,
            lat=profile.birth_lat, lng=profile.birth_lng,
        )
        profile.sun_sign  = signs['sun']
        profile.moon_sign = signs['moon']
        profile.asc_sign  = signs['asc']
    except Exception as e:
        log.warning('key-signs cache failed for profile %s: %s', profile.id, e)


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

    _refresh_profile_signs(p)
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

        _refresh_profile_signs(p)
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

            # Refresh the cached key signs from the real chart (most accurate).
            try:
                def _full(s):
                    if not s:
                        return None
                    s = str(s)
                    if len(s) == 3:
                        m = {'Ari': 'Aries', 'Tau': 'Taurus', 'Gem': 'Gemini',
                             'Can': 'Cancer', 'Leo': 'Leo', 'Vir': 'Virgo',
                             'Lib': 'Libra', 'Sco': 'Scorpio', 'Sag': 'Sagittarius',
                             'Cap': 'Capricorn', 'Aqu': 'Aquarius', 'Pis': 'Pisces'}
                        return m.get(s, s)
                    return s
                p.sun_sign  = _full(result['positions'].get('Sun', {}).get('sign'))
                p.moon_sign = _full(result['positions'].get('Moon', {}).get('sign'))
                p.asc_sign  = _full(result['positions'].get('Ascendant', {}).get('sign'))
                db.session.commit()
            except Exception:
                pass

            try:
                age_point = compute_age_point(
                    result['house_cusps'],
                    p.birth_date,
                    positions=result['positions'],
                )
            except Exception as e:
                log.warning('compute_age_point failed: %s', e)

        except Exception as e:
            error = f'No se pudo calcular la carta: {str(e)[:180]}'
    else:
        error = 'Este perfil necesita fecha y lugar de nacimiento para calcular la carta.'

    from models import Reading, ReadingType
    import datetime as _dt
    from blueprints.readings import person_has_natal, person_has_pack

    reading_types = ReadingType.query.filter_by(active=True).all()

    # All readings that involve this person: their individual readings plus
    # pair readings (synastry / davison) where they are either person.
    others = [q for q in Profile.query.filter(Profile.user_id == current_user.id,
                                              Profile.id != p.id)\
                                      .order_by(Profile.is_self.desc(),
                                                Profile.created_at.asc()).all()
              if q.birth_date and q.birth_place]
    prof_map = {q.id: q for q in others} | {p.id: p}

    reading_items = []
    rows = Reading.query.filter_by(user_id=current_user.id)\
                        .options(defer_blobs())\
                        .order_by(Reading.created_at.desc()).limit(60).all()
    for r in rows:
        if r.reading_type is None:
            continue
        params  = r.params or {}
        other   = None
        if r.profile_id == p.id:
            pid_b = params.get('profile_id_b')
            if pid_b:
                other = prof_map.get(pid_b)
        elif params.get('profile_id_b') == p.id:
            other = prof_map.get(r.profile_id)
        else:
            continue
        reading_items.append({'reading': r, 'other': other})

    return render_template('main/profile_chart.html', p=p, result=result, error=error,
                           age_point=age_point,
                           covered_natal=person_has_natal(current_user, p.id),
                           covered_pack=person_has_pack(current_user, p.id),
                           others_complete=others,
                           reading_items=reading_items,
                           reading_types=reading_types, now=_dt.date.today())


# ── Legacy redirects (compare/compat pages removed; pair readings live on
#    each person's page) ─────────────────────────────────────────────────────

@main_bp.route('/compatibilidad')
@login_required
def compatibility():
    return redirect(url_for('main.dashboard'))


@main_bp.route('/comparar')
@login_required
def compare():
    return redirect(url_for('main.dashboard'))


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
