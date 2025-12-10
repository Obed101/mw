import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "devkey")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or "postgresql://postgres:admin123@localhost:5432/market_window"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
