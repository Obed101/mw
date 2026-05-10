"""
Location utilities for Market Window.

Provides:
  - get_user_location(user)           → (lat, lng) | (None, None)
  - haversine_distance_expr(lat, lng) → SQLAlchemy column expression (km)

The Haversine expression works against Shop.gps which is stored as "lat,lng"
text.  We parse both parts with SQLAlchemy string functions so no schema
change is needed on Shop.
"""
from flask import session
from sqlalchemy import func, literal, case, cast, Float


# Radius below which a shop/product is considered "Near you"
NEAR_YOU_KM = 50


def get_user_location(user=None):
    """
    Return (latitude, longitude) as floats for the current request.

    Priority:
      1. Authenticated user's stored coordinates (if valid)
      2. Anonymous session coordinates
      3. (None, None) — no location available
    """
    if user and getattr(user, 'is_authenticated', False):
        lat = getattr(user, 'latitude', None)
        lng = getattr(user, 'longitude', None)
        if lat is not None and lng is not None:
            return float(lat), float(lng)

    # Fallback: session-stored coordinates (anonymous or freshly captured)
    try:
        lat = session.get('user_lat')
        lng = session.get('user_lng')
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    except RuntimeError:
        # Outside request context — just skip
        pass

    return None, None


def haversine_distance_expr(user_lat, user_lng):
    """
    Return a SQLAlchemy column expression that evaluates the Haversine distance
    (in km) between a Shop's GPS position and the given user coordinates.

    Shop.gps is stored as the text string "lat,lng".  We extract the two parts
    using INSTR / SUBSTR so no extra columns are needed on Shop.

    Usage:
        from ..models import Shop
        dist = haversine_distance_expr(user_lat, user_lng)
        query = query.add_columns(dist.label('distance_km'))
        query = query.order_by(nullslast(dist.asc()))

    Shops without a valid gps value produce NULL and sort to the end when
    ORDER BY ... NULLS LAST is used.
    """
    # Lazy import to avoid circular deps at module load
    from ..models.shop_model import Shop

    R = 6371.0  # Earth radius in km

    # Separator position inside Shop.gps  (e.g.  "5.6037,-0.1870" → pos 7)
    sep_pos = func.instr(Shop.gps, ',')

    # Extract latitude text and cast to float
    shop_lat_text = func.substr(Shop.gps, 1, sep_pos - 1)
    shop_lng_text = func.substr(Shop.gps, sep_pos + 1)

    shop_lat = cast(shop_lat_text, Float)
    shop_lng = cast(shop_lng_text, Float)

    # Convert degrees → radians
    r_user_lat = func.radians(literal(user_lat))
    r_user_lng = func.radians(literal(user_lng))
    r_shop_lat = func.radians(shop_lat)
    r_shop_lng = func.radians(shop_lng)

    dlat = r_shop_lat - r_user_lat
    dlng = r_shop_lng - r_user_lng

    # a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlng/2)
    a = (
        func.pow(func.sin(dlat / 2), 2)
        + func.cos(r_user_lat) * func.cos(r_shop_lat) * func.pow(func.sin(dlng / 2), 2)
    )

    # c = 2·asin(√a)
    c = 2 * func.asin(func.sqrt(a))

    # Guard: only compute when gps contains a comma (i.e. is a valid "lat,lng" string)
    distance = case(
        (sep_pos > 0, literal(R) * c),
        else_=None
    )

    return distance
