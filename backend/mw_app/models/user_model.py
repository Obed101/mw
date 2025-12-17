from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, event
from ..extensions import db


# User status and role constants
USER_STATUS_ACTIVE = 'active'
USER_STATUS_SUSPENDED = 'suspended'
USER_STATUS_PENDING = 'pending_verification'

USER_ROLE_ADMIN = 'admin'
USER_ROLE_SELLER = 'seller'
USER_ROLE_BUYER = 'buyer'

# Valid values for validation
VALID_USER_STATUSES = {USER_STATUS_ACTIVE, USER_STATUS_SUSPENDED, USER_STATUS_PENDING}
VALID_USER_ROLES = {USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Role and status management
    role = db.Column(db.String(20), nullable=False, default=USER_ROLE_BUYER)
    status = db.Column(db.String(20), nullable=False, default=USER_STATUS_PENDING)
    
    # Profile information
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(20), unique=True, index=True)
    profile_picture = db.Column(db.String(255))
    
    # Location information
    region = db.Column(db.String(100))
    district = db.Column(db.String(100))
    town = db.Column(db.String(100))
    address = db.Column(db.String(255))
    
    # Account status and timestamps
    is_email_verified = db.Column(db.Boolean, default=False)
    email_verified_at = db.Column(db.DateTime)
    is_phone_verified = db.Column(db.Boolean, default=False)
    phone_verified_at = db.Column(db.DateTime)
    
    # Premium status
    premium = db.Column(db.Boolean, default=False)
    
    last_login = db.Column(db.DateTime)
    last_activity = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), 
                         onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    owned_shops = db.relationship(
        "Shop",
        foreign_keys="Shop.owner_id",
        back_populates="owner",
        uselist=False
    )
    
    verified_shops = db.relationship(
        "Shop",
        foreign_keys="Shop.verified_by",
        back_populates="verifier"
    )
    
    # Authentication tokens (for password reset, email verification, etc.)
    auth_tokens = db.relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")
    
    # Password hashing and verification
    def set_password(self, password):
        """Create hashed password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check hashed password."""
        return check_password_hash(self.password_hash, password)

    # Status management
    def activate(self):
        """Activate the user account."""
        self.status = UserStatus.ACTIVE
        self.updated_at = datetime.now(timezone.utc)

    def suspend(self):
        """Suspend the user account."""
        self.status = UserStatus.SUSPENDED
        self.updated_at = datetime.now(timezone.utc)

    def is_active(self):
        """Check if user is active."""
        return self.status == USER_STATUS_ACTIVE

    def is_admin(self):
        """Check if user has admin role."""
        return self.role == USER_ROLE_ADMIN

    def is_seller(self):
        """Check if user has seller role."""
        return self.role == USER_ROLE_SELLER

    def is_buyer(self):
        """Check if user has buyer role."""
        return self.role == USER_ROLE_BUYER

    # Utility methods
    def update_last_login(self):
        """Update last login timestamp."""
        self.last_login = datetime.now(timezone.utc)
        db.session.commit()

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)
        db.session.commit()

    def to_dict(self):
        """Convert user object to dictionary."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'status': self.status,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone': self.phone,
            'region': self.region,
            'district': self.district,
            'town': self.town,
            'is_email_verified': self.is_email_verified,
            'is_phone_verified': self.is_phone_verified,
            'premium': self.premium,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

    @classmethod
    def find_by_email(cls, email):
        """Find user by email."""
        return cls.query.filter_by(email=email).first()

    @classmethod
    def find_by_username(cls, username):
        """Find user by username."""
        return cls.query.filter_by(username=username).first()

    @classmethod
    def find_by_phone(cls, phone):
        """Find user by phone number."""
        return cls.query.filter_by(phone=phone).first()

    # Browsing history and recommendations
    def get_recommended_categories(self, limit=5, days_back=30):
        """Get recommended categories based on user's browsing history."""
        from .category_model import Category
        
        cutoff_date = (self.last_login or datetime.now(timezone.utc)) - timedelta(days=days_back)
        
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
    
    def make_premium(self):
        """Upgrade user to premium status"""
        self.premium = True
        db.session.commit()
    
    def revoke_premium(self):
        """Revoke premium status from user"""
        self.premium = False
        db.session.commit()
    
    def is_premium(self):
        """Check if user has premium status"""
        return self.premium
    
    def __repr__(self):
        return f'<User {self.username}>'


class UserBrowsingHistory(db.Model):
    """Track user browsing behavior for recommendations"""
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=True)
    interaction_type = db.Column(db.String(50), nullable=False, default='view')
    viewed_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    duration_seconds = db.Column(db.Integer, default=0)
    
    # Relationships
    user = db.relationship("User", backref="browsing_history")
    product = db.relationship("Product", backref="browsing_history")
    category = db.relationship("Category", backref="browsing_history")
    
    def __repr__(self):
        return f'<UserBrowsingHistory {self.id} - User {self.user_id} - {self.interaction_type}>'
    
    @classmethod
    def track_view(cls, user_id, product_id=None, category_id=None, shop_id=None, interaction_type='view'):
        """Helper method to track a browsing event"""
        try:
            view = cls(
                user_id=user_id,
                product_id=product_id,
                category_id=category_id,
                shop_id=shop_id,
                interaction_type=interaction_type,
                viewed_at=datetime.now(timezone.utc)
            )
            db.session.add(view)
            db.session.commit()
            return view
        except Exception as e:
            db.session.rollback()
            print(f"Error tracking view: {e}")
            return None


# Token types for AuthToken
TOKEN_TYPE_EMAIL_VERIFICATION = 'email_verification'
TOKEN_TYPE_PASSWORD_RESET = 'password_reset'
TOKEN_TYPE_API = 'api'
VALID_TOKEN_TYPES = {
    TOKEN_TYPE_EMAIL_VERIFICATION,
    TOKEN_TYPE_PASSWORD_RESET,
    TOKEN_TYPE_API
}

class AuthToken(db.Model):
    """Authentication tokens for API access and email verification"""
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    token = db.Column(db.String(255), nullable=False, index=True)
    token_type = db.Column(db.String(50), nullable=False)  # 'email_verification', 'password_reset', 'api'
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    used_at = db.Column(db.DateTime)
    
    # Relationships
    user = db.relationship('User', back_populates='auth_tokens')
    
    def __repr__(self):
        return f'<AuthToken {self.token_type} for user {self.user_id}>'
    
    @property
    def is_expired(self):
        """Check if the token has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_valid(self):
        """Check if the token is valid (not used and not expired)."""
        return not self.is_used and not self.is_expired
    
    def mark_as_used(self):
        """Mark the token as used."""
        self.is_used = True
        self.used_at = datetime.now(timezone.utc)
        db.session.commit()
    
    @classmethod
    def create_token(cls, user_id, token_type=TOKEN_TYPE_API, expires_in_hours=24):
        """Create a new authentication token."""
        import secrets
        import string
        
        # Validate token type
        if token_type not in VALID_TOKEN_TYPES:
            raise ValueError(f"Invalid token type: {token_type}")
        
        # Generate a secure random token
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(64))
        
        # Set expiration time
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        
        # Create and return the token
        auth_token = cls(
            user_id=user_id,
            token=token,
            token_type=token_type,
            expires_at=expires_at
        )
        
        db.session.add(auth_token)
        db.session.commit()
        return auth_token
    
    @classmethod
    def validate_token(cls, token, token_type=None):
        """Validate a token and return the associated user if valid."""
        if not token:
            return None
            
        query = cls.query.filter_by(token=token, is_used=False)
        
        if token_type:
            if token_type not in VALID_TOKEN_TYPES:
                raise ValueError(f"Invalid token type: {token_type}")
            query = query.filter_by(token_type=token_type)
            
        auth_token = query.first()
        
        if not auth_token or auth_token.is_expired:
            return None
            
        return auth_token.user
