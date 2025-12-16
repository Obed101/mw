from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_msearch import Search

# Initialize extensions
db = SQLAlchemy()
jwt = JWTManager()
cors = CORS()
search = Search()

# Token blacklist set (in production, use Redis)
token_blacklist = set()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    """Check if JWT token is revoked/blacklisted"""
    jti = jwt_payload['jti']
    return jti in token_blacklist
