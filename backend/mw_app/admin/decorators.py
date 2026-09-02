"""
Admin route decorators with strong backend permission checks.
These are the ONLY guards for admin access — never rely on frontend hiding alone.
"""
from functools import wraps
from flask import redirect, url_for, flash, session, request
from flask_login import current_user


def login_required(func):
    """Overwrites the flask_login's login_required"""
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            session['prev'] = request.url
            flash('A quick login is required first.', 'info')
            return redirect(url_for('main_bp.login'))
        return func(*args, **kwargs)
    return decorated_view

def admin_required(func):
    """
    Allow access only if:
    - User is authenticated
    - User has admin or super_admin role
    - User has admin_mode = True
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please sign in to access that page.', 'info')
            return redirect(url_for('main_bp.login'))
        if not current_user.is_any_admin():
            flash('Admin access is required.', 'error')
            return redirect(url_for('main_bp.index'))
        if not current_user.admin_mode:
            flash('Enable Admin Mode in your profile to access admin pages.', 'warning')
            return redirect(url_for('main_bp.profile'))
        return func(*args, **kwargs)
    return decorated


def super_admin_required(func):
    """
    Allow access only if:
    - User is authenticated
    - User has super_admin role specifically
    - User has admin_mode = True
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please sign in to access that page.', 'info')
            return redirect(url_for('main_bp.login'))
        if not current_user.is_super_admin():
            flash('Super admin access is required for this action.', 'error')
            return redirect(url_for('mw_admin_bp.dashboard'))
        if not current_user.admin_mode:
            flash('Enable Admin Mode in your profile to access admin pages.', 'warning')
            return redirect(url_for('main_bp.profile'))
        return func(*args, **kwargs)
    return decorated


def require_privilege(privilege):
    """Protect a special capability using the central User.has_privilege check."""
    def decorator(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('main_bp.login'))
            if not current_user.has_privilege(privilege):
                flash('You do not have permission for this action.', 'error')
                return redirect(url_for('main_bp.index'))
            return func(*args, **kwargs)
        return decorated
    return decorator
