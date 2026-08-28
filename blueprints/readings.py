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
    from sqlalchemy.orm import defer
    readings = Reading.query.filter_by(user_id=current_user.id)\
                            .options(defer(Reading.chart_image), defer(Reading.chart_png))\
                            .order_by(Reading.created_at.desc()).all()
    return render_template('readings/index.html', readings=readings)


@readings_bp.route('/<int:reading_id>')
@login_required
def view(reading_id):
    from sqlalchemy.orm import defer
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id)\
                           .options(defer(Reading.chart_png))\
                           .first_or_404()
    return render_template('readings/view.html', reading=reading)


@readings_bp.route('/request/<int:reading_type_id>', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def request_reading(reading_type_id):
    from models import Profile
    rtype = ReadingType.query.filter_by(id=reading_type_id, active=True).first_or_404()

    slug = getattr(rtype, 'slug', None) or 'natal'

    # Resolve primary profile
    profile_id = request.form.get('profile_id', type=int)
    if profile_id:
        profile = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()
    else:
        profile = Profile.query.filter_by(user_id=current_user.id, is_self=True).first()

    if not profile or not profile.birth_date or not profile.birth_place:
        flash('Por favor, completa los datos de nacimiento de este perfil primero.')
        return redirect(url_for('main.profiles'))

    # Build params dict
    params = {}

    if slug in ('synastry', 'davison'):
        profile_id_b = request.form.get('profile_id_b', type=int)
        if not profile_id_b:
            flash('Selecciona dos perfiles para este tipo de lectura.')
            return redirect(url_for('main.profiles'))
        pb = Profile.query.filter_by(id=profile_id_b, user_id=current_user.id).first_or_404()
        if not pb.birth_date or not pb.birth_place:
            flash('El segundo perfil necesita fecha y lugar de nacimiento.')
            return redirect(url_for('main.profiles'))
        params['profile_id_b'] = profile_id_b

    if slug == 'solar_return':
        year = request.form.get('year', type=int)
        if not year:
            flash('Indica el año de la revolución solar.')
            return redirect(url_for('main.profiles'))
        params['year']  = year
        params['place'] = request.form.get('sr_place', '').strip() or profile.birth_place
        params['lat']   = request.form.get('sr_lat', type=float)
        params['lng']   = request.form.get('sr_lng', type=float)

    if slug == 'lunar_return':
        year  = request.form.get('year',  type=int)
        month = request.form.get('month', type=int)
        if not year or not month:
            flash('Indica el año y mes de la revolución lunar.')
            return redirect(url_for('main.profiles'))
        params['year']  = year
        params['month'] = month
        params['place'] = request.form.get('lr_place', '').strip() or profile.birth_place
        params['lat']   = request.form.get('lr_lat', type=float)
        params['lng']   = request.form.get('lr_lng', type=float)

    if slug in ('saturn_return', 'jupiter_return'):
        decade_start = request.form.get('decade_start', type=int)
        if not decade_start:
            flash('Indica el año de inicio de la ventana de diez años.')
            return redirect(url_for('main.profiles'))
        params['decade_start'] = decade_start

    # Check payment / tier
    if not _DEV:
        if rtype.price_cents and rtype.min_tier == 'free':
            return redirect(url_for('billing.checkout_reading', reading_type_id=reading_type_id))

        tier_order    = ['free', 'basic', 'vip']
        user_tier_idx = tier_order.index(current_user.tier) if current_user.tier in tier_order else 0
        min_tier_idx  = tier_order.index(rtype.min_tier) if rtype.min_tier in tier_order else 0
        if user_tier_idx < min_tier_idx:
            return redirect(url_for('billing.pricing'))

    reading = Reading(user_id=current_user.id, reading_type_id=rtype.id,
                      profile_id=profile.id, params=params or None)
    db.session.add(reading)
    db.session.commit()

    from worker import enqueue_reading
    enqueue_reading(reading.id)

    flash('Tu lectura se está generando. Te enviaremos un email cuando esté lista.')
    return redirect(url_for('readings.view', reading_id=reading.id))


@readings_bp.route('/download/<int:reading_id>')
@login_required
def download(reading_id):
    from flask import Response, current_app
    import os as _os

    from sqlalchemy.orm import defer
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id)\
                           .options(defer(Reading.chart_image), defer(Reading.chart_png),
                                    defer(Reading.pdf_content))\
                           .first_or_404()
    if reading.status != 'completed' or not reading.content:
        abort(404)

    safe_name = reading.reading_type.name.lower().replace(' ', '-')
    safe_name = safe_name.encode('ascii', errors='ignore').decode('ascii')
    filename  = f"lectura-{safe_name}-{reading.id}.pdf"

    # Serve pre-built PDF if available
    if reading.pdf_content:
        return Response(
            reading.pdf_content,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )

    # Fallback: generate on-the-fly for older readings (no pre-built pdf_content)
    from pdf import generate_reading_pdf
    _chart_png = reading.chart_png
    if not _chart_png and reading.chart_image:
        try:
            from ai import _svg_to_wheel_png
            _chart_png = _svg_to_wheel_png(reading.chart_image)
        except Exception:
            pass
    static_dir = _os.path.join(current_app.root_path, 'static')
    pdf_bytes  = generate_reading_pdf(reading, static_dir, chart_png=_chart_png)
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


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

    from models import Profile
    profiles = Profile.query.filter_by(user_id=current_user.id).all()

    if request.method == 'GET':
        return render_template('readings/dev_generate.html', profiles=profiles)

    profile_id = request.form.get('profile_id', type=int)
    if profile_id:
        profile = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first()
    else:
        profile = next((p for p in profiles if p.is_self), profiles[0] if profiles else None)

    if not profile or not profile.birth_date or not profile.birth_place:
        flash('Completa los datos de nacimiento de este perfil primero.')
        return redirect(url_for('main.profiles'))

    rtype = ReadingType.query.filter_by(active=True).first()
    if not rtype:
        rtype = ReadingType(
            name='Carta Natal Completa',
            description='Interpretacion completa de tu carta natal con IA.',
            price_cents=999,
            min_tier='free',
            active=True,
        )
        db.session.add(rtype)
        db.session.commit()

    reading = Reading(user_id=current_user.id, reading_type_id=rtype.id,
                      profile_id=profile.id, status='generating')
    db.session.add(reading)
    db.session.commit()

    reading_id = reading.id
    profile_id = profile.id
    user_id    = current_user.id

    def _run(app, rid, pid, uid, rtid):
        with app.app_context():
            from ai import generate_horoscope
            from models import Reading, Profile, User, ReadingType
            p  = Profile.query.get(pid)
            rt = ReadingType.query.get(rtid)

            db.session.expunge(p)
            db.session.expunge(rt)
            db.session.close()

            try:
                result = generate_horoscope(p, rt)
                status = 'completed'
            except Exception as e:
                result = None
                status = 'failed'
                print(f'[dev-generate] generation failed: {e}')

            r = Reading.query.get(rid)
            r.status = status
            if result:
                r.content      = result['text']
                r.chart_image  = result.get('chart_image')
                r.completed_at = datetime.utcnow()
            db.session.commit()

    import threading
    from flask import current_app
    t = threading.Thread(
        target=_run,
        args=(current_app._get_current_object(), reading_id, profile_id, user_id, rtype.id),
        daemon=True,
    )
    t.start()

    return redirect(url_for('readings.view', reading_id=reading.id))
