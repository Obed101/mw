import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "devkey")

    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = (
        database_url
        or "postgresql://postgres:1212@localhost:5432/market_window"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
