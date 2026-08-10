"""
One-time migration: expand reading.content from TEXT (64KB) to MEDIUMTEXT (16MB).
Run once on Render via: python migrate_content_mediumtext.py
"""
from app import create_app
from extensions import db

app = create_app()
with app.app_context():
    db.session.execute(db.text(
        'ALTER TABLE reading MODIFY COLUMN content MEDIUMTEXT'
    ))
    db.session.commit()
    print("Done: reading.content is now MEDIUMTEXT.")
