from .. import create_app
from ..extensions import db
from ..models import Shop


def seed_shop_categories():
    """Set 'General Shop' as google_category for shops that don't have one."""

    # Find all shops without google_category
    shops_without_category = Shop.query.filter(
        (Shop.google_category.is_(None)) | (Shop.google_category == '')
    ).all()

    if not shops_without_category:
        print("All shops already have a google_category. No seeding needed.")
        return

    # Update each shop with 'General Shop'
    updated_count = 0

    for shop in shops_without_category:
        shop.google_category = 'General Shop'
        updated_count += 1
        print(f"Updated shop '{shop.name}' with category 'General Shop'")

    db.session.commit()

    print(
        f"Shop category seeding completed! "
        f"Updated {updated_count} shops."
    )


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        seed_shop_categories()