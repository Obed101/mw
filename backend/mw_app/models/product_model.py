import json
from datetime import datetime, timezone
from ..extensions import db
from sqlalchemy.orm import validates


MAX_PRODUCT_IMAGES = 10


def _normalize_image_keys(image_keys):
    normalized = []
    seen = set()
    for image_key in image_keys or []:
        if image_key is None:
            continue
        cleaned = str(image_key).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _parse_legacy_product_images(raw_value):
    if not raw_value:
        return []

    serialized = str(raw_value).strip()
    if not serialized:
        return []

    parsed_values = []
    try:
        loaded = json.loads(serialized)
        if isinstance(loaded, list):
            parsed_values = [str(item).strip() for item in loaded]
        elif isinstance(loaded, str):
            parsed_values = [loaded.strip()]
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed_values = [piece.strip() for piece in serialized.split(",")]

    return _normalize_image_keys(parsed_values)


class Product(db.Model):
    __searchable__ = ['name', 'description', 'tags']

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    type_ = db.Column(db.String(100), nullable=False, default='product')  # product, service
    description = db.Column(db.Text)
    tags = db.Column(db.Text)  # JSON string or comma-separated tags
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    images = db.Column(db.Text)  # Deprecated: legacy JSON/comma-separated URLs
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    # Foreign key: Product belongs to a Shop
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    shop = db.relationship("Shop", backref="products")

    # Foreign key: Product belongs to a Category
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)

    image_records = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order.asc(), ProductImage.id.asc()",
    )

    @validates("image_records")
    def _validate_image_records(self, key, image_record):
        if image_record not in self.image_records and len(self.image_records) >= MAX_PRODUCT_IMAGES:
            raise ValueError(f"A product can have at most {MAX_PRODUCT_IMAGES} images")
        return image_record

    @property
    def image_urls(self):
        if self.image_records:
            return [item.storage_key for item in self.image_records]
        return _parse_legacy_product_images(self.images)

    @property
    def primary_image_url(self):
        urls = self.image_urls
        return urls[0] if urls else None

    def replace_image_urls(self, image_keys):
        normalized = _normalize_image_keys(image_keys)
        if len(normalized) > MAX_PRODUCT_IMAGES:
            raise ValueError(f"A product can have at most {MAX_PRODUCT_IMAGES} images")

        self.image_records.clear()
        for idx, image_key in enumerate(normalized):
            self.image_records.append(
                ProductImage(
                    storage_key=image_key,
                    sort_order=idx,
                    is_primary=(idx == 0),
                )
            )

    def add_image_url(self, image_key):
        normalized = _normalize_image_keys([image_key])
        if not normalized:
            raise ValueError("Image value cannot be empty")
        if normalized[0] in self.image_urls:
            return
        if len(self.image_records) >= MAX_PRODUCT_IMAGES:
            raise ValueError(f"A product can have at most {MAX_PRODUCT_IMAGES} images")

        self.image_records.append(
            ProductImage(
                storage_key=normalized[0],
                sort_order=len(self.image_records),
                is_primary=(len(self.image_records) == 0),
            )
        )

    def __repr__(self):
        return f'<Product {self.name}>'

    def generate_code():
        """Generate a unique 8-character alphanumeric code for the product"""
        import random
        import string
        while True:
            code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            if not Product.query.filter_by(code=code).first():
                return code

    def is_low_stock(self, threshold=10):
        """Check if product stock is below threshold"""
        return self.stock <= threshold

    def is_out_of_stock(self):
        """Check if product is out of stock"""
        return self.stock <= 0


class ProductImage(db.Model):
    __tablename__ = "product_image"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key = db.Column(db.String(512), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    product = db.relationship("Product", back_populates="image_records")

    __table_args__ = (
        db.UniqueConstraint("product_id", "storage_key", name="uq_product_image_product_storage"),
    )

    def __repr__(self):
        return f"<ProductImage product:{self.product_id} order:{self.sort_order}>"


class StockUpdate(db.Model):
    """Track stock update history for audit trail"""

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    old_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    stock_change = db.Column(db.Integer, nullable=False)  # positive for increase, negative for decrease
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)  # Seller who made the update
    reason = db.Column(db.String(255))  # Optional: "restocked", "sold", "damaged", etc.
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    # Relationships
    product = db.relationship("Product", backref="stock_history")
    user = db.relationship("User", backref="stock_updates")

    def __repr__(self):
        return f'<StockUpdate product:{self.product_id} {self.old_stock}->{self.new_stock}>'

    def to_dict(self):
        """Convert stock update to dictionary"""
        return {
            'id': self.id,
            'product_id': self.product_id,
            'old_stock': self.old_stock,
            'new_stock': self.new_stock,
            'stock_change': self.stock_change,
            'updated_by': self.updated_by,
            'reason': self.reason,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
