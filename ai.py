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

def _plan(dossier: dict) -> dict:
    """One planning call: sees whole dossier, produces theses + beats for all 9 chapters."""
    import prompts as P
    material_per_cap = {}
    for spec in P.CAPITULOS:
        sel = P.seleccionar_material(dossier, spec)
        material_per_cap[spec['n']] = P.formatear_material(sel)

    msg = P.PLANNER_PROMPT.format(
        dossier=json.dumps(dossier, ensure_ascii=False, indent=2),
        material=json.dumps(material_per_cap, ensure_ascii=False, indent=2),
    )

    plan = {}
    for attempt in range(3):
        try:
            raw = _ask(
                [{'role': 'user', 'content': msg}],
                model=_MODEL_ANALYSIS, max_tokens=3000, temperature=0.7,
                json_mode=True)
            plan = _json_parse(raw)
            errores = P.validar_plan(plan)
            if not errores:
                return plan
            log.warning('Plan validation failed (attempt %d): %s', attempt + 1, errores)
        except Exception as e:
            log.warning('Plan call failed (attempt %d): %s', attempt + 1, e)
    return plan  # best effort if all attempts had minor issues


def _write_chapter(spec: dict, plan_cap: dict, dossier: dict,
                   enlace_anterior: str, genero: str) -> tuple[int, str]:
    import prompts as P
    sel    = P.seleccionar_material(dossier, spec)
    prompt = P.construir_prompt_escritura(spec, plan_cap, sel, enlace_anterior, genero)
    raw = _ask(
        [{'role': 'system', 'content': P.SYSTEM},
         {'role': 'user',   'content': prompt}],
        model=_MODEL_PROSE,
        max_tokens=P.max_tokens_para(spec),
        temperature=0.85)
    return spec['n'], raw


def _extract_tells(n: int, text: str) -> tuple[int, list[str]]:
    import prompts as P
    try:
        raw = _ask(
            [{'role': 'user', 'content': P.COMPROBAR_PROMPT.format(chapter=text)}],
            model=_MODEL_CHEAP, max_tokens=400, temperature=0.3, json_mode=True)
        got = _json_parse(raw)
        return n, got.get('senales', [])
    except Exception as e:
        log.warning('_extract_tells ch%d failed: %s', n, e)
        return n, []


def _build_index(plan: dict) -> str:
    import prompts as P
    try:
        msg = P.construir_prompt_indice(plan)
        raw = _ask(
            [{'role': 'user', 'content': msg}],
            model=_MODEL_CHEAP, max_tokens=600, temperature=0.3, json_mode=True)
        got = _json_parse(raw)
        lines = []
        for entry in got.get('indice', []):
            caps = ', '.join(str(c) for c in entry.get('capitulos', []))
            lines.append(f"**{entry['area']}** (cap. {caps}): {entry['frase']}")
        return '\n'.join(lines)
    except Exception as e:
        log.warning('_build_index failed: %s', e)
        return ''


def _write_all_chapters(dossier: dict, plan: dict,
                        genero: str) -> tuple[dict[int, str], dict[int, list[str]]]:
    """All 9 chapters in parallel — enlaces come from the plan, not written text."""
    import prompts as P
    by_n      = {c['n']: c for c in P.CAPITULOS}
    plan_by_n = {c['n']: c for c in plan.get('capitulos', [])}

    enlace_map: dict[int, str] = {}
    for cap in plan.get('capitulos', []):
        enlace_beat = next(
            (b['contenido'] for b in cap.get('beats', []) if b.get('tipo') == 'enlace'),
            '')
        next_n = cap['n'] + 1
        if next_n in by_n:
            enlace_map[next_n] = enlace_beat

    def _write(spec):
        plan_cap        = plan_by_n.get(spec['n'], {})
        enlace_anterior = enlace_map.get(spec['n'], '')
        return _write_chapter(spec, plan_cap, dossier, enlace_anterior, genero)

    with ThreadPoolExecutor(max_workers=len(P.CAPITULOS)) as ex:
        results = list(ex.map(_write, [by_n[n] for n in sorted(by_n)]))

    written = {n: txt for n, txt in results}

    # Extract tells in parallel (cheap calls on already-written text)
    with ThreadPoolExecutor(max_workers=len(written)) as ex:
        tells_results = list(ex.map(lambda kv: _extract_tells(*kv), written.items()))
    tells_by_n = dict(tells_results)

    return written, tells_by_n


def _assemble(written: dict[int, str], tells_by_n: dict[int, list[str]],
              index_text: str) -> str:
    import prompts as P
    parts = []
    for spec in P.CAPITULOS:
        n = spec['n']
        if n not in written:
            continue
        block = f"## {n:02d}. {spec['titulo']}\n\n{written[n]}"
        tells = tells_by_n.get(n, [])
        if tells:
            tells_fmt = '\n'.join(f'· {t}' for t in tells)
            block += f"\n\n---\n*Lo que puedes notar en ti:*\n{tells_fmt}"
        parts.append(block)

    doc = '\n\n'.join(parts)
    if index_text:
        doc += f"\n\n---\n## Por dónde volver\n\n{index_text}"
    return doc


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

    # Planner — one call, whole document, produces theses + beats for all 9 chapters
    plan = _plan(dossier)
    log.info('Plan complete: %s', plan.get('tesis_global', '')[:80])

    # Gender for grammatical agreement (neutral fallback if not set)
    genero = getattr(user, 'gender', None) or 'desconocido'

    # Chapters — 9 parallel writing calls + parallel tell extraction
    written, tells_by_n = _write_all_chapters(dossier, plan, genero)
    log.info('Chapters written: %d', len(written))

    # Area index (cheap call, uses plan theses)
    index_text = _build_index(plan)

    # Concatenate with tells after each chapter and index at end
    documento = _assemble(written, tells_by_n, index_text)
    log.info('Document assembled: ~%d words', len(documento.split()))

    return {
        'text':        documento,
        'chart_image': chart_image,
    }
