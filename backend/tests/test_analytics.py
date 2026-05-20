import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mw_app import create_app
from mw_app.extensions import db
from mw_app.models import User, Shop, Product, Category
from mw_app.models.analytics_model import Event, SearchHistory, SavedSearch
from mw_app.services.analytics_service import track_event, save_search_query
from mw_app.services.personalization_service import (
    get_trending_products,
    get_fresh_listings,
    get_personalized_products,
    infer_user_interests
)

def run_tests():
    app = create_app()
    with app.app_context():
        print("Starting Analytics & Personalization Engine tests...")
        
        # 1. Test event tracking helper
        # Find a test user
        user = User.query.first()
        if not user:
            print("No users found to test with, skipping user-specific checks.")
            return

        # Count events before
        initial_count = Event.query.count()
        
        # Track a sample event
        track_event(
            event_type='product_view',
            user=user,
            entity_type='product',
            entity_id=1,
            payload={'source': 'test'}
        )
        
        # Check that event is tracked
        new_count = Event.query.count()
        assert new_count >= initial_count + 1, f"Expected at least {initial_count + 1} events, got {new_count}"
        print("SUCCESS: track_event service successfully tracked event.")

        # 2. Test search query logging
        initial_search_count = db.session.query(SearchHistory).count()
        save_search_query("test query string", user=user, success=True)
        new_search_count = db.session.query(SearchHistory).count()
        assert new_search_count == initial_search_count + 1, "Expected search history count to increment"
        print("SUCCESS: save_search_query successfully saved search history.")

        # 3. Test personalization algorithm functions
        print("Testing personalization functions...")
        trending = get_trending_products(limit=5)
        assert isinstance(trending, list), "get_trending_products should return a list"
        print(f"SUCCESS: get_trending_products returned {len(trending)} items.")

        fresh = get_fresh_listings(limit=5)
        assert isinstance(fresh, list), "get_fresh_listings should return a list"
        print(f"SUCCESS: get_fresh_listings returned {len(fresh)} items.")

        interests = infer_user_interests(user.id)
        assert isinstance(interests, list), "infer_user_interests should return a list"
        print(f"SUCCESS: infer_user_interests returned category scores: {interests}")

        recs = get_personalized_products(user, limit=5)
        assert isinstance(recs, list), "get_personalized_products should return a list"
        print(f"SUCCESS: get_personalized_products returned {len(recs)} items.")
        # 4. Test admin analytics queries
        print("Testing admin analytics dashboard queries...")
        from sqlalchemy import func, case
        from datetime import datetime, timezone, timedelta
        since_30d = datetime.now(timezone.utc) - timedelta(days=30)
        
        top_searches = db.session.query(
            Event.payload['query'].astext.label('query_text'),
            func.count(Event.id).label('count'),
            func.sum(case((Event.event_type == 'search', 1), else_=0)).label('success_count'),
            func.sum(case((Event.event_type == 'failed_search', 1), else_=0)).label('failed_count')
        ).filter(
            Event.event_type.in_(['search', 'failed_search']),
            Event.created_at >= since_30d
        ).group_by(Event.payload['query'].astext).order_by(func.count(Event.id).desc()).limit(10).all()
        print(f"SUCCESS: top searches query executed and returned {len(top_searches)} items.")

        failed_searches = db.session.query(
            Event.payload['query'].astext.label('query_text'),
            func.count(Event.id).label('count'),
            func.max(Event.created_at).label('last_searched')
        ).filter(
            Event.event_type == 'failed_search',
            Event.created_at >= since_30d
        ).group_by(Event.payload['query'].astext).order_by(func.count(Event.id).desc()).limit(10).all()
        print(f"SUCCESS: failed searches query executed and returned {len(failed_searches)} items.")
        
        # Test nearest sort queries
        from mw_app.utils.location import haversine_distance_expr
        from sqlalchemy import nullslast
        
        dist_expr = haversine_distance_expr(5.6037, -0.1870)
        
        nearest_shops = db.session.query(Shop).filter(Shop.is_active.is_(True)).order_by(
            nullslast(dist_expr.asc()), Shop.name.asc()
        ).limit(5).all()
        print(f"SUCCESS: nearest shops query executed and returned {len(nearest_shops)} items.")

        nearest_products = db.session.query(Product).join(Shop).filter(
            Shop.is_active.is_(True), Product.is_active.is_(True)
        ).order_by(
            nullslast(dist_expr.asc()), Product.name.asc()
        ).limit(5).all()
        print(f"SUCCESS: nearest products query executed and returned {len(nearest_products)} items.")

        print("All Analytics & Personalization Engine tests PASSED successfully!")

if __name__ == "__main__":
    run_tests()
