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
    from flask import Response
    from fpdf import FPDF
    import io, re

    from sqlalchemy.orm import defer
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id)\
                           .options(defer(Reading.chart_image), defer(Reading.chart_png))\
                           .first_or_404()
    if reading.status != 'completed' or not reading.content:
        abort(404)

    # Helvetica is Latin-1 only — map common Unicode chars then sanitise
    _UNICODE_MAP = str.maketrans({
        '\u2019': "'",  '\u2018': "'",   # curly apostrophes
        '\u201c': '"',  '\u201d': '"',   # curly double quotes
        '\u2032': "'",  '\u2033': '"',   # prime / double-prime (arcminutes/seconds)
        '\u2014': '-',  '\u2013': '-',   # em/en dash
        '\u2026': '...',                 # ellipsis
        '\u2022': '-',  '\u00b7': '.',   # bullet, middle dot
        '\u2605': '*',  '\u2606': '*',   # stars
        '\u2726': '*',  '\u2727': '*',
        '\u00d7': 'x',                   # multiplication sign
    })

    def _s(text):
        import unicodedata
        text = unicodedata.normalize('NFC', text)
        return text.translate(_UNICODE_MAP).encode('latin-1', errors='replace').decode('latin-1')

    import os as _os
    from flask import current_app

    _logo_path        = _os.path.join(current_app.root_path, 'static', 'logo.png')
    _has_logo         = _os.path.exists(_logo_path)
    _logo_purple_path = _os.path.join(current_app.root_path, 'static', 'logopurple.png')
    _has_logo_purple  = _os.path.exists(_logo_purple_path)

    # ── Wheel PNG: pre-generated by worker, or fall back for older readings ──
    _chart_png = reading.chart_png
    if not _chart_png and reading.chart_image:
        try:
            from ai import _svg_to_wheel_png
            _chart_png = _svg_to_wheel_png(reading.chart_image)
        except Exception:
            pass

    # ── document metadata ─────────────────────────────────────────
    doc_title = _s(reading.reading_type.name)
    _meta_parts = []
    if reading.profile:
        _lbl = reading.profile.name
        if reading.profile.is_self:
            _lbl += ' (tu)'
        _meta_parts.append(_lbl)
    _profile_label = _s('  |  '.join(_meta_parts))

    # Birth data lines for cover header
    _birth_lines = []
    if reading.profile:
        _p = reading.profile
        _bdate = _p.birth_date.strftime('%d/%m/%Y') if _p.birth_date else None
        _btime = _p.birth_time.strftime('%H:%M') if _p.birth_time else None
        if _bdate and _btime:
            _birth_lines.append(_s(f'{_bdate}  {_btime}h'))
        elif _bdate:
            _birth_lines.append(_s(_bdate))
        if _p.birth_place:
            _birth_lines.append(_s(_p.birth_place))

    # ── colour palette ────────────────────────────────────────────
    C_PURPLE    = (53, 15, 76)
    C_COVER_BG  = (15, 6, 35)    # darker purple for the cover page background
    C_GOLD    = (212, 175, 55)
    C_TEXT    = (28, 22, 38)       # near-black body
    C_HEADING = (53, 15, 76)       # brand purple headings
    C_MUTED   = (120, 105, 140)
    C_CREAM   = (245, 235, 200)

    # ── house descriptions ────────────────────────────────────────
    _HOUSE_DESC = {
        1:  _s("Identidad, apariencia y la forma en que te presentas al mundo."),
        2:  _s("Recursos materiales, valores personales y autoestima."),
        3:  _s("Comunicación, mente analítica, hermanos y entorno cercano."),
        4:  _s("Hogar, familia, raíces y base emocional."),
        5:  _s("Creatividad, romance, hijos y expresión personal."),
        6:  _s("Salud, rutina diaria, servicio y trabajo cotidiano."),
        7:  _s("Relaciones íntimas, asociaciones y el otro en tu vida."),
        8:  _s("Transformación, sexualidad, herencias y los misterios de la vida."),
        9:  _s("Filosofía, viajes, educación superior y búsqueda de sentido."),
        10: _s("Carrera, reputación pública y vocación de vida."),
        11: _s("Amistades, comunidad, ideales y esperanzas futuras."),
        12: _s("Inconsciente, espiritualidad, retiro y lo que está oculto."),
    }

    # ── table of contents extraction ──────────────────────────────
    _toc_entries = []
    for _ln in reading.content.split('\n'):
        if _ln.strip().startswith('#'):
            _t = _ln.strip().lstrip('#').strip()
            _hm_t = re.match(r'Casa\s+(\d+)', _t)
            if _hm_t:
                _d = _HOUSE_DESC.get(int(_hm_t.group(1)))
                _t = f'{_t}: {_d}' if _d else _t
            _toc_entries.append(_s(_t))

    class _PDF(FPDF):
        def header(self):
            if self.page_no() == 1:
                # ── Full dark purple cover page ──────────────────
                self.set_fill_color(*C_COVER_BG)
                self.rect(0, 0, 210, 297, 'F')
                # Logo (white) — top left
                if _has_logo:
                    self.image(_logo_path, x=16, y=14, w=80)
                # Reading type — top right, white
                self.set_font('Helvetica', 'B', 9)
                self.set_text_color(255, 255, 255)
                self.set_xy(100, 16)
                self.cell(94, 5, doc_title, align='R', ln=1)
                # Profile label
                self.set_font('Helvetica', '', 8)
                self.set_text_color(255, 255, 255)
                self.set_x(100)
                self.cell(94, 5, _profile_label, align='R', ln=1)
                # Birth data lines
                self.set_font('Helvetica', '', 7.5)
                self.set_text_color(255, 255, 255)
                for _bl in _birth_lines:
                    self.set_x(100)
                    self.cell(94, 4.5, _bl, align='R', ln=1)
                # Gold separator
                self.set_draw_color(*C_GOLD)
                self.set_line_width(0.4)
                self.line(0, 52, 210, 52)
                # Chart image — centred below header band
                if _chart_png:
                    _cw = 228
                    _cx = (210 - _cw) / 2 + _cw * 0.125
                    _w_px = int.from_bytes(_chart_png[16:20], 'big')
                    _h_px = int.from_bytes(_chart_png[20:24], 'big')
                    _ch = _cw * _h_px / _w_px
                    _cy = 52 + (297 - 52 - _ch) / 2
                    self.image(io.BytesIO(_chart_png), x=_cx, y=_cy, w=_cw)
                # Push cursor off-page so no body text bleeds onto cover
                self.set_y(300)
            else:
                # Continuation pages — thin gold top rule
                self.set_draw_color(*C_GOLD)
                self.set_line_width(0.25)
                self.line(16, 13, 194, 13)
                self.set_y(18)

        def footer(self):
            if self.page_no() == 1:
                return
            _fy, _fh = 279, 10
            # Gold separator line
            self.set_draw_color(*C_GOLD)
            self.set_line_width(0.25)
            self.line(16, 275, 194, 275)
            # Purple logo (transparent background) — left
            if _has_logo_purple:
                self.image(_logo_purple_path, x=16, y=_fy, w=44)
            # Three-column footer: logo | page number | title
            self.set_xy(70, _fy)
            self.set_font('Helvetica', '', 7.5)
            self.set_text_color(*C_MUTED)
            self.cell(70, _fh, str(self.page_no()), align='C')
            self.set_xy(140, _fy)
            self.set_font('Helvetica', '', 7)
            self.cell(54, _fh, doc_title, align='R')

    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(16, 10, 16)
    pdf.set_auto_page_break(auto=True, margin=24)

    # ── Page 1: Cover (header draws everything) ───────────────────
    pdf.add_page()

    # ── Page 2: Table of contents ─────────────────────────────────
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 15)
    pdf.set_text_color(*C_HEADING)
    pdf.ln(4)
    pdf.cell(0, 9, _s('Índice de contenidos'), ln=1)
    _ty = pdf.get_y()
    pdf.set_draw_color(*C_GOLD)
    pdf.set_line_width(0.35)
    pdf.line(16, _ty, 194, _ty)
    pdf.ln(6)
    for _i, _entry in enumerate(_toc_entries, 1):
        pdf.set_font('Helvetica', 'B', 8.5)
        pdf.set_text_color(*C_MUTED)
        pdf.set_x(16)
        pdf.cell(10, 7, f'{_i}.', align='R')
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(*C_TEXT)
        pdf.set_x(28)
        pdf.multi_cell(166, 7, _entry)

    # ── Page 3+: Body content ─────────────────────────────────────
    pdf.add_page()
    pdf.set_font('Helvetica', '', 10.5)
    pdf.set_text_color(*C_TEXT)

    for line in reading.content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            text = stripped.lstrip('#').strip()
            pdf.ln(5)
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(*C_HEADING)
            _hm = re.match(r'Casa\s+(\d+)', text)
            if _hm:
                _hdesc = _HOUSE_DESC.get(int(_hm.group(1)))
                _heading_text = _s(f'{text}: {_hdesc}') if _hdesc else _s(text)
            else:
                _heading_text = _s(text)
            pdf.multi_cell(0, 7, _heading_text)
            _y = pdf.get_y()
            pdf.set_draw_color(*C_GOLD)
            pdf.set_line_width(0.3)
            pdf.line(16, _y, 194, _y)
            pdf.ln(2)
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
        elif stripped and stripped.isupper() and len(stripped) > 4:
            pdf.ln(5)
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(*C_HEADING)
            pdf.multi_cell(0, 7, _s(stripped))
            pdf.ln(1)
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
        elif stripped == '':
            pdf.ln(3)
        else:
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
            pdf.multi_cell(0, 6, _s(line))

    pdf_bytes = pdf.output()
    safe_name = reading.reading_type.name.lower().replace(' ', '-')
    safe_name = safe_name.encode('ascii', errors='ignore').decode('ascii')
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
