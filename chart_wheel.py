"""
chart_wheel.py

Self-contained natal-chart wheel renderer. Produces an SVG visually
equivalent to the kerykeion "Natal" chart with the astronode purple
theme: same ring geometry (240 / 204 / 120), same glyph assets, same
planet-ring collision behaviour, same aspect set.

Astronomy is done upstream with Swiss Ephemeris (see ai.py); this module
only draws. No kerykeion dependency.
"""
from __future__ import annotations

import math

from chart_glyphs import GLYPH_DEFS

# ── Geometry (mirrors the kerykeion template) ─────────────────────────────────
CX = CY = 305.0          # wheel centre in a tight 610x610 canvas
R_OUTER = 240.0          # zodiac ring outer edge
R_ZODIAC_IN = 204.0      # zodiac ring inner edge
R_INNER = 120.0          # aspect-ring edge
R_SIGN_GLYPH = 222.0     # zodiac glyph centre radius
R_HOUSE_NUM = 195.4      # house number radius
R_PLANET_A = 146.0       # planet glyph ring (even index)
R_PLANET_B = 166.0       # planet glyph ring (odd index)
R_DEGREE_LABEL = 261.0   # degree label radius (outside the rim)
R_TICK_IN, R_TICK_OUT = 236.0, 244.0   # per-planet true-position tick
MIN_GAP_SAME_RING = 8.0  # degrees between glyphs on the same ring
MIN_GAP_CROSS = 4.0      # degrees between glyphs on different rings

CANVAS = 610.0

# ── Purple palette (the astronode theme, previously injected as CSS) ─────────
PALETTE = {
    'paper-0': '#0d0d1a',
    'paper-1': '#13101e',
    'zodiac-radix-ring-0': '#b89947',
    'zodiac-radix-ring-1': '#a08535',
    'zodiac-radix-ring-2': '#8a7020',
    'houses-radix-line': '#6b637d',
    'house-number': '#d4af37',
    'sun': '#f8f9fa', 'moon': '#f8f9fa', 'mercury': '#f8f9fa',
    'venus': '#f8f9fa', 'mars': '#f8f9fa', 'jupiter': '#f8f9fa',
    'saturn': '#f8f9fa', 'uranus': '#f8f9fa', 'neptune': '#f8f9fa',
    'pluto': '#f8f9fa', 'mean-node': '#f8f9fa', 'true-node': '#f8f9fa',
    'chiron': '#c8a0e0',
    'mean-lilith': 'transparent', 'true-lilith': 'transparent',
    'first-house': '#d4af37', 'tenth-house': '#d4af37',
    'seventh-house': '#d4af37', 'fourth-house': '#d4af37',
    'conjunction': 'rgba(216, 200, 248, 0.35)',
    'sextile': 'rgba(142, 202, 230, 0.35)',
    'square': 'rgba(232, 144, 122, 0.35)',
    'trine': 'rgba(136, 212, 176, 0.35)',
    'opposition': 'rgba(232, 144, 122, 0.35)',
    'quintile': '#1f99b3',
    'fire-percentage': '#f4a87c', 'earth-percentage': '#a8c090',
    'air-percentage': '#8ecae6', 'water-percentage': '#b8a8e8',
}
_ZODIAC_BG = ['#1a1525', '#221c30'] * 6
_ZODIAC_ICON = '#ddc8f5'

# ── Points, glyphs, aspects ───────────────────────────────────────────────────
# (input key, symbol id, css colour var) — order = drawing order per ring sort.
POINT_GLYPHS = {
    'Sun': 'Sun', 'Moon': 'Moon', 'Mercury': 'Mercury', 'Venus': 'Venus',
    'Mars': 'Mars', 'Jupiter': 'Jupiter', 'Saturn': 'Saturn',
    'Uranus': 'Uranus', 'Neptune': 'Neptune', 'Pluto': 'Pluto',
    'North_Node': 'True_North_Lunar_Node', 'South_Node': 'True_South_Lunar_Node',
    'Chiron': 'Chiron', 'Mean_Lilith': 'Mean_Lilith',
    'Ascendant': 'Ascendant', 'MC': 'Medium_Coeli',
    'Descendant': 'Descendant', 'Imum_Coeli': 'Imum_Coeli',
}
SIGN_GLYPHS = ['Ari', 'Tau', 'Gem', 'Can', 'Leo', 'Vir',
               'Lib', 'Sco', 'Sag', 'Cap', 'Aqu', 'Pis']
_CSS_NAME = {'Sun': 'sun', 'Moon': 'moon', 'Mercury': 'mercury', 'Venus': 'venus',
             'Mars': 'mars', 'Jupiter': 'jupiter', 'Saturn': 'saturn',
             'Uranus': 'uranus', 'Neptune': 'neptune', 'Pluto': 'pluto',
             'North_Node': 'true-node', 'South_Node': 'true-node',
             'Chiron': 'chiron', 'Mean_Lilith': 'mean-lilith',
             'Ascendant': 'first-house', 'MC': 'tenth-house',
             'Descendant': 'seventh-house', 'Imum_Coeli': 'fourth-house'}
# Cusp colour quirks preserved from the kerykeion template (var names swapped);
# with the purple palette the net effect is: cusp 1 light purple, 4/7/10 gold.
_CUSP_COLOUR = {1: 'chiron', 4: 'seventh-house', 7: 'tenth-house',
                10: 'first-house'}

ASPECTS = [  # kerykeion default active aspects + orbs
    ('conjunction', 0, 10), ('opposition', 180, 10), ('trine', 120, 8),
    ('sextile', 60, 6), ('square', 90, 5), ('quintile', 72, 1),
]


_AXIS_PAIRS = {frozenset(p) for p in (
    ('Ascendant', 'Descendant'), ('MC', 'Imum_Coeli'),
    ('North_Node', 'South_Node'))}


def _wheel_aspects(positions: dict) -> list[dict]:
    """Aspects among the chart points, kerykeion defaults (orb in degrees).

    Axis self-pairs (ASC/DSC, MC/IC, NN/SN) are skipped, as kerykeion does.
    """
    pts = [(k, positions[k]['longitude'] % 360.0) for k in POINT_GLYPHS
           if k in positions]
    out = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            n1, l1 = pts[i]
            n2, l2 = pts[j]
            if frozenset((n1, n2)) in _AXIS_PAIRS:
                continue
            diff = abs(l1 - l2) % 360.0
            if diff > 180:
                diff = 360.0 - diff
            for name, angle, orb in ASPECTS:
                delta = abs(diff - angle)
                if delta <= orb:
                    out.append({'p1': n1, 'p2': n2, 'name': name,
                                'orb': round(delta, 2)})
                    break
    return out


def _svg_point(angle_deg: float, radius: float,
               cx: float = CX, cy: float = CY) -> tuple[float, float]:
    """SVG coordinates for a math-convention polar point (y up)."""
    a = math.radians(angle_deg)
    return cx + radius * math.cos(a), cy - radius * math.sin(a)


def _place_planets(points: list[tuple[str, float]],
                   dsc_abs: float) -> list[dict]:
    """Glyph placement — kerykeion's exact algorithm.

    Points arrive sorted by absolute longitude. Points closer than 3.4 deg
    are grouped and spread with kerykeion's formulas (draw_planets.py:
    _handle_two_point_group / _handle_multi_point_group), then the glyph
    angle is int(abs + adj) - int(DSC) — which also performs the ASC-to-
    9-o'clock rotation. Rings alternate 146/166 by sorted index.
    """
    n = len(points)
    TH = 3.4
    abss = [lon for _, lon in points]

    dprev = [360.0] * n
    dnext = [360.0] * n
    for i in range(n):
        if n > 1:
            dprev[i] = (abss[i] - abss[i - 1]) % 360.0
            dnext[i] = (abss[(i + 1) % n] - abss[i]) % 360.0

    # Group chain: point joins a group when its distance-to-next < TH; a
    # point with distance-to-next >= TH closes an open group.
    groups: list[list[int]] = []
    open_g = False
    for i in range(n):
        if dnext[i] < TH:
            if open_g:
                groups[-1].append(i)
            else:
                groups.append([i])
                open_g = True
        else:
            if open_g:
                groups[-1].append(i)
            open_g = False

    adj = [0.0] * n
    for g in groups:
        if len(g) == 2:
            a, b = g
            next_to_a = a - 1
            next_to_b = 0 if b == n - 1 else b + 1
            if (dprev[a] > 2 * TH) and (dnext[b] > 2 * TH):
                shift = (TH - dnext[a]) / 2.0
                adj[a] = -shift
                adj[b] = +shift
            elif dprev[a] > 2 * TH:
                adj[a] = -TH
            elif dnext[b] > 2 * TH:
                adj[b] = +TH
            elif (dprev[next_to_a] > 2.4 * TH) and (dnext[next_to_b] > 2.4 * TH):
                adj[next_to_a] = dprev[a] - TH * 2
                adj[a] = -TH * 0.5
                adj[next_to_b] = -(dnext[b] - TH * 2)
                adj[b] = +TH * 0.5
            elif dprev[next_to_a] > 2 * TH:
                adj[next_to_a] = dprev[a] - TH * 2.5
                adj[a] = -TH * 1.2
            elif dnext[next_to_b] > 2 * TH:
                adj[next_to_b] = -(dnext[b] - TH * 2.5)
                adj[b] = +TH * 1.2
        elif len(g) >= 3:
            available = dprev[g[0]] + sum(dnext[i] for i in g)
            needed = (3 * TH) + (1.2 * (len(g) - 1) * TH)
            space_before, space_after = dprev[g[0]], dnext[g[-1]]
            leftover = available - needed
            if (space_before > needed * 0.5) and (space_after > needed * 0.5):
                start = space_before - needed * 0.5
            else:
                start = (leftover / (space_before + space_after)) * space_before
            if available > needed:
                adj[g[0]] = start - space_before + 1.5 * TH
                for k in range(len(g) - 1):
                    adj[g[k + 1]] = (1.2 * TH + adj[g[k]]
                                     - dnext[g[k]])

    placed = []
    for idx, (key, lon) in enumerate(points):
        angle = (int(lon + adj[idx]) - int(dsc_abs)) % 360
        placed.append({'key': key, 'lon': lon,
                       'radius': R_PLANET_A if idx % 2 == 0 else R_PLANET_B,
                       'angle': angle})
    return placed


def render_chart_svg(positions: dict, house_cusps: dict,
                     title: str = 'Natal Chart') -> str:
    """Render the natal wheel. positions/house_cusps use the ai.py contract."""
    asc_abs = positions['Ascendant']['longitude'] % 360.0
    rot = 180.0 - asc_abs           # screen angle = abs + rot (ASC -> 9 o'clock)

    def ang(abs_lon: float) -> float:
        return (abs_lon + rot) % 360.0

    parts: list[str] = []
    parts.append(
        f"<svg xmlns='http://www.w3.org/2000/svg' "
        f"xmlns:xlink='http://www.w3.org/1999/xlink' "
        f"xmlns:kr='https://www.kerykeion.net/' width='100%' height='100%' "
        f"viewBox='0 0 {CANVAS:g} {CANVAS:g}' "
        f"preserveAspectRatio='xMidYMid' "
        f"style='background-color: var(--kerykeion-chart-color-paper-1)'>"
    )
    parts.append(f'<title>{title}</title>')

    # Palette + glyph assets
    style_rules = '\n'.join(
        f'  --kerykeion-chart-color-{k}: {v};' for k, v in PALETTE.items())
    for i in range(12):
        style_rules += f'\n  --kerykeion-chart-color-zodiac-bg-{i}: {_ZODIAC_BG[i]};'
        style_rules += (f'\n  --kerykeion-chart-color-zodiac-icon-{i}: '
                        f'{_ZODIAC_ICON};')
    parts.append('<style>\n:root, svg {\n' + style_rules + '\n}\n</style>')
    parts.append(GLYPH_DEFS)

    parts.append("<g kr:node='Full_Wheel'>")

    # ── Background ──
    parts.append(
        f"<circle cx='{CX:g}' cy='{CY:g}' r='{R_OUTER:g}' style='fill: "
        f"var(--kerykeion-chart-color-paper-1); stroke: "
        f"var(--kerykeion-chart-color-paper-1); stroke-width: 1px;' />")

    # ── Zodiac ring ──
    parts.append("<g kr:node='Zodiac'>")
    for k in range(12):
        a0, a1 = ang(k * 30.0), ang((k + 1) * 30.0)
        x0, y0 = _svg_point(a0, R_OUTER)
        x1, y1 = _svg_point(a1, R_OUTER)
        parts.append(
            f"<path d='M{CX:g},{CY:g} L{x0:.2f},{y0:.2f} A{R_OUTER:g},{R_OUTER:g} "
            f"0 0,0 {x1:.2f},{y1:.2f} z' style='fill:var(--kerykeion-chart-color-"
            f"zodiac-bg-{k}); fill-opacity: 0.5;'/>")
    # 5-degree ticks on the outer rim
    for d in range(0, 360, 5):
        a = ang(float(d))
        xt0, yt0 = _svg_point(a, R_OUTER)
        xt1, yt1 = _svg_point(a, R_OUTER + 2)
        parts.append(
            f"<line x1='{xt0:.2f}' y1='{yt0:.2f}' x2='{xt1:.2f}' y2='{yt1:.2f}' "
            f"style='stroke: var(--kerykeion-chart-color-paper-0); "
            f"stroke-width: 1px; stroke-opacity:.9;'/>")
    # Sign glyphs
    for k in range(12):
        gx, gy = _svg_point(ang(k * 30.0 + 15.0), R_SIGN_GLYPH)
        parts.append(
            f"<use x='{gx:.2f}' y='{gy:.2f}' xlink:href='#{SIGN_GLYPHS[k]}' />")
    parts.append('</g>')

    # ── Inner rings ──
    parts.append(
        f"<circle cx='{CX:g}' cy='{CY:g}' r='{R_ZODIAC_IN:g}' style='fill: "
        f"var(--kerykeion-chart-color-paper-1); fill-opacity:.2; stroke: "
        f"var(--kerykeion-chart-color-zodiac-radix-ring-1); stroke-width: 1px;' />")
    parts.append(
        f"<circle cx='{CX:g}' cy='{CY:g}' r='{R_INNER:g}' style='fill: "
        f"var(--kerykeion-chart-color-paper-1); fill-opacity:.8; stroke: "
        f"var(--kerykeion-chart-color-zodiac-radix-ring-2); stroke-width: 1px;' />")

    # ── House cusps + numbers ──
    for h in range(1, 13):
        cusp = house_cusps[h] % 360.0
        a = ang(cusp)
        xin, yin = _svg_point(a, R_INNER)
        xout, yout = _svg_point(a, R_OUTER)
        colour = _CUSP_COLOUR.get(h, 'houses-radix-line')
        parts.append(
            f"<g kr:node='Cusp'><line x1='{xin:.2f}' y1='{yin:.2f}' "
            f"x2='{xout:.2f}' y2='{yout:.2f}' style='stroke: "
            f"var(--kerykeion-chart-color-{colour}); stroke-width: 1px; "
            f"stroke-opacity:.4;'/></g>")
        if h < 12:
            mid = ang(cusp + ((house_cusps[(h % 12) + 1] - cusp) % 360.0) / 2.0)
        else:
            mid = ang(cusp + ((house_cusps[1] + 360.0 - cusp) % 360.0) / 2.0)
        nx, ny = _svg_point(mid, R_HOUSE_NUM)
        parts.append(
            f"<g kr:node='HouseNumber'><text x='{nx:.2f}' y='{ny + 5:.2f}' "
            f"style='fill: var(--kerykeion-chart-color-house-number); "
            f"fill-opacity: .6; font-size: 14px'>{h}</text></g>")

    # ── Aspect lines (true positions, inner ring edge) ──
    parts.append("<g kr:node='Aspects_Wheel'>")
    for asp in _wheel_aspects(positions):
        a1 = ang(positions[asp['p1']]['longitude'] % 360.0)
        a2 = ang(positions[asp['p2']]['longitude'] % 360.0)
        x1, y1 = _svg_point(a1, R_INNER)
        x2, y2 = _svg_point(a2, R_INNER)
        css = asp['name'].replace(' ', '-')
        parts.append(
            f"<g kr:node='Aspect' kr:aspectname='{asp['name']}' "
            f"kr:from='{asp['p1']}' kr:to='{asp['p2']}' kr:orb='{asp['orb']}'>"
            f"<line class='aspect' x1='{x1:.2f}' y1='{y1:.2f}' "
            f"x2='{x2:.2f}' y2='{y2:.2f}' style='stroke: "
            f"var(--kerykeion-chart-color-{css}); stroke-width: 1; "
            f"stroke-opacity: .9;'/></g>")
    parts.append('</g>')

    # ── Chart points ──
    pts_sorted = sorted(
        ((k, positions[k]['longitude'] % 360.0) for k in POINT_GLYPHS
         if k in positions), key=lambda t: t[1])
    dsc_abs = positions['Descendant']['longitude'] % 360.0
    placed = _place_planets(pts_sorted, dsc_abs)
    lon_by_key = dict(pts_sorted)

    parts.append("<g kr:node='Planets_Wheel'>")
    for p in placed:
        key = p['key']
        lon = lon_by_key[key]
        glyph = POINT_GLYPHS[key]
        css = _CSS_NAME[key]
        true_a = ang(lon)
        gx, gy = _svg_point(p['angle'], p['radius'])

        # glyph (parent -12,-12 centres the 24x24 symbol on the point)
        parts.append(
            f"<g kr:node='ChartPoint' kr:slug='{key}' kr:absoluteposition="
            f"'{lon:.6f}' transform='translate(-12.0,-12.0) scale(1.0)'>"
            f"<use x='{gx:.2f}' y='{gy:.2f}' xlink:href='#{glyph}' />")
        if positions[key].get('retrograde'):
            parts.append(
                f"<g transform='translate({gx + 22:.2f},{gy + 18:.2f}) "
                f"scale(0.55)'><use xlink:href='#retrograde' /></g>")
        parts.append('</g>')

        # true-position tick on the rim
        tx0, ty0 = _svg_point(true_a, R_TICK_IN)
        tx1, ty1 = _svg_point(true_a, R_TICK_OUT)
        parts.append(
            f"<line class='planet-degree-line' x1='{tx0:.2f}' y1='{ty0:.2f}' "
            f"x2='{tx1:.2f}' y2='{ty1:.2f}' style='stroke: "
            f"var(--kerykeion-chart-color-{css}); stroke-width: .8; "
            f"stroke-opacity:.8;'/>")

        # degree label outside the rim (true angle, ~2 deg clockwise side)
        lx, ly = _svg_point(true_a - 2.0, R_DEGREE_LABEL)
        sign_pos = int(lon % 30)
        parts.append(
            f"<g transform='translate({lx:.2f},{ly:.2f})'>"
            f"<text text-anchor='middle' dominant-baseline='middle' "
            f"style='fill: var(--kerykeion-chart-color-{css}); "
            f"font-size: 10px;'>{sign_pos}&#176;</text></g>")
    parts.append('</g>')   # Planets_Wheel
    parts.append('</g>')   # Full_Wheel
    parts.append('</svg>')
    return '\n'.join(parts)
