"""
One-time script: insert saturn_return and jupiter_return ReadingType rows.
Run once on the server:  python scripts/seed_planet_returns.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import ReadingType

app = create_app()

ROWS = [
    dict(
        name='Retorno de Saturno',
        slug='saturn_return',
        description='Cada paso exacto de Saturno a su posición natal — directo y retrógrado — en una ventana de diez años.',
        price_cents=0,
        min_tier='free',
        active=True,
    ),
    dict(
        name='Retorno de Júpiter',
        slug='jupiter_return',
        description='Cada paso exacto de Júpiter a su posición natal — directo y retrógrado — en una ventana de diez años.',
        price_cents=0,
        min_tier='free',
        active=True,
    ),
]

with app.app_context():
    for row in ROWS:
        exists = ReadingType.query.filter_by(slug=row['slug']).first()
        if exists:
            print(f"Already exists: {row['slug']} (id={exists.id})")
        else:
            rt = ReadingType(**row)
            db.session.add(rt)
            db.session.commit()
            print(f"Inserted: {row['slug']} (id={rt.id})")
