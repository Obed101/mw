# Template routes for HTMX frontend
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, current_user, logout_user, login_required
from ..forms import LoginForm, RegistrationForm
from ..utils.helpers import seller_required, admin_required
from ..models.user_model import User, USER_ROLE_BUYER
from ..extensions import oauth, db
import secrets

main_bp = Blueprint('main_bp', __name__)
auth_bp = Blueprint('auth_template_bp', __name__, url_prefix='/auth')
seller_bp = Blueprint('seller_template_bp', __name__, url_prefix='/seller')
buyer_bp = Blueprint('buyer_template_bp', __name__, url_prefix='/buyer')
admin_bp = Blueprint('admin_template_bp', __name__, url_prefix='/admin')

# Public pages
@main_bp.route('/')
def index():
    """Homepage - marketplace overview"""
    return render_template('public/index.html')

@main_bp.route('/login')
def login():
    """Login page"""
    form = LoginForm()
    return render_template('auth/login.html', form=form)

@main_bp.route('/register')
def register():
    """Registration page"""
    form = RegistrationForm()
    return render_template('auth/register.html', form=form)

@main_bp.route('/shops')
def shops():
    """Browse shops page"""
    return render_template('buyer/shops.html')

@main_bp.route('/products')
def products():
    """Browse products page"""
    return render_template('buyer/products.html')

@main_bp.route('/categories')
def categories():
    """Browse categories page"""
    return render_template('public/categories.html')

@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page"""
    from datetime import datetime, timedelta
    
    if request.method == 'POST':
        try:
            # Update user profile fields
            current_user.first_name = request.form.get('first_name', '').strip()
            current_user.last_name = request.form.get('last_name', '').strip()
            current_user.phone = request.form.get('phone', '').strip()
            current_user.region = request.form.get('region', '').strip()
            current_user.district = request.form.get('district', '').strip()
            current_user.town = request.form.get('town', '').strip()
            current_user.address = request.form.get('address', '').strip()
            
            # Update timestamp
            current_user.updated_at = datetime.now()
            
            # Commit changes to database
            db.session.commit()
            
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('main_bp.profile'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error updating profile. Please try again.', 'error')
            print(f"Profile update error: {e}")
    
    # Get user stats (placeholder data for now)
    user_stats = {
        'orders_count': 127,  # TODO: Get from orders table
        'reviews_count': 89,  # TODO: Get from reviews table
        'rating': 4.8,        # TODO: Calculate from reviews
        'member_since': current_user.created_at
    }
    
    # Calculate membership duration
    if current_user.created_at:
        days_since_creation = (datetime.now() - current_user.created_at.replace(tzinfo=None)).days
        if days_since_creation < 30:
            member_duration = f"{days_since_creation}d"
        elif days_since_creation < 365:
            member_duration = f"{days_since_creation // 30}m"
        else:
            member_duration = f"{days_since_creation // 365}y"
    else:
        member_duration = "New"
    
    user_stats['member_duration'] = member_duration
    
    # Get recent activity (placeholder data for now)
    recent_activity = [
        {
            'type': 'order_completed',
            'title': 'Order Completed',
            'description': 'Electronics Store - $249.99',
            'time_ago': '2 hours ago',
            'icon': 'check-circle',
            'color': 'success'
        },
        {
            'type': 'review_posted',
            'title': 'Review Posted',
            'description': 'Fashion Boutique - 5 stars',
            'time_ago': 'Yesterday',
            'icon': 'star',
            'color': 'primary'
        },
        {
            'type': 'wishlist_added',
            'title': 'Added to Wishlist',
            'description': 'Smart Watch Pro',
            'time_ago': '3 days ago',
            'icon': 'heart',
            'color': 'warning'
        },
        {
            'type': 'shop_followed',
            'title': 'New Shop Followed',
            'description': 'Tech Gadgets Store',
            'time_ago': '1 week ago',
            'icon': 'shop',
            'color': 'info'
        }
    ]
    
    return render_template('public/profile.html', 
                         user_stats=user_stats,
                         recent_activity=recent_activity)

@auth_bp.route('/register', methods=['POST'])
def register_post():
    """Handle registration - returns redirect or error"""
    form = RegistrationForm()
    if form.validate_on_submit():
        # TODO: Implement actual registration logic
        flash('Registration functionality coming soon!', 'info')
        return redirect(url_for('main_bp.login'))
    
    if request.headers.get('HX-Request'):
        return render_template('auth/register.html', form=form)
    return redirect(url_for('main_bp.register'))

@auth_bp.route('/logout')
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('main_bp.index'))

###################################
####################################
@main_bp.route('/oauth/login')
def oauth_login():
    redirect_uri = url_for('main_bp.oauth_authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@main_bp.route('/oauth/authorize')
def oauth_authorize():
    try:
        # 1. Exchange code for token
        token = oauth.google.authorize_access_token()

        # 2. Fetch user info explicitly
        resp = oauth.google.get('userinfo')
        user_info = resp.json()

        if not user_info:
            flash('Failed to get user information from Google', 'error')
            return redirect(url_for('main_bp.login'))

        email = user_info.get('email')
        first_name = user_info.get('given_name', '')
        last_name = user_info.get('family_name', '')

        if not email:
            flash('Email is required from Google account', 'error')
            return redirect(url_for('main_bp.login'))

        # 3. Find or create user
        user = User.query.filter_by(email=email).first()

        if user:
            login_user(user)
        else:
            username = email.split('@')[0]
            counter = 1
            base = username
            while User.query.filter_by(username=username).first():
                username = f"{base}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=USER_ROLE_BUYER,
                status='active'
            )
            user.set_password(secrets.token_urlsafe(16))

            db.session.add(user)
            db.session.commit()

            login_user(user)

        # 4. Redirect
        if user.role == 'admin':
            return redirect(url_for('admin_template_bp.admin_dashboard'))
        elif user.role == 'seller':
            return redirect(url_for('seller_template_bp.seller_dashboard'))
        return redirect(url_for('main_bp.index'))

    except Exception as e:
        flash('Authentication failed', 'error')
        current_app.logger.exception(e)
        return redirect(url_for('main_bp.login'))

# Seller template routes
@seller_bp.route('/dashboard')
# @seller_required
def seller_dashboard():
    """Seller dashboard - main overview"""
    return render_template('seller/seller_dashboard.html')

@seller_bp.route('/shop')
@seller_required
def seller_shop():
    """Shop management page"""
    return render_template('seller/shop.html')

@seller_bp.route('/products')
@seller_required
def seller_products():
    """Products management page"""
    return render_template('seller/products.html')

@seller_bp.route('/analytics')
@seller_required
def seller_analytics_page():
    """Analytics dashboard page"""
    return render_template('seller/analytics.html')

@seller_bp.route('/verification')
@seller_required
def seller_verification():
    """Shop verification page"""
    return render_template('seller/verification.html')

# Buyer template routes
@buyer_bp.route('/dashboard')
def buyer_dashboard():
    """Buyer dashboard"""
    return render_template('buyer/dashboard.html')

@buyer_bp.route('/shops')
def buyer_shops():
    """Browse shops page"""
    return render_template('buyer/shops.html')

@buyer_bp.route('/products')
def buyer_products():
    """Browse products page"""
    return render_template('buyer/products.html')

@buyer_bp.route('/shop/<int:shop_id>')
def buyer_shop_detail(shop_id):
    """Shop detail page"""
    return render_template('buyer/shop_detail.html', shop_id=shop_id)

# Admin template routes
@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    return render_template('admin/dashboard.html')

@admin_bp.route('/users')
@admin_required
def admin_users():
    """User management page"""
    return render_template('admin/users.html')

@admin_bp.route('/shops')
@admin_required
def admin_shops():
    """Shop management page"""
    return render_template('admin/shops.html')

@admin_bp.route('/categories')
@admin_required
def admin_categories():
    """Category management page"""
    return render_template('admin/categories.html')

@admin_bp.route('/products')
@admin_required
def admin_products():
    """Product management page"""
    return render_template('admin/products.html')

@admin_bp.route('/reports')
@admin_required
def admin_reports():
    """Reports and analytics page"""
    return render_template('admin/reports.html')

@admin_bp.route('/bulk-operations')
@admin_required
def admin_bulk_operations():
    """Bulk operations page"""
    return render_template('admin/bulk_operations.html')

# HTMX partial endpoints (for dynamic updates)
@seller_bp.route('/partials/products/list')
@seller_required
def products_list_partial():
    """Partial template for products list (HTMX updates)"""
    return render_template('seller/partials/products_list.html')

@seller_bp.route('/partials/analytics/data')
@seller_required
def analytics_data_partial():
    """Partial template for analytics data (HTMX updates)"""
    return render_template('seller/partials/analytics_data.html')

@buyer_bp.route('/partials/shops/list')
def shops_list_partial():
    """Partial template for shops list (HTMX updates)"""
    return render_template('buyer/partials/shops_list.html')

@buyer_bp.route('/partials/products/list')
def products_list_partial():
    """Partial template for products list (HTMX updates)"""
    return render_template('buyer/partials/products_list.html')

@admin_bp.route('/partials/users/list')
@admin_required
def users_list_partial():
    """Partial template for users list (HTMX updates)"""
    return render_template('admin/partials/users_list.html')

@admin_bp.route('/partials/shops/list')
@admin_required
def shops_list_partial():
    """Partial template for shops list (HTMX updates)"""
    return render_template('admin/partials/shops_list.html')

@admin_bp.route('/partials/reports/data')
@admin_required
def reports_data_partial():
    """Partial template for reports data (HTMX updates)"""
    return render_template('admin/partials/reports_data.html')
