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
    from models import Profile
    rtype = ReadingType.query.filter_by(id=reading_type_id, active=True).first_or_404()

    # Resolve the profile to use
    profile_id = request.form.get('profile_id', type=int)
    if profile_id:
        profile = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()
    else:
        profile = Profile.query.filter_by(user_id=current_user.id, is_self=True).first()

    if not profile or not profile.birth_date or not profile.birth_place:
        flash('Por favor, completa los datos de nacimiento de este perfil primero.')
        return redirect(url_for('main.profiles'))

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
                      profile_id=profile.id)
    db.session.add(reading)
    db.session.commit()

    from worker import enqueue_reading
    enqueue_reading(reading.id)

    flash('Tu lectura se está generando. Te enviaremos un email cuando esté lista.')
    return redirect(url_for('readings.view', reading_id=reading.id))


@readings_bp.route('/download/<int:reading_id>')
@login_required
def download(reading_id):
    from flask import Response
    from fpdf import FPDF

    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id).first_or_404()
    if reading.status != 'completed' or not reading.content:
        abort(404)

    # ── colours ──────────────────────────────────────────────────
    C_BG      = (248, 244, 255)   # very light lavender page
    C_HEADER  = (255, 255, 255)   # white header band
    C_ACCENT  = (124, 82, 149)    # purple
    C_GOLD    = (180, 140, 40)    # gold (darker for print)
    C_TEXT    = (26, 10, 46)      # near-black
    C_MUTED   = (107, 91, 128)    # muted purple

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ── header band ──────────────────────────────────────────────
    pdf.set_fill_color(*C_HEADER)
    pdf.rect(0, 0, 210, 38, 'F')

    # Logo text
    pdf.set_xy(14, 8)
    pdf.set_font('Helvetica', 'B', 18)
    pdf.set_text_color(*C_GOLD)
    pdf.cell(8, 10, '\u2726', ln=0)   # ✦  star glyph
    pdf.set_text_color(*C_ACCENT)
    pdf.cell(0, 10, ' ASTRONODE', ln=1)

    # Reading type subtitle
    pdf.set_xy(14, 20)
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 7, reading.reading_type.name, ln=1)

    # Thin gold rule under header
    pdf.set_draw_color(*C_GOLD)
    pdf.set_line_width(0.6)
    pdf.line(14, 38, 196, 38)

    # ── meta line (profile · date) ────────────────────────────────
    pdf.set_fill_color(*C_BG)
    pdf.rect(0, 38, 210, 262, 'F')   # fill rest of page

    pdf.set_xy(14, 43)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(*C_MUTED)
    meta_parts = []
    if reading.profile:
        label = reading.profile.name
        if reading.profile.is_self:
            label += ' (tú)'
        meta_parts.append(label)
    meta_parts.append(reading.created_at.strftime('%d/%m/%Y'))
    pdf.cell(0, 6, '  ·  '.join(meta_parts), ln=1)

    pdf.ln(4)

    # ── body text ────────────────────────────────────────────────
    pdf.set_left_margin(14)
    pdf.set_right_margin(14)
    pdf.set_font('Helvetica', '', 10.5)
    pdf.set_text_color(*C_TEXT)

    for line in reading.content.split('\n'):
        stripped = line.strip()
        # Detect section headings: lines in ALL-CAPS or starting with ★/✦/•
        if stripped and (stripped.isupper() or stripped.startswith(('★', '✦', '•', '—'))):
            pdf.ln(3)
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(*C_ACCENT)
            pdf.multi_cell(0, 6, stripped)
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
        elif stripped == '':
            pdf.ln(3)
        else:
            pdf.multi_cell(0, 6, line)

    # ── footer on each page ──────────────────────────────────────
    pdf.set_y(-14)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 5, f'astronode.com  ·  {reading.created_at.strftime("%d/%m/%Y")}', align='C')

    pdf_bytes = pdf.output()
    safe_name = reading.reading_type.name.lower().replace(' ', '-')
    filename  = f"lectura-{safe_name}-{reading.id}.pdf"
    return Response(
        bytes(pdf_bytes),
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
