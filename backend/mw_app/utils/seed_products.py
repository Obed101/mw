from .. import db
from ..models import Product, Shop, Category
from datetime import datetime, timezone
import random

def seed_products(products_per_shop=15):
    """Create fake products linked to shops and categories"""
    # Get all shops and categories
    shops = Shop.query.filter_by(is_active=True).all()
    categories = Category.query.filter_by(is_active=True).all()
    
    if not shops:
        print("No shops found. Please run seed_shops first.")
        return
    
    if not categories:
        print("No categories found. Please run seed_categories first.")
        return
    
    # Product templates by category
    product_templates = {
        "Electronics": [
            {"name": "Wireless Headphones", "base_price": 49.99},
            {"name": "Smartphone Case", "base_price": 19.99},
            {"name": "USB Cable", "base_price": 9.99},
            {"name": "Portable Charger", "base_price": 29.99},
            {"name": "Bluetooth Speaker", "base_price": 39.99},
        ],
        "Clothing": [
            {"name": "Cotton T-Shirt", "base_price": 19.99},
            {"name": "Denim Jeans", "base_price": 49.99},
            {"name": "Winter Jacket", "base_price": 89.99},
            {"name": "Summer Dress", "base_price": 39.99},
            {"name": "Sports Shoes", "base_price": 59.99},
        ],
        "Home & Garden": [
            {"name": "Garden Tools Set", "base_price": 29.99},
            {"name": "Kitchen Knife", "base_price": 24.99},
            {"name": "Plant Pot", "base_price": 14.99},
            {"name": "LED Light Bulb", "base_price": 8.99},
            {"name": "Storage Box", "base_price": 12.99},
        ],
        "Tools & Hardware": [
            {"name": "Hammer", "base_price": 15.99},
            {"name": "Screwdriver Set", "base_price": 19.99},
            {"name": "Measuring Tape", "base_price": 9.99},
            {"name": "Wrench Set", "base_price": 34.99},
            {"name": "Power Drill", "base_price": 79.99},
        ],
        "Food & Edibles": [
            {"name": "Organic Honey", "base_price": 12.99},
            {"name": "Coffee Beans", "base_price": 18.99},
            {"name": "Chocolate Bar", "base_price": 4.99},
            {"name": "Tea Box", "base_price": 15.99},
            {"name": "Spice Mix", "base_price": 8.99},
        ],
        "Toys & Games": [
            {"name": "Board Game", "base_price": 29.99},
            {"name": "Puzzle Set", "base_price": 19.99},
            {"name": "Action Figure", "base_price": 14.99},
            {"name": "Toy Car", "base_price": 9.99},
            {"name": "Building Blocks", "base_price": 24.99},
        ],
        "Sports & Outdoors": [
            {"name": "Yoga Mat", "base_price": 19.99},
            {"name": "Water Bottle", "base_price": 12.99},
            {"name": "Running Shorts", "base_price": 29.99},
            {"name": "Tennis Racket", "base_price": 49.99},
            {"name": "Camping Tent", "base_price": 89.99},
        ],
        "Health & Beauty": [
            {"name": "Face Cream", "base_price": 24.99},
            {"name": "Shampoo Bottle", "base_price": 12.99},
            {"name": "Toothpaste", "base_price": 6.99},
            {"name": "Soap Bar", "base_price": 4.99},
            {"name": "Lip Balm", "base_price": 3.99},
        ],
        "Automotive": [
            {"name": "Car Air Freshener", "base_price": 4.99},
            {"name": "Phone Holder", "base_price": 14.99},
            {"name": "Seat Covers", "base_price": 39.99},
            {"name": "Car Wax", "base_price": 19.99},
            {"name": "Tire Pressure Gauge", "base_price": 9.99},
        ],
        "Books & Stationery": [
            {"name": "Notebook Set", "base_price": 12.99},
            {"name": "Pen Pack", "base_price": 8.99},
            {"name": "Desk Calendar", "base_price": 14.99},
            {"name": "Highlighter Set", "base_price": 6.99},
            {"name": "Backpack", "base_price": 34.99},
        ],
        "Other": [
            {"name": "Gift Box", "base_price": 9.99},
            {"name": "Decorative Item", "base_price": 15.99},
            {"name": "Keychain", "base_price": 4.99},
            {"name": "Wall Art", "base_price": 24.99},
            {"name": "Storage Bag", "base_price": 7.99},
        ]
    }
    
    product_count = 0
    for shop in shops:
        for i in range(products_per_shop):
            # Random category
            category = random.choice(categories)
            category_name = category.name
            
            # Get template for this category
            templates = product_templates.get(category_name, product_templates["Other"])
            template = random.choice(templates)
            
            # Add some variation to price
            price_variation = random.uniform(0.8, 1.3)
            final_price = round(template["base_price"] * price_variation, 2)
            
            # Generate unique product code
            from ..models.product_model import Product
            code = Product.generate_code()
            
            product = Product(
                name=f"{template['name']} - {shop.name[:10]}",
                code=code,
                type_=random.choice(["product", "service"]),
                description=f"High-quality {template['name'].lower()} from {shop.name}. Perfect for everyday use.",
                price=final_price,
                stock=random.randint(0, 100),
                images=f"https://example.com/images/{code}.jpg",  # Placeholder image URL
                shop_id=shop.id,
                category_id=category.id,
                is_active=random.choice([True, False])  # Some products might be inactive
            )
            
            db.session.add(product)
            product_count += 1
        
        print(f"Created {products_per_shop} products for shop: {shop.name}")
    
    db.session.commit()
    print(f"Product seeding completed! Created {product_count} products across {len(shops)} shops.")

if __name__ == "__main__":
    seed_products()
