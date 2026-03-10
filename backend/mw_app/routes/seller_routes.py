from flask import Blueprint, jsonify, request, render_template
from flask_jwt_extended import jwt_required
from ..extensions import db
from ..models import Shop, UserFollowShop, User, Product, StockUpdate, VerificationOTP, Notification, UserFavoriteProduct, Category, USER_ROLE_ADMIN, USER_ROLE_SELLER, VERIFICATION_STATUS_VERIFIED, VERIFICATION_STATUS_UNDER_REVIEW, VERIFICATION_STATUS_PENDING
from ..utils.helpers import seller_required
from datetime import datetime, timezone

seller_bp = Blueprint('seller_bp', __name__, url_prefix='/seller')
DEFAULT_PRODUCT_PLACEHOLDER_IMAGE = '/static/images/mw_logo_trans.png'
DEFAULT_SHOP_PLACEHOLDER_IMAGE = '/static/images/mw_logo_trans.png'


def _request_json():
    return request.get_json(silent=True) or {}


def _resolve_seller_id(raw_seller_id=None, body=None):
    if raw_seller_id:
        return raw_seller_id
    if body and body.get('seller_id'):
        return body.get('seller_id')
    return None


def _extract_seller_shop(seller):
    if not seller:
        return None

    shop = getattr(seller, 'owned_shops', None) or getattr(seller, 'shop', None)
    if isinstance(shop, list):
        return shop[0] if shop else None
    return shop


def _load_user_and_shop(user_id, require_shop=True):
    user = User.query.get(user_id)
    if not user:
        return None, None, (
            jsonify({
                'success': False,
                'message': 'User not found'
            }),
            404,
        )

    shop = _extract_seller_shop(user)
    if require_shop and not shop:
        return user, None, (
            jsonify({
                'success': False,
                'message': 'Shop not found for this account'
            }),
            404,
        )
    return user, shop, None


def _promote_user_to_seller(user):
    if not user:
        return False
    if user.role != USER_ROLE_SELLER:
        user.role = USER_ROLE_SELLER
        return True
    return False


def _normalize_gps(gps_value):
    if gps_value is None:
        return None

    gps_text = str(gps_value).strip()
    if not gps_text:
        return None

    parts = [part.strip() for part in gps_text.split(',')]
    if len(parts) != 2:
        return None

    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError:
        return None

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    return f"{lat:.6f},{lng:.6f}"


def _parse_bool(raw_value, default=False):
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')


def _parse_key_list(raw_value):
    if raw_value is None:
        return []

    if isinstance(raw_value, list):
        values = raw_value
    else:
        normalized_text = str(raw_value).replace('\r', '\n')
        values = []
        for line in normalized_text.split('\n'):
            for piece in line.split(','):
                cleaned = piece.strip()
                if cleaned:
                    values.append(cleaned)

    deduped = []
    seen = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _normalize_tags(raw_value):
    if raw_value is None:
        return None

    if isinstance(raw_value, list):
        pieces = raw_value
    else:
        pieces = str(raw_value).replace('\r', '\n').replace('\n', ',').split(',')

    tags = []
    seen = set()
    for piece in pieces:
        cleaned = str(piece).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tags.append(cleaned)

    return ', '.join(tags) if tags else None


def _serialize_shop(shop):
    return {
        'id': shop.id,
        'name': shop.name,
        'description': shop.description,
        'address': shop.address,
        'region': shop.region,
        'district': shop.district,
        'town': shop.town,
        'gps': shop.gps,
        'phone': shop.phone,
        'email': shop.email,
        'is_active': bool(shop.is_active),
        'verification_status': shop.verification_status,
        'phone_verified': bool(shop.phone_verified),
        'email_verified': bool(shop.email_verified),
        'can_request_verification': bool(shop.can_request_verification()),
        'image_urls': shop.image_urls,
        'primary_image_url': shop.primary_image_url,
        'last_updated': shop.last_updated.isoformat() if shop.last_updated else None,
    }


def _serialize_product(product):
    return {
        'id': product.id,
        'name': product.name,
        'code': product.code,
        'type_': product.type_,
        'description': product.description,
        'tags': product.tags,
        'price': float(product.price or 0),
        'stock': product.stock,
        'category_id': product.category_id,
        'category_name': product.category.name if product.category else None,
        'shop_id': product.shop_id,
        'is_active': bool(product.is_active),
        'is_low_stock': product.is_low_stock(),
        'is_out_of_stock': product.is_out_of_stock(),
        'image_urls': product.image_urls,
        'primary_image_url': product.primary_image_url,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
    }


def _load_seller_and_shop(seller_id):
    seller, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
    if error_response:
        return None, None, error_response

    if seller.role != USER_ROLE_SELLER:
        return None, None, (
            jsonify({
                'success': False,
                'message': 'Seller not found'
            }),
            404,
        )

    return seller, shop, None


def _notify_buyers_for_product_stock_change(product, seller_id, old_stock, new_stock):
    favorite_rows = UserFavoriteProduct.query.filter_by(product_id=product.id).all()
    buyer_ids = [row.user_id for row in favorite_rows]
    if not buyer_ids:
        return

    Notification.create_for_users(
        user_ids=buyer_ids,
        notification_type='favorite_product_stock_updated',
        title='Favorite Product Update',
        message=f'"{product.name}" stock changed from {old_stock} to {new_stock}.',
        actor_user_id=seller_id,
        related_shop_id=product.shop_id,
        related_product_id=product.id,
        payload={
            'product_id': product.id,
            'old_stock': old_stock,
            'new_stock': new_stock,
        },
    )

@seller_bp.route("/")
@seller_required
def seller_dashboard():
    """Seller dashboard with shop overview and product statistics"""
    # return jsonify({"message": "Seller dashboard"})
    return render_template("seller/seller_dashboard.html")

@seller_bp.route("/shop")
def my_shop():
    """Get seller's shop information"""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        _, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response

        return jsonify({
            'success': True,
            'shop': _serialize_shop(shop),
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shop information',
            'error': str(e),
        }), 500

@seller_bp.route("/shop", methods=["POST"])
def create_shop():
    """Create a shop for an authenticated account (supports non-seller onboarding)."""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        owner, existing_shop, error_response = _load_user_and_shop(seller_id, require_shop=False)
        if error_response:
            return error_response

        if existing_shop:
            return jsonify({
                'success': False,
                'message': 'A shop already exists for this account',
                'shop': _serialize_shop(existing_shop),
            }), 409

        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({
                'success': False,
                'message': 'Shop name is required'
            }), 400

        raw_gps = str(data.get('gps') or '').strip()
        normalized_gps = None
        if raw_gps:
            normalized_gps = _normalize_gps(raw_gps)
            if not normalized_gps:
                return jsonify({
                    'success': False,
                    'message': 'GPS must use "lat,lng" format with valid coordinates'
                }), 400

        image_input = data.get('image_urls')
        if image_input is None:
            image_input = data.get('image_keys')
        image_keys = _parse_key_list(image_input)
        if not image_keys:
            image_keys = [DEFAULT_SHOP_PLACEHOLDER_IMAGE]

        shop = Shop(
            name=name,
            description=str(data.get('description') or '').strip() or None,
            address=str(data.get('address') or '').strip() or None,
            region=str(data.get('region') or '').strip() or None,
            district=str(data.get('district') or '').strip() or None,
            town=str(data.get('town') or '').strip() or None,
            gps=normalized_gps,
            phone=str(data.get('phone') or '').strip() or None,
            email=str(data.get('email') or '').strip() or None,
            is_active=_parse_bool(data.get('is_active'), default=True),
            owner_id=owner.id,
        )
        shop.replace_image_urls(image_keys)

        db.session.add(shop)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Shop created successfully',
            'shop': _serialize_shop(shop),
        }), 201

    except ValueError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e),
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error creating shop',
            'error': str(e),
        }), 500

@seller_bp.route("/shop", methods=["PUT"])
def update_shop():
    """Update shop information"""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        _, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response

        if 'name' in data:
            name = str(data.get('name') or '').strip()
            if not name:
                return jsonify({
                    'success': False,
                    'message': 'Shop name is required'
                }), 400
            shop.name = name

        if 'description' in data:
            description = str(data.get('description') or '').strip()
            shop.description = description or None

        if 'phone' in data:
            phone = str(data.get('phone') or '').strip()
            shop.phone = phone or None

        if 'email' in data:
            email = str(data.get('email') or '').strip()
            shop.email = email or None

        if 'address' in data:
            address = str(data.get('address') or '').strip()
            shop.address = address or None

        if 'region' in data:
            region = str(data.get('region') or '').strip()
            shop.region = region or None

        if 'district' in data:
            district = str(data.get('district') or '').strip()
            shop.district = district or None

        if 'town' in data:
            town = str(data.get('town') or '').strip()
            shop.town = town or None

        if 'gps' in data:
            raw_gps = str(data.get('gps') or '').strip()
            if raw_gps:
                normalized_gps = _normalize_gps(raw_gps)
                if not normalized_gps:
                    return jsonify({
                        'success': False,
                        'message': 'GPS must use "lat,lng" format with valid coordinates'
                    }), 400
                shop.gps = normalized_gps
            else:
                shop.gps = None

        if 'is_active' in data:
            shop.is_active = _parse_bool(data.get('is_active'), default=bool(shop.is_active))

        if 'image_urls' in data or 'image_keys' in data:
            raw_images = data.get('image_urls')
            if raw_images is None:
                raw_images = data.get('image_keys')
            image_keys = _parse_key_list(raw_images)
            if not image_keys:
                image_keys = [DEFAULT_SHOP_PLACEHOLDER_IMAGE]
            shop.replace_image_urls(image_keys)

        shop.last_updated = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Shop updated successfully',
            'shop': _serialize_shop(shop),
        }), 200

    except ValueError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e),
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating shop',
            'error': str(e),
        }), 500


@seller_bp.route("/notifications")
def get_seller_notifications():
    """Get notifications for seller account."""
    try:
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), _request_json())
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        seller, _, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        unread_only = request.args.get('unread_only', '').lower() in ('1', 'true', 'yes')
        limit = min(max(request.args.get('limit', 20, type=int), 1), 100)

        query = Notification.query.filter_by(recipient_user_id=seller.id)
        if unread_only:
            query = query.filter_by(is_read=False)

        notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
        unread_count = Notification.query.filter_by(
            recipient_user_id=seller.id,
            is_read=False,
        ).count()

        return jsonify({
            'success': True,
            'seller_id': seller.id,
            'count': len(notifications),
            'unread_count': unread_count,
            'notifications': [notification.to_dict() for notification in notifications],
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching seller notifications',
            'error': str(e)
        }), 500


@seller_bp.route("/notifications/<int:notification_id>/read", methods=["PATCH"])
def mark_seller_notification_read(notification_id):
    """Mark a seller notification as read."""
    try:
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), _request_json())
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        seller, _, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        notification = Notification.query.filter_by(
            id=notification_id,
            recipient_user_id=seller.id,
        ).first()
        if not notification:
            return jsonify({
                'success': False,
                'message': 'Notification not found'
            }), 404

        if not notification.is_read:
            notification.mark_read()
            db.session.commit()

        return jsonify({
            'success': True,
            'notification': notification.to_dict(),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error marking notification as read',
            'error': str(e)
        }), 500


@seller_bp.route("/notifications/read-all", methods=["POST"])
def mark_all_seller_notifications_read():
    """Mark all seller notifications as read."""
    try:
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), _request_json())
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        seller, _, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        notifications = Notification.query.filter_by(
            recipient_user_id=seller.id,
            is_read=False,
        ).all()

        for notification in notifications:
            notification.mark_read()

        db.session.commit()
        return jsonify({
            'success': True,
            'updated': len(notifications),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error marking notifications as read',
            'error': str(e)
        }), 500

@seller_bp.route("/products")
def my_products():
    """Get all products in seller's shop with filtering"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response
        
        # Get query parameters
        search = request.args.get('search', '').strip()
        in_stock = request.args.get('in_stock')
        low_stock = request.args.get('low_stock')
        out_of_stock = request.args.get('out_of_stock')
        low_stock_threshold = request.args.get('low_stock_threshold', 10, type=int)
        needs_update = request.args.get('needs_update')  # Shows low/out of stock items
        
        # Build query
        query = Product.query.filter_by(shop_id=shop.id)
        
        # Filter by search term
        if search:
            query = query.filter(
                db.or_(
                    Product.name.ilike(f'%{search}%'),
                    Product.description.ilike(f'%{search}%')
                )
            )
        
        # Filter by stock status
        if in_stock and in_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(Product.stock > 0)
        
        if out_of_stock and out_of_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(Product.stock <= 0)
        
        if low_stock and low_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(
                db.and_(
                    Product.stock > 0,
                    Product.stock <= low_stock_threshold
                )
            )
        
        if needs_update and needs_update.lower() in ('true', '1', 'yes'):
            # Show products that need attention (low or out of stock)
            query = query.filter(Product.stock <= low_stock_threshold)
        
        # Order by stock (lowest first) if filtering by stock issues
        if needs_update or low_stock or out_of_stock:
            query = query.order_by(Product.stock.asc(), Product.name.asc())
        else:
            query = query.order_by(Product.name.asc())
        
        products = query.all()
        
        # Build response
        products_list = []
        for product in products:
            product_dict = {
                'id': product.id,
                'code': product.code,
                'name': product.name,
                'type_': product.type_,
                'description': product.description,
                'tags': product.tags,
                'price': product.price,
                'stock': product.stock,
                'is_low_stock': product.is_low_stock(low_stock_threshold),
                'is_out_of_stock': product.is_out_of_stock(),
                'category_id': product.category_id,
                'category_name': product.category.name if product.category else None,
                'is_active': product.is_active,
                'image_urls': product.image_urls,
                'primary_image_url': product.primary_image_url,
                'updated_at': product.updated_at.isoformat() if product.updated_at else None,
            }
            products_list.append(product_dict)
        
        return jsonify({
            'success': True,
            'count': len(products_list),
            'products': products_list
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching products',
            'error': str(e)
        }), 500

@seller_bp.route("/products", methods=["POST"])
def add_product():
    """Add a new product to the shop"""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({
                'success': False,
                'message': 'Product name is required'
            }), 400

        category_id = data.get('category_id')
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'message': 'A valid category is required'
            }), 400

        category = Category.query.filter_by(id=category_id, is_active=True).first()
        if not category:
            return jsonify({
                'success': False,
                'message': 'Category not found or inactive'
            }), 404

        try:
            price = float(data.get('price'))
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'message': 'Price must be a number'
            }), 400
        if price < 0:
            return jsonify({
                'success': False,
                'message': 'Price cannot be negative'
            }), 400

        raw_stock = data.get('stock', 0)
        try:
            stock = int(raw_stock)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'message': 'Stock must be an integer'
            }), 400
        if stock < 0:
            return jsonify({
                'success': False,
                'message': 'Stock cannot be negative'
            }), 400

        product_type = str(data.get('type_') or 'product').strip().lower()
        if product_type not in ('product', 'service'):
            return jsonify({
                'success': False,
                'message': 'type_ must be either "product" or "service"'
            }), 400

        code = str(data.get('code') or '').strip() or Product.generate_code()
        description = str(data.get('description') or '').strip() or None
        tags = _normalize_tags(data.get('tags'))
        is_active = _parse_bool(data.get('is_active'), default=True)

        product = Product(
            name=name,
            code=code,
            type_=product_type,
            description=description,
            tags=tags,
            price=price,
            stock=stock,
            shop_id=shop.id,
            category_id=category_id,
            is_active=is_active,
        )

        image_input = data.get('image_urls')
        if image_input is None:
            image_input = data.get('image_keys')
        image_keys = _parse_key_list(image_input)
        if not image_keys:
            image_keys = [DEFAULT_PRODUCT_PLACEHOLDER_IMAGE]
        product.replace_image_urls(image_keys)

        db.session.add(product)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Product added successfully',
            'product': _serialize_product(product),
        }), 201

    except ValueError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error adding product',
            'error': str(e)
        }), 500

@seller_bp.route("/products/<int:product_id>")
def get_product(product_id):
    """Get a specific product details"""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404

        return jsonify({
            'success': True,
            'product': _serialize_product(product),
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching product',
            'error': str(e)
        }), 500

@seller_bp.route("/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    """Update product information (name, price, stock, images, description)"""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404

        if 'name' in data:
            name = str(data.get('name') or '').strip()
            if not name:
                return jsonify({
                    'success': False,
                    'message': 'Product name is required'
                }), 400
            product.name = name

        if 'description' in data:
            description = str(data.get('description') or '').strip()
            product.description = description or None

        if 'price' in data:
            try:
                price = float(data.get('price'))
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'message': 'Price must be a number'
                }), 400
            if price < 0:
                return jsonify({
                    'success': False,
                    'message': 'Price cannot be negative'
                }), 400
            product.price = price

        if 'stock' in data:
            try:
                stock = int(data.get('stock'))
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'message': 'Stock must be an integer'
                }), 400
            if stock < 0:
                return jsonify({
                    'success': False,
                    'message': 'Stock cannot be negative'
                }), 400
            product.stock = stock

        if 'category_id' in data:
            try:
                category_id = int(data.get('category_id'))
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'message': 'A valid category is required'
                }), 400

            category = Category.query.filter_by(id=category_id, is_active=True).first()
            if not category:
                return jsonify({
                    'success': False,
                    'message': 'Category not found or inactive'
                }), 404
            product.category_id = category_id

        if 'code' in data:
            code = str(data.get('code') or '').strip()
            if not code:
                return jsonify({
                    'success': False,
                    'message': 'Code cannot be empty'
                }), 400
            product.code = code

        if 'type_' in data:
            product_type = str(data.get('type_') or '').strip().lower()
            if product_type not in ('product', 'service'):
                return jsonify({
                    'success': False,
                    'message': 'type_ must be either "product" or "service"'
                }), 400
            product.type_ = product_type

        if 'tags' in data:
            product.tags = _normalize_tags(data.get('tags'))

        if 'is_active' in data:
            product.is_active = _parse_bool(data.get('is_active'), default=bool(product.is_active))

        if 'image_urls' in data or 'image_keys' in data:
            raw_images = data.get('image_urls')
            if raw_images is None:
                raw_images = data.get('image_keys')
            image_keys = _parse_key_list(raw_images)
            if not image_keys:
                image_keys = [DEFAULT_PRODUCT_PLACEHOLDER_IMAGE]
            product.replace_image_urls(image_keys)

        product.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Product updated successfully',
            'product': _serialize_product(product),
        }), 200

    except ValueError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating product',
            'error': str(e)
        }), 500

@seller_bp.route("/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    """Remove a product from the shop"""
    try:
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)

        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400

        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response

        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404

        db.session.delete(product)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Product deleted successfully',
            'product_id': product_id,
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error deleting product',
            'error': str(e)
        }), 500

# Stock Management Routes
@seller_bp.route("/products/<int:product_id>/stock", methods=["PATCH"])
def update_stock(product_id):
    """Quick stock update - supports both absolute and incremental updates"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response
        
        # Get product and verify ownership
        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404
        
        # Get update data
        stock = data.get('stock')
        stock_change = data.get('stock_change')
        reason = data.get('reason', '').strip()
        if not reason:
            # Determine type of stock update for autogenerated reason
            if stock is not None:
                # Absolute stock change
                if int(stock) > product.stock:
                    reason = "restocked"
                elif int(stock) < product.stock:
                    reason = "goods sold"
                else:
                    reason = "stock adjusted"
            elif stock_change is not None:
                if int(stock_change) > 0:
                    reason = "restocked"
                elif int(stock_change) < 0:
                    reason = "goods sold"
                else:
                    reason = "stock adjusted"
            else:
                reason = "stock adjusted"
        
        # Validate that either stock or stock_change is provided
        if stock is None and stock_change is None:
            return jsonify({
                'success': False,
                'message': 'Either "stock" (absolute value) or "stock_change" (incremental) is required'
            }), 400
        
        # Calculate new stock
        old_stock = product.stock
        if stock is not None:
            # Absolute stock update
            new_stock = int(stock)
            stock_change = new_stock - old_stock
        else:
            # Incremental stock update
            stock_change = int(stock_change)
            new_stock = old_stock + stock_change
            # Prevent negative stock
            if new_stock < 0:
                new_stock = 0
                stock_change = -old_stock
        
        # Update product stock
        product.stock = new_stock
        product.updated_at = datetime.now(timezone.utc)
        
        # Create stock update history record
        stock_update = StockUpdate(
            product_id=product_id,
            old_stock=old_stock,
            new_stock=new_stock,
            stock_change=stock_change,
            updated_by=seller_id,
            reason=reason
        )
        
        db.session.add(stock_update)
        _notify_buyers_for_product_stock_change(
            product=product,
            seller_id=seller_id,
            old_stock=old_stock,
            new_stock=new_stock,
        )
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Stock updated successfully',
            'product': {
                'id': product.id,
                'name': product.name,
                'old_stock': old_stock,
                'new_stock': new_stock,
                'stock_change': stock_change,
                'is_low_stock': product.is_low_stock(),
                'is_out_of_stock': product.is_out_of_stock()
            },
            'update': stock_update.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Invalid stock value',
            'error': str(e)
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating stock',
            'error': str(e)
        }), 500

@seller_bp.route("/products/stock/bulk", methods=["POST"])
def bulk_update_stock():
    """Bulk update stock for multiple products"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response
        
        # Get updates array
        updates = data.get('updates', [])
        if not updates or not isinstance(updates, list):
            return jsonify({
                'success': False,
                'message': 'Updates array is required'
            }), 400
        
        results = []
        errors = []
        
        for update_item in updates:
            try:
                product_id = update_item.get('product_id')
                stock = update_item.get('stock')
                stock_change = update_item.get('stock_change')
                reason = update_item.get('reason', '').strip() or None
                
                if not product_id:
                    errors.append({'product_id': None, 'error': 'Product ID is required'})
                    continue
                
                # Get product and verify ownership
                product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
                if not product:
                    errors.append({'product_id': product_id, 'error': 'Product not found or does not belong to your shop'})
                    continue
                
                # Calculate new stock
                old_stock = product.stock
                if stock is not None:
                    new_stock = int(stock)
                    stock_change = new_stock - old_stock
                elif stock_change is not None:
                    stock_change = int(stock_change)
                    new_stock = old_stock + stock_change
                    if new_stock < 0:
                        new_stock = 0
                        stock_change = -old_stock
                else:
                    errors.append({'product_id': product_id, 'error': 'Either "stock" or "stock_change" is required'})
                    continue
                
                # Update product
                product.stock = new_stock
                product.updated_at = datetime.now(timezone.utc)
                
                # Create stock update history
                stock_update = StockUpdate(
                    product_id=product_id,
                    old_stock=old_stock,
                    new_stock=new_stock,
                    stock_change=stock_change,
                    updated_by=seller_id,
                    reason=reason
                )
                db.session.add(stock_update)
                _notify_buyers_for_product_stock_change(
                    product=product,
                    seller_id=seller_id,
                    old_stock=old_stock,
                    new_stock=new_stock,
                )
                
                results.append({
                    'product_id': product_id,
                    'product_name': product.name,
                    'old_stock': old_stock,
                    'new_stock': new_stock,
                    'stock_change': stock_change
                })
                
            except ValueError as e:
                errors.append({'product_id': product_id, 'error': f'Invalid stock value: {str(e)}'})
                continue
            except Exception as e:
                errors.append({'product_id': product_id, 'error': str(e)})
                continue
        
        if results:
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {len(results)} product(s)',
            'updated': results,
            'errors': errors if errors else None
        }), 200 if not errors else 207  # 207 Multi-Status if there are errors
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error performing bulk update',
            'error': str(e)
        }), 500

@seller_bp.route("/products/<int:product_id>/stock/history")
def get_stock_history(product_id):
    """Get stock update history for a product"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = _extract_seller_shop(seller)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Verify product belongs to shop
        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404
        
        # Get history
        limit = request.args.get('limit', 50, type=int)
        history = StockUpdate.query.filter_by(product_id=product_id).order_by(
            StockUpdate.updated_at.desc()
        ).limit(limit).all()
        
        return jsonify({
            'success': True,
            'product_id': product_id,
            'product_name': product.name,
            'current_stock': product.stock,
            'count': len(history),
            'history': [update.to_dict() for update in history]
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching stock history',
            'error': str(e)
        }), 500


@seller_bp.route("/shop/followers")
def get_shop_followers():
    """Get all followers of the seller's shop"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        _, shop, error_response = _load_seller_and_shop(seller_id)
        if error_response:
            return error_response
        
        # Get all followers
        follows = UserFollowShop.query.filter_by(shop_id=shop.id).order_by(
            UserFollowShop.followed_at.desc()
        ).all()
        
        # Get follower details
        followers = []
        for follow in follows:
            user = User.query.get(follow.user_id)
            if user and user.is_active:
                follower_dict = {
                    'user_id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'followed_at': follow.followed_at.isoformat() if follow.followed_at else None
                }
                followers.append(follower_dict)
        
        return jsonify({
            'success': True,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'follower_count': len(followers),
            'followers': followers
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shop followers',
            'error': str(e)
        }), 500

@seller_bp.route("/analytics")
def shop_analytics():
    """View shop analytics (views, popular products, followers, etc.)"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = _extract_seller_shop(seller)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get follower count
        follower_count = UserFollowShop.query.filter_by(shop_id=shop.id).count()
        
        # Product analytics
        total_products = len(shop.products) if shop.products else 0
        active_products = len([p for p in shop.products if p.is_active]) if shop.products else 0
        out_of_stock = len([p for p in shop.products if p.stock <= 0]) if shop.products else 0
        low_stock = len([p for p in shop.products if 0 < p.stock <= 10]) if shop.products else 0
        
        # Stock value calculation
        total_stock_value = sum(p.stock * p.price for p in shop.products if p.is_active) if shop.products else 0
        
        # Shop performance metrics
        verification_status = shop.verification_status
        phone_verified = shop.phone_verified
        email_verified = shop.email_verified
        
        return jsonify({
            'success': True,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'analytics': {
                'followers': {
                    'count': follower_count,
                    'growth': '+12%'  # TODO: Calculate actual growth
                },
                'products': {
                    'total': total_products,
                    'active': active_products,
                    'out_of_stock': out_of_stock,
                    'low_stock': low_stock,
                    'stock_value': round(total_stock_value, 2)
                },
                'verification': {
                    'status': verification_status,
                    'phone_verified': phone_verified,
                    'email_verified': email_verified,
                    'can_request_verification': shop.can_request_verification()
                },
                'performance': {
                    'completion_score': 85,  # TODO: Calculate based on profile completeness
                    'last_updated': shop.last_updated.isoformat() if shop.last_updated else None
                }
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shop analytics',
            'error': str(e)
        }), 500

# Shop Verification Routes
@seller_bp.route("/shop/verification-status")
def get_verification_status():
    """Get shop verification status and requirements"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = _extract_seller_shop(seller)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        return jsonify({
            'success': True,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'verification_status': shop.verification_status if shop.verification_status else None,
            'phone_verified': shop.phone_verified,
            'email_verified': shop.email_verified,
            'can_request_verification': shop.can_request_verification(),
            'verification_requested_at': shop.verification_requested_at.isoformat() if shop.verification_requested_at else None,
            'verified_at': shop.verified_at.isoformat() if shop.verified_at else None,
            'rejection_reason': shop.rejection_reason
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching verification status',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-phone/request-otp", methods=["POST"])
def request_phone_otp():
    """Request OTP for phone verification"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get account shop (supports non-seller onboarding)
        _, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response
        
        if not shop.phone:
            return jsonify({
                'success': False,
                'message': 'Shop phone number is not set'
            }), 400
        
        if shop.phone_verified:
            return jsonify({
                'success': False,
                'message': 'Phone is already verified'
            }), 400
        
        # Generate and create OTP
        otp_record, otp_code = VerificationOTP.create_otp(
            shop_id=shop.id,
            otp_type='phone',
            contact_value=shop.phone
        )
        
        # TODO: Send OTP via SMS service (Twilio, etc.)
        # For now, return OTP in response for testing
        return jsonify({
            'success': True,
            'message': 'OTP sent to phone',
            'otp': otp_code,  # Remove in production - only for testing
            'expires_in_minutes': 15,
            'phone': shop.phone[-4:]  # Show last 4 digits only
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error requesting phone OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-phone/verify", methods=["POST"])
def verify_phone_otp():
    """Verify phone using OTP"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        otp_code = data.get('otp')
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        if not otp_code:
            return jsonify({
                'success': False,
                'message': 'OTP code is required'
            }), 400
        
        # Get account shop (supports non-seller onboarding)
        seller, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response
        
        # Get active OTP
        otp_record = VerificationOTP.get_active_otp(shop.id, 'phone')
        if not otp_record:
            return jsonify({
                'success': False,
                'message': 'No active OTP found. Please request a new one.'
            }), 404
        
        # Verify OTP
        is_valid, message = otp_record.verify_otp(otp_code)
        if not is_valid:
            return jsonify({
                'success': False,
                'message': message
            }), 400
        
        # Mark phone as verified
        shop.phone_verified = True
        if shop.phone_verified and shop.email_verified:
            _promote_user_to_seller(seller)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Phone verified successfully',
            'phone_verified': True
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error verifying phone OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-email/request-otp", methods=["POST"])
def request_email_otp():
    """Request OTP for email verification"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get account shop (supports non-seller onboarding)
        _, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response
        
        if not shop.email:
            return jsonify({
                'success': False,
                'message': 'Shop email is not set'
            }), 400
        
        if shop.email_verified:
            return jsonify({
                'success': False,
                'message': 'Email is already verified'
            }), 400
        
        # Generate and create OTP
        otp_record, otp_code = VerificationOTP.create_otp(
            shop_id=shop.id,
            otp_type='email',
            contact_value=shop.email
        )
        
        # TODO: Send OTP via email service (SendGrid, etc.)
        # For now, return OTP in response for testing
        return jsonify({
            'success': True,
            'message': 'OTP sent to email',
            'otp': otp_code,  # Remove in production - only for testing
            'expires_in_minutes': 15,
            'email': shop.email  # For testing only
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error requesting email OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-email/verify", methods=["POST"])
def verify_email_otp():
    """Verify email using OTP"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        otp_code = data.get('otp')
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        if not otp_code:
            return jsonify({
                'success': False,
                'message': 'OTP code is required'
            }), 400
        
        # Get account shop (supports non-seller onboarding)
        seller, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response
        
        # Get active OTP
        otp_record = VerificationOTP.get_active_otp(shop.id, 'email')
        if not otp_record:
            return jsonify({
                'success': False,
                'message': 'No active OTP found. Please request a new one.'
            }), 404
        
        # Verify OTP
        is_valid, message = otp_record.verify_otp(otp_code)
        if not is_valid:
            return jsonify({
                'success': False,
                'message': message
            }), 400
        
        # Mark email as verified
        shop.email_verified = True
        if shop.phone_verified and shop.email_verified:
            _promote_user_to_seller(seller)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Email verified successfully',
            'email_verified': True
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error verifying email OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/request-verification", methods=["POST"])
def request_verification():
    """Request shop verification (after phone and email are verified)"""
    try:
        # Get seller's user_id from request
        data = _request_json()
        seller_id = _resolve_seller_id(request.args.get('seller_id', type=int), data)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        seller, shop, error_response = _load_user_and_shop(seller_id, require_shop=True)
        if error_response:
            return error_response
        
        # Check if phone and email are verified
        if not shop.phone_verified:
            return jsonify({
                'success': False,
                'message': 'Phone must be verified before requesting shop verification'
            }), 400
        
        if not shop.email_verified:
            return jsonify({
                'success': False,
                'message': 'Email must be verified before requesting shop verification'
            }), 400
        
        # Check if already verified or under review
        if shop.verification_status == VERIFICATION_STATUS_VERIFIED:
            return jsonify({
                'success': False,
                'message': 'Shop is already verified'
            }), 400
        
        if shop.verification_status == VERIFICATION_STATUS_UNDER_REVIEW:
            return jsonify({
                'success': False,
                'message': 'Shop verification is already under review'
            }), 400
        
        # Request verification
        shop.verification_status = VERIFICATION_STATUS_PENDING
        shop.verification_requested_at = datetime.now(timezone.utc)
        _promote_user_to_seller(seller)
        admin_ids = [admin.id for admin in User.query.filter_by(role=USER_ROLE_ADMIN).all()]
        Notification.create_for_users(
            user_ids=admin_ids,
            notification_type='shop_verification_requested',
            title='Shop Verification Request',
            message=f'"{shop.name}" has requested verification review.',
            actor_user_id=seller.id,
            related_shop_id=shop.id,
            payload={
                'shop_id': shop.id,
                'seller_id': seller.id,
            },
        )
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Verification request submitted. Admin will review your shop.',
            'verification_status': shop.verification_status,
            'verification_requested_at': shop.verification_requested_at.isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error requesting verification',
            'error': str(e)
        }), 500


