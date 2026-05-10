from mw_app import create_app
from mw_app.extensions import db
from mw_app.models import Category, Product, Shop
import meilisearch
import os

def sync():
    app = create_app()
    with app.app_context():
        ms_url = app.config.get('MEILISEARCH_URL', 'http://127.0.0.1:7700')
        ms_key = app.config.get('MEILISEARCH_KEY', 'masterKey')
        client = meilisearch.Client(ms_url, ms_key)

        print(f"Connecting to Meilisearch at {ms_url}...")

        print("Syncing Categories...")
        categories = Category.query.all()
        cat_data = [c.to_dict() for c in categories]
        if cat_data:
            client.index('categories').add_documents(cat_data, primary_key='id')
            client.index('categories').update_filterable_attributes(['is_active', 'level', 'name'])
            print(f"Pushed {len(cat_data)} categories.")

        print("Syncing Products...")
        products = Product.query.all()
        prod_data = []
        for p in products:
            prod_data.append({
                'id': p.id,
                'name': p.name,
                'description': p.description,
                'price': p.price,
                'shop_name': p.shop.name if p.shop else 'Unknown',
                'category_name': p.category.name if p.category else 'Uncategorized',
                'is_active': p.is_active
            })
        if prod_data:
            client.index('products').add_documents(prod_data, primary_key='id')
            client.index('products').update_filterable_attributes(['is_active', 'shop_name', 'category_name'])
            print(f"Pushed {len(prod_data)} products.")
        
        print("\nSync complete! Meilisearch is now ready to serve autocomplete suggestions.")

if __name__ == "__main__":
    sync()
