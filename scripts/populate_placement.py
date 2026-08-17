"""
Populate placement_content and sun_moon_interaction tables via LLM API.

Writes status='generated'. Flip to 'published' manually after editing.
meta_title is templated; meta_desc is derived from preview_text — no LLM calls for either.

Usage (from the astronode/ root):
  python scripts/populate_placement.py

Env vars: AI_API_KEY, AI_API_URL (same as main app).
"""

import json
import os
import re
import sys
import time

# Add project root to path and load .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from app import create_app
from extensions import db
from models import PlacementContent, SunMoonInteraction
from openai import OpenAI

# ── LLM client ────────────────────────────────────────────────────────────────

_client = OpenAI(
    api_key=os.environ.get('AI_API_KEY', ''),
    base_url=os.environ.get('AI_API_URL', 'https://openrouter.ai/api/v1'),
)
MODEL = os.environ.get('AI_MODEL_PROSE', os.environ.get('AI_MODEL', 'anthropic/claude-sonnet-4-5'))

# ── Label maps ────────────────────────────────────────────────────────────────

BODY_LABEL   = {'sun': 'Sol', 'moon': 'Luna', 'rising': 'Ascendente'}
SIGN_LABEL   = {
    'Aries': 'Aries', 'Taurus': 'Tauro', 'Gemini': 'Géminis',
    'Cancer': 'Cáncer', 'Leo': 'Leo', 'Virgo': 'Virgo',
    'Libra': 'Libra', 'Scorpio': 'Escorpio', 'Sagittarius': 'Sagitario',
    'Capricorn': 'Capricornio', 'Aquarius': 'Acuario', 'Pisces': 'Piscis',
}
SIGN_EN_TO_ES_SLUG = {
    'Aries': 'aries', 'Taurus': 'tauro', 'Gemini': 'geminis',
    'Cancer': 'cancer', 'Leo': 'leo', 'Virgo': 'virgo',
    'Libra': 'libra', 'Scorpio': 'escorpio', 'Sagittarius': 'sagitario',
    'Capricorn': 'capricornio', 'Aquarius': 'acuario', 'Pisces': 'piscis',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _derive_meta_desc(preview_text, max_chars=155):
    """First ~155 chars of preview_text, truncated at word boundary."""
    if not preview_text:
        return ''
    text = preview_text.strip().replace('\n', ' ')
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(' ')
    return truncated[:last_space].rstrip('.,;:') + '...' if last_space > 0 else truncated


def _call_llm(prompt, max_retries=3):
    """Call LLM, return parsed JSON dict. Retries on parse failure."""
    for attempt in range(max_retries):
        try:
            resp = _client.chat.completions.create(
                model=MODEL,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.8,
                max_tokens=4000,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown code fences if present
            raw = re.sub(r'^```(?:json)?\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            return json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            print(f'  Attempt {attempt + 1} failed: {e}')
            if attempt < max_retries - 1:
                time.sleep(2)
    raise RuntimeError(f'LLM call failed after {max_retries} attempts')


# ── Prompts ───────────────────────────────────────────────────────────────────

def _placement_prompt(body, sign):
    body_label = BODY_LABEL[body]
    sign_label = SIGN_LABEL[sign]
    return f"""Escribe en español para Astronode, una plataforma de astrología personalizada con IA.

Estás escribiendo sobre {body_label.upper()} EN {sign_label.upper()}.

Devuelve únicamente un objeto JSON válido con estos tres campos:

{{
  "preview_text": "Entre 200 y 300 palabras. Segunda persona (tú/te/tu). Prosa fluida — sin listas, sin encabezados. Registro observacional y sosegado: empieza con una afirmación concreta sobre cómo funciona esta persona, no con un superlativo ni con una negación dramática (evita aperturas tipo 'tú no eres X', 'llegas a la vida', 'no sientes a medias'). Sin hooks de marketing. Termina a mitad de pensamiento: la última frase debe crear tensión que pide resolución, pero sin mencionar otros planetas ni la carta completa.",
  "preview_hook": "Una o dos frases. El cierre que aparece en la página individual (/sol/aries, etc.) después del texto largo — apunta hacia el siguiente planeta como lo que viene a continuación sin resolverlo. Ejemplo de registro: 'Lo que el {body_label} en {sign_label} no te dice es qué haces cuando estás solo — eso es la Luna.'",
  "seo_body": "Entre 800 y 1200 palabras. HTML con etiquetas h2 y h3 para estructurar. Tono analítico pero accesible — ni académico ni de revista de belleza. Cubre: qué significa este planeta en este signo, cómo se manifiesta en la vida cotidiana, sus fortalezas, sus tensiones, cómo suele evolucionar con la madurez. Sin mencionar IA, Astronode, ni otras plataformas. Sin listas de palabras clave."
}}

Devuelve solo el JSON. Sin texto adicional antes ni después."""


def _interaction_prompt(sun_sign, moon_sign):
    sun_label  = SIGN_LABEL[sun_sign]
    moon_label = SIGN_LABEL[moon_sign]
    return f"""Escribe en español para Astronode, una plataforma de astrología personalizada con IA.

Estás escribiendo sobre la interacción entre SOL EN {sun_label.upper()} y LUNA EN {moon_label.upper()}.
Esta persona tiene el Sol en {sun_label} (identidad consciente, impulso exterior) y la Luna en {moon_label} (necesidad emocional interior, patrón instintivo).

Devuelve únicamente un objeto JSON válido:

{{
  "text": "Una o dos frases que describan la tensión o armonía específica entre estas dos posiciones. Segunda persona. Concreta, no genérica. Nombra lo que entra en conflicto o lo que se refuerza. Ejemplo de registro: 'Tu Sol en Aries empuja hacia la acción inmediata; tu Luna en Cáncer necesita sentir que hay un hogar esperándote antes de dar el primer paso.'"
}}

Devuelve solo el JSON. Sin texto adicional."""


# ── Writers ───────────────────────────────────────────────────────────────────

def populate_placement(body, sign, lang='es', dry_run=False):
    """Generate and upsert one placement_content row."""
    body_label = BODY_LABEL[body]
    sign_label = SIGN_LABEL[sign]

    if dry_run:
        print(f'  [DRY RUN] Would generate: {body_label} en {sign_label} via {MODEL}')
        return

    print(f'  Generating {body_label} en {sign_label}...')
    data = _call_llm(_placement_prompt(body, sign))

    preview_text = data.get('preview_text', '').strip()
    preview_hook = data.get('preview_hook', '').strip()
    seo_body     = data.get('seo_body',     '').strip()
    meta_title   = f'{body_label} en {sign_label} — Astronode'
    meta_desc    = _derive_meta_desc(preview_text)

    row = PlacementContent.query.filter_by(body=body, sign=sign, lang=lang).first()
    if not row:
        row = PlacementContent(body=body, sign=sign, lang=lang)
        db.session.add(row)

    row.preview_text = preview_text
    row.preview_hook = preview_hook
    row.seo_body     = seo_body
    row.meta_title   = meta_title
    row.meta_desc    = meta_desc
    row.status       = 'generated'
    db.session.commit()
    print(f'  Saved: {body_label} en {sign_label} (status=generated)')


def populate_interaction(sun_sign, moon_sign, lang='es', dry_run=False):
    """Generate and upsert one sun_moon_interaction row."""
    sun_label  = SIGN_LABEL[sun_sign]
    moon_label = SIGN_LABEL[moon_sign]

    if dry_run:
        print(f'  [DRY RUN] Would generate: Sol {sun_label} / Luna {moon_label} via {MODEL}')
        return

    print(f'  Generating interaction: Sol en {sun_label} / Luna en {moon_label}...')
    data = _call_llm(_interaction_prompt(sun_sign, moon_sign))
    text = data.get('text', '').strip()

    row = SunMoonInteraction.query.filter_by(
        sun_sign=sun_sign, moon_sign=moon_sign, lang=lang
    ).first()
    if not row:
        row = SunMoonInteraction(sun_sign=sun_sign, moon_sign=moon_sign, lang=lang)
        db.session.add(row)

    row.text = text
    db.session.commit()
    print(f'  Saved: Sol {sun_label} / Luna {moon_label}')


# ── Run ───────────────────────────────────────────────────────────────────────

# Test batch: Sun Aries, Moon Cancer, Rising Capricorn + Aries→Cancer interaction
# Population order: moon → sun → rising (interaction fires as soon as moon + sun exist)
TEST_PLACEMENTS = [
    ('moon',    'Virgo'),
]
TEST_INTERACTIONS = []

if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv

    app = create_app()
    with app.app_context():
        print('=== Placement content ===')
        for body, sign in TEST_PLACEMENTS:
            try:
                populate_placement(body, sign, dry_run=dry_run)
                time.sleep(1)  # avoid rate limits
            except Exception as e:
                print(f'  ERROR: {e}')

        print('\n=== Sun-Moon interactions ===')
        for sun_sign, moon_sign in TEST_INTERACTIONS:
            try:
                populate_interaction(sun_sign, moon_sign, dry_run=dry_run)
                time.sleep(1)
            except Exception as e:
                print(f'  ERROR: {e}')

    print('\nDone. Review output in DB, then flip status to "published" to index.')
