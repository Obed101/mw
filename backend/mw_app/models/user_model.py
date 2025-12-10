from .. import db
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='buyer')  # buyer, seller, admin
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    location = db.Column(db.String(255)) # region, district, town name
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(datetime.timezone.utc))
    last_login = db.Column(db.DateTime)
    
    # Relationship: A seller can own one shop
    shop = db.relationship("Shop", backref="owner", uselist=False)
    
    def get_recommended_categories(self, limit=5, days_back=30):
        """
        Get recommended categories based on user's browsing history.
        Returns categories sorted by frequency of views in recent history.
        """
        from .category_model import Category
        from sqlalchemy import func
        
        # Calculate cutoff date
        cutoff_date = (self.last_login or datetime.now(datetime.timezone.utc)) - timedelta(days=days_back)
        
        # Get category view counts from browsing history
        category_counts = db.session.query(
            UserBrowsingHistory.category_id,
            func.count(UserBrowsingHistory.id).label('view_count'),
            func.max(UserBrowsingHistory.viewed_at).label('last_viewed')
        ).filter(
            UserBrowsingHistory.user_id == self.id,
            UserBrowsingHistory.category_id.isnot(None),
            UserBrowsingHistory.viewed_at >= cutoff_date
        ).group_by(
            UserBrowsingHistory.category_id
        ).order_by(
            func.count(UserBrowsingHistory.id).desc(),
            func.max(UserBrowsingHistory.viewed_at).desc()
        ).limit(limit).all()
        
        # Get category objects
        recommended_categories = []
        for category_id, view_count, last_viewed in category_counts:
            category = Category.query.get(category_id)
            if category and category.is_active:
                cat_dict = category.to_dict()
                cat_dict['view_count'] = view_count
                cat_dict['last_viewed'] = last_viewed.isoformat() if last_viewed else None
                recommended_categories.append(cat_dict)
        
        return recommended_categories
    
    def set_password(self, password):
        """Hash and set the password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches the hash"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class UserBrowsingHistory(db.Model):
    """Track user browsing behavior for recommendations"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=True)
    interaction_type = db.Column(db.String(50), nullable=False, default='view')  # view, search, compare, etc.
    viewed_at = db.Column(db.DateTime, default=datetime.now(datetime.timezone.utc), nullable=False)
    duration_seconds = db.Column(db.Integer, default=0)  # Time spent viewing (optional)
    
    # Relationships
    user = db.relationship("User", backref="browsing_history")
    product = db.relationship("Product", backref="browsing_history")
    category = db.relationship("Category", backref="browsing_history")
    shop = db.relationship("Shop", backref="browsing_history")
    
    def __repr__(self):
        return f'<UserBrowsingHistory user:{self.user_id} product:{self.product_id} category:{self.category_id}>'
    
    @staticmethod
    def track_view(user_id, product_id=None, category_id=None, shop_id=None, interaction_type='view'):
        """Helper method to track a browsing event"""
        # If product_id is provided, get its category_id
        if product_id and not category_id:
            from .product_model import Product
            product = Product.query.get(product_id)
            if product:
                category_id = product.category_id
        
        browsing_event = UserBrowsingHistory(
            user_id=user_id,
            product_id=product_id,
            category_id=category_id,
            shop_id=shop_id,
            interaction_type=interaction_type
        )
        db.session.add(browsing_event)
        db.session.commit()
        return browsing_event

