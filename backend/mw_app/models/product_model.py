from .. import db
from datetime import datetime

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    type_ = db.Column(db.String(100), nullable=False, default='product') # product, service
    description = db.Column(db.Text)
    tags = db.Column(db.Text) # JSON string or comma-separated tags
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    images = db.Column(db.Text)  # JSON string or comma-separated URLs
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(datetime.timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(datetime.timezone.utc), onupdate=datetime.now(datetime.timezone.utc))
    
    # Foreign key: Product belongs to a Shop
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    shop = db.relationship("Shop", backref="products")
    
    # Foreign key: Product belongs to a Category
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    
    def __repr__(self):
        return f'<Product {self.name}>'
    
    def is_low_stock(self, threshold=10):
        """Check if product stock is below threshold"""
        return self.stock <= threshold
    
    def is_out_of_stock(self):
        """Check if product is out of stock"""
        return self.stock <= 0


class StockUpdate(db.Model):
    """Track stock update history for audit trail"""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    old_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    stock_change = db.Column(db.Integer, nullable=False)  # positive for increase, negative for decrease
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)  # Seller who made the update
    reason = db.Column(db.String(255))  # Optional: "restocked", "sold", "damaged", etc.
    updated_at = db.Column(db.DateTime, default=datetime.now(datetime.timezone.utc), nullable=False)
    
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
