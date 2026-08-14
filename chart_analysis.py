"""
chart_analysis.py

Extraction layer: turns pre-computed Kerykeion data into a weighted, prioritised
dossier that tells the LLM what is DISTINCTIVE about this chart.

Accepts the output of ai._build_chart_kerykeion() directly — no geocoding,
no Kerykeion factory classes. No LLM calls. Pure deterministic astrology.
"""

from __future__ import annotations
from typing import Any, Optional

# --------------------------------------------------------------------------
# Reference tables
# --------------------------------------------------------------------------

SIGNS = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir",
         "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]

# Kerykeion may return full sign names; normalise to 3-letter.
_FULL_TO_SHORT = {
    "Aries": "Ari", "Taurus": "Tau", "Gemini": "Gem", "Cancer": "Can",
    "Leo": "Leo", "Virgo": "Vir", "Libra": "Lib", "Scorpio": "Sco",
    "Sagittarius": "Sag", "Capricorn": "Cap", "Capricornus": "Cap",
    "Aquarius": "Aqu", "Pisces": "Pis",
}

SIGN_ES = {
    "Ari": "Aries", "Tau": "Tauro", "Gem": "Géminis", "Can": "Cáncer",
    "Leo": "Leo", "Vir": "Virgo", "Lib": "Libra", "Sco": "Escorpio",
    "Sag": "Sagitario", "Cap": "Capricornio", "Aqu": "Acuario", "Pis": "Piscis",
}

PLANET_ES = {
    "Sun": "el Sol", "Moon": "la Luna", "Mercury": "Mercurio",
    "Venus": "Venus", "Mars": "Marte", "Jupiter": "Júpiter",
    "Saturn": "Saturno", "Uranus": "Urano", "Neptune": "Neptuno",
    "Pluto": "Plutón", "Ascendant": "el Ascendente",
    "Medium_Coeli": "el Medio Cielo", "MC": "el Medio Cielo",
    "Descendant": "el Descendente", "Imum_Coeli": "el Fondo del Cielo",
    "North_Node": "el Nodo Norte", "South_Node": "el Nodo Sur",
    "Chiron": "Quirón",
}

ASPECT_ES = {
    "conjunction": "conjunción", "opposition": "oposición",
    "square": "cuadratura", "trine": "trígono", "sextile": "sextil",
}

RULER = {
    "Ari": "Mars", "Tau": "Venus", "Gem": "Mercury", "Can": "Moon",
    "Leo": "Sun", "Vir": "Mercury", "Lib": "Venus", "Sco": "Pluto",
    "Sag": "Jupiter", "Cap": "Saturn", "Aqu": "Uranus", "Pis": "Neptune",
}
TRAD_RULER = dict(RULER, **{"Sco": "Mars", "Aqu": "Saturn", "Pis": "Jupiter"})

EXALTATION = {
    "Sun": "Ari", "Moon": "Tau", "Mercury": "Vir", "Venus": "Pis",
    "Mars": "Cap", "Jupiter": "Can", "Saturn": "Lib",
}

ELEMENT_OF = {s: e for s, e in zip(SIGNS, ["Fire", "Earth", "Air", "Water"] * 3)}
MODE_OF    = {s: m for s, m in zip(SIGNS, ["Cardinal", "Fixed", "Mutable"] * 4)}

PERSONAL   = ["Sun", "Moon", "Mercury", "Venus", "Mars"]
SOCIAL     = ["Jupiter", "Saturn"]
OUTER      = ["Uranus", "Neptune", "Pluto"]
ASTEROIDS  = ["Chiron"]
ANGLES     = ["Ascendant", "Medium_Coeli", "Descendant", "Imum_Coeli"]
NODES      = ["North_Node", "South_Node"]
CORE       = PERSONAL + SOCIAL + OUTER

HARD = {"conjunction", "opposition", "square"}
SOFT = {"trine", "sextile"}

OWNER_RANK = {
    "Moon": 1, "Mercury": 2, "Venus": 3, "Sun": 4, "Mars": 5,
    "Ascendant": 6, "Medium_Coeli": 6, "Descendant": 6, "Imum_Coeli": 6,
    "Saturn": 7, "Jupiter": 8,
    "Uranus": 9, "Neptune": 9, "Pluto": 9,
}

# (name, angle, max_orb)
ACTIVE_ASPECTS = [
    ("conjunction",  0,   8),
    ("opposition",   180, 7),
    ("square",       90,  6),
    ("trine",        120, 6),
    ("sextile",      60,  3),
]

ANGULAR_ORB = 5.0   # planet "conjunct" an angle
TIER1_ORB   = 2.0
TIER2_ORB   = 4.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _norm(sign: str) -> str:
    """Return 3-letter sign abbreviation regardless of input format."""
    if len(sign) <= 3:
        return sign
    return _FULL_TO_SHORT.get(sign, sign[:3])


def _sep(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _deg_str(lon: float, sign: str) -> str:
    d_in = lon % 30
    d = int(d_in)
    m = int(round((d_in - d) * 60))
    if m == 60:
        d, m = d + 1, 0
    return f"{d}°{m:02d}′ {SIGN_ES.get(sign, sign)}"


def _dignity(planet: str, sign: str) -> Optional[str]:
    if RULER.get(sign) == planet or TRAD_RULER.get(sign) == planet:
        return "domicilio"
    if EXALTATION.get(planet) == sign:
        return "exaltación"
    if sign in SIGNS:
        opp = SIGNS[(SIGNS.index(sign) + 6) % 12]
        if RULER.get(opp) == planet or TRAD_RULER.get(opp) == planet:
            return "exilio"
        if EXALTATION.get(planet) == opp:
            return "caída"
    return None


def _moon_phase_name(deg: float) -> str:
    names = ["Luna Nueva", "Luna Creciente", "Cuarto Creciente",
             "Luna Gibosa Creciente", "Luna Llena",
             "Luna Gibosa Menguante", "Cuarto Menguante", "Luna Menguante"]
    return names[int(deg // 45)]


# --------------------------------------------------------------------------
# Aspects
# --------------------------------------------------------------------------

def _compute_graded_aspects(pos: dict) -> list[dict]:
    """Compute aspects between all planet+angle pairs, graded by orb."""
    bodies = CORE + ASTEROIDS + ["Ascendant", "Medium_Coeli", "North_Node", "South_Node"]
    available = [(n, pos[n]["longitude"]) for n in bodies if n in pos]

    graded = []
    for i, (n1, lon1) in enumerate(available):
        for j, (n2, lon2) in enumerate(available):
            if j <= i:
                continue
            if n1 in ANGLES and n2 in ANGLES:
                continue
            # Nodes are always exactly opposite — skip their mutual aspect
            if {n1, n2} == {"North_Node", "South_Node"}:
                continue

            diff = abs(lon1 - lon2) % 360
            if diff > 180:
                diff = 360 - diff

            for asp_name, asp_angle, orb_limit in ACTIVE_ASPECTS:
                is_angular = n1 in ANGLES or n2 in ANGLES
                eff_orb = ANGULAR_ORB if (is_angular and asp_name == "conjunction") else orb_limit
                raw_orb = abs(diff - asp_angle)
                if raw_orb > eff_orb:
                    continue

                if raw_orb <= TIER1_ORB:
                    tier, peso = 1, "definitorio"
                elif raw_orb <= TIER2_ORB:
                    tier, peso = 2, "fuerte"
                else:
                    tier, peso = 3, "presente"

                if asp_name in SOFT:
                    tier = min(tier + 1, 4)

                r1 = OWNER_RANK.get(n1, 99)
                r2 = OWNER_RANK.get(n2, 99)
                owner = n1 if r1 <= r2 else n2
                other = n2 if r1 <= r2 else n1

                graded.append({
                    "a": n1, "b": n2,
                    "a_es": PLANET_ES.get(n1, n1),
                    "b_es": PLANET_ES.get(n2, n2),
                    "aspecto": ASPECT_ES.get(asp_name, asp_name),
                    "tipo": "tenso" if asp_name in HARD else "fluido",
                    "orbe": round(raw_orb, 2),
                    "tier": tier,
                    "peso": peso,
                    "movimiento": "separativo",   # simplified; applying needs ephemeris velocity
                    "casa_a": pos.get(n1, {}).get("house"),
                    "casa_b": pos.get(n2, {}).get("house"),
                    "condicionado_por": other,
                })
                break   # one aspect per pair

    graded.sort(key=lambda x: (x["tier"], x["orbe"]))
    return graded


# --------------------------------------------------------------------------
# Configurations
# --------------------------------------------------------------------------

def _find_configurations(pos: dict, graded: list[dict]) -> list[dict]:
    tight = [g for g in graded if g["tier"] <= 3]

    def has(p, q, kind):
        for g in tight:
            if {g["a"], g["b"]} == {p, q} and g["aspecto"] == kind:
                return True
        return False

    pts = [n for n in CORE + ["Ascendant", "Medium_Coeli"] if n in pos]
    configs, seen = [], set()

    # T-squares
    for i, a in enumerate(pts):
        for j, b in enumerate(pts):
            if j <= i:
                continue
            if not has(a, b, "oposición"):
                continue
            for c in pts:
                if c in (a, b):
                    continue
                if has(a, c, "cuadratura") and has(b, c, "cuadratura"):
                    key = ("T", tuple(sorted([a, b, c])))
                    if key not in seen:
                        seen.add(key)
                        configs.append({
                            "tipo": "Cruz en T",
                            "apex": c,
                            "apex_es": PLANET_ES.get(c, c),
                            "apex_casa": pos.get(c, {}).get("house"),
                            "extremos": [PLANET_ES.get(a, a), PLANET_ES.get(b, b)],
                            "nota": "El apex es el punto de descarga: el problema central.",
                        })

    # Grand trines
    for i, a in enumerate(pts):
        for j, b in enumerate(pts):
            if j <= i:
                continue
            if not has(a, b, "trígono"):
                continue
            for k, c in enumerate(pts):
                if k <= j:
                    continue
                if has(a, c, "trígono") and has(b, c, "trígono"):
                    key = ("GT", tuple(sorted([a, b, c])))
                    if key not in seen:
                        seen.add(key)
                        s = pos.get(a, {}).get("sign", "")
                        configs.append({
                            "tipo": "Gran trígono",
                            "planetas": [PLANET_ES.get(x, x) for x in (a, b, c)],
                            "elemento": ELEMENT_OF.get(s),
                            "nota": "Facilidad que la persona da por sentada.",
                        })

    return configs


# --------------------------------------------------------------------------
# Prominence scoring
# --------------------------------------------------------------------------

def _prominence(pos: dict, graded: list, angular: list,
                ruler: str, counts: dict) -> list[dict]:
    scores = {}
    for name in CORE:
        if name not in pos:
            continue
        s = 0.0
        h = pos[name].get("house")
        if h in (1, 4, 7, 10):
            s += 3
        if name == ruler:
            s += 4
        dig = _dignity(name, pos[name].get("sign", ""))
        if dig in ("domicilio", "exaltación"):
            s += 2
        elif dig in ("exilio", "caída"):
            s += 1
        if pos[name].get("retrograde"):
            s += 1
        s += min(counts.get(name, 0), 6) * 0.5
        for g in graded:
            if name in (g["a"], g["b"]) and g["tier"] == 1:
                s += 2
        for a in angular:
            if a["planeta"] == name:
                s += 5 - a["orbe"] * 0.4
        scores[name] = round(s, 2)

    return [{"planeta": n, "planeta_es": PLANET_ES.get(n, n), "puntaje": v}
            for n, v in sorted(scores.items(), key=lambda kv: -kv[1])]


# --------------------------------------------------------------------------
# Headline signals
# --------------------------------------------------------------------------

def _headline_signals(out: dict) -> list[str]:
    sig = []
    if out.get("aspecto_mas_estrecho"):
        g = out["aspecto_mas_estrecho"]
        sig.append(f"Aspecto más estrecho: {g['a_es']} {g['aspecto']} "
                   f"{g['b_es']}, orbe {g['orbe']}°. Eje del documento.")
    for a in out.get("planetas_angulares", [])[:3]:
        sig.append(f"{a['planeta_es']} sobre {a['angulo_es']} (orbe {a['orbe']}°).")
    for c in out.get("configuraciones", []):
        if c["tipo"] == "Cruz en T":
            sig.append(f"Cruz en T, apex {c['apex_es']} casa {c['apex_casa']}.")
    for p in out.get("planetas_sin_aspectos", []):
        sig.append(f"{p['planeta_es']}: sin aspectos, función aislada.")
    if out.get("elementos_ausentes"):
        sig.append("Elemento ausente: " + ", ".join(out["elementos_ausentes"]) + ".")
    r = out.get("regente_carta", {})
    if r:
        sig.append(f"Regente: {r['planeta_es']} en {r['signo']}, casa {r['casa']}.")
    st = out.get("stelliums", {})
    for k, v in {**st.get("por_casa", {}), **st.get("por_signo", {})}.items():
        sig.append(f"Concentración en {k}: {', '.join(v)}.")
    return sig


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def build_dossier(subject, positions: dict, house_cusps: dict,
                  known_birth_time: bool = True) -> dict:
    """
    Build the interpretation dossier.

    subject     — Kerykeion AstrologicalSubject (for lunar_phase, is_diurnal)
    positions   — dict from ai._build_chart_kerykeion():
                  {name: {longitude, sign, house, retrograde}}
                  Must include Sun, Moon, planets, Ascendant, MC (or Medium_Coeli),
                  Descendant, Imum_Coeli.
    house_cusps — {1: float, …, 12: float}
    """
    # Normalise sign abbreviations throughout
    pos: dict[str, Any] = {}
    for name, data in positions.items():
        pos[name] = dict(data)
        pos[name]["sign"] = _norm(data.get("sign", ""))

    # Alias MC <-> Medium_Coeli so chapter routing works either way
    if "MC" in pos and "Medium_Coeli" not in pos:
        pos["Medium_Coeli"] = pos["MC"]
    if "Medium_Coeli" in pos and "MC" not in pos:
        pos["MC"] = pos["Medium_Coeli"]

    out: dict[str, Any] = {}

    # ---- meta ---------------------------------------------------------------
    meta: dict[str, Any] = {"hora_conocida": known_birth_time}
    try:
        meta["diurno"] = bool(subject.is_diurnal)
    except Exception:
        sun_h = pos.get("Sun", {}).get("house", 1) or 1
        meta["diurno"] = sun_h >= 7
    try:
        meta["sistema_casas"] = subject.houses_system_name
    except Exception:
        meta["sistema_casas"] = "Placidus"
    out["meta"] = meta

    # ---- placements ---------------------------------------------------------
    placements: dict[str, Any] = {}
    for name in CORE + ASTEROIDS + ANGLES + NODES:
        data = pos.get(name)
        if not data:
            continue
        sign = data.get("sign", "")
        lon  = data.get("longitude", 0.0)
        placements[name] = {
            "planeta_es": PLANET_ES.get(name, name),
            "signo":      SIGN_ES.get(sign, sign),
            "grado":      _deg_str(lon, sign),
            "casa":       data.get("house"),
            "retrogrado": bool(data.get("retrograde", False)),
            "dignidad":   _dignity(name, sign) if name in CORE else None,
            "abs_pos":    round(lon, 4),
        }
    out["posiciones"] = placements

    # ---- aspects ------------------------------------------------------------
    graded = _compute_graded_aspects(pos)
    out["aspectos"] = graded
    out["aspecto_mas_estrecho"] = graded[0] if graded else None

    # ---- angularity ---------------------------------------------------------
    angle_lons = {n: pos[n]["longitude"] for n in ANGLES if n in pos}
    angular = []
    for name in CORE:
        if name not in pos:
            continue
        lon1 = pos[name]["longitude"]
        for ang, lon2 in angle_lons.items():
            d = _sep(lon1, lon2)
            if d <= ANGULAR_ORB:
                angular.append({
                    "planeta":    name,
                    "planeta_es": PLANET_ES.get(name, name),
                    "angulo":     ang,
                    "angulo_es":  PLANET_ES.get(ang, ang),
                    "orbe":       round(d, 2),
                })
    angular.sort(key=lambda x: x["orbe"])
    out["planetas_angulares"] = angular

    # ---- chart ruler --------------------------------------------------------
    asc_sign  = pos.get("Ascendant", {}).get("sign", "")
    ruler_name = RULER.get(asc_sign, "Sun")
    rdata      = pos.get(ruler_name, {})
    out["regente_carta"] = {
        "planeta":              ruler_name,
        "planeta_es":           PLANET_ES.get(ruler_name, ruler_name),
        "signo":                SIGN_ES.get(rdata.get("sign", ""), ""),
        "casa":                 rdata.get("house"),
        "grado":                _deg_str(rdata.get("longitude", 0), rdata.get("sign", "")) if rdata else "",
        "regente_tradicional":  TRAD_RULER.get(asc_sign, ruler_name),
    }

    # ---- dispositor chain ---------------------------------------------------
    chain: list[str] = []
    order: list[str] = []
    cur = ruler_name
    for _ in range(20):          # cap at 20 to avoid infinite loops
        cdata = pos.get(cur)
        if cdata is None:
            break
        if cur in order:
            loop = order[order.index(cur):]
            if len(loop) == 1:
                chain.append(f"→ dispositor final: {PLANET_ES.get(cur, cur)} (rige su propio signo)")
            else:
                chain.append("→ recepción mutua: " + " ⇄ ".join(PLANET_ES.get(x, x) for x in loop))
            break
        order.append(cur)
        chain.append(f"{PLANET_ES.get(cur, cur)} en {SIGN_ES.get(cdata['sign'], cdata['sign'])}")
        nxt = RULER.get(cdata["sign"], cur)
        if nxt == cur:
            chain.append(f"→ dispositor final: {PLANET_ES.get(cur, cur)}")
            break
        cur = nxt
    out["cadena_dispositores"] = chain

    # ---- unaspected ---------------------------------------------------------
    counts = {n: 0 for n in CORE}
    for g in graded:
        for k in ("a", "b"):
            if g[k] in counts and g["tier"] <= 3:
                counts[g[k]] += 1
    out["planetas_sin_aspectos"] = [
        {"planeta": n, "planeta_es": PLANET_ES.get(n, n)}
        for n, c in counts.items() if c == 0 and n in pos
    ]
    out["conteo_aspectos_por_planeta"] = counts

    # ---- elements / modes ---------------------------------------------------
    els  = {"Fire": 0, "Earth": 0, "Air": 0, "Water": 0}
    mods = {"Cardinal": 0, "Fixed": 0, "Mutable": 0}
    for name in CORE:
        s = pos.get(name, {}).get("sign", "")
        if s in ELEMENT_OF:
            els[ELEMENT_OF[s]] += 1
        if s in MODE_OF:
            mods[MODE_OF[s]] += 1
    el_es = {"Fire": "fuego", "Earth": "tierra", "Air": "aire", "Water": "agua"}
    md_es = {"Cardinal": "cardinal", "Fixed": "fijo", "Mutable": "mutable"}
    out["elementos"]         = {el_es[k]: v for k, v in els.items()}
    out["modalidades"]       = {md_es[k]: v for k, v in mods.items()}
    out["elementos_ausentes"] = [el_es[k] for k, v in els.items() if v == 0]
    out["elemento_dominante"] = el_es[max(els, key=els.get)] if any(els.values()) else ""

    # ---- hemispheres --------------------------------------------------------
    hemi = {"norte(1-6)": 0, "sur(7-12)": 0, "este(10-3)": 0, "oeste(4-9)": 0}
    for name in CORE:
        h = pos.get(name, {}).get("house")
        if not h:
            continue
        hemi["norte(1-6)" if h <= 6 else "sur(7-12)"] += 1
        hemi["este(10-3)" if (h >= 10 or h <= 3) else "oeste(4-9)"] += 1
    out["hemisferios"] = hemi

    # ---- stelliums ----------------------------------------------------------
    by_house: dict[int, list] = {}
    by_sign:  dict[str, list] = {}
    for name in CORE:
        if name not in pos:
            continue
        h = pos[name].get("house")
        s = SIGN_ES.get(pos[name].get("sign", ""), "")
        if h:
            by_house.setdefault(h, []).append(PLANET_ES.get(name, name))
        if s:
            by_sign.setdefault(s,  []).append(PLANET_ES.get(name, name))
    out["stelliums"] = {
        "por_casa":  {k: v for k, v in by_house.items() if len(v) >= 3},
        "por_signo": {k: v for k, v in by_sign.items()  if len(v) >= 3},
    }

    # ---- configurations -----------------------------------------------------
    out["configuraciones"] = _find_configurations(pos, graded)

    # ---- moon phase ---------------------------------------------------------
    try:
        lp = subject.lunar_phase
        out["fase_lunar"] = {
            "nombre":          lp.moon_phase_name,
            "grados_sol_luna": round(lp.degrees_between_s_m, 1),
        }
    except Exception:
        sun_lon  = pos.get("Sun",  {}).get("longitude", 0)
        moon_lon = pos.get("Moon", {}).get("longitude", 0)
        diff = (moon_lon - sun_lon) % 360
        out["fase_lunar"] = {
            "nombre":          _moon_phase_name(diff),
            "grados_sol_luna": round(diff, 1),
        }

    # ---- retrogrades --------------------------------------------------------
    out["retrogrados"] = [
        PLANET_ES.get(n, n) for n in CORE
        if n in pos and pos[n].get("retrograde")
    ]

    # ---- prominence ---------------------------------------------------------
    out["ranking_prominencia"] = _prominence(pos, graded, angular, ruler_name, counts)

    # ---- headline signals ---------------------------------------------------
    out["senales_principales"] = _headline_signals(out)

    # ---- unknown birth time warning -----------------------------------------
    if not known_birth_time:
        out["_aviso"] = (
            "Hora de nacimiento desconocida. Casas, Ascendente, Medio Cielo "
            "y posición exacta de la Luna NO son fiables. "
            "No escribir sobre casas ni ángulos."
        )

    return out
