from app import create_app

app = create_app()
with app.app_context():
    from flask_migrate import upgrade
    upgrade()
    print("Database migrated.")
