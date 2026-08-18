from flask import Flask, request
from flask_login import current_user
from config import Config
from extensions import db, login_manager, csrf, limiter, mail, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'

    from blueprints.public   import public_bp
    from blueprints.auth     import auth_bp
    from blueprints.main     import main_bp
    from blueprints.admin    import admin_bp
    from blueprints.billing  import billing_bp
    from blueprints.readings import readings_bp

    for bp in (public_bp, auth_bp, main_bp, admin_bp, billing_bp, readings_bp):
        app.register_blueprint(bp)

    _register_filters(app)
    _register_hooks(app)
    return app


def _register_filters(app):
    import markdown as _md
    from markupsafe import Markup

    @app.template_filter('md')
    def render_markdown(text):
        return Markup(_md.markdown(
            text or '',
            extensions=['nl2br', 'sane_lists'],
        ))


def _register_hooks(app):
    PUBLIC_BLUEPRINTS = {'public', 'auth', 'static'}

    @app.before_request
    def load_user_context():
        if request.blueprint in PUBLIC_BLUEPRINTS:
            return
        if not current_user.is_authenticated:
            return

    @app.context_processor
    def inject_notifications():
        if not current_user.is_authenticated:
            return {}
        from models import Notification
        count = Notification.query.filter_by(
            user_id=current_user.id, read_at=None).count()
        return {'unread_count': count}

    @app.after_request
    def set_headers(response):
        if request.blueprint in PUBLIC_BLUEPRINTS and not current_user.is_authenticated:
            response.headers['Cache-Control'] = 'public, max-age=300'
        else:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options']        = 'SAMEORIGIN'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))


app = create_app()
