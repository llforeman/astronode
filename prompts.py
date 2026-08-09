"""
prompts.py

Storytelling layer. Two stages:
  1. PLANNER  — one call, whole document, no prose. Produces theses + beats.
  2. CHAPTERS — 9 parallel writing calls, each executing pre-decided beats.

After writing:
  3. TELLS    — cheap call per chapter, extracts 3 observable signals.
  4. INDEX    — cheap call builds area-to-chapter index from plan theses.
"""

from __future__ import annotations
import json
from typing import Any


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
# 2. FIVE SECTIONS — organized by house groups, not by planet
# ==========================================================================

# Each section covers a group of houses. Material selection uses house
# membership (which houses the planets are in) rather than planet identity.
# casas=[] means the section uses Sun/Moon/ASC directly (personality snapshot).

SECCIONES = [
    dict(
        n=1, palabras=900,
        titulo="Quién eres",
        pregunta="¿Cómo te ven desde fuera, cómo lo vives tú por dentro, y "
                 "dónde no coinciden?",
        escena="la primera vez que alguien te describe a otra persona y usas "
               "esa descripción para contrastarte con ella",
        max_factores=3,
        casas=[],   # special: Sun, Moon, Ascendant + their mutual aspects
        fuente_extra=["Sun", "Moon", "Ascendant", "fase_lunar", "regente_carta",
                      "ranking_prominencia"],
        nota="Instantánea de identidad. Sol: quién eres. Luna: cómo lo vives. "
             "Ascendente: cómo te ven. Muestra dónde coinciden y dónde se "
             "contradicen.",
    ),
    dict(
        n=2, palabras=1200,
        titulo="Tu mundo propio",
        pregunta="¿Cómo construye esta persona su identidad, sus recursos y "
                 "su manera de pensar?",
        escena="un momento a solas con algo que te importa mucho y que casi "
               "nadie sabe que te importa",
        max_factores=4,
        casas=[1, 2, 3],
        fuente_extra=["Ascendant", "regente_carta"],
        nota="Casas 1-3: cuerpo e identidad visible (casa 1), recursos y "
             "valores propios (casa 2), mente y entorno inmediato (casa 3). "
             "Los aspectos intragrupo operan dentro de esta zona. Los cruzados "
             "conectan esta zona con otra parte de la vida.",
    ),
    dict(
        n=3, palabras=1200,
        titulo="Raíces y creación",
        pregunta="¿De dónde viene esta persona y qué crea desde ahí?",
        escena="una conversación con alguien de tu familia de origen que saca "
               "a la superficie algo que creías superado",
        max_factores=4,
        casas=[4, 5, 6],
        fuente_extra=["Imum_Coeli"],
        nota="Casas 4-6: hogar y origen privado (casa 4), expresión creativa "
             "y deseo (casa 5), salud y trabajo cotidiano (casa 6). "
             "Los aspectos intragrupo operan dentro de esta zona. Los cruzados "
             "conectan esta zona con otra parte de la vida.",
    ),
    dict(
        n=4, palabras=1400,
        titulo="Vínculos y fondo",
        pregunta="¿Cómo se relaciona esta persona, y qué hay debajo de esas "
                 "relaciones que ella misma tarda en ver?",
        escena="cuando alguien cruza un límite que no habías dicho en voz alta "
               "y tú tienes que decidir si lo nombras",
        max_factores=4,
        casas=[7, 8, 9],
        fuente_extra=["Descendant"],
        nota="Casas 7-9: relaciones y socios (casa 7), transformación y "
             "recursos compartidos (casa 8), filosofía y horizonte (casa 9). "
             "Los aspectos intragrupo operan dentro de esta zona. Los cruzados "
             "conectan esta zona con otra parte de la vida.",
    ),
    dict(
        n=5, palabras=1400,
        titulo="Misión y sombra",
        pregunta="¿Qué papel ocupa esta persona en el mundo, y qué lleva "
                 "consigo que casi nadie ve?",
        escena="cuando algo que guardabas sale a la superficie sin que lo "
               "eligieras y tienes que decidir qué hacer con eso",
        max_factores=4,
        casas=[10, 11, 12],
        fuente_extra=["Medium_Coeli", "configuraciones", "aspecto_mas_estrecho",
                      "planetas_sin_aspectos"],
        nota="Casas 10-12: carrera y reputación pública (casa 10), comunidad "
             "y esperanzas (casa 11), lo oculto y el inconsciente (casa 12). "
             "Los aspectos intragrupo operan dentro de esta zona. Los cruzados "
             "conectan esta zona con otra parte de la vida. "
             "PROHIBIDO el giro de cuarta pared. Cierra sobre la carta, no "
             "sobre el acto de leerla.",
    ),
]

# Keep CAPITULOS as alias so any residual references don't crash
CAPITULOS = SECCIONES


# ==========================================================================
# 3. DETERMINISTIC MATERIAL SELECTION
# ==========================================================================

def seleccionar_material(dossier: dict, spec: dict) -> dict:
    """Hard-cap the factors a section may use, organized by house group."""
    casas = spec.get("casas", [])

    if not casas:
        # Section 1: personality snapshot — Sun, Moon, Ascendant and their
        # mutual aspects only.
        nucleos = {"Sun", "Moon", "Ascendant"}
        all_asp = [a for a in dossier.get("aspectos", [])
                   if a["a"] in nucleos and a["b"] in nucleos]
        for a in all_asp:
            a["tipo_relacion"] = "intra"
        planetas_en_grupo = {k: v for k, v in dossier.get("posiciones", {}).items()
                             if k in nucleos}
    else:
        # Sections 2-5: filter aspects where at least one planet is in this
        # section's house group. Mark intra vs cross.
        casas_set = set(casas)
        all_asp = []
        for a in dossier.get("aspectos", []):
            a_in = a.get("casa_a") in casas_set
            b_in = a.get("casa_b") in casas_set
            if a_in or b_in:
                tagged = dict(a)
                tagged["tipo_relacion"] = "intra" if (a_in and b_in) else "cruzado"
                all_asp.append(tagged)

        planetas_en_grupo = {k: v for k, v in dossier.get("posiciones", {}).items()
                             if v.get("casa") in casas_set}

    duros   = sorted([a for a in all_asp if a.get("tipo") == "tenso"],
                     key=lambda a: a["orbe"])
    blandos = sorted([a for a in all_asp if a.get("tipo") == "fluido"],
                     key=lambda a: a["orbe"])

    elegidos = (duros + blandos)[: spec["max_factores"]]

    extra = {k: dossier[k] for k in spec.get("fuente_extra", [])
             if k in dossier and k not in planetas_en_grupo}

    return {
        "planetas_en_grupo": planetas_en_grupo,
        "aspectos":          elegidos,
        "extra":             extra,
        "descartados_count": len(all_asp) - len(elegidos),
    }


# ==========================================================================
# 4. THE PLANNER — one call, whole document, no prose
# ==========================================================================

PLANNER_PROMPT = """\
Eres el editor que planifica un documento astrológico de cinco secciones \
sobre una persona. NO escribes prosa. Decides la historia.

DOSIER TÉCNICO
{dossier}

MATERIAL YA ASIGNADO A CADA SECCIÓN
{material}

Tu trabajo es que las cinco secciones formen UNA historia, no cinco fichas. \
Eso significa tres cosas:

1. UNA TESIS POR SECCIÓN. Una sola frase sobre esta persona, en segunda \
persona, SIN NOMBRAR NINGÚN PLANETA, SIGNO NI CASA. Si la tesis necesita \
nombrar a Saturno o la casa 8 para sostenerse, es que no has entendido qué \
dice ese factor.

2. DEPENDENCIA. Cada sección termina dejando una pregunta abierta que la \
siguiente responde. La sección 4 debe ser ilegible fuera de orden. Escribe \
explícitamente el "enlace" de cada sección.

3. PROGRESIÓN. Sección 1 muestra quién es. Secciones 2-3 muestran cómo \
funciona y de dónde viene. Sección 4 muestra cómo se relaciona y qué hay \
debajo. Sección 5 llega a la misión y a lo que esta persona no ha visto aún. \
El documento tiene que ponerse más incómodo, no más simpático.

Devuelve JSON con esta forma exacta:

{{
  "tesis_global": "Una frase. Quién es esta persona. Sin astrología.",
  "capitulos": [
    {{
      "n": 1,
      "tesis": "Una sola frase sobre esta persona. Sin planetas, signos ni casas.",
      "beats": [
        {{"tipo": "apertura", "contenido": "Qué afirmar. PROHIBIDO mencionar \
astrología en este beat."}},
        {{"tipo": "evidencia", "contenido": "Qué factor de la carta lo \
sostiene y por qué significa eso"}},
        {{"tipo": "complicacion", "contenido": "Qué contradice lo anterior. \
No lo resuelvas."}},
        {{"tipo": "coste", "contenido": "Qué rompe esto. Quién paga."}},
        {{"tipo": "escena", "contenido": "Qué ocurre exactamente en la escena \
asignada"}},
        {{"tipo": "senal", "contenido": "El momento observable en que esta \
persona puede pillarse a sí misma haciéndolo. NO es un consejo. No digas qué \
debería hacer: di qué va a notar. Tiene que ser algo que ocurra en menos de \
un segundo y que se pueda comprobar."}},
        {{"tipo": "enlace", "contenido": "La pregunta que queda abierta para \
la siguiente sección"}}
      ]
    }}
  ]
}}

REGLAS
- Cinco secciones, en orden del 1 al 5.
- Ninguna tesis puede repetir la idea de otra. Si dos secciones dicen lo \
mismo, una de las dos está mal planteada: cámbiala.
- Cada beat es una instrucción para el que escribe, no prosa acabada.
- Si una sección no tiene material suficiente para seis beats, dale cuatro. \
Es preferible a rellenar.
- La sección 5 no lleva beat de escena.
- Los aspectos marcados [cruzado] conectan zonas de la vida distintas: son \
los que más revelan cómo un área interfiere en otra. Úsalos para eso.

Solo el JSON.
"""


# ==========================================================================
# 5. PLAN VALIDATION — deterministic gate, no LLM
# ==========================================================================

_ASTRO = ["sol", "luna", "mercurio", "venus", "marte", "júpiter", "jupiter",
          "saturno", "urano", "neptuno", "plutón", "pluton", "ascendente",
          "quirón", "quiron", "aries", "tauro", "géminis", "geminis",
          "cáncer", "cancer", "leo", "virgo", "libra", "escorpio",
          "sagitario", "capricornio", "acuario", "piscis", "casa ",
          "cuadratura", "trígono", "trigono", "oposición", "oposicion",
          "conjunción", "conjuncion", "orbe"]


def validar_plan(plan: dict) -> list[str]:
    """Deterministic gate before a single word is written."""
    errores = []
    caps = plan.get("capitulos", [])
    if len(caps) != len(SECCIONES):
        errores.append(f"faltan secciones: se esperan {len(SECCIONES)}, hay {len(caps)}")

    vistas = []
    for c in caps:
        t = (c.get("tesis") or "").lower()
        if any(w in t for w in _ASTRO):
            errores.append(f"sec {c.get('n')}: tesis nombra astrología → {t}")
        if t in vistas:
            errores.append(f"sec {c.get('n')}: tesis duplicada")
        vistas.append(t)
        tipos = [b.get("tipo") for b in c.get("beats", [])]
        if c.get("n") != len(SECCIONES) and "enlace" not in tipos:
            errores.append(f"sec {c.get('n')}: sin beat de enlace")
        if "coste" not in tipos:
            errores.append(f"sec {c.get('n')}: sin beat de coste")
    return errores


# ==========================================================================
# 6. WRITING CALL — executes beats, decides nothing
# ==========================================================================

# Spanish runs ~2.5-3.0 tokens per word. At 2.2 every long chapter truncates
# mid-sentence. 3.4 leaves headroom; finish_reason=length is logged as warning.
TOKENS_POR_PALABRA = 3.4


def max_tokens_para(spec: dict) -> int:
    return int(spec["palabras"] * TOKENS_POR_PALABRA)


ESCRIBIR_PROMPT = """\
{exemplars}

Escribes UNA sección. Las decisiones narrativas ya están tomadas: no las \
cambies, ejecútalas.

SECCIÓN {n} DE 5 — «{titulo}»
ZONA DE LA CARTA QUE CUBRE ESTA SECCIÓN
{nota}

PREGUNTA QUE RESPONDE ESTA SECCIÓN
{pregunta}

TESIS — toda la sección sostiene esta frase y ninguna otra
{tesis}

BEATS — escribe uno o dos párrafos por beat, EN ESTE ORDEN
{beats}

MATERIAL DE LA CARTA — solo esto. No uses ningún otro dato.
Los aspectos marcados [intragrupo] conectan planetas dentro de la misma zona \
de la vida. Los marcados [cruzado con otra zona] conectan esta zona con otra \
parte de la vida: son los que más revelan interferencias entre áreas.
{material}

ESCENA ASIGNADA — la única escena de la sección
{escena}

DE DÓNDE VIENE EL LECTOR — la sección anterior terminó preguntando:
{enlace_anterior}

CINCO REGLAS QUE ANULAN LA SECCIÓN SI SE INCUMPLEN
1. El primer párrafo no contiene NI UN nombre de planeta, signo, casa o \
aspecto. Habla de la persona. La carta aparece después.
2. Ninguna frase empieza por el nombre de un planeta. El sujeto de tus frases \
es esta persona, no el cielo.
3. Prohibida la construcción «X en Y sugiere que…» y todas sus variantes \
(«indica que», «se debe a que», «lo que sugiere»). Afirma primero; explica \
después, en otra frase.
4. Una sola escena, la asignada. No inventes reuniones de trabajo ni cenas \
con amigos.
5. Sin párrafo de resumen. Nada de «en resumen» ni «en conclusión». El último \
párrafo es el enlace: deja la pregunta abierta.

PROHIBIDO DAR CONSEJOS
No escribas nunca qué debería hacer esta persona. Nada de «aprende a», \
«intenta», «es importante que», «te conviene», «trabaja tu», «busca el \
equilibrio». En cuanto aconsejas, dejas de describir a alguien concreto y \
empiezas a decir lo que vale para cualquiera.
Lo que sí haces es el beat de señal: nombrar el momento observable en que \
esta persona se puede pillar. «Sabrás que está ocurriendo cuando…». Un \
segundo, comprobable, imposible de escribir para otra carta.

GÉNERO GRAMATICAL
Esta persona es: {genero}. Mantén ese género en todos los adjetivos y \
participios de la sección. Si es desconocido, escribe en español neutro: evita \
adjetivos con marca de género referidos al lector.

EXTENSIÓN
Unas {palabras} palabras. Si el material no da, escribe menos. Rellenar es \
peor que quedarse corto.

Solo el texto. Sin título, sin encabezados, sin listas.
"""


def formatear_beats(beats: list[dict]) -> str:
    return "\n".join(
        f"  {i+1}. [{b.get('tipo','')}] {b.get('contenido','')}"
        for i, b in enumerate(beats))


def formatear_material(sel: dict) -> str:
    lineas = []
    # Planets in this section's house group (or Sun/Moon/ASC for section 1)
    planetas = sel.get("planetas_en_grupo") or sel.get("posiciones", {})
    for k, p in planetas.items():
        lineas.append(
            f"  - {p.get('planeta_es', k)}: {p.get('grado', '')}, "
            f"casa {p.get('casa', '')}"
            + (f", {p['dignidad']}" if p.get("dignidad") else "")
            + (", retrógrado" if p.get("retrogrado") else ""))
    for a in sel["aspectos"]:
        rel = a.get("tipo_relacion", "")
        rel_str = (" [intragrupo]" if rel == "intra"
                   else " [cruzado con otra zona]" if rel == "cruzado"
                   else "")
        lineas.append(
            f"  - {a['a_es']} {a['aspecto']} {a['b_es']} · orbe {a['orbe']}° "
            f"· {a['peso']} · {a['tipo']}{rel_str}")
    if sel.get("extra"):
        lineas.append("  - " + json.dumps(sel["extra"], ensure_ascii=False))
    if sel.get("descartados_count"):
        lineas.append(f"  ({sel['descartados_count']} factores menores "
                      f"descartados a propósito — no los busques)")
    return "\n".join(lineas) or "  (sin material asignado)"


def construir_prompt_escritura(spec: dict, plan_cap: dict, sel: dict,
                               enlace_anterior: str,
                               genero: str = "desconocido") -> str:
    return ESCRIBIR_PROMPT.format(
        exemplars=EXEMPLARS,
        n=spec["n"], titulo=spec["titulo"], pregunta=spec["pregunta"],
        nota=spec.get("nota", ""),
        tesis=plan_cap.get("tesis", ""),
        beats=formatear_beats(plan_cap.get("beats", [])),
        material=formatear_material(sel),
        escena=spec.get("escena") or "(esta sección no lleva escena)",
        enlace_anterior=enlace_anterior or "(es la primera sección)",
        genero=genero,
        palabras=spec["palabras"],
    )


# ==========================================================================
# 7. TELLS — observable signals, not advice (cheap call per chapter)
# ==========================================================================

COMPROBAR_PROMPT = """\
Este es un capítulo de un documento astrológico:

{chapter}

Extrae TRES señales observables: momentos concretos en los que esta persona \
puede pillarse a sí misma haciendo lo que el capítulo describe.

REGLAS
- No son consejos. Prohibido «deberías», «intenta», «aprende a».
- Cada una ocurre en menos de un segundo y se puede comprobar.
- Cada una sale de este capítulo concreto, no de la astrología en general.
- Máximo 20 palabras cada una.
- Empieza cada una por un verbo o por «Cuando».

Ejemplos del registro correcto:
  «Cuando reduces una cifra dos veces antes de decirla en voz alta.»
  «Cuando dices que sí antes de haber mirado el calendario.»

Devuelve JSON: {{"senales": ["...", "...", "..."]}}
"""


# ==========================================================================
# 8. AREA INDEX — findability without restructuring the arc
# ==========================================================================

AREAS = {
    "Amor y pareja":       [1, 4],
    "Amistad y grupo":     [2, 5],
    "Trabajo y propósito": [3, 5],
    "Conflicto":           [2, 4],
    "Raíces y soledad":    [1, 3],
}

INDICE_PROMPT = """\
Aquí están las tesis de las cinco secciones de un documento astrológico:

{tesis}

Escribe el índice por áreas de la vida que cierra el documento. Para cada \
área, una sola frase que diga qué dice este documento concreto sobre ella y \
en qué secciones está.

Áreas y secciones donde aparece cada una:
{areas}

REGLAS
- Una frase por área. Sin astrología, sin nombres de planetas ni casas.
- No resumas las secciones: di qué encontrará el lector si vuelve ahí.
- Segunda persona.

Devuelve JSON: {{"indice": [{{"area": "...", "frase": "...", \
"capitulos": [1,2]}}]}}
"""


def construir_prompt_indice(plan: dict) -> str:
    tesis = "\n".join(f"  {c['n']}. {c.get('tesis', '')}"
                      for c in plan.get("capitulos", []))
    areas = "\n".join(f"  {k}: secciones {', '.join(map(str, v))}"
                      for k, v in AREAS.items())
    return INDICE_PROMPT.format(tesis=tesis, areas=areas)
