from ..extensions import db
from ..models import Subscription, User, Shop, Product, SUBSCRIPTION_TYPE_USER, SUBSCRIPTION_TYPE_SHOP, SUBSCRIPTION_TYPE_PRODUCT,USER_ROLE_ADMIN, USER_ROLE_BUYER, USER_ROLE_SELLER
from datetime import datetime, timezone, timedelta
import random

def seed_subscriptions():
    """Create premium subscriptions for users, shops, and products"""
    # Get all entities
    users = User.query.filter(User.role.in_([USER_ROLE_BUYER, USER_ROLE_SELLER])).all()
    shops = Shop.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).all()
    
    # Get an admin for created_by field
    admin = User.query.filter_by(role=USER_ROLE_ADMIN).first()
    admin_id = admin.id if admin else None
    
    subscription_count = 0
    
    # Create premium subscriptions for some users (30% of buyers/sellers)
    premium_users = random.sample(users, max(1, len(users) // 3))
    for user in premium_users:
        if not user.premium:
            user.premium = True
        
        # Create subscription record
        end_date = datetime.now(timezone.utc) + timedelta(days=random.randint(30, 365))
        subscription = Subscription(
            subscription_type=SUBSCRIPTION_TYPE_USER,
            target_id=user.id,
            start_date=datetime.now(timezone.utc),
            end_date=end_date,
            created_by=admin_id
        )
        db.session.add(subscription)
        subscription_count += 1
        print(f"Created premium subscription for user: {user.username}")
    
    # Create premium subscriptions for some shops (40% of shops)
    premium_shops = random.sample(shops, max(1, len(shops) * 2 // 5))
    for shop in premium_shops:
        end_date = datetime.now(timezone.utc) + timedelta(days=random.randint(60, 365))
        subscription = Subscription(
            subscription_type=SUBSCRIPTION_TYPE_SHOP,
            target_id=shop.id,
            start_date=datetime.now(timezone.utc),
            end_date=end_date,
            created_by=admin_id
        )
        db.session.add(subscription)
        subscription_count += 1
        print(f"Created premium subscription for shop: {shop.name}")
    
    # Create premium subscriptions for some products (20% of products)
    premium_products = random.sample(products, max(1, len(products) // 5))
    for product in premium_products:
        end_date = datetime.now(timezone.utc) + timedelta(days=random.randint(15, 180))
        subscription = Subscription(
            subscription_type=SUBSCRIPTION_TYPE_PRODUCT,
            target_id=product.id,
            start_date=datetime.now(timezone.utc),
            end_date=end_date,
            created_by=admin_id
        )
        db.session.add(subscription)
        subscription_count += 1
        print(f"Created premium subscription for product: {product.name}")
    
    # Also create some expired subscriptions for testing
    expired_count = random.randint(2, 5)
    for i in range(expired_count):
        target_type = random.choice([SUBSCRIPTION_TYPE_USER, SUBSCRIPTION_TYPE_SHOP, SUBSCRIPTION_TYPE_PRODUCT])
        
        if target_type == SUBSCRIPTION_TYPE_USER and users:
            target_id = random.choice(users).id
        elif target_type == SUBSCRIPTION_TYPE_SHOP and shops:
            target_id = random.choice(shops).id
        elif target_type == SUBSCRIPTION_TYPE_PRODUCT and products:
            target_id = random.choice(products).id
        else:
            continue
        
        # Create expired subscription
        start_date = datetime.now(timezone.utc) - timedelta(days=random.randint(60, 120))
        end_date = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 30))
        
        subscription = Subscription(
            subscription_type=target_type,
            target_id=target_id,
            start_date=start_date,
            end_date=end_date,
            is_active=False,  # Expired subscriptions are inactive
            created_by=admin_id
        )
        db.session.add(subscription)
        subscription_count += 1
        print(f"Created expired subscription for {target_type} ID: {target_id}")
    
    db.session.commit()
    print(f"Subscription seeding completed! Created {subscription_count} subscriptions.")

if __name__ == "__main__":
    seed_subscriptions()
