"""
Print all currently-seeded rows for all models.

Usage:
python backend/tests/test_seeds.py

Optional (reseed before printing):
$env:RUN_SEEDERS="1"; python backend/tests/test_seeds.py
"""

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mw_app import create_app
from mw_app.models import (
    AuthToken,
    Category,
    Product,
    Shop,
    StockUpdate,
    Subscription,
    User,
    UserBrowsingHistory,
    UserFollowShop,
    VerificationOTP,
)
from mw_app.utils.seed_all import seed_all


MODEL_CLASSES = [
    User,
    AuthToken,
    UserBrowsingHistory,
    Shop,
    UserFollowShop,
    VerificationOTP,
    Category,
    Product,
    StockUpdate,
    Subscription,
]


def _serialize_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _instance_to_dict(instance):
    return {
        column.key: _serialize_value(getattr(instance, column.key))
        for column in instance.__table__.columns
    }


def _print_model_rows(model_class):
    query = model_class.query
    if hasattr(model_class, "id"):
        query = query.order_by(model_class.id.asc())

    rows = query.all()
    print(f"\n=== {model_class.__name__} ({len(rows)}) ===")

    if not rows:
        print("  (none)")
        return

    for idx, row in enumerate(rows, start=1):
        payload = _instance_to_dict(row)
        print(f"{idx}. {json.dumps(payload, default=str, sort_keys=True)}")


def main():
    app = create_app()

    with app.app_context():
        if os.getenv("RUN_SEEDERS") == "1":
            print("RUN_SEEDERS=1 detected. Running seeders first...")
            seed_all()

        print("\n=== Current Seed Snapshot ===")
        for model_class in MODEL_CLASSES:
            try:
                _print_model_rows(model_class)
            except Exception as exc:
                print(f"\n=== {model_class.__name__} (query failed) ===")
                print(f"Error: {exc}")


if __name__ == "__main__":
    main()
