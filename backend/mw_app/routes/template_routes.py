# Template routes for HTMX frontend
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..forms import LoginForm, RegistrationForm
from ..utils.helpers import seller_required, admin_required

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

@main_bp.route('/profile')
def profile():
    """User profile page"""
    return render_template('public/profile.html')

# Auth template routes
@auth_bp.route('/login', methods=['POST'])
def login_post():
    """Handle login - returns redirect or error"""
    form = LoginForm()
    if form.validate_on_submit():
        # TODO: Implement actual login logic
        flash('Login functionality coming soon!', 'info')
        return redirect(url_for('main_bp.index'))
    
    if request.headers.get('HX-Request'):
        return render_template('auth/login.html', form=form)
    return redirect(url_for('main_bp.login'))

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

# Seller template routes
@seller_bp.route('/dashboard')
@seller_required
def seller_dashboard():
    """Seller dashboard - main overview"""
    return render_template('seller/dashboard.html')

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
