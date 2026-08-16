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

# ==========================================================================
# Carta Kármica
# ==========================================================================

SECCIONES_KARMICA = [
    {"n": 1, "titulo": "El alma que llega: karma pasado"},
    {"n": 2, "titulo": "La misión del alma: Nodo Norte"},
    {"n": 3, "titulo": "Lecciones kármicas: Saturno"},
    {"n": 4, "titulo": "La herida y la sanación: Quirón"},
    {"n": 5, "titulo": "Patrones del pasado: planetas retrógrados y Casa 12"},
    {"n": 6, "titulo": "Síntesis kármica"},
]

PROMPT_KARMICA_KARMA_PASADO = """\
Analiza el karma pasado de esta persona basándote en el Nodo Sur, la Casa 12 y los planetas retrógrados.
El Nodo Sur indica habilidades traídas de vidas anteriores y patrones que hay que soltar.
La Casa 12 muestra lo oculto, las limitaciones kármicas y el material inconsciente acumulado.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. Tono profundo pero accesible.
{gender_note}

DATOS
{data}
"""

PROMPT_KARMICA_NODO_NORTE = """\
Analiza la misión del alma de esta persona basándote en el Nodo Norte: su signo, casa y aspectos principales.
El Nodo Norte señala hacia dónde debe evolucionar el alma en esta vida — lo que resulta nuevo, incómodo y finalmente liberador.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. Tono esperanzador y motivador.
{gender_note}

DATOS
{data}
"""

PROMPT_KARMICA_SATURNO = """\
Analiza las lecciones kármicas de Saturno: su signo, casa, aspectos y si está retrógrado.
Saturno representa las deudas kármicas, las restricciones que el alma eligió para crecer, y la madurez que emerge al trabajar con ellas conscientemente.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. Tono serio pero alentador.
{gender_note}

DATOS
{data}
"""

PROMPT_KARMICA_CHIRON = """\
Analiza Quirón en esta carta: su signo, casa y aspectos principales.
Quirón es la herida primordial que no cierra del todo, pero que al ser integrada convierte a esta persona en sanadora para otros en esa misma área.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. Tono compasivo y transformador.
{gender_note}

DATOS
{data}
"""

PROMPT_KARMICA_PATRONES = """\
Analiza los patrones del pasado presentes en esta carta: planetas retrógrados (qué energías se interiorizan), \
la Casa 12 (planetas allí alojados o su vacío), y cualquier stellium que concentre karma en un área.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas.
{gender_note}

DATOS
{data}
"""

PROMPT_KARMICA_SINTESIS = """\
Escribe una síntesis kármica integradora para esta persona. Une el karma pasado (Nodo Sur), \
la misión futura (Nodo Norte), las lecciones de Saturno y la herida de Quirón en un relato coherente \
sobre el propósito del alma en esta vida. Acaba con un mensaje de cierre poderoso y personalizado.
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. 3-4 párrafos.
{gender_note}

DATOS COMPLETOS
{data}
"""

# ==========================================================================
# Sinastría
# ==========================================================================

SECCIONES_SINASTRIA = [
    {"n": 1, "titulo": "Visión general de la compatibilidad"},
    {"n": 2, "titulo": "Atracción y amor"},
    {"n": 3, "titulo": "Comunicación y mente"},
    {"n": 4, "titulo": "Tensiones y retos"},
    {"n": 5, "titulo": "Flujos de apoyo y armonía"},
    {"n": 6, "titulo": "Propósito conjunto: Nodos"},
    {"n": 7, "titulo": "Síntesis de la relación"},
]

PROMPT_SINASTRIA_BASE = """\
Analiza la sinastría entre {nombre_a} y {nombre_b}.
{instruccion}
Escribe en español de España, en tercera persona refiriéndote a ambas personas por nombre. \
Prosa corrida, sin listas ni viñetas. Tono cercano, honesto y profundo.

CARTA DE {nombre_a}
{carta_a}

CARTA DE {nombre_b}
{carta_b}

INTERASPECTOS (planetas de {nombre_a} aspectando planetas de {nombre_b} y viceversa)
{interaspectos}
"""

INSTRUCCION_SINASTRIA = {
    1: "Da una visión general de la dinámica entre ambas personas: qué energías se atraen, qué las une, qué las reta. Menciona los interaspectos más definitorios.",
    2: "Analiza la atracción física y emocional: aspectos Venus-Marte, Venus-Luna, Sol-Luna y Sol-Venus entre ambas cartas. Explica qué tipo de amor y atracción existe.",
    3: "Analiza la comunicación y compatibilidad mental: aspectos Mercurio-Mercurio, Mercurio-Sol, Mercurio-Luna. ¿Se entienden? ¿Dónde hay fricción intelectual?",
    4: "Analiza las tensiones y retos: cuadraturas y oposiciones entre las dos cartas, especialmente las que involucran planetas personales. Sé honesto pero constructivo.",
    5: "Analiza los flujos de apoyo: trígonos y sextiles entre las dos cartas. ¿Dónde fluye la energía con facilidad? ¿Qué se refuerzan mutuamente?",
    6: "Analiza el propósito conjunto usando los Nodos de ambas cartas y cómo los planetas de uno activan los Nodos del otro. ¿Hay un propósito kármico en esta relación?",
    7: "Escribe una síntesis integradora: ¿qué tipo de relación es esta, cuáles son sus mayores fortalezas y retos, y qué necesitan para que funcione? Cierra con un mensaje poderoso.",
}

# ==========================================================================
# Carta de Relación de Davison
# ==========================================================================

SECCIONES_DAVISON = [
    {"n": 1, "titulo": "La esencia de la relación"},
    {"n": 2, "titulo": "Identidad y propósito conjunto"},
    {"n": 3, "titulo": "Emociones y hogar de la relación"},
    {"n": 4, "titulo": "Comunicación en la relación"},
    {"n": 5, "titulo": "Amor, valores y atracción compartida"},
    {"n": 6, "titulo": "Retos y tensiones de la relación"},
    {"n": 7, "titulo": "Síntesis: el destino de esta relación"},
]

PROMPT_DAVISON_BASE = """\
Analiza la carta de relación de Davison entre {nombre_a} y {nombre_b}.
La carta de Davison es un punto medio temporal y espacial entre dos personas: representa la relación como entidad propia, con su propio carácter, misión y desafíos.
{instruccion}
Escribe en español de España, refiriéndote a la relación como entidad ("esta relación", "entre ellos", "la unión"). \
Prosa corrida, sin listas. Tono profundo y revelador.

NOMBRES: {nombre_a} y {nombre_b}
CARTA DAVISON (punto medio)
{carta_davison}
"""

INSTRUCCION_DAVISON = {
    1: "Da una visión general de la relación como entidad: su Sol, Luna y Ascendente de Davison. ¿Qué tipo de relación es fundamentalmente?",
    2: "Analiza el Sol y el Medio Cielo de Davison: el propósito y la identidad pública de esta relación. ¿Para qué existe esta unión?",
    3: "Analiza la Luna de Davison: la vida emocional de la relación, el hogar que crean juntos, las necesidades emocionales de la unión.",
    4: "Analiza Mercurio de Davison: cómo se comunican, cómo piensan juntos, qué tipo de conversaciones definen esta relación.",
    5: "Analiza Venus y Marte de Davison: los valores compartidos, el amor que construyen, la atracción y la energía sexual de la relación.",
    6: "Analiza los aspectos tensos de la carta Davison (cuadraturas, oposiciones) y Saturno: los retos que la relación debe trabajar para sobrevivir y crecer.",
    7: "Escribe una síntesis integradora: el destino y la lección de esta relación, su mayor regalo y su mayor desafío. Cierra con un mensaje poderoso.",
}

# ==========================================================================
# Revolución Solar
# ==========================================================================

SECCIONES_SOLAR = [
    {"n": 1, "titulo": "El tema del año"},
    {"n": 2, "titulo": "Áreas de vida activadas"},
    {"n": 3, "titulo": "Retos del año"},
    {"n": 4, "titulo": "Oportunidades del año"},
    {"n": 5, "titulo": "Síntesis: tu año en profundidad"},
]

PROMPT_SOLAR_BASE = """\
Analiza la revolución solar de {nombre} para el año que empieza en {fecha_rs}.
{instruccion}
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. \
Compara con la carta natal cuando sea relevante.
{gender_note}

CARTA NATAL
{carta_natal}

REVOLUCIÓN SOLAR
{carta_rs}
"""

INSTRUCCION_SOLAR = {
    1: "Analiza el Ascendente de la RS, el Sol en su casa de RS, y la Luna de RS. ¿Cuál es el tema central de este año para esta persona?",
    2: "Analiza qué casas de la RS están más activadas (muchos planetas, ángulos importantes) y qué áreas de vida estarán en foco este año.",
    3: "Analiza los aspectos tensos de la RS (cuadraturas, oposiciones) y cómo los planetas de RS aspectan la carta natal. ¿Qué retos hay?",
    4: "Analiza los trígonos y sextiles de la RS, y los planetas de RS que apoyan la carta natal. ¿Qué oportunidades trae este año?",
    5: "Escribe una síntesis del año completo: su tema central, los meses más importantes, los retos a trabajar y las oportunidades a aprovechar. Cierra con un mensaje de año.",
}

# ==========================================================================
# Revolución Lunar
# ==========================================================================

SECCIONES_LUNAR = [
    {"n": 1, "titulo": "El tema del mes"},
    {"n": 2, "titulo": "Emociones y vida interior"},
    {"n": 3, "titulo": "Síntesis del mes"},
]

PROMPT_LUNAR_BASE = """\
Analiza la revolución lunar de {nombre} para el mes que empieza en {fecha_rl}.
{instruccion}
Escribe en español de España, tuteando al lector. Prosa corrida, sin listas. \
Compara con la carta natal cuando sea relevante.
{gender_note}

CARTA NATAL
{carta_natal}

REVOLUCIÓN LUNAR
{carta_rl}
"""

INSTRUCCION_LUNAR = {
    1: "Analiza el Ascendente de la RL, la Luna en su casa de RL, y el Sol de RL. ¿Cuál es el tema central de este mes para esta persona?",
    2: "Analiza la vida emocional de este mes: aspectos de la Luna de RL, planetas en casas emocionales (4, 8, 12), y qué temas internos emergen.",
    3: "Escribe una síntesis del mes: el tono emocional, los momentos clave, lo que hay que atender y lo que fluirá con facilidad. Cierra con un consejo concreto para este mes.",
}
