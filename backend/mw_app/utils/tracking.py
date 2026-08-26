from threading import Thread

from flask import has_app_context, current_app

from ..services.analytics_service import track_event as _sync_track_event


def _track_event_worker(app, event_kwargs):
    with app.app_context():
        _sync_track_event(**event_kwargs)


def track_event_async(
    event_type,
    user=None,
    entity_type=None,
    entity_id=None,
    payload=None,
):
    """Track an analytics event without blocking the request thread."""
    try:
        safe_user_id = getattr(user, 'id', None) if user else None
        if not has_app_context():
            return _sync_track_event(
                event_type=event_type,
                user=user,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
                user_id=safe_user_id,
            )

        app = current_app._get_current_object()
        Thread(
            target=_track_event_worker,
            args=(
                app,
                {
                    'event_type': event_type,
                    'user': None,
                    'user_id': safe_user_id,
                    'entity_type': entity_type,
                    'entity_id': entity_id,
                    'payload': payload,
                },
            ),
            daemon=True,
        ).start()
    except Exception:
        current_app.logger.exception("Failed to queue analytics event: %s", event_type)
