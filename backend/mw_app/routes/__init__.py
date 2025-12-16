# Initialize blueprint package
from .admin_routes import admin_bp
from .seller_routes import seller_bp
from .buyer_routes import buyer_bp
from .auth_routes import auth_bp

__all__ = ['admin_bp', 'seller_bp', 'buyer_bp', 'auth_bp']
