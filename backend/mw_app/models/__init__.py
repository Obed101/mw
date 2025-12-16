# Models package
# Import all models here to make them available when importing from mw_app.models
from .user_model import (
    User, UserBrowsingHistory, AuthToken,
    USER_STATUS_ACTIVE, USER_STATUS_SUSPENDED, USER_STATUS_PENDING,
    USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER,
    VALID_USER_STATUSES, VALID_USER_ROLES,
    TOKEN_TYPE_EMAIL_VERIFICATION, TOKEN_TYPE_PASSWORD_RESET, TOKEN_TYPE_API,
    VALID_TOKEN_TYPES
)

from .shop_model import Shop, UserFollowShop, VerificationOTP, VerificationStatus
from .product_model import Product, StockUpdate
from .category_model import Category, \
    CATEGORY_LEVEL_TRUNK, CATEGORY_LEVEL_BRANCH, CATEGORY_LEVEL_LEAF, \
    VALID_CATEGORY_LEVELS
from .subscription_model import Subscription, SubscriptionType

# Make these available at the package level
__all__ = [
    # Models
    'User', 'UserBrowsingHistory', 'AuthToken',
    'Shop', 'UserFollowShop', 'VerificationOTP', 'VerificationStatus',
    'Product', 'StockUpdate',
    'Category',
    'Subscription', 'SubscriptionType',
    
    # Constants
    'USER_STATUS_ACTIVE', 'USER_STATUS_SUSPENDED', 'USER_STATUS_PENDING',
    'USER_ROLE_ADMIN', 'USER_ROLE_SELLER', 'USER_ROLE_BUYER',
    'VALID_USER_STATUSES', 'VALID_USER_ROLES',
    'TOKEN_TYPE_EMAIL_VERIFICATION', 'TOKEN_TYPE_PASSWORD_RESET', 'TOKEN_TYPE_API',
    'VALID_TOKEN_TYPES',
    'CATEGORY_LEVEL_TRUNK', 'CATEGORY_LEVEL_BRANCH', 'CATEGORY_LEVEL_LEAF',
    'VALID_CATEGORY_LEVELS'
]
