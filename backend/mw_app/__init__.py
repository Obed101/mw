from flask import Flask
from flask_migrate import Migrate

from .extensions import db, jwt, cors

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("config.Config")
    
    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
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
