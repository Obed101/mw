from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, make_response, jsonify
from flask_login import login_required, current_user
from ..extensions import db
from ..models import Shop, Product, Category, USER_ROLE_ADMIN, CATEGORY_LEVEL_LEAF
from ..models.product_model import ProductImage
from ..utils.helpers import shop_owner_required, get_managed_shop
from ..utils.cloudinary_images import process_and_upload_image, delete_image
from ..services.ai_service import AIService
from datetime import datetime, timezone
from flask import current_app
from pathlib import Path
from uuid import uuid4
from werkzeug.utils import secure_filename
# import meilisearch (deprecated)

manage_bp = Blueprint('manage_bp', __name__, url_prefix='/manage')

def get_ms_client():
    # Deprecated: use global search_service
    return None

# Use search_service from app.search
from ..search import search_service


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
        res = search_service.search('categories', q, {'limit': 8})
        hits = res.get('hits', [])
        return render_template('manage/partials/category_options.html', hits=hits)
    except Exception as e:
        current_app.logger.warning(f'Category search failed: {e}')
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
    shop, error = get_managed_shop(current_user, request.args.get('shop_id', type=int))
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

def _apply_product_form_data(product, form):
    """Helper function - Apply product form data to a Product instance."""

    name = form.get('name', '').strip()
    category_name = form.get('category_name', '').strip()
    category_id = form.get('category_id')

    if not name:
        raise ValueError('Product name is required.')

    if not category_name and category_id:
        cat = Category.query.get(category_id)
        if cat:
            category_name = cat.name

    if not category_name:
        raise ValueError('Category is required.')

    price_raw = form.get('price', '0').strip()

    try:
        price = float(price_raw) if price_raw else 0.0
    except ValueError as exc:
        raise ValueError(f'Invalid numeric value: {exc}')

    # Resolve category
    resolved_category = None

    try:
        res = search_service.search('categories', category_name, {'limit': 1})
        if res.get('hits'):
            hit = res['hits'][0]
            resolved_category = Category.query.filter_by(name=hit['name']).first()
    except Exception as ms_err:
        current_app.logger.warning(f'Category resolution via search failed: {ms_err}')
    if not resolved_category:
        try:
            ai_service = AIService()

            corrected = ai_service.generate_text(
                f"""
                Check if "{category_name}" contains spelling mistakes.
                Return only the corrected category name.
                If correct already, return it unchanged.
                """
            ).strip().replace('"', '').replace("'", '')

            category_name = corrected

        except Exception:
            pass

        resolved_category = Category.query.filter(
            Category.name.ilike(category_name)
        ).first()

        if not resolved_category:
            resolved_category = Category(
                name=category_name,
                level=CATEGORY_LEVEL_LEAF,
                is_active=True,
            )
            db.session.add(resolved_category)
            db.session.flush()

    product.name = name
    product.category_id = resolved_category.id
    product.price = price
    product.description = form.get('description', '').strip()
    product.type_ = form.get('type_', 'product')

    specs_raw = form.get('specifications')
    if specs_raw:
        import json
        try:
            specs_dict = json.loads(specs_raw)
            product.set_specifications(specs_dict)
        except Exception:
            pass

    return product

@manage_bp.route('/products/draft', methods=['POST'])
@login_required
@shop_owner_required
def save_product_draft():
    session['product_draft'] = {
        'name': request.form.get('name', ''),
        'category_name': request.form.get('category_name', ''),
        'price': request.form.get('price', ''),
        'stock': request.form.get('stock', ''),
        'description': request.form.get('description', ''),
        'type_': request.form.get('type_', 'product'),
    }

    session.modified = True

    return '', 204


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
            
            product = Product(
                shop_id=shop.id,
                is_active=True
            )

            _apply_product_form_data(product, request.form)

            db.session.add(product)
            db.session.commit()

            session.pop('product_draft', None)
            
            # If HTMX, return updated list or just success message
            if request.headers.get('HX-Request'):
                response = make_response('', 200)
                response.headers['HX-Trigger'] = 'product-added'
                return response
            
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
        
        if not name:
            print("DEBUG: Product name is required.")
            return '<div class="alert alert-danger">Product name is required.</div>', 400
        try:
            _apply_product_form_data(product, request.form)
        except ValueError as exc:
            return (
                f'<div class="alert alert-danger">{str(exc)}</div>',
                400
            )
        product.is_active = 'is_active' in request.form
        product.updated_at = datetime.now(timezone.utc)

        db.session.commit()
        
        return render_template('manage/partials/product_row.html', product=product)
        
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    return render_template('manage/partials/product_row_edit.html', product=product, categories=categories)

def _save_product_image(file_storage, product_id):
    return process_and_upload_image(
        file_storage,
        'market_window/products/images',
        max_dimensions=(1200, 1200),
        entity_type='product',
        entity_id=product_id,
    )


@manage_bp.route('/products/<int:product_id>/images', methods=['POST'])
@login_required
@shop_owner_required
def update_product_images(product_id):
    """HTMX: Save up to 5 images for a product via file upload.
    """
    shop, error = get_managed_shop(current_user)
    product = Product.query.get_or_404(product_id)

    if product.shop_id != shop.id:
        abort(403)

    incoming = []
    incoming_public_ids = {}
    upload_errors = []
    for i in range(1, 6):
        file         = request.files.get(f'file_{i}')
        existing_url = request.form.get(f'existing_url_{i}', '').strip()
        remove       = request.form.get(f'remove_{i}', '')

        if file and file.filename:
            try:
                upload = _save_product_image(file, product_id)
                incoming.append(upload['secure_url'])
                incoming_public_ids[upload['secure_url']] = upload['public_id']
            except Exception as exc:
                upload_errors.append(f'Slot {i}: {exc}')
        elif remove == '1':
            pass
        elif existing_url:
            incoming.append(existing_url)

    if upload_errors:
        current_app.logger.warning('Product image upload errors for product %s: %s', product_id, upload_errors)
        print("upload error = ", upload_errors)
        return (
            '<div class="alert alert-danger">Upload failed. ' + upload_errors[0] + '</div>',
            400,
        )

    # --- Validate type-specific limit ---
    max_allowed = 1 if product.type_ == 'service' else 5
    if len(incoming) > max_allowed:
        return (
            f'<div class="alert alert-danger">'
            f'A {product.type_} can have at most {max_allowed} image(s).</div>',
            400,
        )

    # --- Early exit if nothing changed ---
    if incoming == list(product.image_urls):
        return render_template('manage/partials/product_row.html', product=product)

    try:
        existing_by_url = {rec.storage_key: rec for rec in list(product.image_records)}
        incoming_set    = set(incoming)

        removed_public_ids = []
        for url, rec in list(existing_by_url.items()):
            if url not in incoming_set:
                if rec.cloudinary_public_id:
                    removed_public_ids.append(rec.cloudinary_public_id)
                product.image_records.remove(rec)

        for idx, url in enumerate(incoming):
            if url in existing_by_url:
                rec            = existing_by_url[url]
                rec.sort_order = idx
                rec.is_primary = (idx == 0)
            else:
                product.image_records.append(
                    ProductImage(
                        storage_key=url,
                        cloudinary_public_id=incoming_public_ids.get(url),
                        sort_order=idx,
                        is_primary=(idx == 0),
                    )
                )

        product.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        for public_id in removed_public_ids:
            delete_image(public_id)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Product image record update failed for product %s', product_id)
        return '<div class="alert alert-danger">Image update failed. Please try again.</div>', 400

    return render_template('manage/partials/product_row.html', product=product)

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

@manage_bp.route('/products/<int:product_id>/description', methods=['POST'])
@login_required
@shop_owner_required
def autosave_product_description(product_id):
    """Autosave product description"""
    shop, error = get_managed_shop(current_user)
    product = Product.query.get_or_404(product_id)

    if product.shop_id != shop.id:
        abort(403)

    data = request.get_json(silent=True) or {}
    description = data.get('description', '').strip()

    product.description = description
    product.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Saved'})

@manage_bp.route('/products/<int:product_id>/specifications', methods=['POST'])
@login_required
@shop_owner_required
def autosave_product_specifications(product_id):
    """Autosave product specifications"""
    shop, error = get_managed_shop(current_user)
    product = Product.query.get_or_404(product_id)

    if product.shop_id != shop.id:
        abort(403)

    data = request.get_json(silent=True) or {}
    specifications = data.get('specifications', {})

    product.set_specifications(specifications)
    product.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Saved'})

@manage_bp.route('/shop', methods=['GET', 'POST'])
@login_required
@shop_owner_required
def edit_shop_page():
    """Shop management/editing page"""
    requested_shop_id = request.args.get('shop_id', type=int) or request.form.get('shop_id', type=int)
    shop, error = get_managed_shop(current_user, requested_shop_id)
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
        return redirect(url_for('manage_bp.edit_shop_page', shop_id=shop.id))
    
    return render_template('manage/shop_edit.html', shop=shop)


@manage_bp.route('/shop/autosave', methods=['POST'])
@login_required
@shop_owner_required
def autosave_shop_field():
    """Autosave one shop field from the dashboard."""
    shop, error = get_managed_shop(current_user)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    data = request.get_json(silent=True) or request.form or {}
    field = str(data.get('field') or '').strip()
    value = data.get('value')

    allowed_fields = {
        'name',
        'phone',
        'email',
        'town',
        'address',
        'description',
        'business_type',
        'is_active',
    }
    if field not in allowed_fields:
        return jsonify({'success': False, 'message': 'Unsupported field'}), 400

    if field == 'is_active':
        if isinstance(value, str):
            value = value.strip().lower() in {'1', 'true', 'yes', 'on'}
        else:
            value = bool(value)
        shop.is_active = value
    else:
        value = ('' if value is None else str(value)).strip()
        if field == 'name' and not value:
            return jsonify({'success': False, 'message': 'Shop name is required'}), 400
        if field == 'business_type' and value not in {'sales', 'service', 'both'}:
            return jsonify({'success': False, 'message': 'Invalid business type'}), 400
        setattr(shop, field, value or None)

    shop.last_updated = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Saved',
        'shop': {
            'id': shop.id,
            'name': shop.name,
            'phone': shop.phone,
            'email': shop.email,
            'town': shop.town,
            'address': shop.address,
            'description': shop.description,
            'business_type': shop.business_type,
            'is_active': bool(shop.is_active),
            'last_updated': shop.last_updated.isoformat() if shop.last_updated else None,
        },
    })
