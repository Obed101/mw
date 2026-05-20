from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user, login_required
from ..services.analytics_service import track_event
from ..models.analytics_model import SavedSearch, SearchHistory
from ..extensions import db

analytics_bp = Blueprint('analytics_bp', __name__)

@analytics_bp.route('/track', methods=['POST'])
def track_client_event():
    """
    Accepts client-side event tracking requests.
    Format:
    {
      "event_type": "product_share",
      "entity_type": "product",
      "entity_id": 42,
      "payload": { ... }
    }
    """
    data = request.get_json() or {}
    event_type = data.get('event_type')
    entity_type = data.get('entity_type')
    entity_id = data.get('entity_id')
    payload = data.get('payload') or {}

    if not event_type:
        return jsonify({'success': False, 'message': 'event_type is required'}), 400

    # Pass it to our safety-wrapped tracking service
    track_event(
        event_type=event_type,
        user=current_user,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        request=request
    )

    return jsonify({'success': True}), 200


@analytics_bp.route('/saved-searches', methods=['POST'])
@login_required
def save_search():
    """
    Saves a search query.
    Expects JSON: {"query": "shoes"}
    """
    data = request.get_json() or {}
    query = data.get('query', '').strip()

    if not query:
        return jsonify({'success': False, 'message': 'query is required'}), 400

    # Avoid duplicate saved searches for the same user
    existing = db.session.query(SavedSearch).filter_by(user_id=current_user.id, query=query).first()
    if existing:
        return jsonify({'success': True, 'message': 'Already saved', 'id': existing.id}), 200

    try:
        saved = SavedSearch(user_id=current_user.id, query=query)
        db.session.add(saved)
        db.session.commit()
        return jsonify({'success': True, 'id': saved.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@analytics_bp.route('/saved-searches/<int:search_id>', methods=['DELETE'])
@login_required
def delete_saved_search(search_id):
    """
    Deletes a saved search.
    """
    saved = db.session.query(SavedSearch).filter_by(id=search_id, user_id=current_user.id).first_or_404()
    try:
        db.session.delete(saved)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@analytics_bp.route('/recent-searches', methods=['GET'])
def get_recent_searches():
    """
    Get recent searches for the current user.
    """
    if not current_user.is_authenticated:
        return jsonify({'success': True, 'recent': []}), 200

    histories = db.session.query(SearchHistory).filter_by(user_id=current_user.id).order_by(
        SearchHistory.created_at.desc()
    ).limit(5).all()

    return jsonify({
        'success': True,
        'recent': [h.query for h in histories]
    }), 200
