from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_required, current_user
from ..extensions import db
from ..models import Shop, Product, Category, USER_ROLE_ADMIN, CATEGORY_LEVEL_LEAF
from ..utils.helpers import shop_owner_required, get_managed_shop
from ..services.ai_service import AIService
from datetime import datetime, timezone
from flask import current_app
import meilisearch

manage_bp = Blueprint('manage_bp', __name__, url_prefix='/manage')

def get_ms_client():
    ms_url = current_app.config.get('MEILISEARCH_URL', 'http://127.0.0.1:7700')
    ms_key = current_app.config.get('MEILISEARCH_KEY', 'masterKey')
    return meilisearch.Client(ms_url, ms_key)

@manage_bp.route('/search-categories')
@login_required
@shop_owner_required
def search_categories():
    """HTMX: Search categories using Meilisearch for autocomplete"""
    # Accept both 'q' and 'category_name' for flexibility
    q = request.args.get('category_name', request.args.get('q', '')).strip()
    if not q:
        return ""
        
    try:
        client = get_ms_client()
        res = client.index('categories').search(q, {'limit': 8})
        hits = res.get('hits', [])
        print(f"DEBUG: Category search query='{q}', hits={len(hits)}")
        return render_template('manage/partials/category_options.html', hits=hits)
    except Exception as e:
        print(f"Meilisearch Category Search Error: {e}")
        # Fallback to DB
        cats = Category.query.filter(Category.name.ilike(f"%{q}%")).limit(8).all()
        return render_template('manage/partials/category_options.html', hits=[{'name': c.name} for c in cats])

@manage_bp.context_processor
def inject_management_context():
    def is_active(path):
        current_path = request.path
        if current_path == path or current_path.startswith(path + '/'):
            return 'active'
        return ''
    
    # Global management context
    shop, error = get_managed_shop(current_user)
    managed_shops = []
    if current_user.is_authenticated:
        if current_user.role == USER_ROLE_ADMIN:
            managed_shops = Shop.query.all()
        else:
            managed_shops = current_user.owned_shops
            
    return dict(
        is_active=is_active,
        shop=shop,
        managed_shops=managed_shops
    )

@manage_bp.route('/')
@login_required
@shop_owner_required
def index():
    """Management hub - redirects to products by default"""
    return redirect(url_for('manage_bp.products'))

@manage_bp.route('/switch/<int:shop_id>', methods=['POST'])
@login_required
@shop_owner_required
def switch_shop(shop_id):
    """Switch the active shop in the session"""
    shop = Shop.query.get_or_404(shop_id)
    
    # Verify ownership or admin
    if current_user.role != USER_ROLE_ADMIN and shop.owner_id != current_user.id:
        abort(403)
        
    session['managed_shop_id'] = shop.id
    flash(f"Switched to {shop.name}", "info")
    
    # Redirect back to where they were, or products
    next_url = request.referrer or url_for('manage_bp.products')
    return redirect(next_url)

@manage_bp.route('/products')
@login_required
@shop_owner_required
def products():
    """Main product management page"""
    shop, error = get_managed_shop(current_user)
    if error:
        flash(error, "danger")
        return redirect(url_for('main_bp.index'))
    
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    
    return render_template('manage/products.html', 
                           shop=shop, 
                           categories=categories,
                           managed_shops=current_user.owned_shops if current_user.role != USER_ROLE_ADMIN else Shop.query.all())

@manage_bp.route('/products/list')
@login_required
@shop_owner_required
def product_list():
    """HTMX partial: render product list with search/filter"""
    shop, error = get_managed_shop(current_user)
    if error:
        return f'<div class="alert alert-danger">{error}</div>'
    
    search = request.args.get('search', '').strip()
    filter_status = request.args.get('filter', 'all')
    
    query = Product.query.filter_by(shop_id=shop.id)
    
    if search:
        query = query.filter(db.or_(
            Product.name.ilike(f'%{search}%'),
            Product.code.ilike(f'%{search}%'),
            Product.tags.ilike(f'%{search}%')
        ))
    
    if filter_status == 'active':
        query = query.filter_by(is_active=True)
    elif filter_status == 'inactive':
        query = query.filter_by(is_active=False)
    elif filter_status == 'low':
        query = query.filter(Product.stock <= 10, Product.stock > 0)
    elif filter_status == 'out':
        query = query.filter_by(stock=0)
        
    products = query.order_by(Product.name).all()
    
    return render_template('manage/partials/product_list.html', products=products)

@manage_bp.route('/products/new', methods=['GET', 'POST'])
@login_required
@shop_owner_required
def add_product():
    """HTMX or Full: Add a new product"""
    shop, error = get_managed_shop(current_user)
    if error:
        return f'<div class="alert alert-danger">{error}</div>'
        
    if request.method == 'POST':
        print(f"DEBUG: add_product POST request data: {request.form}")
        try:
            # Simple implementation for now, mirroring seller_bp logic
            name = request.form.get('name', '').strip()
            category_name = request.form.get('category_name', '').strip()
            category_id = request.form.get('category_id')
            
            # Fallback: If category_name is empty but category_id is present, resolve name
            if not category_name and category_id:
                cat = Category.query.get(category_id)
                if cat:
                    category_name = cat.name
            
            price_raw = request.form.get('price', '0').strip()
            stock_raw = request.form.get('stock', '0').strip()
            
            if not name or not category_name:
                print(f"DEBUG: Missing name or category_name. name='{name}', category_name='{category_name}', category_id='{category_id}'")
                return f'<div class="alert alert-danger">Name (got "{name}") and category (got "{category_name}") are required.</div>', 400
                
            try:
                price = float(price_raw) if price_raw else 0.0
                stock = int(stock_raw) if stock_raw else 0
            except ValueError as e:
                return f'<div class="alert alert-danger">Invalid numeric value: {str(e)}</div>', 400

            # 1. Resolve category using Meilisearch (Typo tolerance)
            resolved_category = None
            try:
                client = get_ms_client()
                ms_res = client.index('categories').search(category_name, {'limit': 1})
                if ms_res.get('hits'):
                    hit = ms_res['hits'][0]
                    # Only accept if it's a very close match (Meilisearch handles this well)
                    resolved_category = Category.query.filter_by(name=hit['name']).first()
            except Exception as ms_err:
                print(f"Meilisearch Resolution Error: {ms_err}")

            if not resolved_category:
                # 2. Fallback to AI for spelling check ONLY if Meilisearch missed it
                try:
                    ai_service = AIService()
                    correction_prompt = (
                        f"Check if '{category_name}' is a correctly spelled category name. "
                        "If it has obvious typos, return the corrected version. If it's correct or a new category, return it as is. "
                        "Return only the name."
                    )
                    category_name = ai_service.generate_text(correction_prompt).strip().replace('"', '').replace("'", "")
                except:
                    pass
                
                # Check DB one last time after AI correction
                resolved_category = Category.query.filter(Category.name.ilike(category_name)).first()
                
                if not resolved_category:
                    # 3. Create new category
                    resolved_category = Category(
                        name=category_name,
                        level=CATEGORY_LEVEL_LEAF,
                        is_active=True
                    )
                    db.session.add(resolved_category)
                    db.session.flush()

            product = Product(
                name=name,
                shop_id=shop.id,
                category_id=resolved_category.id,
                price=price,
                stock=stock,
                description=request.form.get('description', ''),
                type_=request.form.get('type_', 'product'),
                is_active=True
            )
            # Note: product.code is automatically generated in Product.__init__
            db.session.add(product)
            db.session.commit()
            
            # If HTMX, return updated list or just success message
            if request.headers.get('HX-Request'):
                 # Trigger a refresh of the list
                 return '<div hx-get="' + url_for('manage_bp.product_list') + '" hx-trigger="load" hx-target="#product-list-container"></div>'
            
            return redirect(url_for('manage_bp.products'))
            
        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc()
            return f'<div class="alert alert-danger">Unexpected error: {str(e)}</div>', 400
        
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    return render_template('manage/partials/product_form_add.html', categories=categories)

@manage_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@shop_owner_required
def edit_product(product_id):
    """HTMX: Render row edit form or Save product edits"""
    shop, error = get_managed_shop(current_user)
    product = Product.query.get_or_404(product_id)
    
    if product.shop_id != shop.id:
        abort(403)
        
    if request.method == 'POST':
        print(f"DEBUG: edit_product POST request data: {request.form}")
        name = request.form.get('name', '').strip()
        price_raw = request.form.get('price', '').strip()
        stock_raw = request.form.get('stock', '').strip()
        
        if not name:
            print("DEBUG: Product name is required.")
            return '<div class="alert alert-danger">Product name is required.</div>', 400
            
        try:
            product.name = name
            product.price = float(price_raw) if price_raw else product.price
            product.stock = int(stock_raw) if stock_raw else product.stock
        except Exception as e:
            print(f"DEBUG: ValueError in edit_product. price_raw='{price_raw}', stock_raw='{stock_raw}'")
            return f'<div class="alert alert-danger">Invalid numeric value: {str(e)}</div>', 400
        
        product.is_active = 'is_active' in request.form
        
        category_name = request.form.get('category_name', '').strip()
        if category_name:
            resolved_category = None
            # 1. Resolve category using Meilisearch (Typo tolerance)
            try:
                client = get_ms_client()
                ms_res = client.index('categories').search(category_name, {'limit': 1})
                if ms_res.get('hits'):
                    hit = ms_res['hits'][0]
                    resolved_category = Category.query.filter_by(name=hit['name']).first()
            except Exception as ms_err:
                print(f"Meilisearch Resolution Error in edit_product: {ms_err}")

            if not resolved_category:
                # 2. Fallback to AI for spelling check
                try:
                    ai_service = AIService()
                    category_name = ai_service.generate_text(f"Fix spelling for category: '{category_name}'. Return only the name.").strip().replace('"', '').replace("'", "")
                except:
                    pass
                
                # Check DB after correction
                resolved_category = Category.query.filter(Category.name.ilike(category_name)).first()
                
                if not resolved_category:
                    # 3. Create new category
                    resolved_category = Category(
                        name=category_name,
                        level=CATEGORY_LEVEL_LEAF,
                        is_active=True
                    )
                    db.session.add(resolved_category)
                    db.session.flush()
            
            product.category_id = resolved_category.id

        product.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        
        return render_template('manage/partials/product_row.html', product=product)
        
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    return render_template('manage/partials/product_row_edit.html', product=product, categories=categories)

@manage_bp.route('/products/<int:product_id>/stock', methods=['POST'])
@login_required
@shop_owner_required
def quick_stock_update(product_id):
    """HTMX: Fast stock ± update"""
    shop, error = get_managed_shop(current_user)
    product = Product.query.get_or_404(product_id)
    
    if product.shop_id != shop.id:
        abort(403)
        
    change = int(request.form.get('change', 0))
    product.stock = max(0, product.stock + change)
    product.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    
    return render_template('manage/partials/stock_badge.html', product=product)

@manage_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
@shop_owner_required
def delete_product(product_id):
    """HTMX: Delete product"""
    shop, error = get_managed_shop(current_user)
    product = Product.query.get_or_404(product_id)
    
    if product.shop_id != shop.id:
        abort(403)
        
    db.session.delete(product)
    db.session.commit()
    
    # Return empty content to remove the row from DOM
    return ""

@manage_bp.route('/shop', methods=['GET', 'POST'])
@login_required
@shop_owner_required
def edit_shop_page():
    """Shop management/editing page"""
    shop, error = get_managed_shop(current_user)
    if error:
        flash(error, "danger")
        return redirect(url_for('main_bp.index'))
    
    if request.method == 'POST':
        shop.name = request.form.get('name', shop.name)
        shop.phone = request.form.get('phone', shop.phone)
        shop.email = request.form.get('email', shop.email)
        shop.town = request.form.get('town', shop.town)
        shop.address = request.form.get('address', shop.address)
        shop.description = request.form.get('description', shop.description)
        shop.is_active = 'is_active' in request.form
        
        shop.last_updated = datetime.now(timezone.utc)
        db.session.commit()
        flash("Shop profile updated successfully.", "success")
        return redirect(url_for('manage_bp.edit_shop_page'))
    
    return render_template('manage/shop_edit.html', shop=shop)
