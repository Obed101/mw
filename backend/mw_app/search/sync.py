from flask import current_app
from .service import SearchService
from ..models import Product, Shop, Category
from ..extensions import db
import click

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
        "location": shop.region,  # assuming region field represents location
        "business_type": getattr(shop, 'business_type', None),
        "is_verified": getattr(shop, 'is_verified', False),
        "is_active": shop.is_active,
        "category_names": category_names,
    }

# Sync individual product
def sync_product(product):
    svc: SearchService = current_app.search
    doc = _product_to_doc(product)
    svc.add_documents('products', [doc])
    current_app.logger.info('Synced product %s to Meilisearch', product.id)

def delete_product(product_id):
    svc: SearchService = current_app.search
    svc.delete_documents('products', [product_id])
    current_app.logger.info('Deleted product %s from Meilisearch', product_id)

# Sync individual shop
def sync_shop(shop):
    svc: SearchService = current_app.search
    doc = _shop_to_doc(shop)
    svc.add_documents('shops', [doc])
    current_app.logger.info('Synced shop %s to Meilisearch', shop.id)

def delete_shop(shop_id):
    svc: SearchService = current_app.search
    svc.delete_documents('shops', [shop_id])
    current_app.logger.info('Deleted shop %s from Meilisearch', shop_id)

# Rebuild full indexes
@click.command('search-rebuild')
def rebuild_products():
    """Clear and repopulate the products index."""
    svc: SearchService = current_app.search
    svc.clear_documents('products')
    products = Product.query.all()
    docs = [_product_to_doc(p) for p in products]
    if docs:
        svc.add_documents('products', docs)
    current_app.logger.info('Rebuilt products index with %d documents', len(docs))

@click.command('search-rebuild')
def rebuild_shops():
    """Clear and repopulate the shops index."""
    svc: SearchService = current_app.search
    svc.clear_documents('shops')
    shops = Shop.query.all()
    docs = [_shop_to_doc(s) for s in shops]
    if docs:
        svc.add_documents('shops', docs)
    current_app.logger.info('Rebuilt shops index with %d documents', len(docs))
