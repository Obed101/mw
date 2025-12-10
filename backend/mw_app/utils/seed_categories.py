"""
Utility script to seed initial product categories into the database.
Run this after creating the Category model to populate default categories.
"""

from backend.mw_app import db
from backend.mw_app.models import Category

# Default categories that were previously in the Enum
DEFAULT_CATEGORIES = [
    {"name": "Electronics", "description": "Electronic devices and accessories"},
    {"name": "Clothing", "description": "Apparel and fashion items"},
    {"name": "Home & Garden", "description": "Home improvement and gardening supplies"},
    {"name": "Tools & Hardware", "description": "Tools and hardware equipment"},
    {"name": "Food & Edibles", "description": "Food items and consumables"},
    {"name": "Toys & Games", "description": "Toys, games, and entertainment items"},
    {"name": "Sports & Outdoors", "description": "Sports equipment and outdoor gear"},
    {"name": "Health & Beauty", "description": "Health and beauty products"},
    {"name": "Automotive", "description": "Automotive parts and accessories"},
    {"name": "Books & Stationery", "description": "Books, notebooks, and stationery"},
    {"name": "Other", "description": "Miscellaneous items"}
]

def seed_categories():
    """Seed the database with default categories if they don't exist"""
    for category_data in DEFAULT_CATEGORIES:
        # Check if category already exists
        existing_category = Category.query.filter_by(name=category_data["name"]).first()
        
        if not existing_category:
            category = Category(
                name=category_data["name"],
                description=category_data["description"],
                is_active=True
            )
            db.session.add(category)
            print(f"Added category: {category_data['name']}")
        else:
            print(f"Category already exists: {category_data['name']}")
    
    db.session.commit()
    print("Category seeding completed!")

if __name__ == "__main__":
    from backend.mw_app import create_app
    app = create_app()
    with app.app_context():
        seed_categories()

