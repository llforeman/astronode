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


def _build_chart(birth_date, birth_time, birth_place):
    """Geocode the birth place, get timezone, and build flatlib chart."""
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    import pytz
    import datetime
    from flatlib.chart import Chart
    from flatlib import const, aspects

    # Geocode
    geolocator = Nominatim(user_agent='astronode_app')
    location = geolocator.geocode(birth_place)
    if not location:
        raise ValueError(f'Could not geocode location: {birth_place}')
    lat, lon = location.latitude, location.longitude

    # Timezone
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    if not tz_name:
        raise ValueError(f'Could not determine timezone for {birth_place}')
    local_tz = pytz.timezone(tz_name)

    # Build local datetime
    btime = birth_time if birth_time else datetime.time(12, 0)
    local_dt = datetime.datetime(
        birth_date.year, birth_date.month, birth_date.day,
        btime.hour, btime.minute,
    )
    local_dt = local_tz.localize(local_dt)
    offset_hours = local_dt.utcoffset().total_seconds() / 3600

    date_str     = local_dt.strftime('%Y/%m/%d')
    time_str     = local_dt.strftime('%H:%M')
    location_str = f'{lat},{lon}'

    chart = Chart(date_str, time_str, location_str,
                  hsys=const.HOUSE_EQUAL, timezone=offset_hours)

    # Planets + nodes + angles
    planet_names = [
        const.SUN, const.MOON, const.MERCURY, const.VENUS,
        const.MARS, const.JUPITER, const.SATURN, const.URANUS,
        const.NEPTUNE, const.PLUTO,
    ]
    positions = {}
    for name in planet_names:
        obj = chart.get(name)
        positions[name] = {'lon': float(obj.lon), 'sign': obj.sign, 'house': obj.house}

    for node in (const.N_NODE, const.S_NODE):
        try:
            obj = chart.get(node)
            positions[node] = {'lon': float(obj.lon), 'sign': obj.sign, 'house': obj.house}
        except Exception:
            pass

    for angle in (const.ASC, const.MC):
        obj = chart.get(angle)
        positions[angle] = {'lon': float(obj.lon), 'sign': obj.sign, 'house': obj.house}

    # House cusps
    house_cusps = {i: float(chart.houses[f'House{i}'].lon) for i in range(1, 13)}

    # Aspects
    all_aspects = aspects.getAspects(chart)

    return chart, positions, house_cusps, all_aspects, lat, lon, local_dt


def _format_chart_context(positions, house_cusps):
    planet_text = 'Overall Planetary Positions and Points:\n'
    for key, data in positions.items():
        planet_text += f"  {key}: {data['lon']:.2f}° - {data['sign']} - House {data['house']}\n"

    cusps_text = 'Equal House Cusps:\n'
    for i in range(1, 13):
        cusps_text += f'  House {i}: {house_cusps[i]:.2f}°\n'

    asc = positions.get('Asc', {})
    asc_text = f"Ascendant: {asc.get('lon', 0):.2f}° - {asc.get('sign', '')}\n"

    return planet_text, cusps_text, asc_text


def _format_house_group(start, end, positions, all_aspects, chart):
    from flatlib import const
    text = f'Houses {start} to {end} Breakdown:\n'
    for h in range(start, end + 1):
        text += f'\nHouse {h}:\n'
        planets_in = [
            f"{k} ({v['sign']}, {v['lon']:.2f}°)"
            for k, v in positions.items() if v['house'] == h
        ]
        text += ('  Planets: ' + ', '.join(planets_in) + '\n') if planets_in else '  No planets.\n'

        intra, inter = [], []
        for asp in all_aspects:
            h1 = chart.get(asp.obj1).house
            h2 = chart.get(asp.obj2).house
            asp_str = (
                f"{asp.obj1} ({chart.get(asp.obj1).sign}, H{h1}) "
                f"{asp.aspect} "
                f"{asp.obj2} ({chart.get(asp.obj2).sign}, H{h2}), orb {asp.orb:+.2f}°"
            )
            if h1 == h and h2 == h:
                intra.append(asp_str)
            elif h1 == h or h2 == h:
                inter.append(asp_str)

        if intra:
            text += '  Intra-house aspects:\n' + ''.join(f'    - {a}\n' for a in intra)
        if inter:
            text += '  Inter-house aspects:\n' + ''.join(f'    - {a}\n' for a in inter)
    return text


def generate_horoscope(user, reading_type):
    model = os.environ.get('AI_MODEL', 'meta-llama/llama-3.3-70b-instruct')

    try:
        from flatlib import const as _
        flatlib_ok = True
    except ImportError:
        flatlib_ok = False

    birth_date  = user.birth_date
    birth_time  = user.birth_time
    birth_place = user.birth_place or 'unknown'

    # ── Full chart path ───────────────────────────────────────────────────────
    if flatlib_ok:
        try:
            chart, positions, house_cusps, all_aspects, lat, lon, local_dt = \
                _build_chart(birth_date, birth_time, birth_place)

            planet_text, cusps_text, asc_text = _format_chart_context(positions, house_cusps)

            from flatlib import const
            quick_text = (
                'Key Points:\n'
                f"  Sun: {positions[const.SUN]['lon']:.2f}° - {positions[const.SUN]['sign']} - House {positions[const.SUN]['house']}\n"
                f"  Moon: {positions[const.MOON]['lon']:.2f}° - {positions[const.MOON]['sign']} - House {positions[const.MOON]['house']}\n"
                f"  Ascendant: {positions[const.ASC]['lon']:.2f}° - {positions[const.ASC]['sign']}\n"
            )

            sections = []

            # 1. Quick personality
            sections.append(_ask(
                'Proporciona una identificación rápida de la personalidad basada en el Sol, la Luna y el Ascendente. '
                'Analiza sus signos zodiacales, casas y posiciones. RESPONDE EN ESPAÑOL.\n\n'
                + quick_text,
                model,
            ))

            # 2-5. Houses in groups
            for start, end in [(1, 3), (4, 6), (7, 9), (10, 12)]:
                group_text = _format_house_group(start, end, positions, all_aspects, chart)
                sections.append(_ask(
                    f'Analiza las casas {start} a {end} del siguiente tema natal casa por casa. '
                    'Para cada casa explica la significancia de los planetas, aspectos intra-casa e inter-casa. '
                    'Menciona desafíos específicos. RESPONDE EN ESPAÑOL.\n\n'
                    + planet_text + '\n' + asc_text + '\n' + cusps_text + '\n\n'
                    + group_text,
                    model,
                ))

            full_text = '\n\n' + ('=' * 60) + '\n\n'
            full_text = full_text.join(sections)

            return {'text': full_text, 'usage': {'model': model}}

        except Exception as e:
            log.error('Full chart generation failed, falling back: %s', e)

    # ── Fallback: simple prompt ───────────────────────────────────────────────
    birth_str  = birth_date.strftime('%d de %B de %Y') if birth_date else 'desconocida'
    time_str   = birth_time.strftime('%H:%M') if birth_time else 'desconocida'

    prompt = (
        f'Proporciona una lectura de carta natal detallada y personalizada en ESPAÑOL para alguien nacido el '
        f'{birth_str} a las {time_str} en {birth_place}.\n\n'
        f'Tipo de lectura: {reading_type.name if reading_type else "Carta Natal General"}\n\n'
        'Incluye: análisis del signo solar, rasgos de personalidad, influencias planetarias actuales, '
        'consejos para el período próximo y áreas de vida en las que enfocarse. '
        'Escribe en un tono personal y evocador. Extensión: 500-700 palabras.'
    )
    text = _ask(prompt, model)
    return {'text': text, 'usage': {'model': model}}
