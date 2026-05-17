"""
Admin route decorators with strong backend permission checks.
These are the ONLY guards for admin access — never rely on frontend hiding alone.
"""
from functools import wraps
from flask import redirect, url_for, flash, abort
from flask_login import current_user


def login_required(func):
    """Redirect unauthenticated users to login."""
    @wraps(func)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please sign in to access that page.', 'info')
            return redirect(url_for('main_bp.login'))
        return func(*args, **kwargs)
    return decorated


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
