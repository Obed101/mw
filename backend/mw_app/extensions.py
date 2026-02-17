from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_msearch import Search
from flask_login import LoginManager
from flask_session import Session
from authlib.integrations.flask_client import OAuth

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
search = Search()
login_manager = LoginManager()
session = Session()
oauth = OAuth()

# Token blacklist set (in production, use Redis)
token_blacklist = set()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    """Check if JWT token is revoked/blacklisted"""
    jti = jwt_payload['jti']
    return jti in token_blacklist

# Flask-Login user loader
@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    from .models.user_model import User
    return User.query.get(int(user_id))
