from flask import Flask
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from .extensions import db, jwt, cors, search

def create_app():
    import os
    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
    app = Flask(__name__, 
                instance_relative_config=True,
                template_folder=template_dir)
    app.config.from_object("config.Config")
    
    # Configure CSRF protection
    csrf = CSRFProtect(app)
    
    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)

    # Settings for flask Msearch
    if 'sqlalchemy' not in app.extensions:
        app.extensions['sqlalchemy'] = {}
    setattr(app.extensions['sqlalchemy'], 'db', db)
    search.init_app(app)


    cors.init_app(app, resources={
        r"/api/*": {
            "origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    # Initialize Flask-Migrate
    migrate = Migrate()
    migrate.init_app(app, db)

    # Register blueprints with proper URL prefixes
    from .routes import admin_bp, seller_bp, buyer_bp, auth_bp
    from .routes.template_routes import main_bp, admin_bp as admin_template_bp, seller_bp as seller_template_bp, buyer_bp as buyer_template_bp, auth_bp as auth_template_bp
    
    # Template routes (for HTMX)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_template_bp)
    app.register_blueprint(seller_template_bp)
    app.register_blueprint(buyer_template_bp)
    app.register_blueprint(auth_template_bp)
    
    # API routes
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(seller_bp, url_prefix='/api/seller')
    app.register_blueprint(buyer_bp, url_prefix='/api/buyer')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    # Add CORS headers to all responses
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        return response

    return app
