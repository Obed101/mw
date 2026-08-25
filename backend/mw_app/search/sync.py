from flask import current_app
from .service import SearchService
from ..models import Product, Shop, Category
from ..extensions import db


def _get_value(obj, attr, default=None):
    """Get an attribute value, calling it if it's a callable."""
    v = getattr(obj, attr, default)
    return v() if callable(v) else v


# Helper to transform product to document
def _product_to_doc(product):
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": product.price,
        "shop_id": product.shop_id,
        "shop_name": product.shop.name if product.shop else None,
        "category_id": product.category_id,
        "category_name": product.category.name if product.category else None,
        "is_active": product.is_active,
        "item_type": getattr(product, 'type_', None),
        "is_hidden": not product.is_active,
    }

# Helper to transform shop to document, including aggregated category names
def _shop_to_doc(shop):
    # collect distinct active product categories for this shop
    category_names = [c.name for c in db.session.query(Category.name).join(Product).filter(
        Product.shop_id == shop.id,
        Product.is_active.is_(True)
    ).distinct()]
    return {
        "id": shop.id,
        "name": shop.name,
        "description": shop.description,
        "google_category": shop.google_category,
        "location": shop.region,  # assuming region field represents location
        "town": shop.town,
        "business_type": _get_value(shop, 'business_type'),
        "is_verified": _get_value(shop, 'is_verified'),
        "is_active": shop.is_active,
        "category_names": category_names,
    }

# Sync individual product
def sync_product(product):
    svc: SearchService = current_app.extensions['search_service']
    doc = _product_to_doc(product)
    svc.add_documents('products', [doc])
    current_app.logger.info('Synced product %s to Meilisearch', product.id)

def delete_product(product_id):
    svc: SearchService = current_app.extensions['search_service']
    svc.delete_documents('products', [product_id])
    current_app.logger.info('Deleted product %s from Meilisearch', product_id)

# Sync individual shop
def sync_shop(shop):
    svc: SearchService = current_app.extensions['search_service']
    doc = _shop_to_doc(shop)
    svc.add_documents('shops', [doc])
    current_app.logger.info('Synced shop %s to Meilisearch', shop.id)

def delete_shop(shop_id):
    svc: SearchService = current_app.extensions['search_service']
    svc.delete_documents('shops', [shop_id])
    current_app.logger.info('Deleted shop %s from Meilisearch', shop_id)

# Sync individual category
def sync_category(category):
    svc: SearchService = current_app.extensions['search_service']
    doc = _category_to_doc(category)
    svc.add_documents('categories', [doc])
    current_app.logger.info('Synced category %s to Meilisearch', category.id)

def delete_category(category_id):
    svc: SearchService = current_app.extensions['search_service']
    svc.delete_documents('categories', [category_id])
    current_app.logger.info('Deleted category %s from Meilisearch', category_id)

def _category_to_doc(category):
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
        "is_active": category.is_active,
        "level": category.level,
        "parent_id": category.parent_id,
    }

# Rebuild full indexes
def rebuild_products():
    """Clear and repopulate the products index."""
    svc: SearchService = current_app.extensions['search_service']
    svc.clear_documents('products')
    products = Product.query.all()
    docs = [_product_to_doc(p) for p in products]
    if docs:
        svc.add_documents('products', docs)
    current_app.logger.info('Rebuilt products index with %d documents', len(docs))

def rebuild_shops():
    """Clear and repopulate the shops index."""
    svc: SearchService = current_app.extensions['search_service']
    svc.clear_documents('shops')
    shops = Shop.query.all()
    docs = [_shop_to_doc(s) for s in shops]
    if docs:
        svc.add_documents('shops', docs)
    current_app.logger.info('Rebuilt shops index with %d documents', len(docs))

def rebuild_categories():
    """Clear and repopulate the categories index."""
    svc: SearchService = current_app.extensions['search_service']
    svc.clear_documents('categories')
    categories = Category.query.all()
    docs = [_category_to_doc(c) for c in categories]
    if docs:
        svc.add_documents('categories', docs)
    current_app.logger.info('Rebuilt categories index with %d documents', len(docs))

# ---------------------------------------------------------------------
# SQLAlchemy event listeners for auto-sync
# ---------------------------------------------------------------------

def _register_sync_listeners():
    """Register SQLAlchemy event listeners to keep Meilisearch in sync."""
    from sqlalchemy import event

    @event.listens_for(Product, 'after_insert')
    def _on_product_insert(mapper, connection, target):
        try:
            sync_product(target)
        except Exception:
            current_app.logger.exception('Failed to sync product %s to Meilisearch', target.id)

    @event.listens_for(Product, 'after_update')
    def _on_product_update(mapper, connection, target):
        try:
            sync_product(target)
        except Exception:
            current_app.logger.exception('Failed to sync product %s to Meilisearch', target.id)

    @event.listens_for(Product, 'after_delete')
    def _on_product_delete(mapper, connection, target):
        try:
            delete_product(target.id)
        except Exception:
            current_app.logger.exception('Failed to delete product %s from Meilisearch', target.id)

    @event.listens_for(Shop, 'after_insert')
    def _on_shop_insert(mapper, connection, target):
        try:
            sync_shop(target)
        except Exception:
            current_app.logger.exception('Failed to sync shop %s to Meilisearch', target.id)

    @event.listens_for(Shop, 'after_update')
    def _on_shop_update(mapper, connection, target):
        try:
            sync_shop(target)
        except Exception:
            current_app.logger.exception('Failed to sync shop %s to Meilisearch', target.id)

    @event.listens_for(Shop, 'after_delete')
    def _on_shop_delete(mapper, connection, target):
        try:
            delete_shop(target.id)
        except Exception:
            current_app.logger.exception('Failed to delete shop %s from Meilisearch', target.id)

    @event.listens_for(Category, 'after_insert')
    def _on_category_insert(mapper, connection, target):
        try:
            sync_category(target)
        except Exception:
            current_app.logger.exception('Failed to sync category %s to Meilisearch', target.id)

    @event.listens_for(Category, 'after_update')
    def _on_category_update(mapper, connection, target):
        try:
            sync_category(target)
        except Exception:
            current_app.logger.exception('Failed to sync category %s to Meilisearch', target.id)

    @event.listens_for(Category, 'after_delete')
    def _on_category_delete(mapper, connection, target):
        try:
            delete_category(target.id)
        except Exception:
            current_app.logger.exception('Failed to delete category %s from Meilisearch', target.id)
