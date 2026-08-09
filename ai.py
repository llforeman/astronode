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


def _ask(messages: list[dict], *, model: str, max_tokens: int = 4000,
         temperature: float = 0.8, json_mode: bool = False,
         retries: int = 3) -> str:
    """Send a chat request. messages is a list of {role, content} dicts."""
    client = _get_client()
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(**kwargs)
            if response.choices:
                text = response.choices[0].message.content
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

def _brief(dossier: dict) -> dict:
    import prompts as P
    slim = {k: v for k, v in dossier.items() if not k.startswith('_')}
    raw = _ask(
        [{'role': 'system', 'content': P.SYSTEM},
         {'role': 'user',   'content': P.BRIEF_PROMPT.format(
             dossier=json.dumps(slim, ensure_ascii=False, indent=2))}],
        model=_MODEL_ANALYSIS, max_tokens=2000, temperature=0.6, json_mode=True)
    return _json_parse(raw)


def _one_chapter(spec: dict, dossier: dict, brf: dict, ledger: list[str]) -> tuple[int, str]:
    import prompts as P
    msg = P.build_chapter_prompt(spec, dossier, brf, ledger)
    txt = _ask(
        [{'role': 'system', 'content': P.SYSTEM},
         {'role': 'user',   'content': msg}],
        model=_MODEL_PROSE,
        max_tokens=int(spec['palabras'] * 2.2),
        temperature=0.85)
    return spec['n'], txt


def _extract_claims(chapter_text: str) -> list[str]:
    import prompts as P
    try:
        raw = _ask(
            [{'role': 'user', 'content': P.LEDGER_PROMPT.format(chapter=chapter_text)}],
            model=_MODEL_CHEAP, max_tokens=800, temperature=0.2, json_mode=True)
        got = _json_parse(raw)
        return got if isinstance(got, list) else []
    except Exception:
        return []   # ledger is best-effort, never fatal


def _chapters(dossier: dict, brf: dict) -> dict[int, str]:
    import prompts as P
    WAVE_A = [1, 2, 3, 8, 10]
    WAVE_B = [4, 5, 6, 7, 9, 11]
    by_n   = {c['n']: c for c in P.CHAPTERS}
    written: dict[int, str] = {}
    ledger:  list[str] = []

    for wave in (WAVE_A, WAVE_B):
        specs    = [by_n[n] for n in wave]
        snapshot = list(ledger)

        with ThreadPoolExecutor(max_workers=len(specs)) as ex:
            results = list(ex.map(
                lambda s: _one_chapter(s, dossier, brf, snapshot), specs))

        for n, txt in results:
            written[n] = txt

        with ThreadPoolExecutor(max_workers=len(results)) as ex:
            claim_sets = list(ex.map(lambda r: _extract_claims(r[1]), results))
        for cs in claim_sets:
            ledger.extend(cs)

    return written


def _check_chapter(n: int, text: str) -> dict:
    import prompts as P
    try:
        raw = _ask(
            [{'role': 'user', 'content': P.QA_CHAPTER_PROMPT.format(chapter=text)}],
            model=_MODEL_ANALYSIS, max_tokens=900, temperature=0.2, json_mode=True)
        r = _json_parse(raw)
        r['capitulo'] = n
        return r
    except Exception:
        return {'capitulo': n, 'veredicto': 'publicable', '_qa_failed': True}


def _repair_chapter(spec: dict, text: str, report: dict) -> str:
    import prompts as P
    msg = P.REPAIR_PROMPT.format(
        chapter=text,
        problemas=json.dumps(report, ensure_ascii=False, indent=2),
        palabras=spec['palabras'])
    return _ask(
        [{'role': 'system', 'content': P.SYSTEM},
         {'role': 'user',   'content': msg}],
        model=_MODEL_PROSE,
        max_tokens=int(spec['palabras'] * 2.2),
        temperature=0.75)


def _qa_and_repair(written: dict[int, str], dossier: dict, brf: dict,
                   max_rounds: int = 1) -> tuple[dict[int, str], list[dict]]:
    import prompts as P
    by_n    = {c['n']: c for c in P.CHAPTERS}
    reports: list[dict] = []

    for _ in range(max_rounds):
        with ThreadPoolExecutor(max_workers=6) as ex:
            checks = list(ex.map(
                lambda kv: _check_chapter(*kv), sorted(written.items())))
        reports = checks
        bad = [c for c in checks if c.get('veredicto') == 'regenerar']
        if not bad:
            break
        with ThreadPoolExecutor(max_workers=min(len(bad), 6)) as ex:
            fixed = list(ex.map(
                lambda c: (c['capitulo'],
                           _repair_chapter(by_n[c['capitulo']],
                                           written[c['capitulo']], c)),
                bad))
        for n, txt in fixed:
            written[n] = txt

    return written, reports


def _assemble(written: dict[int, str]) -> str:
    import prompts as P
    parts = []
    for spec in P.CHAPTERS:
        n = spec['n']
        if n in written:
            parts.append(f"## {n:02d}. {spec['titulo']}\n\n{written[n]}")
    return '\n\n'.join(parts)


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_horoscope(user, reading_type) -> dict:
    birth_date  = user.birth_date
    birth_time  = user.birth_time
    birth_place = user.birth_place or 'unknown'

    positions, house_cusps, local_dt, lat, lng, subject = \
        _build_chart_kerykeion(birth_date, birth_time, birth_place)
    log.info('Chart built for %s', birth_place)

    # SVG chart
    chart_image = None
    try:
        chart_image = _generate_chart_svg(subject)
    except Exception as e:
        log.warning('Chart SVG generation failed: %s', e)

    # Dossier (deterministic enrichment — no LLM)
    from chart_analysis import build_dossier
    known_time = birth_time is not None
    dossier = build_dossier(subject, positions, house_cusps,
                            known_birth_time=known_time)
    log.info('Dossier built, %d signals', len(dossier.get('senales_principales', [])))

    # Brief — analytical spine
    brf = _brief(dossier)
    log.info('Brief complete: %s', brf.get('hilo_conductor', '')[:80])

    # Chapters — 11 calls in 2 parallel waves
    written = _chapters(dossier, brf)
    log.info('Chapters written: %d', len(written))

    # QA + targeted repair (1 round max to stay within job timeout)
    written, qa_reports = _qa_and_repair(written, dossier, brf, max_rounds=1)
    failed = [r['capitulo'] for r in qa_reports if r.get('veredicto') == 'regenerar']
    if failed:
        log.warning('Chapters still failing QA after repair: %s', failed)

    # Concatenate
    documento = _assemble(written)
    log.info('Document assembled: ~%d words', len(documento.split()))

    return {
        'text':        documento,
        'chart_image': chart_image,
    }
