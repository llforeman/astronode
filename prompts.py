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

SECCIONES = [
    {"n": 1, "titulo": "Quién eres",        "casas": []},        # Sun / Moon / ASC
    {"n": 2, "titulo": "Tu mundo propio",   "casas": [1, 2, 3]},
    {"n": 3, "titulo": "Raíces y creación", "casas": [4, 5, 6]},
    {"n": 4, "titulo": "Vínculos y fondo",  "casas": [7, 8, 9]},
    {"n": 5, "titulo": "Misión y sombra",   "casas": [10, 11, 12]},
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

{data}
"""

PROMPT_CASAS = """\
Analiza las casas {start} a {end} de esta carta natal, casa por casa.
Para cada casa, explica la significancia de los planetas presentes (o su ausencia) \
y los aspectos intradomiciliarios e interdomiciliarios que la involucran.
Usa las posiciones planetarias globales, el Ascendente y las cúspides como contexto.
Explica las {num_casas} casas. Proporciona los retos de cada casa según la carta natal.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas ni viñetas.

POSICIONES PLANETARIAS GLOBALES Y CÚSPIDES
{overall}

DESGLOSE CASA POR CASA
{breakdown}
"""
