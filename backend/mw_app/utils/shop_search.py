from sqlalchemy import case, func, or_

from ..models import Shop


def build_shop_search_filter(search_term):
    term = str(search_term or "").strip()
    if not term:
        return None

    pattern = f"%{term}%"
    return or_(
        Shop.name.ilike(pattern),
        Shop.google_category.ilike(pattern),
        Shop.description.ilike(pattern),
        Shop.address.ilike(pattern),
        Shop.region.ilike(pattern),
        Shop.district.ilike(pattern),
        Shop.town.ilike(pattern),
    )


def build_shop_search_rank(search_term):
    term = str(search_term or "").strip().lower()
    if not term:
        return None

    pattern = f"%{term}%"
    return case(
        (func.lower(func.coalesce(Shop.name, "")).like(pattern), 0),
        (func.lower(func.coalesce(Shop.google_category, "")).like(pattern), 1),
        (func.lower(func.coalesce(Shop.description, "")).like(pattern), 2),
        else_=3,
    )


def order_query_by_ids(query, column, ordered_ids):
    ids = [item for item in ordered_ids if item is not None]
    if not ids:
        return query

    ordering = case(
        *[(item_id, idx) for idx, item_id in enumerate(ids)],
        value=column,
        else_=len(ids),
    )
    return query.order_by(ordering)
