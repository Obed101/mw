from ..services.email_service import send_welcome_email
from flask import request, jsonify, url_for, redirect, flash, Blueprint, session
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt
from flask_login import login_user, logout_user, current_user
from datetime import datetime, timezone
from sqlalchemy import func
from ..extensions import db, token_blacklist
from ..models.user_model import User, USER_STATUS_ACTIVE, USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER, AuthToken
from ..models.engagement_model import Notification
from ..services.analytics_service import track_event

# Notification types - defined as module-level constants for import
NOTIFICATION_TYPE_LOCATION_SETUP = 'home_location_setup'
NOTIFICATION_TYPE_PHONE_SETUP = 'phone_number_setup'

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user.

    Accepts:
      - full_name (required): auto-split into first_name / last_name; username generated from it
      - email (optional): stored as-is; left NULL if not provided
      - password + confirm_password (required for non-OAuth)
      - phone (optional)
      - is_oauth (bool): skip password validation for OAuth flow
      - terms (required)
    """
    from ..utils.username_utils import generate_username

    # Handle both JSON and form data
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    is_oauth = data.get('is_oauth', False)

    # ── Required field validation ─────────────────────────────────────────────
    if not data.get('full_name', '').strip():
        error_msg = "Full name is required"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('main_bp.register'))

    if not is_oauth:
        if not data.get('password'):
            error_msg = "Password is required"
            if request.is_json:
                return jsonify({"error": error_msg}), 400
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))

        if data.get('password') != data.get('confirm_password'):
            error_msg = "Passwords do not match"
            if request.is_json:
                return jsonify({"error": error_msg}), 400
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))

    # ── Terms ─────────────────────────────────────────────────────────────────
    if not data.get('terms'):
        error_msg = "You must agree to the terms of service"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('main_bp.register'))

    # ── Role ──────────────────────────────────────────────────────────────────
    role = (data.get('role') or USER_ROLE_BUYER).strip()
    valid_roles = [USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER]
    if role not in valid_roles:
        error_msg = "Invalid role"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('main_bp.register'))

    # ── Email uniqueness (only if provided) ───────────────────────────────────
    email = (data.get('email') or '').strip().lower() or None
    if email and User.query.filter(func.lower(User.email) == email).first():
        error_msg = "Email already registered"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('main_bp.register'))

    # ── Auto-generate username from full name ─────────────────────────────────
    full_name = data['full_name'].strip()
    username, first_name, last_name = generate_username(full_name)

    # ── Create user ───────────────────────────────────────────────────────────
    try:
        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            status=USER_STATUS_ACTIVE
        )

        if not is_oauth:
            user.set_password(data['password'])

        # Optional extra fields
        if data.get('phone'):
            user.phone = data['phone'].strip()
        if data.get('region'):
            user.region = data['region']
        if data.get('district'):
            user.district = data['district']
        if data.get('town'):
            user.town = data['town']

        db.session.add(user)
        db.session.commit()

        user.update_last_login()
        login_user(user)
        track_event('signup', user)

        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)

        send_welcome_email(user)
        _check_and_create_location_notification(user)
        _check_and_create_phone_notification(user)

        if request.is_json:
            return jsonify({
                "message": "User registered successfully",
                "user": user.to_dict(),
                "username": username,
                "access_token": access_token,
                "refresh_token": refresh_token
            }), 201
        else:
            flash(f'Account created! Your username is <strong>{username}</strong>', 'success')
            return redirect(url_for('main_bp.login'))

    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({"error": str(e)}), 500
        flash('An error occurred during registration. Please try again.', 'error')
        return redirect(url_for('main_bp.register'))

@auth_bp.route('/login', methods=['POST'])
def login():
    """User login"""
    # Handle both JSON and form data
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    
    # Validate required fields
    identifier = ''
    if data:
        identifier = (data.get('username') or data.get('email') or '').strip()

    if not identifier:
        error_msg = "Username or email is required"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # Check if this is OAuth login (no password required)
    is_oauth = data.get('is_oauth', False)
    
    if not is_oauth and not data.get('password'):
        error_msg = "Password is required"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # Find user (try username first, then email)
    user = User.query.filter_by(username=identifier).first()
    if not user:
        user = User.query.filter(func.lower(User.email) == identifier.lower()).first()
    
    if not user:
        error_msg = "Invalid username/email"
        if request.is_json:
            return jsonify({"error": error_msg}), 401
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # For OAuth users, no password check needed
    if not is_oauth:
        if not user.password_hash or not user.check_password(data['password']):
            error_msg = "Invalid password"
            if request.is_json:
                return jsonify({"error": error_msg}), 401
            else:
                flash(error_msg, 'error')
                return redirect(url_for('main_bp.login'))
    
    # Check if user is active
    if not user.is_active():
        error_msg = "Account is not active"
        if request.is_json:
            return jsonify({"error": error_msg}), 401
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # Update last login
    user.update_last_login()
    
    # Log user in with Flask-Login for session management
    login_user(user, remember=True)
    track_event('login', user)
    
    # Generate tokens for API usage
    access_token = create_access_token(identity=user.id)
    refresh_token = create_refresh_token(identity=user.id)
    
    # Check if user needs location or phone setup notification
    _check_and_create_location_notification(user)
    _check_and_create_phone_notification(user)
    
    # Handle form vs API responses
    if request.is_json:
        return jsonify({
            "message": "Login successful",
            "user": user.to_dict(),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer"
        }), 200
    else:
        # For form submissions, flash message and redirect to appropriate dashboard
        flash(f'Welcome back! {user.first_name} {user.last_name}', 'success')
        
        next_page = session.pop('prev', None)
        if next_page:
            return redirect(next_page)
        else:
            return redirect(url_for('main_bp.index'))

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token"""
    current_user_id = get_jwt_identity()
    access_token = create_access_token(identity=current_user_id)
    return jsonify({"access_token": access_token}), 200

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout user"""
    if current_user and not current_user.is_anonymous:
        track_event('logout', current_user)

    if request.is_json:
        jti = get_jwt()['jti']
        token_blacklist.add(jti)
        return jsonify({"message": "Successfully logged out"}), 200

    logout_user()
    flash('You have been logged out successfully.', 'success')

    next_page = request.referrer
    return redirect(next_page or url_for('main_bp.index'))

@auth_bp.route('/revoke', methods=['POST'])
@jwt_required()
def revoke_token():
    """Revoke a specific token"""
    data = request.get_json()
    if not data or not data.get('token'):
        return jsonify({"error": "Token is required"}), 400
    
    try:
        # Add to blacklist
        token_blacklist.add(data['token'])
        
        # Also mark as used in database
        auth_token = AuthToken.query.filter_by(token=data['token']).first()
        if auth_token and auth_token.user_id == get_jwt_identity():
            auth_token.mark_as_used()
            return jsonify({"message": "Token revoked successfully"}), 200
        else:
            return jsonify({"error": "Invalid token"}), 404
    except Exception as e:
        return jsonify({"error": "Error revoking token"}), 500

@auth_bp.route('/tokens', methods=['GET'])
@jwt_required()
def list_active_tokens():
    """List all active tokens for the current user"""
    current_user_id = get_jwt_identity()
    
    try:
        tokens = AuthToken.query.filter_by(
            user_id=current_user_id,
            is_used=False
        ).filter(
            AuthToken.expires_at > datetime.now(timezone.utc)
        ).all()
        
        return jsonify({
            "tokens": [
                {
                    "id": token.id,
                    "token_type": token.token_type,
                    "created_at": token.created_at.isoformat(),
                    "expires_at": token.expires_at.isoformat()
                }
                for token in tokens
            ]
        }), 200
    except Exception as e:
        return jsonify({"error": "Error fetching tokens"}), 500

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current user info"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    return jsonify(user.to_dict()) if user else ({"error": "User not found"}, 404)


def _check_and_create_location_notification(user):
    """Check if user needs location setup notification and create if needed"""
    # Check if user already has all location fields
    if user.region and user.district and user.town:
        return
    
    # Check if location setup notification already exists
    existing_notification = Notification.query.filter_by(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_LOCATION_SETUP,
        is_read=False
    ).first()
    
    if existing_notification:
        return  # Don't create duplicate notifications
    
    # Create the location setup notification
    # NOTE: payload column is db.Text — must use set_payload() to JSON-serialize the dict
    notification = Notification(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_LOCATION_SETUP,
        title='Set your home location',
        message='Set your home location so we can always show you shops and products around you.',
    )
    notification.set_payload({'action_url': url_for('main_bp.home_location_setup')})
    db.session.add(notification)
    db.session.commit()


def _check_and_create_phone_notification(user):
    """Check if user needs phone number setup notification and create if needed"""
    if user.phone:
        return
    
    # Check if phone setup notification already exists and is unread
    existing_notification = Notification.query.filter_by(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_PHONE_SETUP,
        is_read=False
    ).first()
    
    if existing_notification:
        return  # Don't create duplicate notifications
    
    # Create the phone setup notification
    notification = Notification(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_PHONE_SETUP,
        title='Add your phone number',
        message='Please add your phone number so buyers can contact you easily when necessary.',
    )
    notification.set_payload({'action_url': url_for('main_bp.profile'), 'icon': 'phone'})
    db.session.add(notification)
    db.session.commit()


# --- CONTACT VERIFICATION ROUTES (PHONE & EMAIL) ---

@auth_bp.route('/verify-phone/request-otp', methods=['POST'])
def request_user_phone_otp():
    """Request SMS OTP for user phone verification with 180s cooldown"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    data = request.get_json(silent=True) or request.form.to_dict()
    raw_phone = data.get('phone') or current_user.phone
    if not raw_phone:
        return jsonify({'success': False, 'message': 'Phone number is required'}), 400

    from ..utils.phone_utils import normalize_ghana_phone, mask_phone_number
    from ..models.shop_model import VerificationOTP
    from ..services.sms_service import send_phone_otp_sms

    normalized_phone = normalize_ghana_phone(raw_phone)
    if not normalized_phone:
        return jsonify({'success': False, 'message': 'Invalid Ghanaian phone number format'}), 400

    # Check if phone number is registered to a different user
    existing = User.query.filter(User.phone == normalized_phone, User.id != current_user.id).first()
    if existing:
        return jsonify({'success': False, 'message': 'That phone number is already registered to another account'}), 400
    if not existing and not current_user.phone == normalized_phone:
        current_user.phone = normalized_phone
        db.session.commit()

    # Check server-side 180s cooldown
    is_in_cooldown, remaining_seconds = VerificationOTP.check_resend_cooldown(
        user_id=current_user.id,
        otp_type='phone',
        contact_value=normalized_phone
    )
    if is_in_cooldown:
        return jsonify({
            'success': False,
            'message': f'Please wait {remaining_seconds} seconds before requesting a new code.',
            'cooldown_seconds': remaining_seconds,
            'in_cooldown': True
        }), 429

    # Generate OTP record
    otp_record, otp_code = VerificationOTP.create_otp(
        user_id=current_user.id,
        otp_type='phone',
        contact_value=normalized_phone,
        expires_in_minutes=10,
        cooldown_seconds=180
    )

    # Save initial phone on user record if not set
    if not current_user.phone:
        current_user.phone = normalized_phone
        db.session.commit()

    # Dispatch SMS
    sms_sent, sms_msg = send_phone_otp_sms(normalized_phone, otp_code)
    if not sms_sent:
        return jsonify({
            'success': False,
            'message': sms_msg or 'Failed to send SMS OTP'
        }), 500

    masked = mask_phone_number(normalized_phone)
    return jsonify({
        'success': True,
        'message': f'Verification code sent to {masked}',
        'masked_phone': masked,
        'cooldown_seconds': 180,
        'expires_in_minutes': 10
    }), 200


@auth_bp.route('/verify-phone/verify-otp', methods=['POST'])
def verify_user_phone_otp():
    """Verify phone SMS OTP code"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    data = request.get_json(silent=True) or request.form.to_dict()
    otp_code = data.get('otp')
    if not otp_code:
        return jsonify({'success': False, 'message': 'OTP code is required'}), 400

    from ..models.shop_model import VerificationOTP
    active_otp = VerificationOTP.get_active_otp(user_id=current_user.id, otp_type='phone')
    if not active_otp:
        return jsonify({'success': False, 'message': 'No active verification code found. Please request a new code.'}), 404

    is_valid, msg = active_otp.verify_otp(otp_code)
    if not is_valid:
        return jsonify({'success': False, 'message': msg}), 400

    # Mark user phone as verified
    current_user.phone = active_otp.contact_value
    current_user.is_phone_verified = True
    current_user.phone_verified_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Phone number successfully verified!',
        'is_phone_verified': True,
        'phone': current_user.phone
    }), 200


@auth_bp.route('/verify-email/request-otp', methods=['POST'])
def request_user_email_otp():
    """Request email verification OTP with 180s cooldown"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    data = request.get_json(silent=True) or request.form.to_dict()
    target_email = (data.get('email') or current_user.email or '').strip().lower()
    if not target_email:
        return jsonify({'success': False, 'message': 'Email address is required'}), 400

    from ..models.shop_model import VerificationOTP
    from ..services.email_service import send_email_verification

    # Check server-side 180s cooldown
    is_in_cooldown, remaining_seconds = VerificationOTP.check_resend_cooldown(
        user_id=current_user.id,
        otp_type='email',
        contact_value=target_email
    )
    if is_in_cooldown:
        return jsonify({
            'success': False,
            'message': f'Please wait {remaining_seconds} seconds before requesting a new email code.',
            'cooldown_seconds': remaining_seconds,
            'in_cooldown': True
        }), 429

    otp_record, otp_code = VerificationOTP.create_otp(
        user_id=current_user.id,
        otp_type='email',
        contact_value=target_email,
        expires_in_minutes=10,
        cooldown_seconds=180
    )

    email_sent, email_msg = send_email_verification(current_user, otp_code)
    if not email_sent:
        return jsonify({
            'success': False,
            'message': email_msg or 'Failed to send verification email'
        }), 500

    return jsonify({
        'success': True,
        'message': f'Verification code sent to {target_email}',
        'email': target_email,
        'cooldown_seconds': 180,
        'expires_in_minutes': 10
    }), 200


@auth_bp.route('/verify-email/verify-otp', methods=['POST'])
def verify_user_email_otp():
    """Verify email OTP code"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    data = request.get_json(silent=True) or request.form.to_dict()
    otp_code = data.get('otp')
    if not otp_code:
        return jsonify({'success': False, 'message': 'OTP code is required'}), 400

    from ..models.shop_model import VerificationOTP
    active_otp = VerificationOTP.get_active_otp(user_id=current_user.id, otp_type='email')
    if not active_otp:
        return jsonify({'success': False, 'message': 'No active verification code found. Please request a new code.'}), 404

    is_valid, msg = active_otp.verify_otp(otp_code)
    if not is_valid:
        return jsonify({'success': False, 'message': msg}), 400

    current_user.email = active_otp.contact_value
    current_user.is_email_verified = True
    current_user.email_verified_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Email address successfully verified!',
        'is_email_verified': True,
        'email': current_user.email
    }), 200


@auth_bp.route('/verification-status', methods=['GET'])
def get_user_verification_status():
    """Get current verification status of the user"""
    if not current_user.is_authenticated:
        return jsonify({
            'is_authenticated': False,
            'is_phone_verified': False,
            'is_email_verified': False,
            'has_verified_contact': False
        }), 200

    from ..utils.phone_utils import mask_phone_number

    masked_phone = mask_phone_number(current_user.phone) if current_user.phone else None
    masked_email = None
    if current_user.email and '@' in current_user.email:
        parts = current_user.email.split('@')
        name = parts[0]
        masked_email = (name[0] + '***' + name[-1] if len(name) > 2 else name[0] + '***') + '@' + parts[1]

    return jsonify({
        'is_authenticated': True,
        'user_id': current_user.id,
        'is_phone_verified': bool(current_user.is_phone_verified),
        'phone_verified_at': current_user.phone_verified_at.isoformat() if current_user.phone_verified_at else None,
        'phone': current_user.phone,
        'masked_phone': masked_phone,
        'is_email_verified': bool(current_user.is_email_verified),
        'email_verified_at': current_user.email_verified_at.isoformat() if current_user.email_verified_at else None,
        'email': current_user.email,
        'masked_email': masked_email,
        'has_verified_contact': bool(current_user.is_phone_verified or current_user.is_email_verified)
    }), 200

