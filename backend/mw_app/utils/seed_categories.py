"""
Utility script to seed initial product categories into the database.
Creates a 3-level hierarchy: Trunk -> Branch -> Leaf
Run this after creating the Category model to populate default categories.
"""

from ..extensions import db
from ..models import Category, CATEGORY_LEVEL_TRUNK, CATEGORY_LEVEL_BRANCH, CATEGORY_LEVEL_LEAF

# 3-level category hierarchy: Trunk -> Branch -> Leaf
CATEGORY_HIERARCHY = {
    "Electronics": {
        "Computers": ["Laptops", "Desktops", "Tablets", "Monitors"],
        "Phones": ["Smartphones", "Feature Phones", "Accessories"],
        "Audio": ["Headphones", "Speakers", "Microphones"]
    },
    "Clothing": {
        "Men's Wear": ["Shirts", "Pants", "Jackets", "Underwear"],
        "Women's Wear": ["Dresses", "Tops", "Skirts", "Lingerie"],
        "Kids' Wear": ["Boys Clothes", "Girls Clothes", "Baby Clothes"]
    },
    "Home & Garden": {
        "Furniture": ["Living Room", "Bedroom", "Kitchen", "Office"],
        "Garden": ["Tools", "Plants", "Outdoor Furniture", "Pots"],
        "Appliances": ["Kitchen", "Laundry", "Cleaning", "Heating"]
    },
    "Tools & Hardware": {
        "Power Tools": ["Drills", "Saws", "Grinders", "Sanders"],
        "Hand Tools": ["Hammers", "Screwdrivers", "Wrenches", "Pliers"],
        "Building": ["Lumber", "Hardware", "Paint", "Plumbing"]
    },
    "Food & Edibles": {
        "Fresh Produce": ["Fruits", "Vegetables", "Herbs", "Organic"],
        "Packaged Foods": ["Snacks", "Canned Goods", "Pasta", "Rice"],
        "Beverages": ["Coffee", "Tea", "Juices", "Soft Drinks"]
    },
    "Toys & Games": {
        "Educational": ["Puzzles", "Science Kits", "Books", "Art Supplies"],
        "Outdoor": ["Sports", "Ride-ons", "Playground", "Water Toys"],
        "Indoor": ["Board Games", "Video Games", "Building Blocks", "Dolls"]
    },
    "Sports & Outdoors": {
        "Fitness": ["Equipment", "Clothing", "Accessories", "Track"],
        "Outdoor Recreation": ["Camping", "Hiking", "Fishing", "Hunting"],
        "Team Sports": ["Soccer", "Basketball", "Football", "Baseball"]
    },
    "Health & Beauty": {
        "Skincare": ["Face", "Body", "Sun Care", "Lips"],
        "Haircare": ["Shampoo", "Conditioner", "Styling", "Color"],
        "Makeup": ["Face", "Eyes", "Lips", "Nails"]
    },
    "Automotive": {
        "Parts": ["Engine", "Brakes", "Tires", "Battery"],
        "Accessories": ["Interior", "Exterior", "Electronics", "Storage"],
        "Maintenance": ["Oil", "Fluids", "Filters", "Tools"]
    },
    "Books & Stationery": {
        "Books": ["Fiction", "Non-Fiction", "Educational", "Children"],
        "Office Supplies": ["Paper", "Pens", "Desk", "Organization"],
        "Art & Craft": ["Drawing", "Painting", "Scrapbooking", "Knitting"]
    }
}

def seed_categories():
    """Seed the database with 3-level category hierarchy"""
    trunk_count = 0
    branch_count = 0
    leaf_count = 0
    
    for trunk_name, branches in CATEGORY_HIERARCHY.items():
        # Create Trunk category
        existing_trunk = Category.query.filter_by(name=trunk_name, level=CATEGORY_LEVEL_TRUNK).first()
        if not existing_trunk:
            trunk = Category(
                name=trunk_name,
                level=CATEGORY_LEVEL_TRUNK,
                parent_id=None,
                description=f"Main category for {trunk_name.lower()}",
                is_active=True
            )
            db.session.add(trunk)
            db.session.flush()  # Get the ID without committing
            print(f"Added trunk: {trunk_name}")
            trunk_id = trunk.id
            trunk_count += 1
        else:
            trunk_id = existing_trunk.id
            print(f"Trunk already exists: {trunk_name}")
        
        # Create Branch categories
        for branch_name, leaves in branches.items():
            existing_branch = Category.query.filter_by(name=branch_name, level=CATEGORY_LEVEL_BRANCH, parent_id=trunk_id).first()
            if not existing_branch:
                branch = Category(
                    name=branch_name,
                    level=CATEGORY_LEVEL_BRANCH,
                    parent_id=trunk_id,
                    description=f"{branch_name} under {trunk_name}",
                    is_active=True
                )
                db.session.add(branch)
                db.session.flush()  # Get the ID without committing
                print(f"  Added branch: {branch_name}")
                branch_id = branch.id
                branch_count += 1
            else:
                branch_id = existing_branch.id
                print(f"  Branch already exists: {branch_name}")
            
            # Create Leaf categories
            for leaf_name in leaves:
                existing_leaf = Category.query.filter_by(name=leaf_name, level=CATEGORY_LEVEL_LEAF, parent_id=branch_id).first()
                if not existing_leaf:
                    leaf = Category(
                        name=leaf_name,
                        level=CATEGORY_LEVEL_LEAF,
                        parent_id=branch_id,
                        description=f"{leaf_name} products under {branch_name}",
                        is_active=True
                    )
                    db.session.add(leaf)
                    print(f"    Added leaf: {leaf_name}")
                    leaf_count += 1
                else:
                    print(f"    Leaf already exists: {leaf_name}")
    
    db.session.commit()
    print(f"\nCategory seeding completed!")
    print(f"Created {trunk_count} trunks, {branch_count} branches, and {leaf_count} leaves")
    print(f"Total categories: {trunk_count + branch_count + leaf_count}")

if __name__ == "__main__":
    seed_categories()

