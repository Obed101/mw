import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mw_app import create_app
from mw_app.extensions import db
from mw_app.models import User, Shop
from mw_app.routes.template_routes import _resolve_owned_shop

def run_tests():
    app = create_app()
    with app.app_context():
        print("Testing shop resolution logic...")
        
        # Find a user with at least one shop
        user = None
        for u in User.query.all():
            shops = getattr(u, 'owned_shops', None) or getattr(u, 'shop', None)
            if shops:
                user = u
                break
                
        if not user:
            print("No user with existing shop found, creating dummy shop to test.")
            user = User.query.first()
            if not user:
                print("No user in db, cannot test.")
                return
            dummy_shop = Shop(
                name="Test Shop",
                gps="5.6037,-0.1870",
                address="Test Address",
                is_active=True,
                owner_id=user.id
            )
            db.session.add(dummy_shop)
            db.session.commit()
        
        shops = getattr(user, 'owned_shops', None) or getattr(user, 'shop', None)
        if not isinstance(shops, list):
            shops = [shops]
            
        existing_shop = shops[0]
        print(f"User: {user.email}, Existing Shop ID: {existing_shop.id}")
        
        # Test 1: Allow default is True, shop_id is None -> Should return the existing shop
        resolved = _resolve_owned_shop(user, None, allow_default=True)
        assert resolved is not None, "Expected shop to be resolved"
        assert resolved.id == existing_shop.id, f"Expected shop ID {existing_shop.id}, got {resolved.id}"
        print("SUCCESS: _resolve_owned_shop with allow_default=True returned existing shop.")
        
        # Test 2: Allow default is False, shop_id is None -> Should return None
        resolved = _resolve_owned_shop(user, None, allow_default=False)
        assert resolved is None, f"Expected resolved to be None, got {resolved}"
        print("SUCCESS: _resolve_owned_shop with allow_default=False returned None.")
        
        # Test 3: Allow default is False, shop_id is valid -> Should return the shop
        resolved = _resolve_owned_shop(user, existing_shop.id, allow_default=False)
        assert resolved is not None, "Expected shop to be resolved with valid ID"
        assert resolved.id == existing_shop.id, f"Expected shop ID {existing_shop.id}, got {resolved.id}"
        print("SUCCESS: _resolve_owned_shop with valid ID and allow_default=False returned the shop.")
        
        print("All shop resolution tests PASSED!")

if __name__ == "__main__":
    run_tests()
