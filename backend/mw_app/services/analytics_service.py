import traceback
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from flask import request as flask_request, session, has_request_context
from ..extensions import db
from ..models.analytics_model import Event, SearchHistory
from ..models.user_model import User
from ..models.engagement_model import Notification

def track_event(event_type, user=None, entity_type=None, entity_id=None, payload=None, request=None):
    """
    Centralized event tracking helper.
    Extracts session, IP, and user-agent details from request.
    Always wraps DB transactions in try-except to never block core flows.
    """
    try:
        # Determine the user ID
        user_id = None
        if user and not getattr(user, 'is_anonymous', True):
            user_id = getattr(user, 'id', None)
        elif has_request_context():
            from flask_login import current_user
            if current_user and not getattr(current_user, 'is_anonymous', True):
                user_id = getattr(current_user, 'id', None)

        req = request or (flask_request if has_request_context() else None)
        session_id = None
        ip_address = None
        user_agent = None

        if has_request_context():
            # Seed session ID if missing
            if 'session_id' not in session:
                session['session_id'] = str(uuid4())
            session_id = session['session_id']

            if req:
                # Handle proxy headers
                if req.headers.getlist("X-Forwarded-For"):
                    ip_address = req.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
                else:
                    ip_address = req.remote_addr
                
                if req.user_agent:
                    user_agent = req.user_agent.string

        # Prepare payload
        meta = payload or {}

        # Construct and add Event
        event = Event(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=meta,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(event)
        db.session.commit()

        # --- Automatic Behavioral Trigger: Repeated views ---
        if event_type == 'product_view' and entity_type == 'product' and entity_id:
            # Check for another view in last 24h
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            prev_view_query = Event.query.filter(
                Event.event_type == 'product_view',
                Event.entity_type == 'product',
                Event.entity_id == entity_id,
                Event.id != event.id,
                Event.created_at >= cutoff
            )
            if session_id:
                prev_view_query = prev_view_query.filter(Event.session_id == session_id)
            elif user_id:
                prev_view_query = prev_view_query.filter(Event.user_id == user_id)
            
            if prev_view_query.first() is not None:
                # Track repeated product view as a separate background event
                repeated_event = Event(
                    user_id=user_id,
                    event_type='repeated_product_view',
                    entity_type='product',
                    entity_id=entity_id,
                    payload={'trigger_event_id': event.id},
                    session_id=session_id,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                db.session.add(repeated_event)
                db.session.commit()

        # --- Automatic Behavioral Trigger: Return visits ---
        if (event_type == 'login' or event_type == 'homepage_visit') and user_id:
            user_obj = User.query.get(user_id)
            if user_obj and user_obj.last_login:
                last_login_time = user_obj.last_login
                if last_login_time.tzinfo is None:
                    last_login_time = last_login_time.replace(tzinfo=timezone.utc)
                
                diff = datetime.now(timezone.utc) - last_login_time
                if timedelta(hours=2) <= diff <= timedelta(hours=48):
                    # Track return visit
                    return_visit_event = Event(
                        user_id=user_id,
                        event_type='return_visit',
                        payload={'last_login': last_login_time.isoformat()},
                        session_id=session_id,
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    db.session.add(return_visit_event)
                    db.session.commit()

        return event

    except Exception as e:
        db.session.rollback()
        print(f"[Analytics] Error tracking event '{event_type}': {e}")
        traceback.print_exc()
        return None


def save_search_query(query, user=None, request=None, success=True):
    """
    Saves a search query to search history and tracks search/failed_search events.
    """
    if not query or not query.strip():
        return None

    query = query.strip()
    try:
        user_id = None
        if user and not getattr(user, 'is_anonymous', True):
            user_id = getattr(user, 'id', None)
        elif has_request_context():
            from flask_login import current_user
            if current_user and not getattr(current_user, 'is_anonymous', True):
                user_id = getattr(current_user, 'id', None)

        history = SearchHistory(
            user_id=user_id,
            query=query
        )
        db.session.add(history)
        db.session.commit()

        # Track event
        event_type = 'search' if success else 'failed_search'
        track_event(
            event_type=event_type,
            user=user,
            entity_type='query',
            payload={'query': query},
            request=request
        )

        if not success:
            notify_admins_failed_search(query)

        return history

    except Exception as e:
        db.session.rollback()
        print(f"[Analytics] Error saving search query '{query}': {e}")
        return None


def notify_admins_failed_search(query):
    """
    Find all system admins and issue them an alert notification about a failed search.
    """
    try:
        admins = User.query.filter(User.role == 'admin').all()
        admin_ids = [admin.id for admin in admins]
        if admin_ids:
            Notification.create_for_users(
                user_ids=admin_ids,
                notification_type='failed_search_alert',
                title='Failed Search Alert',
                message=f"A buyer's search for '{query}' returned no results.",
                payload={'query': query, 'icon': 'exclamation-circle'}
            )
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Analytics] Error alerting admins for failed search '{query}': {e}")
