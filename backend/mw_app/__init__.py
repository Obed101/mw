from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes import admin_bp, seller_bp, buyer_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(seller_bp)
    app.register_blueprint(buyer_bp)

    return app
