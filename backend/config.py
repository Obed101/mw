import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "devkey")
    
    # Session configuration
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'market_window:'
    
    # Database configuration
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = (
        database_url
        or "sqlite:///" + os.path.join(os.path.abspath(os.path.dirname(__file__)), "market_window.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Force PostgreSQL to use UTC timezone for all sessions
    # This ensures consistent datetime handling regardless of server timezone
    if database_url and "postgresql" in database_url:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {
                "options": "-c timezone=UTC"
            }
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}
    
    # Google OAuth configuration
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    OAUTHLIB_INSECURE_TRANSPORT = os.getenv("OAUTHLIB_INSECURE_TRANSPORT", "1")  # For development
    
    # Mail configuration
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 465
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True

    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    MAIL_DEFAULT_SENDER = (
        "Market Window",
        os.environ.get("MAIL_USERNAME")
    )

    # Arkesel SMS Configuration
    ARKESEL_API_KEY = os.getenv("ARKESEL_API_KEY")
    ARKESEL_SENDER_ID = os.getenv("ARKESEL_SENDER_ID", "Markt Wndow")

