import os
import time
import logging

from openai import OpenAI

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get('AI_API_KEY', ''),
            base_url=os.environ.get('AI_API_URL', 'https://openrouter.ai/api/v1'),
        )
    return _client


def _ask(prompt, model, retry_delay=3, max_retries=5):
    client = _get_client()
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=30000,
            )
            if response.choices:
                text = response.choices[0].message.content.strip()
                if text:
                    return text
            log.warning('Empty response on attempt %d', attempt + 1)
        except Exception as e:
            log.warning('AI call failed (attempt %d): %s', attempt + 1, e)
        time.sleep(retry_delay)
    raise RuntimeError('AI generation failed after %d attempts' % max_retries)


# ── Kerykeion chart calculation ────────────────────────────────────────────────

_HOUSE_NAME_MAP = {
    'First_House': 1, 'Second_House': 2, 'Third_House': 3,
    'Fourth_House': 4, 'Fifth_House': 5, 'Sixth_House': 6,
    'Seventh_House': 7, 'Eighth_House': 8, 'Ninth_House': 9,
    'Tenth_House': 10, 'Eleventh_House': 11, 'Twelfth_House': 12,
}

_HOUSE_ATTRS = [
    'first_house', 'second_house', 'third_house', 'fourth_house',
    'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
    'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house',
]

_PLANET_ATTRS = [
    ('Sun', 'sun'), ('Moon', 'moon'), ('Mercury', 'mercury'),
    ('Venus', 'venus'), ('Mars', 'mars'), ('Jupiter', 'jupiter'),
    ('Saturn', 'saturn'), ('Uranus', 'uranus'), ('Neptune', 'neptune'),
    ('Pluto', 'pluto'),
]


def _house_num(val):
    if isinstance(val, int):
        return val
    return _HOUSE_NAME_MAP.get(str(val), 1)


def _build_chart_kerykeion(birth_date, birth_time, birth_place):
    import pytz
    import datetime
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    from kerykeion import AstrologicalSubject

    # Geocode
    geolocator = Nominatim(user_agent='astronode_app')
    location = geolocator.geocode(birth_place, timeout=10)
    if not location:
        raise ValueError(f'Could not geocode: {birth_place}')
    lat, lng = location.latitude, location.longitude

    # Timezone
    tf = TimezoneFinder()
    tz_str = tf.timezone_at(lng=lng, lat=lat)
    if not tz_str:
        raise ValueError(f'Could not find timezone for {birth_place}')

    # Localize datetime
    local_tz = pytz.timezone(tz_str)
    local_dt = datetime.datetime(
        birth_date.year, birth_date.month, birth_date.day,
        birth_time.hour, birth_time.minute,
    )
    local_dt = local_tz.localize(local_dt)

    subject = AstrologicalSubject(
        birth_place,
        birth_date.year, birth_date.month, birth_date.day,
        birth_time.hour, birth_time.minute,
        lng=lng, lat=lat, tz_str=tz_str,
        online=False,
    )

    # Planet positions
    positions = {}
    for name, attr in _PLANET_ATTRS:
        p = getattr(subject, attr)
        positions[name] = {
            'longitude': p.abs_pos,
            'sign':      p.sign,
            'house':     _house_num(p.house),
        }

    # Ascendant + MC from house objects
    asc = getattr(subject, 'first_house')
    mc  = getattr(subject, 'tenth_house')
    positions['Ascendant'] = {'longitude': asc.abs_pos, 'sign': asc.sign, 'house': 1}
    positions['MC']        = {'longitude': mc.abs_pos,  'sign': mc.sign,  'house': 10}

    # House cusps
    house_cusps = {}
    for i, attr in enumerate(_HOUSE_ATTRS, 1):
        h = getattr(subject, attr)
        house_cusps[i] = h.abs_pos

    return positions, house_cusps, local_dt, lat, lng, subject


_PURPLE_THEME_CSS = """
<style>
:root, svg {
  /* ── General text/content colors — cascade into info panel labels ── */
  --kerykeion-color-neutral-content: #a0a0b0;
  --kerykeion-color-base-content:    #a0a0b0;

  /* ── Backgrounds ── */
  --kerykeion-chart-color-paper-0: #0d0d1a;
  --kerykeion-chart-color-paper-1: #13101e;

  /* ── Zodiac segments — two close deep purples alternating ── */
  --kerykeion-chart-color-zodiac-bg-0:  #1a1525;
  --kerykeion-chart-color-zodiac-bg-1:  #221c30;
  --kerykeion-chart-color-zodiac-bg-2:  #1a1525;
  --kerykeion-chart-color-zodiac-bg-3:  #221c30;
  --kerykeion-chart-color-zodiac-bg-4:  #1a1525;
  --kerykeion-chart-color-zodiac-bg-5:  #221c30;
  --kerykeion-chart-color-zodiac-bg-6:  #1a1525;
  --kerykeion-chart-color-zodiac-bg-7:  #221c30;
  --kerykeion-chart-color-zodiac-bg-8:  #1a1525;
  --kerykeion-chart-color-zodiac-bg-9:  #221c30;
  --kerykeion-chart-color-zodiac-bg-10: #1a1525;
  --kerykeion-chart-color-zodiac-bg-11: #221c30;

  /* ── Zodiac sign icons — bright silvery-lavender ── */
  --kerykeion-chart-color-zodiac-icon-0:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-1:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-2:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-3:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-4:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-5:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-6:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-7:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-8:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-9:  #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-10: #ddc8f5;
  --kerykeion-chart-color-zodiac-icon-11: #ddc8f5;

  /* ── Concentric ring borders — muted gold ── */
  --kerykeion-chart-color-zodiac-radix-ring-0: #b89947;
  --kerykeion-chart-color-zodiac-radix-ring-1: #a08535;
  --kerykeion-chart-color-zodiac-radix-ring-2: #8a7020;

  /* ── House division lines — muted slate ── */
  --kerykeion-chart-color-houses-radix-line: #6b637d;

  /* ── House numbers — gold ── */
  --kerykeion-chart-color-house-number: #d4af37;

  /* ── All planets — crisp off-white ── */
  --kerykeion-chart-color-sun:       #f8f9fa;
  --kerykeion-chart-color-moon:      #f8f9fa;
  --kerykeion-chart-color-mercury:   #f8f9fa;
  --kerykeion-chart-color-venus:     #f8f9fa;
  --kerykeion-chart-color-mars:      #f8f9fa;
  --kerykeion-chart-color-jupiter:   #f8f9fa;
  --kerykeion-chart-color-saturn:    #f8f9fa;
  --kerykeion-chart-color-uranus:    #f8f9fa;
  --kerykeion-chart-color-neptune:   #f8f9fa;
  --kerykeion-chart-color-pluto:     #f8f9fa;
  --kerykeion-chart-color-mean-node: #f8f9fa;
  --kerykeion-chart-color-true-node: #f8f9fa;

  /* ── Chiron and Lilith — hidden ── */
  --kerykeion-chart-color-chiron:      transparent;
  --kerykeion-chart-color-mean-lilith: transparent;
  --kerykeion-chart-color-true-lilith: transparent;

  /* ── Angles (ASC/MC/DC/IC) — gold ── */
  --kerykeion-chart-color-first-house:   #d4af37;
  --kerykeion-chart-color-tenth-house:   #d4af37;
  --kerykeion-chart-color-seventh-house: #d4af37;
  --kerykeion-chart-color-fourth-house:  #d4af37;

  /* ── Major aspects — 35% opacity pastels, traceable without dominating ── */
  --kerykeion-chart-color-conjunction: rgba(216, 200, 248, 0.35);
  --kerykeion-chart-color-sextile:     rgba(142, 202, 230, 0.35);
  --kerykeion-chart-color-square:      rgba(232, 144, 122, 0.35);
  --kerykeion-chart-color-trine:       rgba(136, 212, 176, 0.35);
  --kerykeion-chart-color-opposition:  rgba(232, 144, 122, 0.35);

  /* ── Minor aspects — transparent ── */
  --kerykeion-chart-color-semi-sextile:   transparent;
  --kerykeion-chart-color-semi-square:    transparent;
  --kerykeion-chart-color-quintile:       transparent;
  --kerykeion-chart-color-sesquiquadrate: transparent;
  --kerykeion-chart-color-biquintile:     transparent;
  --kerykeion-chart-color-quincunx:       transparent;

  /* ── Element/modality percentages — pastels ── */
  --kerykeion-chart-color-fire-percentage:     #f4a87c;
  --kerykeion-chart-color-earth-percentage:    #a8c090;
  --kerykeion-chart-color-air-percentage:      #8ecae6;
  --kerykeion-chart-color-water-percentage:    #b8a8e8;
  --kerykeion-chart-color-cardinal-percentage: #88d4b0;
  --kerykeion-chart-color-fixed-percentage:    #e8cc84;
  --kerykeion-chart-color-mutable-percentage:  #e8a08c;
}

/* Info panel text — muted grey, sits quietly behind the wheel */
text { fill: #a0a0b0; }

/* House division lines — no dashes */
line { stroke-dasharray: none; }
</style>
"""


def _apply_purple_theme(svg_string):
    import re
    return re.sub(r'(<svg\b[^>]*>)', r'\1' + _PURPLE_THEME_CSS, svg_string, count=1)


def _scale_planet_glyphs(svg_string, factor=0.85):
    """Scale down planet glyphs inside ChartPoint groups."""
    import re
    # Kerykeion renders natal chart planets at scale(1.0). Reduce to factor.
    def _shrink(m):
        tag = m.group(0)
        tag = re.sub(r'scale\(1(?:\.0)?(?:,\s*1(?:\.0)?)?\)', f'scale({factor},{factor})', tag)
        return tag
    return re.sub(r'<use\b[^/]*/>', _shrink, svg_string)


def _generate_chart_svg(subject):
    """Generate styled SVG natal chart using Kerykeion."""
    import tempfile
    import os as _os
    from kerykeion import KerykeionChartSVG

    svg_string = None

    with tempfile.TemporaryDirectory() as tmpdir:
        chart = KerykeionChartSVG(subject, 'Natal', new_output_directory=tmpdir)
        chart.makeSVG()
        svg_files = [f for f in _os.listdir(tmpdir) if f.endswith('.svg')]
        if svg_files:
            with open(_os.path.join(tmpdir, svg_files[0]), 'r', encoding='utf-8') as f:
                svg_string = f.read()

    if svg_string is None:
        try:
            chart = KerykeionChartSVG(subject, 'Natal')
            svg_string = chart.makeTemplate()
        except Exception as e:
            log.warning('KerykeionChartSVG.makeTemplate() failed: %s', e)

    if svg_string:
        svg_string = _apply_purple_theme(svg_string)
        svg_string = _scale_planet_glyphs(svg_string)

    return svg_string


# ── Aspects ───────────────────────────────────────────────────────────────────

ASPECT_TYPES = [
    ('Conjuncion',  0,   8),
    ('Oposicion',   180, 8),
    ('Trigono',     120, 8),
    ('Cuadratura',  90,  7),
    ('Sextil',      60,  6),
]


def _compute_aspects(positions):
    planets = [(name, data['longitude']) for name, data in positions.items()
               if name not in ('MC',)]
    aspects = []
    for i in range(len(planets)):
        for j in range(i + 1, len(planets)):
            n1, lon1 = planets[i]
            n2, lon2 = planets[j]
            diff = abs(lon1 - lon2) % 360
            if diff > 180:
                diff = 360 - diff
            for asp_name, asp_angle, orb in ASPECT_TYPES:
                if abs(diff - asp_angle) <= orb:
                    aspects.append({
                        'p1': n1, 'p2': n2,
                        'aspect': asp_name,
                        'orb': round(abs(diff - asp_angle), 2),
                    })
                    break
    return aspects


# ── Text prompts ───────────────────────────────────────────────────────────────

def _positions_text(positions):
    lines = 'Posiciones Planetarias:\n'
    for name, data in positions.items():
        lines += f"  {name}: {data['longitude']:.2f}° - {data['sign']} - Casa {data['house']}\n"
    return lines


def _house_group_text(start, end, positions, house_cusps):
    text = f'Casas {start} a {end}:\n'
    for h in range(start, end + 1):
        text += f'\nCasa {h} (cuspide {house_cusps.get(h, 0):.1f}°):\n'
        planets = [f"{n} ({d['sign']}, {d['longitude']:.1f}°)"
                   for n, d in positions.items() if d['house'] == h]
        text += ('  Planetas: ' + ', '.join(planets) + '\n') if planets else '  Sin planetas.\n'
    return text


# ── Public chart computation (no AI) ──────────────────────────────────────────

def compute_chart(birth_date, birth_time, birth_place):
    """Compute chart data and SVG image without AI text. Used for the free public chart page."""
    positions, house_cusps, local_dt, lat, lng, subject = \
        _build_chart_kerykeion(birth_date, birth_time, birth_place)

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Chart SVG generation failed: %s', e)

    aspects = _compute_aspects(positions)

    return {
        'positions':   positions,
        'house_cusps': house_cusps,
        'aspects':     aspects,
        'chart_image': chart_image,
        'local_dt':    local_dt,
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_horoscope(user, reading_type):
    model       = os.environ.get('AI_MODEL', 'meta-llama/llama-3.3-70b-instruct')
    birth_date  = user.birth_date
    birth_time  = user.birth_time
    birth_place = user.birth_place or 'unknown'

    positions, house_cusps, local_dt, lat, lng, subject = \
        _build_chart_kerykeion(birth_date, birth_time, birth_place)
    log.info('Chart built with Kerykeion')

    # Generate SVG chart
    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Chart SVG generation failed: %s', e)

    # Generate text reading (5 AI calls in Spanish)
    pos_text = _positions_text(positions)
    asc      = positions.get('Ascendant', {})
    asc_text = f"Ascendente: {asc.get('longitude', 0):.2f}° - {asc.get('sign', '')}\n"

    cusps_text = 'Cuspides de Casas:\n' + ''.join(
        f'  Casa {i}: {house_cusps.get(i, 0):.2f}°\n' for i in range(1, 13)
    )

    sun  = positions.get('Sun', {})
    moon = positions.get('Moon', {})
    quick_text = (
        f"Sol: {sun.get('longitude', 0):.2f}° - {sun.get('sign', '')} - Casa {sun.get('house', '')}\n"
        f"Luna: {moon.get('longitude', 0):.2f}° - {moon.get('sign', '')} - Casa {moon.get('house', '')}\n"
        f"Ascendente: {asc.get('longitude', 0):.2f}° - {asc.get('sign', '')}\n"
    )

    sections = []

    sections.append(_ask(
        'Proporciona una identificacion rapida de la personalidad en ESPANOL basada en el Sol, la Luna y el Ascendente. '
        'Analiza signos zodiacales, casas y posiciones. Explica los rasgos de personalidad generales.\n\n'
        + quick_text,
        model,
    ))

    for start, end in [(1, 3), (4, 6), (7, 9), (10, 12)]:
        group_text = _house_group_text(start, end, positions, house_cusps)
        sections.append(_ask(
            f'Analiza las casas {start} a {end} del tema natal casa por casa en ESPANOL. '
            'Para cada casa explica la significancia de los planetas presentes (o su ausencia), '
            'las influencias y los desafios especificos indicados por el tema natal. '
            'Usa las posiciones planetarias y cuspides como contexto.\n\n'
            + pos_text + '\n' + asc_text + '\n' + cusps_text + '\n\n' + group_text,
            model,
        ))

    divider = '\n\n' + '-' * 60 + '\n\n'
    full_text = divider.join(sections)

    return {'text': full_text, 'chart_image': chart_image, 'usage': {'model': model}}
