"""
prompts.py

Simple house-based prompts, mirroring the astro12 approach.
One LLM call per section. No planner, no beats, no validation.
The model decides what is interesting given the chart data.
"""

from __future__ import annotations

# ==========================================================================
# Section definitions
# ==========================================================================

# n=1  → personality snapshot (Sun / Moon / ASC)
# n=2-13 → one call per house (casa = house number 1-12)
SECCIONES = [{"n": 1, "titulo": "Quién eres", "casa": None}] + [
    {"n": h + 1, "titulo": f"Casa {h}", "casa": h} for h in range(1, 13)
]

CAPITULOS = SECCIONES  # backward-compat alias

# ==========================================================================
# Prompts
# ==========================================================================

PROMPT_PERSONALIDAD = """\
Analiza la personalidad de esta persona basándote en su Sol, Luna y Ascendente.
Para cada uno, explica su signo y casa, y lo que significa para esta persona concreta.
Explica cómo trabajan juntos y dónde se contradicen.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas ni viñetas.
{gender_note}

{data}
"""

PROMPT_CASA = """\
Analiza la casa {n} de esta carta natal.
Explica los planetas presentes (o su ausencia), los aspectos intradomiciliarios \
e interdomiciliarios que la involucran, y los retos que indica esta casa según la carta.
Usa las posiciones planetarias globales y las cúspides como contexto.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas ni viñetas.
{gender_note}

POSICIONES PLANETARIAS GLOBALES Y CÚSPIDES
{overall}

CASA {n}
{breakdown}
"""
