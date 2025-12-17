from ..extensions import db
from ..models import User, USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER, USER_STATUS_ACTIVE
from datetime import datetime, timezone
import random

def seed_users(count=20):
    """Create fake users with different roles"""
    users_data = [
        # Admins
        {"username": "admin1", "email": "admin1@marketwindow.com", "role": USER_ROLE_ADMIN, "first_name": "Alice", "last_name": "Admin"},
        {"username": "admin2", "email": "admin2@marketwindow.com", "role": USER_ROLE_ADMIN, "first_name": "Bob", "last_name": "Administrator"},
        
        # Sellers
        {"username": "seller1", "email": "seller1@shop.com", "role": USER_ROLE_SELLER, "first_name": "Carol", "last_name": "Crafts"},
        {"username": "seller2", "email": "seller2@store.com", "role": USER_ROLE_SELLER, "first_name": "David", "last_name": "Designs"},
        {"username": "seller3", "email": "seller3@market.com", "role": USER_ROLE_SELLER, "first_name": "Eve", "last_name": "Electronics"},
        {"username": "seller4", "email": "seller4@retail.com", "role": USER_ROLE_SELLER, "first_name": "Frank", "last_name": "Fashion"},
        {"username": "seller5", "email": "seller5@goods.com", "role": USER_ROLE_SELLER, "first_name": "Grace", "last_name": "Groceries"},
        {"username": "seller6", "email": "seller6@boutique.com", "role": USER_ROLE_SELLER, "first_name": "Henry", "last_name": "Handmade"},
        {"username": "seller7", "email": "seller7@depot.com", "role": USER_ROLE_SELLER, "first_name": "Iris", "last_name": "Imports"},
        {"username": "seller8", "email": "seller8@emporium.com", "role": USER_ROLE_SELLER, "first_name": "Jack", "last_name": "Jewelry"},
        
        # Buyers
        {"username": "buyer1", "email": "buyer1@email.com", "role": USER_ROLE_BUYER, "first_name": "Kate", "last_name": "Customer"},
        {"username": "buyer2", "email": "buyer2@email.com", "role": USER_ROLE_BUYER, "first_name": "Liam", "last_name": "Shopper"},
        {"username": "buyer3", "email": "buyer3@email.com", "role": USER_ROLE_BUYER, "first_name": "Mia", "last_name": "Buyer"},
        {"username": "buyer4", "email": "buyer4@email.com", "role": USER_ROLE_BUYER, "first_name": "Noah", "last_name": "Consumer"},
        {"username": "buyer5", "email": "buyer5@email.com", "role": USER_ROLE_BUYER, "first_name": "Olivia", "last_name": "Client"},
        {"username": "buyer6", "email": "buyer6@email.com", "role": USER_ROLE_BUYER, "first_name": "Peter", "last_name": "Patron"},
        {"username": "buyer7", "email": "buyer7@email.com", "role": USER_ROLE_BUYER, "first_name": "Quinn", "last_name": "Purchaser"},
        {"username": "buyer8", "email": "buyer8@email.com", "role": USER_ROLE_BUYER, "first_name": "Ruby", "last_name": "Shopper"},
    ]
    
    # Add more random users if needed
    if count > len(users_data):
        for i in range(len(users_data), count):
            users_data.append({
                "username": f"user{i}",
                "email": f"user{i}@example.com",
                "role": random.choice([USER_ROLE_BUYER, USER_ROLE_SELLER]),
                "first_name": f"User{i}",
                "last_name": f"Test{i}"
            })
    
    for user_data in users_data[:count]:
        existing_user = User.query.filter_by(username=user_data["username"]).first()
        if not existing_user:
            user = User(
                username=user_data["username"],
                email=user_data["email"],
                role=user_data["role"],
                status=USER_STATUS_ACTIVE,
                first_name=user_data["first_name"],
                last_name=user_data["last_name"],
                phone=f"+1234567{random.randint(1000, 9999)}",
                region=f"Region {random.randint(1, 10)}",
                district=f"District {random.randint(1, 20)}",
                town=f"City {random.randint(1, 50)}",
                premium=random.choice([True, False]) if user_data["role"] != USER_ROLE_ADMIN else False
            )
            user.set_password("password123")  # Default password for all seed users
            db.session.add(user)
    
    db.session.commit()
    print(f"Seeded {min(count, len(users_data))} users")

if __name__ == "__main__":
    seed_users()
