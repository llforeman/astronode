"""
prompts.py

Everything the model is told. Three stages:
  1. BRIEF     — one analytical call, no prose. Produces the spine.
  2. CHAPTERS  — 11 calls, 2 parallel waves, each with assigned factors.
  3. QA/REPAIR — per-chapter quality gate and targeted rewrite if needed.

The system prompt is the single highest-leverage artefact in the pipeline.
Facts vary per person; voice must not vary at all.
"""

# ==========================================================================
# 1. SYSTEM PROMPT — sent with every generation call
# ==========================================================================

SYSTEM = """\
Eres un astrólogo con treinta años de práctica, formación en astrología \
tradicional y psicológica, y una prosa cuidada. Escribes en español de España, \
tuteando al lector. Tienes su carta natal delante.

REGISTRO
Escribes ensayo, no informe. Prosa corrida, párrafos largos, sin listas, sin \
viñetas, sin titulares internos, sin negritas. Frases de longitud variable: \
alterna periodos largos con frases cortas y secas. El tono es cálido pero no \
adulador, preciso pero no técnico, y ocasionalmente incómodo.

QUÉ ES ESTE DOCUMENTO
Es una descripción de quién es esta persona, no una predicción de lo que le \
va a pasar. No hables del futuro. No des consejos. No prometas nada. La \
astrología aquí es un lenguaje para describir a alguien, no un oráculo.

LAS CUATRO OBLIGACIONES
Cada pasaje sustancial debe hacer estas cuatro cosas, en este orden:
  1. AFIRMACIÓN: una afirmación concreta sobre esta persona.
  2. EVIDENCIA: qué elemento de la carta lo dice y por qué significa eso. \
Enseña el razonamiento; que el lector aprenda a leer su carta, no solo a \
consumirla.
  3. COSTE: qué rompe ese rasgo. Innegociable. La adulación se lee como \
horóscopo; el coste se lee como comprensión.
  4. ESCENA: una situación concreta y cotidiana donde eso aparece. \
Específica, no genérica: "en una reunión, habrás reescrito la frase de otro \
antes de decidir si quería que la reescribieran".
Si un pasaje no puede cumplir las cuatro, no hay material suficiente: \
recórtalo en lugar de rellenarlo.

PROHIBIDO — ESTAS FÓRMULAS ANULAN EL DOCUMENTO
- "puede que a veces", "tiendes a", "en ocasiones sueles", "es posible que"
- "tu naturaleza dual", "un alma vieja", "energía", "vibración", "el universo"
- "tu viaje", "tu camino", "tu propósito", "abrazar", "sanar", "manifestar"
- cualquier frase que sea verdadera para más de la mitad de la población
- cualquier frase que solo halague
- listas de adjetivos ("eres creativo, sensible e intuitivo")
- hablar de un signo en abstracto en lugar de hablar de esta persona

CÓMO SONAR ESPECÍFICO
- Di lo que esta persona NO es. Las afirmaciones negativas convencen \
enormemente y el texto genérico nunca las hace: "No te interesa especialmente \
caer bien, aunque todo el mundo asuma lo contrario."
- Nombra las contradicciones, no las resuelvas. Las personas reales son \
incoherentes; el texto genérico es liso.
- Varía la confianza. Algunas cosas gritan en una carta y otras son notas al \
pie. Di "esto es un matiz menor" cuando lo sea.
- Cita algún grado o orbe exacto de vez en cuando (no constantemente): señala \
que algo se ha calculado de verdad.
- Los aspectos tensos (cuadraturas, oposiciones, conjunciones duras) producen \
personas; los fluidos (trígonos, sextiles) producen cumplidos. Dedica el \
espacio en consecuencia. Un trígono merece una frase que señale que la \
persona ni siquiera lo vive como algo propio.
- En un aspecto, el planeta más lento condiciona al más rápido: Saturno \
cuadratura Venus significa que Saturno da forma a cómo opera Venus, no al \
revés. El planeta lento es el sujeto de la frase.

JERARQUÍA
No todo pesa igual. Un aspecto con orbe de 0,3° es la columna vertebral de \
una persona; uno de 6° es ruido de fondo. Un planeta sobre un ángulo domina \
más que cualquier posición por signo. Escribe con esa jerarquía o el \
documento se lee como una base de datos.
"""

# Two exemplar paragraphs, sent as few-shot. Voice is fixed here, not described.
EXEMPLARS = """\
Ejemplo del registro esperado (de otra carta distinta, solo como muestra de \
tono y estructura):

«Saturno estaba a menos de un grado del Ascendente cuando naciste, y eso es \
lo primero que hay que decir de ti porque es lo primero que nota cualquiera \
que entra en una habitación contigo. No pareces frío. Pareces alguien que \
está calculando el coste de algo. La diferencia importa, aunque casi nadie \
sepa distinguirla, y esa confusión te ha costado más amistades de las que \
crees.

Lo que la carta dice, técnicamente, es que la función de Saturno —el límite, \
la responsabilidad, la contención— no está guardada en algún rincón del mapa \
sino puesta exactamente en la puerta. No es una parte de ti: es el filtro por \
el que pasa todo lo demás antes de salir. El precio de eso es una lentitud \
que a ti te parece prudencia y que a los demás les parece desinterés. En una \
cena con gente nueva, tú todavía estás decidiendo si merece la pena hablar \
cuando la conversación ya ha pasado de largo.»
"""


# ==========================================================================
# 2. BRIEF — stage 2. Analytical, not prose. Produces the spine.
# ==========================================================================

BRIEF_PROMPT = """\
Aquí está el dosier técnico de una carta natal, ya calculado y jerarquizado.

{dossier}

NO escribas prosa todavía. Analiza y devuelve un JSON con esta forma exacta:

{{
  "tensiones_centrales": [
    "Dos o tres tensiones estructurales de esta carta, en una frase cada una. \
Una tensión es un conflicto entre dos funciones, no una descripción."
  ],
  "hilo_conductor": "Una sola frase: el tema que atraviesa toda la carta. \
Debe apoyarse en el regente, el aspecto más estrecho o la configuración \
principal.",
  "lo_que_quiere": "Qué busca esta persona, en una frase.",
  "lo_que_lo_impide": "Qué se lo impide, en una frase. Debe salir de un \
aspecto tenso concreto.",
  "contradiccion_principal": "Dos cosas de esta carta que no encajan entre \
sí. No la resuelvas.",
  "lo_que_no_es": [
    "Dos o tres afirmaciones NEGATIVAS: cosas que la gente asumiría de esta \
persona y que la carta desmiente."
  ],
  "riesgo_generico": "Qué parte de esta carta es la más banal y corre más \
riesgo de producir texto que valdría para cualquiera. Nómbrala para evitarla."
}}

Solo el JSON. Sin preámbulo, sin markdown, sin ```.
"""


# ==========================================================================
# 3. CHAPTERS — the structure
# ==========================================================================
# 'factores' are the dossier keys this chapter owns.
# Aspects are routed here automatically by chart_analysis (campo 'capitulo').

CHAPTERS = [
    dict(
        n=1, palabras=800,
        titulo="La forma del conjunto",
        encargo=(
            "Capítulo de apertura. NO empieces por el Sol ni por el "
            "Ascendente. Describe la carta como una figura: dónde se "
            "concentra, qué hemisferio pesa, qué elemento falta, qué "
            "planetas están sobre los ángulos, qué stelliums hay. La "
            "ausencia es información. El objetivo es que el lector piense "
            "'esto no es un horóscopo' en la segunda página."),
        factores=["elementos", "modalidades", "elementos_ausentes",
                  "hemisferios", "stelliums", "planetas_angulares",
                  "ranking_prominencia", "retrogrados", "fase_lunar",
                  "planetas_sin_aspectos"],
    ),
    dict(
        n=2, palabras=1400,
        titulo="La cara que muestras antes de hablar",
        encargo=(
            "Ascendente y regente de la carta. El regente es lo importante: "
            "es el hilo conductor de todo el documento, y aquí es donde se "
            "presenta. Incluye la cadena de dispositores si dice algo. "
            "Planetas angulares en casa 1."),
        factores=["regente_carta", "cadena_dispositores", "planetas_angulares"],
        puntos=["Ascendant"],
    ),
    dict(
        n=3, palabras=1300,
        titulo="El motor de debajo",
        encargo=(
            "Sol: signo, casa, aspectos, dignidad, y su relación con la fase "
            "lunar (el ángulo Sol-Luna dice si esta persona se vive como una "
            "cosa o como tres). Menciona al regente del Sol."),
        factores=["fase_lunar"],
        puntos=["Sun"],
    ),
    dict(
        n=4, palabras=1300,
        titulo="Lo que necesitas para estar en casa",
        encargo=(
            "Luna: signo, casa, aspectos, condición. Aquí van los aspectos de "
            "Saturno o de los exteriores a la Luna: se viven como una "
            "condición emocional, no como un dato sobre Saturno. Fondo del "
            "Cielo si tiene contactos."),
        puntos=["Moon", "Imum_Coeli"],
    ),
    dict(
        n=5, palabras=1200,
        titulo="Cómo funciona tu cabeza",
        encargo=(
            "Mercurio: signo, casa, aspectos, retrogradación si la hay, "
            "velocidad respecto al Sol. Cómo piensa y cómo habla, que no son "
            "lo mismo."),
        puntos=["Mercury"],
    ),
    dict(
        n=6, palabras=1400,
        titulo="El amor, el deseo y lo que te parece bello",
        encargo=(
            "Venus: signo, casa, aspectos, dignidad. Descendente y casa 7. "
            "Si Venus y Marte se aspectan, el aspecto se explica aquí o en el "
            "capítulo 7, nunca en los dos."),
        puntos=["Venus", "Descendant"],
    ),
    dict(
        n=7, palabras=1300,
        titulo="Cómo vas a por lo que quieres",
        encargo=(
            "Marte: signo, casa, aspectos. Cómo discute, cómo se enfada, cómo "
            "empieza cosas. Presta atención especial al aspecto tenso más "
            "estrecho que haga Marte."),
        puntos=["Mars"],
    ),
    dict(
        n=8, palabras=1600,
        titulo="Lo que has venido a dominar",
        encargo=(
            "Saturno: casa, signo, aspectos, dignidad. Suele ser el centro "
            "emocional del documento: dale el espacio más largo. Habla de lo "
            "que a esta persona le enseñaron a tener cuidado, y de qué le "
            "cuesta esa cautela."),
        puntos=["Saturn"],
    ),
    dict(
        n=9, palabras=1200,
        titulo="En qué eres bueno y qué te cuesta",
        encargo=(
            "Júpiter: casa, signo, aspectos. NO lo escribas como 'dónde está "
            "tu suerte' — eso es promesa de horóscopo. Escríbelo como dónde "
            "esta persona se excede, dónde da de más, dónde su virtud se le "
            "va de las manos. Medio Cielo si tiene contactos."),
        puntos=["Jupiter", "Medium_Coeli"],
    ),
    dict(
        n=10, palabras=1600,
        titulo="El patrón que repites",
        encargo=(
            "El capítulo estructural. Configuración principal y su apex (el "
            "apex suele ser el problema central de la persona). Contactos de "
            "Urano, Neptuno y Plutón A PLANETAS PERSONALES O ÁNGULOS "
            "únicamente. Nodos. Quirón.\n"
            "PROHIBIDO hablar de Urano, Neptuno o Plutón por signo: eso lo "
            "comparten millones de personas nacidas en los mismos años y no "
            "dice nada de este individuo. Solo son personales por aspecto, "
            "por casa o por ser apex."),
        factores=["configuraciones", "aspecto_mas_estrecho"],
        puntos=["Uranus", "Neptune", "Pluto"],
    ),
    dict(
        n=11, palabras=900,
        titulo="El hilo, y lo que esto no puede decirte",
        encargo=(
            "Síntesis. Recoge el hilo conductor del brief y muéstralo "
            "atravesando los capítulos anteriores. No resumas: cierra.\n"
            "El último tercio del capítulo debe ser honesto sobre los límites: "
            "que una carta describe disposiciones, no destinos; que nada de "
            "esto determina decisiones; que dos personas con cartas casi "
            "idénticas llevan vidas completamente distintas. Sin ironía y sin "
            "desdecirse: es el capítulo que la gente cita a sus amigos."),
        factores=["hilo_conductor"],
    ),
]


CHAPTER_PROMPT = """\
{exemplars}

DOSIER TÉCNICO COMPLETO DE LA CARTA
(lo tienes entero para no contradecirte, pero solo escribes sobre lo asignado)

{dossier}

BRIEF ANALÍTICO — la columna vertebral del documento
{brief}

CAPÍTULO {n} DE 11 — «{titulo}»

ENCARGO
{encargo}

FACTORES ASIGNADOS A ESTE CAPÍTULO
Posiciones: {puntos}
Aspectos que se explican AQUÍ y en ningún otro sitio:
{aspectos}
Datos adicionales:
{factores}

YA DICHO EN CAPÍTULOS ANTERIORES — no lo repitas ni lo reformules
{ledger}

EXTENSIÓN
Unas {palabras} palabras. Es un objetivo real, no un techo. Si no llegas con \
material verdadero, es que el capítulo no da para más: escribe menos antes que \
rellenar.

Escribe solo el texto del capítulo. Sin título, sin encabezados, sin listas.
"""


# ==========================================================================
# 4. LEDGER + QA/REPAIR
# ==========================================================================

LEDGER_PROMPT = """\
Este es un capítulo de un documento astrológico:

{chapter}

Extrae las afirmaciones sustantivas que hace sobre la persona, como lista \
JSON de strings breves (máximo 12 palabras cada una). Solo afirmaciones sobre \
el carácter o la conducta, no descripciones técnicas de la carta.

Solo el JSON.
"""

QA_CHAPTER_PROMPT = """\
Lee este capítulo de un documento astrológico y devuelve un JSON:

{{
  "frases_genericas": ["frases que valdrían para cualquier persona"],
  "porcentaje_generico": 0-100,
  "formulas_prohibidas": ["muletillas vetadas que aparecen"],
  "tiene_coste": true/false,
  "tiene_escena_concreta": true/false,
  "solo_halaga": true/false,
  "veredicto": "publicable" | "regenerar"
}}

Criterio: veredicto "regenerar" si el porcentaje genérico supera el 10%, si \
falta el coste, si falta la escena concreta, o si el capítulo solo halaga.

Sé severo. Solo el JSON.

CAPÍTULO:
{chapter}
"""

REPAIR_PROMPT = """\
Este capítulo no ha pasado el control de calidad.

PROBLEMAS DETECTADOS
{problemas}

Reescríbelo entero corrigiendo esos problemas concretos. Mantén intacta toda \
afirmación técnica (grados, signos, casas, aspectos): no cambies ni un dato \
de la carta. Si has de quitar frases genéricas y el capítulo se queda corto, \
déjalo corto: es preferible a rellenar.

Unas {palabras} palabras. Solo el texto del capítulo, sin título ni \
encabezados.

CAPÍTULO ORIGINAL:
{chapter}
"""


def build_chapter_prompt(spec, dossier_json, brief_json, ledger_lines):
    """Assemble the per-chapter user message."""
    import json

    aspects = [a for a in dossier_json.get("aspectos", [])
               if a["capitulo"] == spec["n"]]
    aspects.sort(key=lambda a: (a["tier"], a["orbe"]))
    if aspects:
        asp_txt = "\n".join(
            f"  - {a['a_es']} {a['aspecto']} {a['b_es']} · orbe {a['orbe']}° · "
            f"{a['peso']} · {a['tipo']}"
            for a in aspects)
    else:
        asp_txt = "  (ninguno — no inventes aspectos)"

    puntos = spec.get("puntos", [])
    if puntos:
        pos = dossier_json.get("posiciones", {})
        pts_txt = "\n".join(
            f"  - {pos[p]['planeta_es']}: {pos[p]['grado']}, casa "
            f"{pos[p]['casa']}"
            + (f", {pos[p]['dignidad']}" if pos[p].get("dignidad") else "")
            + (", retrógrado" if pos[p].get("retrogrado") else "")
            for p in puntos if p in pos)
    else:
        pts_txt = "  (capítulo estructural, sin planeta asignado)"

    extra = {k: dossier_json[k] for k in spec.get("factores", [])
             if k in dossier_json}
    extra_txt = json.dumps(extra, ensure_ascii=False, indent=2) if extra \
        else "  (ninguno)"

    ledger_txt = "\n".join(f"  - {l}" for l in ledger_lines) or \
        "  (primer capítulo)"

    return CHAPTER_PROMPT.format(
        exemplars=EXEMPLARS,
        dossier=json.dumps(dossier_json, ensure_ascii=False, indent=2),
        brief=json.dumps(brief_json, ensure_ascii=False, indent=2),
        n=spec["n"], titulo=spec["titulo"], encargo=spec["encargo"],
        puntos=pts_txt, aspectos=asp_txt, factores=extra_txt,
        ledger=ledger_txt, palabras=spec["palabras"],
    )
