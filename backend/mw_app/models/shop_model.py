from .. import db
from datetime import datetime, timedelta, timezone
import enum
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

class VerificationStatus(enum.Enum):
    """Shop verification status"""
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"

class Shop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    promoted = db.Column(db.Boolean)
    address = db.Column(db.String(255))
    region = db.Column(db.String(100))
    district = db.Column(db.String(100))
    town = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    last_updated = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Verification fields
    verification_status = db.Column(db.Enum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False)
    phone_verified = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    verification_requested_at = db.Column(db.DateTime)
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # Admin who verified
    rejection_reason = db.Column(db.Text)
    verification_notes = db.Column(db.Text)  # Admin notes
    
    # Foreign key: Shop is owned by a User (seller)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    
    # Explicit relationships to avoid AmbiguousForeignKeysError
    owner = db.relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="owned_shops"
    )
    
    verifier = db.relationship(
        "User",
        foreign_keys=[verified_by],
        back_populates="verified_shops"
    )
    
    def __repr__(self):
        return f'<Shop {self.name}>'
    
    def is_verified(self):
        """Check if shop is verified"""
        return self.verification_status == VerificationStatus.VERIFIED
    
    def can_request_verification(self):
        """Check if shop can request verification (phone and email must be verified)"""
        return self.phone_verified and self.email_verified and self.verification_status == VerificationStatus.PENDING


class UserFollowShop(db.Model):
    """Track which users follow which shops"""
    __tablename__ = 'user_follow_shop'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    followed_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    
    # Unique constraint: a user can only follow a shop once
    __table_args__ = (db.UniqueConstraint('user_id', 'shop_id', name='unique_user_shop_follow'),)
    
    # Relationships
    user = db.relationship("User", backref="followed_shops")
    shop = db.relationship("Shop", backref="followers")
    
    def __repr__(self):
        return f'<UserFollowShop user:{self.user_id} shop:{self.shop_id}>'
    
    def to_dict(self):
        """Convert follow relationship to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'shop_id': self.shop_id,
            'followed_at': self.followed_at.isoformat() if self.followed_at else None
        }


class VerificationOTP(db.Model):
    """Track OTP codes for phone and email verification"""
    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    otp_hash = db.Column(db.String(255), nullable=False)  # Hashed OTP
    otp_type = db.Column(db.String(20), nullable=False)  # 'phone' or 'email'
    contact_value = db.Column(db.String(120), nullable=False)  # phone number or email
    expires_at = db.Column(db.DateTime, nullable=False)
    verified_at = db.Column(db.DateTime)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    
    # Relationship
    shop = db.relationship("Shop", backref="otp_requests")
    
    def __repr__(self):
        return f'<VerificationOTP shop:{self.shop_id} type:{self.otp_type}>'
    
    @staticmethod
    def generate_otp():
        """Generate a 6-digit OTP"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(6)])
    
    @staticmethod
    def create_otp(shop_id, otp_type, contact_value, expires_in_minutes=25):
        """Create and store a new OTP"""
        # Invalidate any existing active OTPs for this shop and type
        VerificationOTP.query.filter_by(
            shop_id=shop_id,
            otp_type=otp_type,
            is_used=False
        ).update({'is_used': True})
        
        # Generate OTP
        otp_code = VerificationOTP.generate_otp()
        otp_hash = generate_password_hash(otp_code)
        
        # Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
        
        # Create OTP record
        otp = VerificationOTP(
            shop_id=shop_id,
            otp_hash=otp_hash,
            otp_type=otp_type,
            contact_value=contact_value,
            expires_at=expires_at
        )
        
        db.session.add(otp)
        db.session.commit()
        
        return otp, otp_code  # Return both the record and the plain code
    
    def verify_otp(self, otp_code):
        """Verify the OTP code"""
        if self.is_used:
            return False, "OTP has already been used"
        
        if datetime.now(timezone.utc) > self.expires_at:
            return False, "OTP has expired"
        
        if not check_password_hash(self.otp_hash, otp_code):
            return False, "Invalid OTP code"
        
        # Mark as used
        self.is_used = True
        self.verified_at = datetime.now(timezone.utc)
        db.session.commit()
        
        return True, "OTP verified successfully"
    
    @staticmethod
    def get_active_otp(shop_id, otp_type):
        """Get active (unused, not expired) OTP for a shop"""
        now = datetime.now(timezone.utc)
        return VerificationOTP.query.filter_by(
            shop_id=shop_id,
            otp_type=otp_type,
            is_used=False
        ).filter(
            VerificationOTP.expires_at > now
        ).order_by(VerificationOTP.created_at.desc()).first()
