from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from ..extensions import db
from ..models import (
    User,
    SupportConversation,
    SupportMessage,
    Notification,
    USER_ROLE_ADMIN,
    CONVERSATION_STATUS_OPEN,
    CONVERSATION_STATUS_PENDING,
    CONVERSATION_STATUS_CLOSED
)
from datetime import datetime, timezone

support_bp = Blueprint('support_bp', __name__)

def _is_htmx_request():
    return request.headers.get('HX-Request') == 'true'

def _admin_required(func):
    from functools import wraps
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != USER_ROLE_ADMIN:
            flash('Admin access is required for that page.', 'error')
            return redirect(url_for('main_bp.index'))
        return func(*args, **kwargs)
    return decorated_view

# ==========================================
# PUBLIC / BUYER ROUTES
# ==========================================

@support_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        if not current_user.is_authenticated:
            # For now, require login. In the future, could allow anonymous emails.
            if _is_htmx_request():
                return '<div class="alert alert-warning">Please <a href="/login">log in</a> to contact support.</div>', 401
            flash('Please log in to contact support.', 'warning')
            return redirect(url_for('main_bp.login'))

        subject = request.form.get('subject', '').strip()
        message_text = request.form.get('message', '').strip()

        if not message_text:
            if _is_htmx_request():
                return '<div class="alert alert-danger">Message is required.</div>', 400
            flash('Message is required.', 'error')
            return redirect(url_for('support_bp.contact'))

        # Create new conversation
        conversation = SupportConversation(
            user_id=current_user.id,
            subject=subject if subject else None
        )
        db.session.add(conversation)
        db.session.flush() # get ID

        msg = SupportMessage(
            conversation_id=conversation.id,
            sender_id=current_user.id,
            message=message_text,
            is_admin=False
        )
        db.session.add(msg)
        
        # Notify admins
        admins = User.query.filter_by(role=USER_ROLE_ADMIN).all()
        admin_ids = [admin.id for admin in admins]
        if admin_ids:
            Notification.create_for_users(
                user_ids=admin_ids,
                notification_type='new_support_ticket',
                title='New Support Ticket',
                message=f'New ticket from {current_user.username}: {message_text[:50]}...',
                actor_user_id=current_user.id,
                payload={'conversation_id': conversation.id}
            )
            
        db.session.commit()

        if _is_htmx_request():
            return render_template('public/partials/contact_success.html')
        
        flash('Your message has been sent to support!', 'success')
        return redirect(url_for('support_bp.my_support_list'))

    return render_template('public/contact.html')

@support_bp.route('/me/support')
@login_required
def my_support_list():
    conversations = SupportConversation.query.filter_by(user_id=current_user.id).order_by(SupportConversation.updated_at.desc()).all()
    return render_template('buyer/support_list.html', conversations=conversations)

@support_bp.route('/me/support/<int:id>')
@login_required
def my_support_chat(id):
    conversation = SupportConversation.query.options(
        joinedload(SupportConversation.messages).joinedload(SupportMessage.sender)
    ).filter_by(id=id, user_id=current_user.id).first_or_404()
    
    # Mark messages from admin as read
    unread_messages = [m for m in conversation.messages if m.is_admin and not m.is_read]
    if unread_messages:
        for m in unread_messages:
            m.is_read = True
        db.session.commit()
        
    return render_template('buyer/support_chat.html', conversation=conversation)

@support_bp.route('/me/support/<int:id>/reply', methods=['POST'])
@login_required
def my_support_reply(id):
    conversation = SupportConversation.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    message_text = request.form.get('message', '').strip()
    
    if not message_text:
        return 'Message cannot be empty', 400
        
    msg = SupportMessage(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        message=message_text,
        is_admin=False
    )
    
    conversation.updated_at = datetime.now(timezone.utc)
    conversation.last_message_at = datetime.now(timezone.utc)
    
    if conversation.status == CONVERSATION_STATUS_CLOSED:
        conversation.status = CONVERSATION_STATUS_OPEN
        
    db.session.add(msg)
    
    # Notify admins
    admins = User.query.filter_by(role=USER_ROLE_ADMIN).all()
    admin_ids = [admin.id for admin in admins]
    if admin_ids:
        Notification.create_for_users(
            user_ids=admin_ids,
            notification_type='support_reply',
            title='Support Ticket Reply',
            message=f'Reply from {current_user.username} on ticket #{conversation.id}',
            actor_user_id=current_user.id,
            payload={'conversation_id': conversation.id}
        )
        
    db.session.commit()
    
    if _is_htmx_request():
        return render_template('support/partials/message_bubble.html', message=msg, is_admin=False)
        
    return redirect(url_for('support_bp.my_support_chat', id=id))

@support_bp.route('/me/support/<int:conv_id>/messages/<int:msg_id>', methods=['DELETE'])
@login_required
def delete_message(conv_id, msg_id):
    msg = SupportMessage.query.join(SupportConversation).filter(
        SupportMessage.id == msg_id,
        SupportConversation.id == conv_id,
        SupportConversation.user_id == current_user.id,
        SupportMessage.sender_id == current_user.id
    ).first_or_404()
    
    msg.is_deleted = True
    db.session.commit()
    
    if _is_htmx_request():
        return render_template('support/partials/message_bubble.html', message=msg, is_admin=False)
        
    return redirect(url_for('support_bp.my_support_chat', id=conv_id))

# ==========================================
# ADMIN ROUTES
# ==========================================

@support_bp.route('/admin/support')
@login_required
@_admin_required
def admin_support_inbox():
    status_filter = request.args.get('status')
    
    query = SupportConversation.query.options(
        joinedload(SupportConversation.user)
    )
    
    if status_filter in [CONVERSATION_STATUS_OPEN, CONVERSATION_STATUS_PENDING, CONVERSATION_STATUS_CLOSED]:
        query = query.filter_by(status=status_filter)
        
    conversations = query.order_by(SupportConversation.updated_at.desc()).all()
    
    if _is_htmx_request():
        return render_template('support/partials/inbox_rows.html', conversations=conversations)
        
    return render_template('admin/support_inbox.html', conversations=conversations, active_status=status_filter)

@support_bp.route('/admin/support/<int:id>')
@login_required
@_admin_required
def admin_support_chat(id):
    conversation = SupportConversation.query.options(
        joinedload(SupportConversation.messages).joinedload(SupportMessage.sender),
        joinedload(SupportConversation.user)
    ).filter_by(id=id).first_or_404()
    
    # Mark messages from user as read
    unread_messages = [m for m in conversation.messages if not m.is_admin and not m.is_read]
    if unread_messages:
        for m in unread_messages:
            m.is_read = True
        db.session.commit()
        
    return render_template('admin/support_chat.html', conversation=conversation)

@support_bp.route('/admin/support/<int:id>/reply', methods=['POST'])
@login_required
@_admin_required
def admin_support_reply(id):
    conversation = SupportConversation.query.filter_by(id=id).first_or_404()
    message_text = request.form.get('message', '').strip()
    
    if not message_text:
        return 'Message cannot be empty', 400
        
    msg = SupportMessage(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        message=message_text,
        is_admin=True
    )
    
    conversation.updated_at = datetime.now(timezone.utc)
    conversation.last_message_at = datetime.now(timezone.utc)
    
    if conversation.status == CONVERSATION_STATUS_OPEN:
        conversation.status = CONVERSATION_STATUS_PENDING
        
    db.session.add(msg)
    
    # Notify user
    Notification.create_for_users(
        user_ids=[conversation.user_id],
        notification_type='support_reply',
        title='Support Ticket Reply',
        message=f'Admin replied to your ticket: {message_text[:50]}...',
        actor_user_id=current_user.id,
        payload={'conversation_id': conversation.id}
    )
        
    db.session.commit()
    
    if _is_htmx_request():
        return render_template('support/partials/admin_message_bubble.html', message=msg)
        
    return redirect(url_for('support_bp.admin_support_chat', id=id))

@support_bp.route('/admin/support/<int:id>/status', methods=['POST'])
@login_required
@_admin_required
def admin_support_status(id):
    conversation = SupportConversation.query.filter_by(id=id).first_or_404()
    new_status = request.form.get('status')
    
    if new_status in [CONVERSATION_STATUS_OPEN, CONVERSATION_STATUS_PENDING, CONVERSATION_STATUS_CLOSED]:
        conversation.status = new_status
        db.session.commit()
        
    if _is_htmx_request():
        return render_template('support/partials/status_badge.html', conversation=conversation)
        
    return redirect(url_for('support_bp.admin_support_chat', id=id))
