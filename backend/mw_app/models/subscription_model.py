from ..extensions import db
from datetime import datetime, timezone

# Subscription type constants
SUBSCRIPTION_TYPE_USER = 'user'
SUBSCRIPTION_TYPE_PRODUCT = 'product'
SUBSCRIPTION_TYPE_SHOP = 'shop'
VALID_SUBSCRIPTION_TYPES = {
    SUBSCRIPTION_TYPE_USER,
    SUBSCRIPTION_TYPE_PRODUCT,
    SUBSCRIPTION_TYPE_SHOP
}

class Subscription(db.Model):
    """Relationship table for subscription periods linked to users, products, or shops"""
    
    id = db.Column(db.Integer, primary_key=True)
    subscription_type = db.Column(db.String(20), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)  # References user.id, product.id, or shop.id
    start_date = db.Column(db.DateTime, nullable=False, default=datetime.now(timezone.utc))
    end_date = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Optional: reference to user who owns/created the subscription (useful for audit)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    
    # Relationships
    creator = db.relationship("User", foreign_keys=[created_by], backref="created_subscriptions")
    
    # Polymorphic relationships based on subscription_type
    user_target = db.relationship(
        "User", 
        foreign_keys=[target_id],
        primaryjoin="and_(Subscription.target_id==User.id, Subscription.subscription_type=='USER')",
        backref="subscriptions",
        viewonly=True
    )
    product_target = db.relationship(
        "Product",
        foreign_keys=[target_id],
        primaryjoin="and_(Subscription.target_id==Product.id, Subscription.subscription_type=='PRODUCT')",
        backref="subscriptions",
        viewonly=True
    )
    shop_target = db.relationship(
        "Shop",
        foreign_keys=[target_id],
        primaryjoin="and_(Subscription.target_id==Shop.id, Subscription.subscription_type=='SHOP')",
        backref="subscriptions",
        viewonly=True
    )
    
    # Ensure one active subscription per target at a time
    __table_args__ = (
        db.UniqueConstraint('subscription_type', 'target_id', 'is_active', name='unique_active_subscription'),
    )
    
    def __repr__(self):
        return f'<Subscription {self.subscription_type.value}:{self.target_id} {self.start_date}->{self.end_date}>'
    
    def is_expired(self):
        """Check if subscription has expired"""
        return datetime.now(timezone.utc) > self.end_date
    
    def is_valid(self):
        """Check if subscription is active and not expired"""
        return self.is_active and not self.is_expired()
    
    def extend(self, days):
        """Extend subscription by specified number of days"""
        if self.end_date:
            self.end_date = self.end_date + datetime.timedelta(days=days)
        else:
            self.end_date = datetime.now(timezone.utc) + datetime.timedelta(days=days)
        self.updated_at = datetime.now(timezone.utc)
    
    def deactivate(self):
        """Deactivate subscription"""
        self.is_active = False
        self.updated_at = datetime.now(timezone.utc)
    
    def to_dict(self):
        """Convert subscription to dictionary"""
        return {
            'id': self.id,
            'subscription_type': self.subscription_type.value,
            'target_id': self.target_id,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
            'is_expired': self.is_expired(),
            'is_valid': self.is_valid()
        }
    
    @staticmethod
    def create_subscription(subscription_type, target_id, end_date, created_by=None):
        """Create a new subscription, deactivating any existing active ones"""
        # Deactivate existing active subscription for this target
        Subscription.query.filter_by(
            subscription_type=subscription_type,
            target_id=target_id,
            is_active=True
        ).update({'is_active': False})
        
        # Create new subscription
        subscription = Subscription(
            subscription_type=subscription_type,
            target_id=target_id,
            end_date=end_date,
            created_by=created_by
        )
        db.session.add(subscription)
        db.session.commit()
        return subscription
    
    @staticmethod
    def get_active_subscription(subscription_type, target_id):
        """Get current active subscription for a target"""
        return Subscription.query.filter_by(
            subscription_type=subscription_type,
            target_id=target_id,
            is_active=True
        ).first()
    
    @staticmethod
    def get_valid_subscriptions_for_target(subscription_type, target_id):
        """Get all valid (active and not expired) subscriptions for a target"""
        now = datetime.now(timezone.utc)
        return Subscription.query.filter(
            Subscription.subscription_type == subscription_type,
            Subscription.target_id == target_id,
            Subscription.is_active == True,
            Subscription.end_date > now
        ).all()
