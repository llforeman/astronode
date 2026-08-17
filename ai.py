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

        # Chiron
        ch_res  = swe.calc_ut(jd, swe.CHIRON)
        ch_lon  = ch_res[0][0]
        ch_spd  = ch_res[0][3]   # daily motion; negative = retrograde
        ch_house = _lon_to_house(ch_lon, house_cusps)
        positions['Chiron'] = {
            'longitude':  ch_lon,
            'sign':       _SIGN_ABBR[int(ch_lon // 30) % 12],
            'house':      ch_house,
            'retrograde': ch_spd < 0,
        }
        log.info('Chiron via swisseph: %.2f° Casa %d', ch_lon, ch_house)
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

  --kerykeion-chart-color-chiron:      #c8a0e0;
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


# ── Age Point (Huber) ─────────────────────────────────────────────────────────

_SIGNS_ES = [
    'Aries', 'Tauro', 'Géminis', 'Cáncer', 'Leo', 'Virgo',
    'Libra', 'Escorpio', 'Sagitario', 'Capricornio', 'Acuario', 'Piscis',
]


def compute_age_point(house_cusps: dict, birth_date, target_date=None,
                      positions: dict = None) -> dict:
    """
    Compute the Huber Age Point.

    The AP completes one full loop through all 12 houses in 72 years,
    starting at the Ascendant (house 1 cusp) at birth.
    Time spent in each house is proportional to its angular span.

    Args:
        house_cusps: {1: lon, ..., 12: lon} ecliptic degrees 0-360
        birth_date:  datetime.date
        target_date: datetime.date (defaults to today)
        positions:   natal planet dict from compute_chart / _build_chart_kerykeion

    Returns dict with current house, longitude, sign, aspects, upcoming aspects.
    """
    import datetime as _dt

    if target_date is None:
        target_date = _dt.date.today()

    age = (target_date - birth_date).days / 365.25
    cycle = int(age // 72)
    age_in_cycle = age % 72

    # Angular span of each house (degrees from its cusp to next cusp)
    spans = {}
    for h in range(1, 13):
        next_h = (h % 12) + 1
        spans[h] = (house_cusps[next_h] - house_cusps[h]) % 360

    # Age at entry into each house (proportional to cumulative span)
    entry_ages = {}
    cumulative_deg = 0.0
    for h in range(1, 13):
        entry_ages[h] = cumulative_deg / 360.0 * 72.0
        cumulative_deg += spans[h]

    # Locate current house
    current_house = 12
    house_entry_age = entry_ages[12]
    house_exit_age = 72.0
    for h in range(1, 13):
        next_h = (h % 12) + 1
        exit_age = entry_ages[next_h] if next_h != 1 else 72.0
        if entry_ages[h] <= age_in_cycle < exit_age:
            current_house = h
            house_entry_age = entry_ages[h]
            house_exit_age = exit_age
            break

    span_h = max(spans[current_house], 0.001)
    dur_h  = max(house_exit_age - house_entry_age, 0.001)
    progress = (age_in_cycle - house_entry_age) / dur_h
    ap_lon = (house_cusps[current_house] + progress * span_h) % 360

    out = {
        'age':               round(age, 1),
        'cycle':             cycle + 1,
        'age_in_cycle':      round(age_in_cycle, 1),
        'longitude':         round(ap_lon, 2),
        'sign':              _SIGNS_ES[int(ap_lon // 30) % 12],
        'degree':            round(ap_lon % 30, 1),
        'house':             current_house,
        'house_entry_age':   round(house_entry_age, 1),
        'house_exit_age':    round(house_exit_age, 1),
        'progress_in_house': min(round(progress * 100), 100),
        'current_aspects':   [],
        'upcoming_aspects':  [],
    }

    if not positions:
        return out

    _ASPECT_TYPES = [
        ('conjunción', 0), ('oposición', 180), ('trígono', 120),
        ('cuadratura', 90), ('sextil', 60),
    ]
    _SKIP = {'MC', 'Medium_Coeli', 'Descendant', 'Imum_Coeli'}
    ORB = 3.0

    # Current aspects
    current_aspects = []
    for pname, pdata in positions.items():
        if pname in _SKIP:
            continue
        plon = pdata['longitude']
        diff = abs(ap_lon - plon) % 360
        if diff > 180:
            diff = 360 - diff
        for asp_name, asp_angle in _ASPECT_TYPES:
            orb = abs(diff - asp_angle)
            if orb <= ORB:
                current_aspects.append({'planet': pname, 'aspect': asp_name, 'orb': round(orb, 1)})
                break
    current_aspects.sort(key=lambda x: x['orb'])
    out['current_aspects'] = current_aspects

    # Upcoming aspects in next 5 years
    upcoming = []
    LOOKAHEAD = 5.0

    for pname, pdata in positions.items():
        if pname in _SKIP:
            continue
        plon = pdata['longitude']
        for asp_name, asp_angle in _ASPECT_TYPES:
            target_lons = {(plon + asp_angle) % 360, (plon - asp_angle) % 360}
            for tlon in target_lons:
                for h in range(1, 13):
                    delta = (tlon - house_cusps[h]) % 360
                    if delta < spans[h]:
                        next_h2 = (h % 12) + 1
                        exit_h = entry_ages[next_h2] if next_h2 != 1 else 72.0
                        frac = delta / max(spans[h], 0.001)
                        asp_age = entry_ages[h] + frac * (exit_h - entry_ages[h])

                        years_away = asp_age - age_in_cycle
                        if years_away <= 0:
                            years_away += 72.0

                        if 0 < years_away <= LOOKAHEAD:
                            asp_date = target_date + _dt.timedelta(days=int(years_away * 365.25))
                            upcoming.append({
                                'planet':     pname,
                                'aspect':     asp_name,
                                'age':        round(age_in_cycle + years_away, 1),
                                'date':       asp_date.strftime('%b %Y'),
                                'years_away': round(years_away, 1),
                            })
                        break

    upcoming.sort(key=lambda x: x['years_away'])
    out['upcoming_aspects'] = upcoming[:10]

    return out


# ── Pipeline ───────────────────────────────────────────────────────────────────

def _build_overall_text(pos_es: dict, house_cusps: dict) -> str:
    """Full planet list + house cusps — included in every house-group call for context."""
    ORDER = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
             'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto',
             'Chiron', 'North_Node', 'South_Node',
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


# ── Inter-aspects (synastry) ───────────────────────────────────────────────────

def _compute_inter_aspects(pos_a: dict, pos_b: dict) -> list[dict]:
    """Aspects between planet set A and planet set B (no intra-set pairs)."""
    from chart_analysis import CORE, ASTEROIDS, ANGLES, NODES, ASPECT_ES, PLANET_ES
    bodies = CORE + ASTEROIDS + ANGLES[:2] + NODES  # ASC + MC only

    inter = []
    _TYPES = [('conjunción', 0, 8), ('oposición', 180, 7),
              ('cuadratura', 90, 6), ('trígono', 120, 6), ('sextil', 60, 4)]

    for n1 in bodies:
        if n1 not in pos_a:
            continue
        lon1 = pos_a[n1]['longitude']
        for n2 in bodies:
            if n2 not in pos_b:
                continue
            lon2 = pos_b[n2]['longitude']
            diff = abs(lon1 - lon2) % 360
            if diff > 180:
                diff = 360 - diff
            for asp, angle, orb in _TYPES:
                if abs(diff - angle) <= orb:
                    inter.append({
                        'a': n1, 'b': n2,
                        'a_es': PLANET_ES.get(n1, n1),
                        'b_es': PLANET_ES.get(n2, n2),
                        'aspecto': asp,
                        'orbe': round(abs(diff - angle), 2),
                        'casa_a': pos_a[n1].get('house'),
                        'casa_b': pos_b[n2].get('house'),
                    })
                    break
    inter.sort(key=lambda x: x['orbe'])
    return inter


def _inter_aspects_text(inter: list, name_a: str, name_b: str) -> str:
    from chart_analysis import PLANET_ES
    lines = []
    for asp in inter[:40]:  # cap to avoid huge prompts
        lines.append(
            f"  {name_a}/{asp['a_es']} {asp['aspecto']} {name_b}/{asp['b_es']} "
            f"(orbe {asp['orbe']}°, casa {asp['casa_a']} — casa {asp['casa_b']})"
        )
    return '\n'.join(lines) if lines else '  (ninguno encontrado)'


def _positions_summary(pos_es: dict) -> str:
    """Compact text of all placements for prompt context."""
    lines = []
    for name, p in pos_es.items():
        retro = ' R' if p.get('retrogrado') else ''
        lines.append(f"  {p['planeta_es']}: {p['grado']} Casa {p['casa']}{retro}")
    return '\n'.join(lines)


# ── Carta Kármica ──────────────────────────────────────────────────────────────

def generate_karmic(profile, reading_type) -> dict:
    import prompts as P
    birth_date  = profile.birth_date
    birth_time  = profile.birth_time
    birth_place = profile.birth_place or 'unknown'

    positions, house_cusps, local_dt, lat, lng, subject = \
        _build_chart_kerykeion(birth_date, birth_time, birth_place,
                               lat=getattr(profile, 'birth_lat', None),
                               lng=getattr(profile, 'birth_lng', None))

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Chart SVG failed: %s', e)

    from chart_analysis import build_dossier
    dossier = build_dossier(subject, positions, house_cusps,
                            known_birth_time=birth_time is not None)
    pos_es  = dossier['posiciones']
    aspects = dossier['aspectos']
    gender  = getattr(profile, 'gender', None)
    gnote   = _gender_note(gender)

    def _karmic_data(*keys):
        lines = []
        for k in keys:
            p = pos_es.get(k)
            if p:
                retro = ' (retrógrado)' if p.get('retrogrado') else ''
                lines.append(f"  {p['planeta_es']}: {p['grado']} — {p['signo']} — Casa {p['casa']}{retro}")
        # add aspects involving these planets
        for asp in aspects:
            if asp['a'] in keys or asp['b'] in keys:
                lines.append(f"  Aspecto: {asp['a_es']} {asp['aspecto']} {asp['b_es']} orbe {asp['orbe']}°")
        return '\n'.join(lines)

    retrogrades = [n for n, p in pos_es.items() if p.get('retrogrado')]
    retro_text  = ', '.join(pos_es[n]['planeta_es'] for n in retrogrades if n in pos_es) or 'ninguno'

    casa12_planets = [p['planeta_es'] for p in pos_es.values() if p.get('casa') == 12]
    casa12_text    = ', '.join(casa12_planets) or 'ninguno'

    calls = [
        (1, P.PROMPT_KARMICA_KARMA_PASADO.format(
            gender_note=gnote,
            data=_karmic_data('South_Node') + f"\n  Casa 12: {casa12_text}")),
        (2, P.PROMPT_KARMICA_NODO_NORTE.format(
            gender_note=gnote,
            data=_karmic_data('North_Node'))),
        (3, P.PROMPT_KARMICA_SATURNO.format(
            gender_note=gnote,
            data=_karmic_data('Saturn'))),
        (4, P.PROMPT_KARMICA_CHIRON.format(
            gender_note=gnote,
            data=_karmic_data('Chiron'))),
        (5, P.PROMPT_KARMICA_PATRONES.format(
            gender_note=gnote,
            data=f"  Retrógrados: {retro_text}\n  Casa 12: {casa12_text}")),
        (6, P.PROMPT_KARMICA_SINTESIS.format(
            gender_note=gnote,
            data=_build_overall_text(pos_es, house_cusps))),
    ]

    from concurrent.futures import ThreadPoolExecutor
    def _call(item):
        n, msg = item
        return n, _ask([{'role': 'user', 'content': msg}],
                       model=_MODEL_PROSE, temperature=0.85)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_call, calls))

    by_n = dict(results)
    parts = [f"## {sec['titulo']}\n\n{by_n[sec['n']]}"
             for sec in P.SECCIONES_KARMICA if sec['n'] in by_n]
    return {'text': '\n\n'.join(parts), 'chart_image': chart_image}


# ── Sinastría ─────────────────────────────────────────────────────────────────

def generate_synastry(profile_a, profile_b, reading_type) -> dict:
    import prompts as P
    import datetime as _dt

    def _chart(p):
        bd = p.birth_date
        bt = p.birth_time or _dt.time(12, 0)
        bp = p.birth_place or 'unknown'
        pos, cusps, ldt, lat, lng, subj = _build_chart_kerykeion(
            bd, bt, bp,
            lat=getattr(p, 'birth_lat', None),
            lng=getattr(p, 'birth_lng', None))
        from chart_analysis import build_dossier
        dossier = build_dossier(subj, pos, cusps, known_birth_time=p.birth_time is not None)
        return pos, dossier['posiciones']

    pos_a, es_a = _chart(profile_a)
    pos_b, es_b = _chart(profile_b)

    inter = _compute_inter_aspects(pos_a, pos_b)
    inter_txt = _inter_aspects_text(inter, profile_a.name, profile_b.name)
    carta_a = _positions_summary(es_a)
    carta_b = _positions_summary(es_b)

    calls = []
    for sec in P.SECCIONES_SINASTRIA:
        n = sec['n']
        msg = P.PROMPT_SINASTRIA_BASE.format(
            nombre_a=profile_a.name,
            nombre_b=profile_b.name,
            instruccion=P.INSTRUCCION_SINASTRIA[n],
            carta_a=carta_a,
            carta_b=carta_b,
            interaspectos=inter_txt,
        )
        calls.append((n, msg))

    from concurrent.futures import ThreadPoolExecutor
    def _call(item):
        n, msg = item
        return n, _ask([{'role': 'user', 'content': msg}],
                       model=_MODEL_PROSE, temperature=0.85)

    with ThreadPoolExecutor(max_workers=7) as ex:
        results = list(ex.map(_call, calls))

    by_n = dict(results)
    parts = [f"## {sec['titulo']}\n\n{by_n[sec['n']]}"
             for sec in P.SECCIONES_SINASTRIA if sec['n'] in by_n]
    return {'text': '\n\n'.join(parts), 'chart_image': None}


# ── Carta Davison ─────────────────────────────────────────────────────────────

def generate_davison(profile_a, profile_b, reading_type) -> dict:
    import prompts as P
    import datetime as _dt
    import pytz
    from timezonefinder import TimezoneFinder

    def _jd(p):
        import swisseph as swe
        bt = p.birth_time or _dt.time(12, 0)
        return swe.julday(p.birth_date.year, p.birth_date.month, p.birth_date.day,
                          bt.hour + bt.minute / 60.0)

    jd_a  = _jd(profile_a)
    jd_b  = _jd(profile_b)
    jd_mid = (jd_a + jd_b) / 2.0

    lat_a = getattr(profile_a, 'birth_lat', None) or _geocode(profile_a.birth_place or 'Madrid')[0]
    lng_a = getattr(profile_a, 'birth_lng', None) or _geocode(profile_a.birth_place or 'Madrid')[1]
    lat_b = getattr(profile_b, 'birth_lat', None) or _geocode(profile_b.birth_place or 'Madrid')[0]
    lng_b = getattr(profile_b, 'birth_lng', None) or _geocode(profile_b.birth_place or 'Madrid')[1]
    lat_mid = (lat_a + lat_b) / 2.0
    lng_mid = (lng_a + lng_b) / 2.0

    # Convert midpoint JD back to a datetime for Kerykeion
    import swisseph as swe
    jd_parts = swe.revjul(jd_mid)
    year, month, day = int(jd_parts[0]), int(jd_parts[1]), int(jd_parts[2])
    hour_frac = jd_parts[3]
    hour, minute = int(hour_frac), int((hour_frac % 1) * 60)
    mid_date = _dt.date(year, month, day)
    mid_time = _dt.time(hour, minute)

    tf = TimezoneFinder()
    tz_str = tf.timezone_at(lng=lng_mid, lat=lat_mid) or 'UTC'

    positions, house_cusps, local_dt, _lat, _lng, subject = \
        _build_chart_kerykeion(mid_date, mid_time, f'{lat_mid:.4f},{lng_mid:.4f}',
                               lat=lat_mid, lng=lng_mid)

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Davison SVG failed: %s', e)

    from chart_analysis import build_dossier
    dossier = build_dossier(subject, positions, house_cusps, known_birth_time=True)
    pos_es  = dossier['posiciones']
    carta_d = _positions_summary(pos_es)

    calls = []
    for sec in P.SECCIONES_DAVISON:
        n = sec['n']
        msg = P.PROMPT_DAVISON_BASE.format(
            nombre_a=profile_a.name,
            nombre_b=profile_b.name,
            instruccion=P.INSTRUCCION_DAVISON[n],
            carta_davison=carta_d,
        )
        calls.append((n, msg))

    from concurrent.futures import ThreadPoolExecutor
    def _call(item):
        n, msg = item
        return n, _ask([{'role': 'user', 'content': msg}],
                       model=_MODEL_PROSE, temperature=0.85)

    with ThreadPoolExecutor(max_workers=7) as ex:
        results = list(ex.map(_call, calls))

    by_n = dict(results)
    parts = [f"## {sec['titulo']}\n\n{by_n[sec['n']]}"
             for sec in P.SECCIONES_DAVISON if sec['n'] in by_n]
    return {'text': '\n\n'.join(parts), 'chart_image': chart_image}


# ── Solar / Lunar Return helpers ───────────────────────────────────────────────

def _find_return(natal_lon: float, body_id: int, start_jd: float,
                 period_days: float) -> float:
    """Binary-search for the JD when body reaches natal_lon after start_jd."""
    import swisseph as swe
    jd = start_jd
    for _ in range(50):
        lon = swe.calc_ut(jd, body_id)[0][0]
        diff = (natal_lon - lon) % 360
        if diff > 180:
            diff -= 360
        if abs(diff) < 0.0001:
            break
        jd += diff / (360 / period_days)
    return jd


def _jd_for_profile(profile) -> float:
    import swisseph as swe
    import datetime as _dt
    bt = profile.birth_time or _dt.time(12, 0)
    return swe.julday(profile.birth_date.year, profile.birth_date.month,
                      profile.birth_date.day, bt.hour + bt.minute / 60.0)


def _chart_summary(pos_es: dict, house_cusps: dict) -> str:
    return _build_overall_text(pos_es, house_cusps)


# ── Revolución Solar ──────────────────────────────────────────────────────────

def generate_solar_return(profile, params: dict, reading_type) -> dict:
    import prompts as P
    import swisseph as swe
    import datetime as _dt

    target_year = int(params.get('year', profile.birth_date.year + 1))
    sr_place    = params.get('place') or profile.birth_place or 'unknown'
    sr_lat      = params.get('lat') or getattr(profile, 'birth_lat', None)
    sr_lng      = params.get('lng') or getattr(profile, 'birth_lng', None)

    # Natal chart
    positions_n, cusps_n, _, _lat_n, _lng_n, subj_n = _build_chart_kerykeion(
        profile.birth_date, profile.birth_time or _dt.time(12, 0),
        profile.birth_place or 'unknown',
        lat=getattr(profile, 'birth_lat', None),
        lng=getattr(profile, 'birth_lng', None))

    natal_sun_lon = positions_n['Sun']['longitude']

    # Start search a bit before birthday in target year
    start_jd = swe.julday(target_year, profile.birth_date.month,
                           max(1, profile.birth_date.day - 5), 12.0)
    sr_jd = _find_return(natal_sun_lon, swe.SUN, start_jd, 365.25)

    # Build SR chart at the return location
    jd_parts = swe.revjul(sr_jd)
    sr_date = _dt.date(int(jd_parts[0]), int(jd_parts[1]), int(jd_parts[2]))
    hf = jd_parts[3]
    sr_time = _dt.time(int(hf), int((hf % 1) * 60))

    positions_sr, cusps_sr, _, _lat_sr, _lng_sr, subj_sr = _build_chart_kerykeion(
        sr_date, sr_time, sr_place, lat=sr_lat, lng=sr_lng)

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subj_sr)
    except Exception as e:
        log.warning('SR SVG failed: %s', e)

    from chart_analysis import build_dossier
    dossier_n  = build_dossier(subj_n,  positions_n,  cusps_n,  known_birth_time=profile.birth_time is not None)
    dossier_sr = build_dossier(subj_sr, positions_sr, cusps_sr, known_birth_time=True)

    gender  = getattr(profile, 'gender', None)
    gnote   = _gender_note(gender)
    carta_n  = _chart_summary(dossier_n['posiciones'],  cusps_n)
    carta_sr = _chart_summary(dossier_sr['posiciones'], cusps_sr)
    fecha_rs = sr_date.strftime('%d/%m/%Y')

    calls = []
    for sec in P.SECCIONES_SOLAR:
        n = sec['n']
        msg = P.PROMPT_SOLAR_BASE.format(
            nombre=profile.name,
            fecha_rs=fecha_rs,
            instruccion=P.INSTRUCCION_SOLAR[n],
            gender_note=gnote,
            carta_natal=carta_n,
            carta_rs=carta_sr,
        )
        calls.append((n, msg))

    from concurrent.futures import ThreadPoolExecutor
    def _call(item):
        n, msg = item
        return n, _ask([{'role': 'user', 'content': msg}],
                       model=_MODEL_PROSE, temperature=0.85)

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(_call, calls))

    by_n = dict(results)
    header = f"Revolución Solar {target_year} — {sr_place}\nFecha exacta del retorno: {fecha_rs}\n\n"
    parts = [f"## {sec['titulo']}\n\n{by_n[sec['n']]}"
             for sec in P.SECCIONES_SOLAR if sec['n'] in by_n]
    return {'text': header + '\n\n'.join(parts), 'chart_image': chart_image}


# ── Revolución Lunar ──────────────────────────────────────────────────────────

def generate_lunar_return(profile, params: dict, reading_type) -> dict:
    import prompts as P
    import swisseph as swe
    import datetime as _dt

    target_year  = int(params.get('year',  _dt.date.today().year))
    target_month = int(params.get('month', _dt.date.today().month))
    lr_place = params.get('place') or profile.birth_place or 'unknown'
    lr_lat   = params.get('lat') or getattr(profile, 'birth_lat', None)
    lr_lng   = params.get('lng') or getattr(profile, 'birth_lng', None)

    # Natal chart
    positions_n, cusps_n, _, _lat_n, _lng_n, subj_n = _build_chart_kerykeion(
        profile.birth_date, profile.birth_time or _dt.time(12, 0),
        profile.birth_place or 'unknown',
        lat=getattr(profile, 'birth_lat', None),
        lng=getattr(profile, 'birth_lng', None))

    natal_moon_lon = positions_n['Moon']['longitude']

    # Start search at first day of target month
    start_jd = swe.julday(target_year, target_month, 1, 0.0)
    lr_jd = _find_return(natal_moon_lon, swe.MOON, start_jd, 27.3)

    jd_parts = swe.revjul(lr_jd)
    lr_date  = _dt.date(int(jd_parts[0]), int(jd_parts[1]), int(jd_parts[2]))
    hf = jd_parts[3]
    lr_time  = _dt.time(int(hf), int((hf % 1) * 60))

    positions_lr, cusps_lr, _, _lat_lr, _lng_lr, subj_lr = _build_chart_kerykeion(
        lr_date, lr_time, lr_place, lat=lr_lat, lng=lr_lng)

    chart_image = None
    try:
        chart_image = _generate_chart_svg(subj_lr)
    except Exception as e:
        log.warning('LR SVG failed: %s', e)

    from chart_analysis import build_dossier
    dossier_n  = build_dossier(subj_n,  positions_n,  cusps_n,  known_birth_time=profile.birth_time is not None)
    dossier_lr = build_dossier(subj_lr, positions_lr, cusps_lr, known_birth_time=True)

    gender  = getattr(profile, 'gender', None)
    gnote   = _gender_note(gender)
    carta_n  = _chart_summary(dossier_n['posiciones'],  cusps_n)
    carta_lr = _chart_summary(dossier_lr['posiciones'], cusps_lr)
    fecha_rl = lr_date.strftime('%d/%m/%Y')

    calls = []
    for sec in P.SECCIONES_LUNAR:
        n = sec['n']
        msg = P.PROMPT_LUNAR_BASE.format(
            nombre=profile.name,
            fecha_rl=fecha_rl,
            instruccion=P.INSTRUCCION_LUNAR[n],
            gender_note=gnote,
            carta_natal=carta_n,
            carta_rl=carta_lr,
        )
        calls.append((n, msg))

    from concurrent.futures import ThreadPoolExecutor
    def _call(item):
        n, msg = item
        return n, _ask([{'role': 'user', 'content': msg}],
                       model=_MODEL_PROSE, temperature=0.85)

    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(_call, calls))

    by_n = dict(results)
    import calendar
    month_name = calendar.month_name[target_month]
    header = f"Revolución Lunar — {month_name} {target_year} — {lr_place}\nFecha exacta del retorno: {fecha_rl}\n\n"
    parts = [f"## {sec['titulo']}\n\n{by_n[sec['n']]}"
             for sec in P.SECCIONES_LUNAR if sec['n'] in by_n]
    return {'text': header + '\n\n'.join(parts), 'chart_image': chart_image}


# ── Reading router ────────────────────────────────────────────────────────────

def generate_reading(profile, reading_type, params: dict = None,
                     profile_b=None) -> dict:
    """Route to the correct generator based on reading_type.slug."""
    params = params or {}
    slug   = getattr(reading_type, 'slug', None) or 'natal'

    if slug == 'karmic':
        return generate_karmic(profile, reading_type)
    if slug == 'synastry':
        if not profile_b:
            raise ValueError('synastry requires profile_b')
        return generate_synastry(profile, profile_b, reading_type)
    if slug == 'davison':
        if not profile_b:
            raise ValueError('davison requires profile_b')
        return generate_davison(profile, profile_b, reading_type)
    if slug == 'solar_return':
        return generate_solar_return(profile, params, reading_type)
    if slug == 'lunar_return':
        return generate_lunar_return(profile, params, reading_type)
    # default: natal
    return generate_horoscope(profile, reading_type)


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
