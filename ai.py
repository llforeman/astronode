import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI

log = logging.getLogger(__name__)

_client = None

# ── Model env vars ─────────────────────────────────────────────────────────────
_MODEL_PROSE    = os.environ.get('AI_MODEL_PROSE',    os.environ.get('AI_MODEL', 'anthropic/claude-sonnet-4-5'))
_MODEL_ANALYSIS = os.environ.get('AI_MODEL_ANALYSIS', _MODEL_PROSE)
_MODEL_CHEAP    = os.environ.get('AI_MODEL_CHEAP',    _MODEL_PROSE)

log.info('Models — prose: %s | analysis: %s | cheap: %s',
         _MODEL_PROSE, _MODEL_ANALYSIS, _MODEL_CHEAP)

# ── Geocoding cache (process-lifetime) ────────────────────────────────────────
_geocode_cache: dict = {}


def _geocode(place):
    """Return (lat, lng) for a place string, with cache + fallback geocoders."""
    from geopy.geocoders import Photon, Nominatim
    from geopy.exc import GeocoderRateLimited, GeocoderTimedOut, GeocoderServiceError

    key = place.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]

    geocoders = [
        Photon(user_agent='astronode/1.0', timeout=10),
        Nominatim(user_agent='astronode/1.0', timeout=10),
    ]

    for geocoder in geocoders:
        try:
            location = geocoder.geocode(place)
            if location:
                result = (location.latitude, location.longitude)
                _geocode_cache[key] = result
                return result
        except (GeocoderRateLimited, GeocoderTimedOut, GeocoderServiceError) as e:
            log.warning('Geocoder %s failed for "%s": %s', type(geocoder).__name__, place, e)

    raise ValueError(f'Could not geocode "{place}". Check the city name and try again.')


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get('AI_API_KEY', ''),
            base_url=os.environ.get('AI_API_URL', 'https://openrouter.ai/api/v1'),
        )
    return _client


def _ask(messages: list[dict], *, model: str, max_tokens: int = None,
         temperature: float = 0.8, json_mode: bool = False,
         retries: int = 3) -> str:
    """Send a chat request. messages is a list of {role, content} dicts."""
    client = _get_client()
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    if max_tokens is not None:
        kwargs['max_tokens'] = max_tokens
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(**kwargs)
            if response.choices:
                choice = response.choices[0]
                finish = choice.finish_reason
                text   = choice.message.content
                usage  = getattr(response, 'usage', None)
                log.info('finish_reason=%s | tokens: prompt=%s completion=%s',
                         finish,
                         getattr(usage, 'prompt_tokens', '?'),
                         getattr(usage, 'completion_tokens', '?'))
                if finish == 'length':
                    log.warning('Output was TRUNCATED by token limit (finish_reason=length)')
                if text and text.strip():
                    return text.strip()
            log.warning('Empty AI response on attempt %d', attempt + 1)
        except Exception as e:
            log.warning('AI call failed (attempt %d): %s', attempt + 1, e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f'AI generation failed after {retries} attempts')


def _json_parse(text: str) -> Any:
    """Parse JSON from a model response that may be wrapped in markdown fences."""
    t = re.sub(r'^```(?:json)?\s*|```\s*$', '', text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r'[\{\[].*[\}\]]', t, re.S)
        if m:
            return json.loads(m.group(0))
        raise


# ── Kerykeion chart building ───────────────────────────────────────────────────

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


def _house_num(val) -> int:
    if isinstance(val, int):
        return val
    return _HOUSE_NAME_MAP.get(str(val), 1)


def _build_chart_kerykeion(birth_date, birth_time, birth_place,
                            lat=None, lng=None):
    import pytz
    import datetime
    from timezonefinder import TimezoneFinder
    from kerykeion import AstrologicalSubject

    if lat is None or lng is None:
        lat, lng = _geocode(birth_place)

    tf = TimezoneFinder()
    tz_str = tf.timezone_at(lng=lng, lat=lat)
    if not tz_str:
        raise ValueError(f'Could not find timezone for {birth_place}')

    local_tz = pytz.timezone(tz_str)
    local_dt = local_tz.localize(datetime.datetime(
        birth_date.year, birth_date.month, birth_date.day,
        birth_time.hour, birth_time.minute,
    ))

    subject = AstrologicalSubject(
        birth_place,
        birth_date.year, birth_date.month, birth_date.day,
        birth_time.hour, birth_time.minute,
        lng=lng, lat=lat, tz_str=tz_str,
        online=False,
    )

    # Planet positions (include retrograde flag)
    positions = {}
    for name, attr in _PLANET_ATTRS:
        p = getattr(subject, attr)
        positions[name] = {
            'longitude':  p.abs_pos,
            'sign':       p.sign,
            'house':      _house_num(p.house),
            'retrograde': bool(getattr(p, 'retrograde', False)),
        }

    # Angles
    asc = getattr(subject, 'first_house')
    mc  = getattr(subject, 'tenth_house')
    dc  = getattr(subject, 'seventh_house')
    ic  = getattr(subject, 'fourth_house')

    positions['Ascendant']   = {'longitude': asc.abs_pos, 'sign': asc.sign, 'house': 1,  'retrograde': False}
    positions['MC']          = {'longitude': mc.abs_pos,  'sign': mc.sign,  'house': 10, 'retrograde': False}
    positions['Medium_Coeli']= {'longitude': mc.abs_pos,  'sign': mc.sign,  'house': 10, 'retrograde': False}
    positions['Descendant']  = {'longitude': dc.abs_pos,  'sign': dc.sign,  'house': 7,  'retrograde': False}
    positions['Imum_Coeli']  = {'longitude': ic.abs_pos,  'sign': ic.sign,  'house': 4,  'retrograde': False}

    # House cusps
    house_cusps = {}
    for i, attr in enumerate(_HOUSE_ATTRS, 1):
        h = getattr(subject, attr)
        house_cusps[i] = h.abs_pos

    # Lunar nodes via swisseph directly (Kerykeion's mean_node is None in some versions)
    try:
        import swisseph as swe
        _SIGN_ABBR = ['Ari', 'Tau', 'Gem', 'Can', 'Leo', 'Vir',
                      'Lib', 'Sco', 'Sag', 'Cap', 'Aqu', 'Pis']
        utc_dt = local_dt.astimezone(pytz.utc)
        jd     = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day,
                            utc_dt.hour + utc_dt.minute / 60.0)
        nn_lon = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
        sn_lon = (nn_lon + 180) % 360

        def _lon_to_house(lon, cusps):
            lon = lon % 360
            for h in range(1, 13):
                c1 = cusps[h] % 360
                c2 = cusps[(h % 12) + 1] % 360
                if c1 <= c2:
                    if c1 <= lon < c2:
                        return h
                else:
                    if lon >= c1 or lon < c2:
                        return h
            return 1

        nn_house = _lon_to_house(nn_lon, house_cusps)
        sn_house = _lon_to_house(sn_lon, house_cusps)
        positions['North_Node'] = {
            'longitude':  nn_lon,
            'sign':       _SIGN_ABBR[int(nn_lon // 30) % 12],
            'house':      nn_house,
            'retrograde': True,
        }
        positions['South_Node'] = {
            'longitude':  sn_lon,
            'sign':       _SIGN_ABBR[int(sn_lon // 30) % 12],
            'house':      sn_house,
            'retrograde': True,
        }
        log.info('Lunar nodes via swisseph: NN Casa %d, SN Casa %d', nn_house, sn_house)
    except Exception as e:
        log.warning('Could not compute lunar nodes via swisseph: %s', e)

    return positions, house_cusps, local_dt, lat, lng, subject


# ── SVG chart ─────────────────────────────────────────────────────────────────

_PURPLE_THEME_CSS = """
<style>
:root, svg {
  --kerykeion-color-neutral-content: #a0a0b0;
  --kerykeion-color-base-content:    #a0a0b0;

  --kerykeion-chart-color-paper-0: #0d0d1a;
  --kerykeion-chart-color-paper-1: #13101e;

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

  --kerykeion-chart-color-zodiac-radix-ring-0: #b89947;
  --kerykeion-chart-color-zodiac-radix-ring-1: #a08535;
  --kerykeion-chart-color-zodiac-radix-ring-2: #8a7020;

  --kerykeion-chart-color-houses-radix-line: #6b637d;
  --kerykeion-chart-color-house-number: #d4af37;

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

  --kerykeion-chart-color-chiron:      transparent;
  --kerykeion-chart-color-mean-lilith: transparent;
  --kerykeion-chart-color-true-lilith: transparent;

  --kerykeion-chart-color-first-house:   #d4af37;
  --kerykeion-chart-color-tenth-house:   #d4af37;
  --kerykeion-chart-color-seventh-house: #d4af37;
  --kerykeion-chart-color-fourth-house:  #d4af37;

  --kerykeion-chart-color-conjunction: rgba(216, 200, 248, 0.35);
  --kerykeion-chart-color-sextile:     rgba(142, 202, 230, 0.35);
  --kerykeion-chart-color-square:      rgba(232, 144, 122, 0.35);
  --kerykeion-chart-color-trine:       rgba(136, 212, 176, 0.35);
  --kerykeion-chart-color-opposition:  rgba(232, 144, 122, 0.35);

  --kerykeion-chart-color-semi-sextile:   transparent;
  --kerykeion-chart-color-semi-square:    transparent;
  --kerykeion-chart-color-quintile:       transparent;
  --kerykeion-chart-color-sesquiquadrate: transparent;
  --kerykeion-chart-color-biquintile:     transparent;
  --kerykeion-chart-color-quincunx:       transparent;

  --kerykeion-chart-color-fire-percentage:     #f4a87c;
  --kerykeion-chart-color-earth-percentage:    #a8c090;
  --kerykeion-chart-color-air-percentage:      #8ecae6;
  --kerykeion-chart-color-water-percentage:    #b8a8e8;
  --kerykeion-chart-color-cardinal-percentage: #88d4b0;
  --kerykeion-chart-color-fixed-percentage:    #e8cc84;
  --kerykeion-chart-color-mutable-percentage:  #e8a08c;
}

[kr\:node="Top_Left_Text"],
[kr\:node="Bottom_Left_Text"],
[kr\:node="Elements_Percentages"],
[kr\:node="Qualities_Percentages"],
[kr\:node="Houses_And_Planets_Grid"],
[kr\:node="Aspect_Grid"],
[kr\:node="Aspect_List"],
[kr\:node="Lunar_Phase"] { display: none; }

text { fill: #e0e0e0; }
line { stroke-dasharray: none; }
</style>
"""


def _apply_purple_theme(svg_string: str) -> str:
    svg_string = re.sub(r'(<svg\b[^>]*>)', r'\1' + _PURPLE_THEME_CSS, svg_string, count=1)
    m = re.search(r'<svg\b[^>]+\bwidth=["\'](\d+(?:\.\d+)?)["\']', svg_string)
    if m:
        w = m.group(1)
        svg_string = re.sub(r'(<svg\b[^>]*\bheight=)["\'][\d. ]+["\']', rf'\g<1>"{w}"', svg_string)
        svg_string = re.sub(r'(<svg\b[^>]*\bviewBox=)["\'][\d. ]+["\']', rf'\g<1>"0 0 {w} {w}"', svg_string)
    return svg_string


def _scale_planet_glyphs(svg_string: str, factor: float = 0.85) -> str:
    def _shrink(m):
        tag = m.group(0)
        tag = re.sub(r'scale\(1(?:\.0)?(?:,\s*1(?:\.0)?)?\)', f'scale({factor},{factor})', tag)
        return tag
    return re.sub(r'<use\b[^/]*/>', _shrink, svg_string)


def _generate_chart_svg(subject) -> str | None:
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


# ── Aspects for public chart (simple, no grading) ─────────────────────────────

_ASPECT_TYPES = [
    ('Conjuncion', 0, 8), ('Oposicion', 180, 8), ('Trigono', 120, 8),
    ('Cuadratura', 90, 7), ('Sextil', 60, 6),
]


def _compute_aspects(positions: dict) -> list[dict]:
    planets = [(name, data['longitude']) for name, data in positions.items()
               if name not in ('MC', 'Medium_Coeli', 'Descendant', 'Imum_Coeli')]
    aspects = []
    for i in range(len(planets)):
        for j in range(i + 1, len(planets)):
            n1, lon1 = planets[i]
            n2, lon2 = planets[j]
            diff = abs(lon1 - lon2) % 360
            if diff > 180:
                diff = 360 - diff
            for asp_name, asp_angle, orb in _ASPECT_TYPES:
                if abs(diff - asp_angle) <= orb:
                    aspects.append({'p1': n1, 'p2': n2, 'aspect': asp_name,
                                    'orb': round(abs(diff - asp_angle), 2)})
                    break
    return aspects


# ── Public chart (no AI) ───────────────────────────────────────────────────────

def compute_chart(birth_date, birth_time, birth_place, lat=None, lng=None) -> dict:
    """Compute positions + SVG only. Used by the free public /chart page."""
    positions, house_cusps, local_dt, lat, lng, subject = \
        _build_chart_kerykeion(birth_date, birth_time, birth_place, lat=lat, lng=lng)

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Chart SVG generation failed: %s', e)

    return {
        'positions':   positions,
        'house_cusps': house_cusps,
        'aspects':     _compute_aspects(positions),
        'chart_image': chart_image,
        'local_dt':    local_dt,
    }


# ── Pipeline ───────────────────────────────────────────────────────────────────

def _build_overall_text(pos_es: dict, house_cusps: dict) -> str:
    """Full planet list + house cusps — included in every house-group call for context."""
    ORDER = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
             'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto',
             'North_Node', 'South_Node',
             'Ascendant', 'Medium_Coeli', 'Descendant', 'Imum_Coeli']
    lines = ['Posiciones planetarias:']
    for name in ORDER:
        if name in pos_es:
            p     = pos_es[name]
            retro = ' (retrógrado)' if p.get('retrogrado') else ''
            dig   = f", {p['dignidad']}" if p.get('dignidad') else ''
            lines.append(
                f"  {p['planeta_es']}: {p['grado']} — {p['signo']} — "
                f"Casa {p['casa']}{dig}{retro}")
    lines.append('')
    lines.append('Cúspides:')
    for h in sorted(house_cusps):
        lines.append(f'  Casa {h}: {house_cusps[h]:.2f}°')
    return '\n'.join(lines)


def _build_house_breakdown_single(house: int, pos_es: dict, aspects: list) -> str:
    """Planets + intra-house + inter-house aspects for a single house."""
    planets = []
    for name, p in pos_es.items():
        if p.get('casa') == house:
            retro = ' (retrógrado)' if p.get('retrogrado') else ''
            dig   = f", {p['dignidad']}" if p.get('dignidad') else ''
            planets.append(f"  — {p['planeta_es']}: {p['grado']} — {p['signo']}{dig}{retro}")

    intra, inter = [], []
    for asp in aspects:
        h1, h2 = asp.get('casa_a'), asp.get('casa_b')
        if h1 is None or h2 is None:
            continue
        if h1 != house and h2 != house:
            continue
        s1  = pos_es.get(asp['a'], {}).get('signo', '')
        s2  = pos_es.get(asp['b'], {}).get('signo', '')
        txt = (f"  — {asp['a_es']} ({s1}, Casa {h1}) {asp['aspecto']} "
               f"{asp['b_es']} ({s2}, Casa {h2}), orbe {asp['orbe']:+.2f}°")
        if h1 == house and h2 == house:
            intra.append(txt)
        else:
            inter.append(txt)

    lines = []
    lines.append('Planetas:')
    lines.extend(planets or ['  (ninguno)'])
    lines.append('Aspectos intradomiciliarios:')
    lines.extend(intra or ['  (ninguno)'])
    lines.append('Aspectos interdomiciliarios:')
    lines.extend(inter or ['  (ninguno)'])
    return '\n'.join(lines)


def _gender_note(gender: str | None) -> str:
    if gender == 'femenino':
        return 'El lector es mujer. Usa concordancia gramatical en femenino en todo momento.'
    if gender == 'masculino':
        return 'El lector es hombre. Usa concordancia gramatical en masculino en todo momento.'
    return ''


def _call_section(sec: dict, pos_es: dict, aspects: list,
                  house_cusps: dict, gender: str | None = None) -> tuple[int, str]:
    import prompts as P
    n    = sec['n']
    casa = sec['casa']
    gnote = _gender_note(gender)

    if casa is None:
        # Section 1: personality snapshot — Sun, Moon, Ascendant
        data_lines = []
        for name in ['Sun', 'Moon', 'Ascendant']:
            if name in pos_es:
                p     = pos_es[name]
                retro = ' (retrógrado)' if p.get('retrogrado') else ''
                dig   = f", {p['dignidad']}" if p.get('dignidad') else ''
                data_lines.append(
                    f"  {p['planeta_es']}: {p['grado']} — {p['signo']} — "
                    f"Casa {p['casa']}{dig}{retro}")
        msg = P.PROMPT_PERSONALIDAD.format(data='\n'.join(data_lines), gender_note=gnote)
        raw = _ask([{'role': 'user', 'content': msg}],
                   model=_MODEL_PROSE, temperature=0.85)
    else:
        overall   = _build_overall_text(pos_es, house_cusps)
        breakdown = _build_house_breakdown_single(casa, pos_es, aspects)
        msg = P.PROMPT_CASA.format(n=casa, overall=overall, breakdown=breakdown, gender_note=gnote)
        raw = _ask([{'role': 'user', 'content': msg}],
                   model=_MODEL_PROSE, temperature=0.85)
    return n, raw


def _assemble(results: list) -> str:
    import prompts as P
    by_n = dict(results)
    parts = []
    for sec in P.SECCIONES:
        n = sec['n']
        if n in by_n:
            parts.append(f"## {sec['titulo']}\n\n{by_n[n]}")
    return '\n\n'.join(parts)


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_horoscope(user, reading_type) -> dict:
    import prompts as P
    birth_date  = user.birth_date
    birth_time  = user.birth_time
    birth_place = user.birth_place or 'unknown'

    positions, house_cusps, local_dt, lat, lng, subject = \
        _build_chart_kerykeion(birth_date, birth_time, birth_place)
    log.info('Chart built for %s', birth_place)

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Chart SVG generation failed: %s', e)

    from chart_analysis import build_dossier
    known_time = birth_time is not None
    dossier    = build_dossier(subject, positions, house_cusps,
                               known_birth_time=known_time)
    pos_es     = dossier['posiciones']   # Spanish names, signs, dignity
    aspects    = dossier['aspectos']     # graded, with casa_a / casa_b
    log.info('Dossier built, %d aspects', len(aspects))

    gender = getattr(user, 'gender', None)
    with ThreadPoolExecutor(max_workers=13) as ex:
        results = list(ex.map(
            lambda sec: _call_section(sec, pos_es, aspects, house_cusps, gender),
            P.SECCIONES))
    log.info('Sections written: %d', len(results))

    documento = _assemble(results)
    log.info('Document assembled: ~%d words', len(documento.split()))

    return {
        'text':        documento,
        'chart_image': chart_image,
    }
