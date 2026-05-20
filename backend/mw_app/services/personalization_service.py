import math
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from ..extensions import db
from ..models.product_model import Product
from ..models.shop_model import Shop, UserFollowShop
from ..models.analytics_model import Event, SearchHistory
from ..models.user_model import User
from ..models.engagement_model import UserFavoriteProduct

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points in km."""
    if None in (lat1, lon1, lat2, lon2):
        return float('inf')
    R = 6371.0  # Earth radius in km
    try:
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2) ** 2)
        c = 2 * math.asin(math.sqrt(a))
        return R * c
    except Exception:
        return float('inf')

def parse_gps(gps_str):
    """Parse lat/lng floats from Shop.gps string 'lat,lng'."""
    if not gps_str:
        return None, None
    try:
        parts = gps_str.split(',')
        if len(parts) == 2:
            return float(parts[0].strip()), float(parts[1].strip())
    except Exception:
        pass
    return None, None


def get_trending_products(limit=12, user_lat=None, user_lng=None):
    """
    Weighted gravity-decay trending score:
    Score = (views * 1 + favorites * 5 + shares * 4 + engagements * 2 + 1) / (age_hours + 2)^1.5
    Applies 1.5x boost for hyper-local products within 25km.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)

        # Gather views count
        views_data = db.session.query(
            Event.entity_id, func.count(Event.id).label('cnt')
        ).filter(
            Event.event_type == 'product_view',
            Event.entity_type == 'product',
            Event.created_at >= since
        ).group_by(Event.entity_id).all()
        views_map = {item[0]: item[1] for item in views_data if item[0]}

        # Gather shares count
        shares_data = db.session.query(
            Event.entity_id, func.count(Event.id).label('cnt')
        ).filter(
            Event.event_type == 'product_share',
            Event.entity_type == 'product',
            Event.created_at >= since
        ).group_by(Event.entity_id).all()
        shares_map = {item[0]: item[1] for item in shares_data if item[0]}

        # Gather engagement counts (image expand, contact seller, compare, click)
        engage_types = ['product_image_expand', 'product_contact', 'product_compare', 'product_click']
        engage_data = db.session.query(
            Event.entity_id, func.count(Event.id).label('cnt')
        ).filter(
            Event.event_type.in_(engage_types),
            Event.entity_type == 'product',
            Event.created_at >= since
        ).group_by(Event.entity_id).all()
        engage_map = {item[0]: item[1] for item in engage_data if item[0]}

        # Gather favorites count
        fav_data = db.session.query(
            UserFavoriteProduct.product_id, func.count(UserFavoriteProduct.id).label('cnt')
        ).filter(
            UserFavoriteProduct.favorited_at >= since
        ).group_by(UserFavoriteProduct.product_id).all()
        fav_map = {item[0]: item[1] for item in fav_data if item[0]}

        # Query active products
        products = Product.query.join(Shop).filter(
            Product.is_active.is_(True),
            Shop.is_active.is_(True)
        ).all()

        now = datetime.now(timezone.utc)
        scored_products = []

        for p in products:
            p_id = p.id
            views = views_map.get(p_id, 0)
            shares = shares_map.get(p_id, 0)
            engages = engage_map.get(p_id, 0)
            favs = fav_map.get(p_id, 0)

            # Age in hours
            created = p.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (now - created).total_seconds() / 3600.0

            # Compute raw base score
            raw_score = float(views * 1 + favs * 5 + shares * 4 + engages * 2)

            # Gravity decay
            gravity = 1.5
            score = (raw_score + 1.0) / ((age_hours + 2.0) ** gravity)

            # Proximity boost
            if user_lat is not None and user_lng is not None and p.shop.gps:
                s_lat, s_lng = parse_gps(p.shop.gps)
                if s_lat is not None and s_lng is not None:
                    dist = haversine_distance(user_lat, user_lng, s_lat, s_lng)
                    if dist <= 25.0:
                        score *= 1.5

            scored_products.append((p, score))

        # Sort and return
        scored_products.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored_products[:limit]]

    except Exception as e:
        print(f"[Personalization] Error fetching trending products: {e}")
        # Fallback to simple newest products
        return Product.query.join(Shop).filter(
            Product.is_active.is_(True),
            Shop.is_active.is_(True)
        ).order_by(Product.created_at.desc()).limit(limit).all()


def get_fresh_listings(limit=12, user_lat=None, user_lng=None):
    """
    Freshness Discoverability Rank:
    Prioritizes newly posted items, active sellers, and view velocity, with proximity boosting.
    """
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=3)

        # Get view velocity (views in the last 24 hours)
        velocity_since = now - timedelta(hours=24)
        views_24h = db.session.query(
            Event.entity_id, func.count(Event.id).label('cnt')
        ).filter(
            Event.event_type == 'product_view',
            Event.entity_type == 'product',
            Event.created_at >= velocity_since
        ).group_by(Event.entity_id).all()
        views_map = {item[0]: item[1] for item in views_24h if item[0]}

        # Active sellers (last activity in 24h)
        active_sellers = db.session.query(User.id).filter(
            User.last_activity >= velocity_since
        ).all()
        active_seller_ids = {u[0] for u in active_sellers}

        products = Product.query.join(Shop).filter(
            Product.is_active.is_(True),
            Shop.is_active.is_(True)
        ).all()

        scored_products = []
        for p in products:
            p_id = p.id
            created = p.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            
            age_hours = (now - created).total_seconds() / 3600.0

            # Base score: heavily favor newly posted (within 72 hours)
            if age_hours <= 72:
                base_score = 100.0 - age_hours  # Higher score for newer
            else:
                base_score = max(0.0, 20.0 - (age_hours / 24.0)) # Slowly decay older ones

            # Seller activity boost (20% boost)
            if p.shop.owner_id in active_seller_ids:
                base_score += 15.0

            # Velocity boost
            views = views_map.get(p_id, 0)
            base_score += min(30.0, float(views) * 2.0)

            # Updated recently boost (within last 48h)
            updated = p.updated_at or p.created_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if (now - updated).total_seconds() / 3600.0 <= 48.0:
                base_score += 10.0

            # Proximity boost
            if user_lat is not None and user_lng is not None and p.shop.gps:
                s_lat, s_lng = parse_gps(p.shop.gps)
                if s_lat is not None and s_lng is not None:
                    dist = haversine_distance(user_lat, user_lng, s_lat, s_lng)
                    if dist <= 25.0:
                        base_score *= 1.3

            scored_products.append((p, base_score))

        scored_products.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored_products[:limit]]

    except Exception as e:
        print(f"[Personalization] Error fetching fresh listings: {e}")
        return Product.query.join(Shop).filter(
            Product.is_active.is_(True),
            Shop.is_active.is_(True)
        ).order_by(Product.created_at.desc()).limit(limit).all()


def infer_user_interests(user_id):
    """
    Score category interests based on user activity over the last 30 days.
    Scoring:
    - Favorite Product: 10 pts
    - Follow Shop (with products in category): 8 pts
    - Search Query: 5 pts
    - Product Details View: 2 pts
    Returns sorted list of Category IDs and scores: [(category_id, score), ...]
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        scores = {}

        # 1. Favorites
        favs = UserFavoriteProduct.query.filter(
            UserFavoriteProduct.user_id == user_id,
            UserFavoriteProduct.favorited_at >= since
        ).all()
        for f in favs:
            if f.product and f.product.category_id:
                scores[f.product.category_id] = scores.get(f.product.category_id, 0) + 10

        # 2. Followed Shops
        follows = UserFollowShop.query.filter(
            UserFollowShop.user_id == user_id,
            UserFollowShop.followed_at >= since
        ).all()
        for f in follows:
            # Add weight to categories of products in this shop
            shop_products = Product.query.filter_by(shop_id=f.shop_id, is_active=True).all()
            for sp in shop_products:
                if sp.category_id:
                    scores[sp.category_id] = scores.get(sp.category_id, 0) + 1

        # 3. Product Views & Clicks
        views = Event.query.filter(
            Event.user_id == user_id,
            Event.event_type.in_(['product_view', 'product_click']),
            Event.entity_type == 'product',
            Event.created_at >= since
        ).all()
        for v in views:
            p = Product.query.get(v.entity_id)
            if p and p.category_id:
                scores[p.category_id] = scores.get(p.category_id, 0) + 2

        # 4. Search Queries
        searches = db.session.query(SearchHistory).filter(
            SearchHistory.user_id == user_id,
            SearchHistory.created_at >= since
        ).all()
        for s in searches:
            # Check if search keyword matches any product category name
            from ..models.category_model import Category
            matched_cats = Category.query.filter(
                Category.name.ilike(f"%{s.query}%"),
                Category.is_active.is_(True)
            ).all()
            for mc in matched_cats:
                scores[mc.id] = scores.get(mc.id, 0) + 5

        # Sort category interests
        sorted_interests = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_interests

    except Exception as e:
        print(f"[Personalization] Error inferring user interests: {e}")
        return []


def get_personalized_products(user, limit=12):
    """
    Returns personalized product recommendations for a user.
    Integrates inferred category interests and followed shops, excluding already favorited products.
    """
    try:
        user_id = getattr(user, 'id', None)
        if not user_id or getattr(user, 'is_anonymous', True):
            # Guest fallback
            lat, lng = None, None
            try:
                from flask import session
                lat = session.get('user_lat')
                lng = session.get('user_lng')
            except Exception:
                pass
            return get_trending_products(limit=limit, user_lat=lat, user_lng=lng)

        # Get user's favorites to exclude them
        fav_products = UserFavoriteProduct.query.filter_by(user_id=user_id).all()
        exclude_ids = {f.product_id for f in fav_products}

        # Query candidates from followed shops
        followed_shops = UserFollowShop.query.filter_by(user_id=user_id).all()
        shop_ids = {f.shop_id for f in followed_shops}

        followed_shop_products = []
        if shop_ids:
            followed_shop_products = Product.query.join(Shop).filter(
                Product.shop_id.in_(shop_ids),
                Product.is_active.is_(True),
                Shop.is_active.is_(True),
                ~Product.id.in_(exclude_ids) if exclude_ids else True
            ).order_by(Product.created_at.desc()).limit(limit // 2).all()

        # Query candidates from top interest categories
        interests = infer_user_interests(user_id)
        interest_products = []
        if interests:
            top_category_ids = [item[0] for item in interests[:3]]
            interest_products = Product.query.join(Shop).filter(
                Product.category_id.in_(top_category_ids),
                Product.is_active.is_(True),
                Shop.is_active.is_(True),
                ~Product.id.in_(exclude_ids) if exclude_ids else True
            ).order_by(Product.created_at.desc()).limit(limit).all()

        # Combine, ensure uniqueness and size limit
        seen_ids = set()
        combined = []
        for p in followed_shop_products + interest_products:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                combined.append(p)

        # Fallback filler using trending/fresh listings
        if len(combined) < limit:
            lat = getattr(user, 'latitude', None)
            lng = getattr(user, 'longitude', None)
            trending = get_trending_products(limit=limit, user_lat=lat, user_lng=lng)
            for p in trending:
                if p.id not in seen_ids and p.id not in exclude_ids:
                    seen_ids.add(p.id)
                    combined.append(p)
                    if len(combined) >= limit:
                        break

        return combined[:limit]

    except Exception as e:
        print(f"[Personalization] Error fetching personalized products: {e}")
        return Product.query.join(Shop).filter(
            Product.is_active.is_(True),
            Shop.is_active.is_(True)
        ).limit(limit).all()


def get_recommended_products_for_user(user, limit=12):
    """
    Wrapper interface that extracts user lat/lng location context and returns personalized sets.
    """
    return get_personalized_products(user, limit=limit)
