import datetime
import logging
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, abort, Response
from flask_login import current_user
from extensions import limiter

log = logging.getLogger(__name__)

public_bp = Blueprint('public', __name__)

# ── Sign / body mappings ───────────────────────────────────────────────────────

SIGN_ES_TO_EN = {
    'aries': 'Aries', 'tauro': 'Taurus', 'geminis': 'Gemini',
    'cancer': 'Cancer', 'leo': 'Leo', 'virgo': 'Virgo',
    'libra': 'Libra', 'escorpio': 'Scorpio', 'sagitario': 'Sagittarius',
    'capricornio': 'Capricorn', 'acuario': 'Aquarius', 'piscis': 'Pisces',
}
SIGN_EN_TO_ES = {v: k for k, v in SIGN_ES_TO_EN.items()}

# Accent variants that 301 to the canonical (no-accent) slug
SIGN_SLUG_ALIASES = {
    'géminis': 'geminis',
    'gémeinis': 'geminis',
    'cáncer': 'cancer',
}

BODY_ES_TO_EN  = {'sol': 'sun', 'luna': 'moon', 'ascendente': 'rising'}
BODY_LABEL_ES  = {'sun': 'Sol', 'moon': 'Luna', 'rising': 'Ascendente'}
SIGN_LABEL_ES  = {
    'Aries': 'Aries', 'Taurus': 'Tauro', 'Gemini': 'Géminis',
    'Cancer': 'Cáncer', 'Leo': 'Leo', 'Virgo': 'Virgo',
    'Libra': 'Libra', 'Scorpio': 'Escorpio', 'Sagittarius': 'Sagitario',
    'Capricorn': 'Capricornio', 'Aquarius': 'Acuario', 'Pisces': 'Piscis',
}

ALL_SIGNS_EN = list(SIGN_ES_TO_EN.values())


# ── Preview stitcher ───────────────────────────────────────────────────────────

def build_chart_preview(sun_sign, moon_sign, rising_sign):
    """Assemble preview snippets from DB for a given chart.

    Assembly order: sun → moon → interaction → rising.
    Each placement has {'text', 'hook', 'available'}.
    Degrades gracefully — any piece may be None.
    """
    from models import PlacementContent, SunMoonInteraction

    def get_piece(body, sign):
        row = PlacementContent.query.filter_by(body=body, sign=sign, lang='es').first()
        text = row.preview_text if row else None
        hook = row.preview_hook if row else None
        return {'text': text, 'hook': hook, 'available': bool(text)}

    sun    = get_piece('sun',    sun_sign)
    moon   = get_piece('moon',   moon_sign)
    rising = get_piece('rising', rising_sign)

    row = SunMoonInteraction.query.filter_by(
        sun_sign=sun_sign, moon_sign=moon_sign, lang='es'
    ).first()
    interaction = {'text': row.text if row else None, 'available': bool(row and row.text)}

    return {
        'sun':         sun,
        'moon':        moon,
        'rising':      rising,
        'interaction': interaction,
        'has_any':     sun['available'] or moon['available'] or rising['available'],
    }


# ── Static pages ───────────────────────────────────────────────────────────────

@public_bp.route('/')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('public/landing.html')


@public_bp.route('/pricing')
def pricing():
    return render_template('public/pricing.html')


@public_bp.route('/privacy')
def privacy():
    return render_template('public/legal.html', title='Privacy Policy', body='Privacy policy coming soon.')


@public_bp.route('/terms')
def terms():
    return render_template('public/legal.html', title='Terms of Service', body='Terms of service coming soon.')


@public_bp.route('/refunds')
def refunds():
    return render_template('public/legal.html', title='Refund Policy', body='Refund policy coming soon.')


@public_bp.route('/chart', methods=['GET', 'POST'])
@limiter.limit("200 per hour")
def chart():
    result    = None
    error     = None
    form_data = {}

    if request.method == 'POST':
        birth_date_str = request.form.get('birth_date', '').strip()
        birth_time_str = request.form.get('birth_time', '').strip()
        birth_place    = request.form.get('birth_place', '').strip()
        birth_lat_str  = request.form.get('birth_lat', '').strip()
        birth_lng_str  = request.form.get('birth_lng', '').strip()

        try:
            birth_lat = float(birth_lat_str) if birth_lat_str else None
            birth_lng = float(birth_lng_str) if birth_lng_str else None
        except ValueError:
            birth_lat = birth_lng = None

        form_data = {
            'birth_date': birth_date_str, 'birth_time': birth_time_str,
            'birth_place': birth_place, 'birth_lat': birth_lat_str, 'birth_lng': birth_lng_str,
        }

        if not birth_date_str or not birth_time_str or not birth_place:
            error = 'All fields are required.'
        else:
            try:
                birth_date = datetime.date.fromisoformat(birth_date_str)
                h, m       = birth_time_str.split(':')
                birth_time = datetime.time(int(h), int(m))
            except (ValueError, AttributeError):
                error = 'Invalid date or time format.'
                birth_date = birth_time = None

            if not error:
                try:
                    from ai import compute_chart
                    result = compute_chart(birth_date, birth_time, birth_place,
                                          lat=birth_lat, lng=birth_lng)
                    result['birth_place'] = birth_place
                    result['birth_date']  = birth_date
                    result['birth_time']  = birth_time

                    session['chart_prefill'] = {
                        'birth_date':  birth_date_str,
                        'birth_time':  birth_time_str,
                        'birth_place': birth_place,
                        'birth_lat':   birth_lat_str,
                        'birth_lng':   birth_lng_str,
                    }
                except Exception as e:
                    error = f'Could not compute chart: {str(e)}'

    preview = None
    if result and 'positions' in result:
        try:
            sun_sign    = result['positions'].get('Sun',       {}).get('sign')
            moon_sign   = result['positions'].get('Moon',      {}).get('sign')
            rising_sign = result['positions'].get('Ascendant', {}).get('sign')
            print(f'[PREVIEW DEBUG] sun={sun_sign!r} moon={moon_sign!r} rising={rising_sign!r}', flush=True)
            if sun_sign and moon_sign and rising_sign:
                preview = build_chart_preview(sun_sign, moon_sign, rising_sign)
                print(f'[PREVIEW DEBUG] has_any={preview.get("has_any") if preview else None}', flush=True)
        except Exception as e:
            import traceback
            print(f'[PREVIEW ERROR] {e}\n{traceback.format_exc()}', flush=True)
            log.exception('build_chart_preview failed: %s', e)
            preview = None

    return render_template('public/chart.html', result=result, error=error,
                           form_data=form_data, preview=preview)


# ── Sitemap ────────────────────────────────────────────────────────────────────

@public_bp.route('/sitemap.xml')
def sitemap():
    from models import PlacementContent

    static_urls = [
        url_for('public.landing',  _external=True),
        url_for('public.chart',    _external=True),
        url_for('public.pricing',  _external=True),
    ]
    for body_slug in BODY_ES_TO_EN:
        static_urls.append(url_for('public.body_index', body_slug=body_slug, _external=True))

    # Only include placement pages that have been manually published
    indexed_rows = PlacementContent.query.filter_by(status='published', lang='es').all()
    placement_urls = [
        url_for('public.placement_page',
                body_slug={v: k for k, v in BODY_ES_TO_EN.items()}[r.body],
                sign_slug=SIGN_EN_TO_ES[r.sign],
                _external=True)
        for r in indexed_rows
    ]

    xml = render_template('public/sitemap.xml',
                          static_urls=static_urls,
                          placement_urls=placement_urls)
    return Response(xml, mimetype='application/xml')


# ── Body index pages (/sol, /luna, /ascendente) ───────────────────────────────

@public_bp.route('/<body_slug>')
def body_index(body_slug):
    if body_slug not in BODY_ES_TO_EN:
        abort(404)

    from models import PlacementContent
    body = BODY_ES_TO_EN[body_slug]
    rows = PlacementContent.query.filter_by(body=body, lang='es')\
                                  .order_by(PlacementContent.sign).all()
    published_count = sum(1 for r in rows if r.status == 'published')

    return render_template(
        'public/body_index.html',
        body=body,
        body_slug=body_slug,
        body_label=BODY_LABEL_ES[body],
        rows=rows,
        sign_en_to_es=SIGN_EN_TO_ES,
        sign_label_es=SIGN_LABEL_ES,
        indexable=published_count >= 8,
    )


# ── Placement SEO pages ────────────────────────────────────────────────────────

@public_bp.route('/<body_slug>/<sign_slug>')
def placement_page(body_slug, sign_slug):
    # 301 for accented slug variants
    if sign_slug in SIGN_SLUG_ALIASES:
        return redirect(
            url_for('public.placement_page', body_slug=body_slug,
                    sign_slug=SIGN_SLUG_ALIASES[sign_slug]),
            code=301,
        )

    if body_slug not in BODY_ES_TO_EN or sign_slug not in SIGN_ES_TO_EN:
        abort(404)

    from models import PlacementContent
    body = BODY_ES_TO_EN[body_slug]
    sign = SIGN_ES_TO_EN[sign_slug]

    content = PlacementContent.query.filter_by(body=body, sign=sign, lang='es').first_or_404()

    # noindex until manually published after editing
    indexable = content.status == 'published'

    related = PlacementContent.query.filter_by(body=body, lang='es')\
                                    .filter(PlacementContent.sign != sign)\
                                    .order_by(PlacementContent.sign).all()

    canonical = url_for('public.placement_page', body_slug=body_slug,
                        sign_slug=sign_slug, _external=True)

    return render_template(
        'public/placement.html',
        content=content,
        body=body,
        sign=sign,
        body_slug=body_slug,
        sign_slug=sign_slug,
        body_label=BODY_LABEL_ES[body],
        sign_label=SIGN_LABEL_ES[sign],
        related=related,
        sign_en_to_es=SIGN_EN_TO_ES,
        sign_label_es=SIGN_LABEL_ES,
        indexable=indexable,
        canonical=canonical,
    )
