import io
import os
import time
import base64
import logging

import matplotlib
matplotlib.use('Agg')  # headless backend — must be set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

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


# ── Swiss Ephemeris chart calculation ─────────────────────────────────────────

def _get_sign(degrees):
    signs = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
             'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']
    return signs[int(degrees % 360 / 30)]


def _determine_house(planet_lon, house_cusps):
    planet_lon = planet_lon % 360
    for h in range(1, 13):
        current = house_cusps[h]
        next_h  = house_cusps[h + 1 if h < 12 else 1]
        if next_h < current:  # crosses 0°
            if planet_lon >= current or planet_lon < next_h:
                return h
        else:
            if current <= planet_lon < next_h:
                return h
    return 1


def _build_chart_swisseph(birth_date, birth_time, birth_place):
    import swisseph as swe
    import pytz
    import datetime
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder

    # Geocode
    geolocator = Nominatim(user_agent='astronode_app')
    location = geolocator.geocode(birth_place, timeout=10)
    if not location:
        raise ValueError(f'Could not geocode: {birth_place}')
    lat, lon = location.latitude, location.longitude

    # Timezone
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    if not tz_name:
        raise ValueError(f'Could not find timezone for {birth_place}')
    local_tz = pytz.timezone(tz_name)

    btime = birth_time if birth_time else datetime.time(12, 0)
    local_dt = datetime.datetime(
        birth_date.year, birth_date.month, birth_date.day,
        btime.hour, btime.minute,
    )
    local_dt = local_tz.localize(local_dt)
    utc_dt   = local_dt.astimezone(pytz.UTC)

    jd = swe.julday(
        utc_dt.year, utc_dt.month, utc_dt.day,
        utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0,
    )

    planet_ids = {
        'Sun': swe.SUN, 'Moon': swe.MOON, 'Mercury': swe.MERCURY,
        'Venus': swe.VENUS, 'Mars': swe.MARS, 'Jupiter': swe.JUPITER,
        'Saturn': swe.SATURN, 'Uranus': swe.URANUS,
        'Neptune': swe.NEPTUNE, 'Pluto': swe.PLUTO,
    }

    positions = {}
    for name, pid in planet_ids.items():
        try:
            xx, _ = swe.calc_ut(jd, pid, swe.FLG_SWIEPH)
            lon_deg = xx[0] % 360
            positions[name] = {'longitude': lon_deg, 'sign': _get_sign(lon_deg), 'house': 1}
        except Exception as e:
            log.warning('Could not calculate %s: %s', name, e)

    # Houses (Placidus)
    house_cusps = {}
    try:
        houses_data, ascmc = swe.houses(jd, lat, lon, b'P')
        for i in range(12):
            house_cusps[i + 1] = houses_data[i] % 360
        asc_lon = ascmc[0] % 360
        mc_lon  = ascmc[1] % 360
        positions['Ascendant'] = {'longitude': asc_lon, 'sign': _get_sign(asc_lon), 'house': 1}
        positions['MC']        = {'longitude': mc_lon,  'sign': _get_sign(mc_lon),  'house': 10}
        for name in positions:
            if name not in ('Ascendant', 'MC'):
                positions[name]['house'] = _determine_house(positions[name]['longitude'], house_cusps)
    except Exception as e:
        log.warning('House calculation failed: %s', e)

    return positions, house_cusps, local_dt, lat, lon


def _build_chart_flatlib(birth_date, birth_time, birth_place):
    import pytz
    import datetime
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    from flatlib.chart import Chart
    from flatlib import const, aspects

    geolocator = Nominatim(user_agent='astronode_app')
    location = geolocator.geocode(birth_place, timeout=10)
    if not location:
        raise ValueError(f'Could not geocode: {birth_place}')
    lat, lon = location.latitude, location.longitude

    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    local_tz = pytz.timezone(tz_name)

    btime = birth_time if birth_time else datetime.time(12, 0)
    local_dt = datetime.datetime(birth_date.year, birth_date.month, birth_date.day, btime.hour, btime.minute)
    local_dt = local_tz.localize(local_dt)
    offset_hours = local_dt.utcoffset().total_seconds() / 3600

    chart = Chart(
        local_dt.strftime('%Y/%m/%d'),
        local_dt.strftime('%H:%M'),
        f'{lat},{lon}',
        hsys=const.HOUSE_EQUAL,
        timezone=offset_hours,
    )

    planet_names = [const.SUN, const.MOON, const.MERCURY, const.VENUS,
                    const.MARS, const.JUPITER, const.SATURN, const.URANUS,
                    const.NEPTUNE, const.PLUTO]
    positions = {}
    for name in planet_names:
        obj = chart.get(name)
        positions[name] = {'longitude': float(obj.lon), 'sign': obj.sign, 'house': obj.house}

    for node in (const.N_NODE, const.S_NODE):
        try:
            obj = chart.get(node)
            positions[node] = {'longitude': float(obj.lon), 'sign': obj.sign, 'house': obj.house}
        except Exception:
            pass

    for angle in (const.ASC, const.MC):
        obj = chart.get(angle)
        positions[angle] = {'longitude': float(obj.lon), 'sign': obj.sign, 'house': obj.house}

    house_cusps = {i: float(chart.houses[f'House{i}'].lon) for i in range(1, 13)}

    return positions, house_cusps, local_dt, lat, lon


# ── Chart image generation ─────────────────────────────────────────────────────

PLANET_SYMBOLS = {
    'Sun': '☉', 'Moon': '☽', 'Mercury': '☿', 'Venus': '♀', 'Mars': '♂',
    'Jupiter': '♃', 'Saturn': '♄', 'Uranus': '♅', 'Neptune': '♆', 'Pluto': '♇',
    'Ascendant': 'AC', 'MC': 'MC',
}
PLANET_COLORS = {
    'Sun': '#FFD700', 'Moon': '#C0C0C0', 'Mercury': '#A0522D', 'Venus': '#FF69B4',
    'Mars': '#FF4500', 'Jupiter': '#4169E1', 'Saturn': '#8B8682', 'Uranus': '#00CED1',
    'Neptune': '#0000CD', 'Pluto': '#800080', 'Ascendant': '#FF0000', 'MC': '#006400',
}
SIGN_COLORS = {
    'Aries': '#FF6B6B', 'Taurus': '#4ECDC4', 'Gemini': '#45B7D1', 'Cancer': '#96CEB4',
    'Leo': '#FFEAA7', 'Virgo': '#DDA0DD', 'Libra': '#98D8C8', 'Scorpio': '#F7DC6F',
    'Sagittarius': '#BB8FCE', 'Capricorn': '#85C1E9', 'Aquarius': '#F8C471', 'Pisces': '#82E0AA',
}
ZODIAC_SIGNS = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']


def _generate_chart_image(positions, house_cusps, local_dt, birth_place):
    fig, ax = plt.subplots(figsize=(10, 10), facecolor='#0d0d1a')
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.3, 1.3)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_facecolor('#0d0d1a')

    # Outer zodiac ring
    outer = plt.Circle((0, 0), 1.05, fill=False, color='#9b59b6', linewidth=2)
    inner_z = plt.Circle((0, 0), 0.78, fill=False, color='#9b59b6', linewidth=1.5)
    house_ring = plt.Circle((0, 0), 0.55, fill=False, color='#5d3a7a', linewidth=1)
    center = plt.Circle((0, 0), 0.08, color='#9b59b6', zorder=5)
    ax.add_patch(outer)
    ax.add_patch(inner_z)
    ax.add_patch(house_ring)
    ax.add_patch(center)

    # Zodiac sign segments and labels
    for i, sign in enumerate(ZODIAC_SIGNS):
        start_angle = 90 - i * 30
        wedge = patches.Wedge(
            (0, 0), 1.05, start_angle - 30, start_angle,
            width=0.27, facecolor=SIGN_COLORS[sign], alpha=0.25, edgecolor='#9b59b6', linewidth=0.5,
        )
        ax.add_patch(wedge)
        label_angle = np.radians(start_angle - 15)
        lx = 0.915 * np.cos(label_angle)
        ly = 0.915 * np.sin(label_angle)
        ax.text(lx, ly, sign[:3], ha='center', va='center', fontsize=7,
                color=SIGN_COLORS[sign], fontweight='bold')

    # House lines
    asc_lon = positions.get('Ascendant', {}).get('longitude', 0)
    for h in range(1, 13):
        cusp = house_cusps.get(h, (h - 1) * 30)
        angle = np.radians(90 - (cusp - asc_lon + asc_lon))
        angle = np.radians(90 - cusp)
        x1 = 0.08 * np.cos(angle)
        y1 = 0.08 * np.sin(angle)
        x2 = 0.55 * np.cos(angle)
        y2 = 0.55 * np.sin(angle)
        ax.plot([x1, x2], [y1, y2], color='#5d3a7a', linewidth=0.8, alpha=0.8)
        # House number
        hx = 0.34 * np.cos(np.radians(90 - (cusp + 15) % 360))
        hy = 0.34 * np.sin(np.radians(90 - (cusp + 15) % 360))
        ax.text(hx, hy, str(h), ha='center', va='center', fontsize=7,
                color='#8a7fa0', fontweight='bold')

    # Planets
    for planet, data in positions.items():
        if planet not in PLANET_SYMBOLS:
            continue
        angle = np.radians(90 - data['longitude'])
        radius = 0.67
        px = radius * np.cos(angle)
        py = radius * np.sin(angle)
        symbol = PLANET_SYMBOLS[planet]
        color  = PLANET_COLORS.get(planet, '#e8e0f0')
        ax.text(px, py, symbol, ha='center', va='center', fontsize=14,
                color=color, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.1', facecolor='#0d0d1a', edgecolor='none', alpha=0.7))

    # Title
    date_str = local_dt.strftime('%d %b %Y %H:%M')
    ax.text(0, -1.22, f'✦ Carta Natal — {date_str} — {birth_place}',
            ha='center', va='center', fontsize=9, color='#c39bd3', fontweight='bold')

    plt.tight_layout(pad=0.5)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, facecolor='#0d0d1a', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


# ── Text prompts ───────────────────────────────────────────────────────────────

def _positions_text(positions):
    lines = 'Posiciones Planetarias:\n'
    for name, data in positions.items():
        lines += f"  {name}: {data['longitude']:.2f}° - {data['sign']} - Casa {data['house']}\n"
    return lines


def _house_group_text(start, end, positions, house_cusps):
    text = f'Casas {start} a {end}:\n'
    for h in range(start, end + 1):
        text += f'\nCasa {h} (cúspide {house_cusps.get(h, 0):.1f}°):\n'
        planets = [f"{n} ({d['sign']}, {d['longitude']:.1f}°)"
                   for n, d in positions.items() if d['house'] == h]
        text += ('  Planetas: ' + ', '.join(planets) + '\n') if planets else '  Sin planetas.\n'
    return text


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_horoscope(user, reading_type):
    model       = os.environ.get('AI_MODEL', 'meta-llama/llama-3.3-70b-instruct')
    birth_date  = user.birth_date
    birth_time  = user.birth_time
    birth_place = user.birth_place or 'unknown'

    positions   = None
    house_cusps = {}
    local_dt    = None

    # 1. Try Swiss Ephemeris
    try:
        import swisseph  # noqa
        positions, house_cusps, local_dt, lat, lon = \
            _build_chart_swisseph(birth_date, birth_time, birth_place)
        log.info('Chart built with Swiss Ephemeris')
    except Exception as e:
        log.warning('Swiss Ephemeris failed: %s', e)

    # 2. Fall back to flatlib
    if positions is None:
        try:
            from flatlib import const  # noqa
            positions, house_cusps, local_dt, lat, lon = \
                _build_chart_flatlib(birth_date, birth_time, birth_place)
            log.info('Chart built with flatlib')
        except Exception as e:
            log.warning('flatlib failed: %s', e)

    # 3. Generate chart image
    chart_image = None
    if positions and local_dt:
        try:
            chart_image = _generate_chart_image(positions, house_cusps, local_dt, birth_place)
        except Exception as e:
            log.warning('Chart image generation failed: %s', e)

    # 4. Generate text reading
    if positions:
        pos_text = _positions_text(positions)
        asc      = positions.get('Ascendant', {})
        asc_text = f"Ascendente: {asc.get('longitude', 0):.2f}° - {asc.get('sign', '')}\n"

        cusps_text = 'Cúspides de Casas:\n' + ''.join(
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
            'Proporciona una identificación rápida de la personalidad en ESPAÑOL basada en el Sol, la Luna y el Ascendente. '
            'Analiza signos zodiacales, casas y posiciones. Explica los rasgos de personalidad generales.\n\n'
            + quick_text,
            model,
        ))

        for start, end in [(1, 3), (4, 6), (7, 9), (10, 12)]:
            group_text = _house_group_text(start, end, positions, house_cusps)
            sections.append(_ask(
                f'Analiza las casas {start} a {end} del tema natal casa por casa en ESPAÑOL. '
                'Para cada casa explica la significancia de los planetas presentes (o su ausencia), '
                'las influencias y los desafíos específicos indicados por el tema natal. '
                'Usa las posiciones planetarias y cúspides como contexto.\n\n'
                + pos_text + '\n' + asc_text + '\n' + cusps_text + '\n\n' + group_text,
                model,
            ))

        divider = '\n\n' + '─' * 60 + '\n\n'
        full_text = divider.join(sections)

    else:
        # Full fallback — no chart data, just birth info
        import datetime
        birth_str = birth_date.strftime('%d de %B de %Y') if birth_date else 'desconocida'
        time_str  = birth_time.strftime('%H:%M') if birth_time else 'desconocida'
        full_text = _ask(
            f'Proporciona una lectura de carta natal detallada en ESPAÑOL para alguien nacido el '
            f'{birth_str} a las {time_str} en {birth_place}.\n\n'
            'Incluye: análisis del signo solar, rasgos de personalidad, influencias planetarias, '
            'consejos y áreas de vida en las que enfocarse. 500-700 palabras.',
            model,
        )

    return {'text': full_text, 'chart_image': chart_image, 'usage': {'model': model}}
