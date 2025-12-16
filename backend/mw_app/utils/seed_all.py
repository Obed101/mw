"""
Master seeding script that runs all seed scripts in dependency order.
Usage: from backend.mw_app.utils.seed_all import seed_all; seed_all()
"""

from . import seed_users, seed_categories, seed_shops, seed_products, seed_subscriptions

def seed_all():
    """Run all seeding scripts in the correct dependency order"""
    print("Starting complete database seeding...")
    
    try:
        # Step 1: Seed categories (no dependencies)
        print("\n=== Seeding Categories ===")
        seed_categories.seed_categories()
        
        # Step 2: Seed users (no dependencies)
        print("\n=== Seeding Users ===")
        seed_users.seed_users(count=20)
        
        # Step 3: Seed shops (depends on users)
        print("\n=== Seeding Shops ===")
        seed_shops.seed_shops()
        
        # Step 4: Seed products (depends on shops and categories)
        print("\n=== Seeding Products ===")
        seed_products.seed_products(products_per_shop=15)
        
        # Step 5: Seed subscriptions (depends on users, shops, products)
        print("\n=== Seeding Subscriptions ===")
        seed_subscriptions.seed_subscriptions()
        
        print("\n=== Database Seeding Complete! ===")
        print("All seed scripts executed successfully.\n")
        
    except Exception as e:
        print(f"\n=== Seeding Failed ===")
        print(f"Error during seeding: \n{str(e)}")
        raise

if __name__ == "__main__":
    seed_all()
