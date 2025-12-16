from .. import db
from ..models import Shop, User, VerificationStatus
from datetime import datetime, timezone
import random

def seed_shops():
    """Create fake shops linked to seller users"""
    # Get all seller users
    sellers = User.query.filter_by(role='seller').all()
    
    if not sellers:
        print("No sellers found. Please run seed_users first.")
        return
    
    shops_data = [
        {"name": "Craft Corner", "description": "Handmade crafts and artisanal goods", "region": "Central", "district": "Downtown", "town": "Craftville"},
        {"name": "Tech Haven", "description": "Latest electronics and gadgets", "region": "North", "district": "Tech Park", "town": "Electronica"},
        {"name": "Fashion Forward", "description": "Trendy clothing and accessories", "region": "East", "district": "Fashion District", "town": "Style City"},
        {"name": "Green Grocer", "description": "Fresh produce and organic foods", "region": "South", "district": "Market Quarter", "town": "Farmington"},
        {"name": "Handmade Boutique", "description": "Unique handmade items and gifts", "region": "West", "district": "Artisan Alley", "town": "Craftsbury"},
        {"name": "Import Emporium", "description": "Exotic imports from around the world", "region": "Central", "district": "International Plaza", "town": "Global Town"},
        {"name": "Jewelry Box", "description": "Fine jewelry and accessories", "region": "North", "district": "Luxury Lane", "town": "Gem City"},
        {"name": "Sports Central", "description": "Sports equipment and athletic gear", "region": "East", "district": "Athletic Zone", "town": "Sportstown"},
    ]
    
    # Create shops for each seller (cycle through shop data if needed)
    for i, seller in enumerate(sellers):
        shop_data = shops_data[i % len(shops_data)]
        
        # Check if seller already has a shop
        existing_shop = Shop.query.filter_by(owner_id=seller.id).first()
        if not existing_shop:
            shop = Shop(
                name=f"{shop_data['name']} #{i+1}" if len(sellers) > len(shops_data) else shop_data['name'],
                description=shop_data['description'],
                address=f"{random.randint(100, 999)} {shop_data['district']} Street",
                region=shop_data['region'],
                district=shop_data['district'],
                town=shop_data['town'],
                phone=f"+123456789{random.randint(10, 99)}",
                email=f"contact{seller.username}@shop.com",
                owner_id=seller.id,
                verification_status=random.choice([
                    VerificationStatus.VERIFIED,
                    VerificationStatus.PENDING,
                    VerificationStatus.UNDER_REVIEW
                ]),
                phone_verified=random.choice([True, False]),
                email_verified=random.choice([True, False]),
                promoted=random.choice([True, False])
            )
            
            # Set verification timestamps if verified
            if shop.verification_status == VerificationStatus.VERIFIED:
                shop.verified_at = datetime.now(timezone.utc)
                shop.phone_verified = True
                shop.email_verified = True
                # Assign a random admin as verifier
                admin = User.query.filter_by(role='admin').first()
                if admin:
                    shop.verified_by = admin.id
            
            db.session.add(shop)
            print(f"Created shop: {shop.name} for seller: {seller.username}")
        else:
            print(f"Shop already exists for seller: {seller.username}")
    
    db.session.commit()
    print(f"Shop seeding completed! Created shops for {len(sellers)} sellers.")

if __name__ == "__main__":
    seed_shops()
