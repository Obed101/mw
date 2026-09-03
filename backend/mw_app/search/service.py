"""Meilisearch search service – optional enhancement.

Meilisearch is **not** a required dependency.  The application starts and
operates normally when Meilisearch is unavailable; affected features
gracefully degrade to empty results or DB fallback queries.

Configuration (Flask config keys, with development defaults):
  * ``MEILISEARCH_URL``        – e.g. ``http://127.0.0.1:7700`` (dev default)
  * ``MEILISEARCH_MASTER_KEY`` – the master/API key  (dev default ``masterKey``)
"""

import logging
from flask import current_app
from sqlalchemy import or_

from ..extensions import db
from ..models import Product
from .indexes import SEARCH_INDEXES

# Optional import – app continues without meilisearch installed.
try:
    import meilisearch
    import meilisearch.errors
    _MEILISEARCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MEILISEARCH_AVAILABLE = False

_fallback_logger = logging.getLogger(__name__)


def _logger():
    """Return the Flask app logger when inside an application context, else the module logger."""
    try:
        return current_app.logger
    except RuntimeError:
        return _fallback_logger


class SearchService:
    """Centralized Meilisearch service used throughout the application.

    The service is instantiated once per Flask app via ``init_search(app)``.
    It reads the ``MEILISEARCH_URL`` and ``MEILISEARCH_MASTER_KEY`` Flask
    config values (falling back to development defaults) and creates a
    ``meilisearch.Client``.  All index definitions live in
    ``SEARCH_INDEXES``.

    When Meilisearch is **not** available (library missing, config absent, or
    server unreachable) every method degrades gracefully:
    * Write operations (add/delete/clear) are silently skipped.
    * ``search()`` returns ``{'hits': []}``.
    * ``search_in_shop()`` falls back to a database ILIKE query.
    * ``ensure_indexes()`` logs a warning and returns.
    """

    def __init__(self, app=None):
        self.client = None
        self._app = None
        if app is not None:
            self.init_app(app)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_app(self, app):
        """Initialise the Meilisearch client using Flask configuration.

        Expected config keys (with development defaults):
        * ``MEILISEARCH_URL``        – default ``http://127.0.0.1:7700``
        * ``MEILISEARCH_MASTER_KEY`` – default ``masterKey``

        The method **never raises**.  When Meilisearch is unavailable the
        service marks itself as disabled and the rest of the app continues.
        """
        self._app = app

        if not _MEILISEARCH_AVAILABLE:
            app.logger.warning(
                'meilisearch package not installed; search features disabled'
            )
            app.extensions['search_service'] = self
            return

        ms_url = app.config.get('MEILISEARCH_URL') or 'http://127.0.0.1:7700'
        ms_key = app.config.get('MEILISEARCH_MASTER_KEY') or 'masterKey'

        try:
            client = meilisearch.Client(ms_url, ms_key)
            # Verify the server is reachable before committing to the client.
            client.health()
            self.client = client
            app.logger.info('Meilisearch connected: %s', ms_url)
        except Exception as exc:
            app.logger.warning(
                'Meilisearch unavailable at %s – search features disabled. (%s: %s)',
                ms_url,
                type(exc).__name__,
                exc,
            )
            self.client = None

        # Always register in app.extensions so existing imports don't break.
        app.extensions['search_service'] = self

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def ensure_indexes(self):
        """Create / update indexes defined in ``SEARCH_INDEXES``.

        This method is **idempotent** and **never raises**.  When Meilisearch
        is unavailable a warning is logged and the function returns silently.
        """
        if not self.client:
            _logger().warning(
                'Meilisearch client not initialised; skipping ensure_indexes()'
            )
            return

        for name, cfg in SEARCH_INDEXES.items():
            try:
                self.client.create_index(
                    uid=name, options={"primaryKey": cfg["primary_key"]}
                )
                _logger().info('Created search index: %s', name)
            except meilisearch.errors.MeilisearchApiError as e:
                if e.error_code == 'index_already_exists':
                    pass  # expected – carry on to update settings
                else:
                    _logger().warning(
                        'Meilisearch API error creating index %s: %s', name, e
                    )
                    continue
            except Exception as exc:
                _logger().warning(
                    'Failed to create/update index %s: %s', name, exc
                )
                continue

            # Apply searchable / filterable attributes (idempotent).
            try:
                idx = self.client.index(name)
                idx.update_searchable_attributes(
                    cfg.get('searchable_attributes', [])
                )
                idx.update_filterable_attributes(
                    cfg.get('filterable_attributes', [])
                )
                idx.update_typo_tolerance(
                    cfg.get('typo_tolerance', {'enabled': True})
                )
            except Exception as exc:
                _logger().warning(
                    'Failed to update settings for index %s: %s', name, exc
                )

    # ------------------------------------------------------------------
    # Document operations
    # ------------------------------------------------------------------

    def add_documents(self, index_name, documents):
        """Add/update documents in *index_name*.  No-op when client is unavailable."""
        if not self.client:
            _logger().debug(
                'Meilisearch disabled; skipping add_documents to %s', index_name
            )
            return None
        try:
            return self.client.index(index_name).add_documents(documents)
        except Exception as exc:
            _logger().warning(
                'Meilisearch add_documents failed for %s: %s', index_name, exc
            )
            return None

    def delete_documents(self, index_name, ids):
        """Delete documents by id from *index_name*.  No-op when client is unavailable."""
        if not self.client:
            _logger().debug(
                'Meilisearch disabled; skipping delete_documents from %s', index_name
            )
            return None
        try:
            return self.client.index(index_name).delete_documents(ids)
        except Exception as exc:
            _logger().warning(
                'Meilisearch delete_documents failed for %s: %s', index_name, exc
            )
            return None

    def clear_documents(self, index_name):
        """Delete **all** documents from *index_name*.  No-op when unavailable."""
        if not self.client:
            _logger().debug(
                'Meilisearch disabled; skipping clear_documents for %s', index_name
            )
            return
        try:
            idx = self.client.index(index_name)
            stats = idx.get_stats()
            total = stats.number_of_documents
            if total == 0:
                return
            # Simple approach: fetch all docs with a wildcard query.
            res = idx.search('', {"limit": total, "attributesToRetrieve": ["id"]})
            ids = [hit["id"] for hit in res.get("hits", [])]
            if ids:
                idx.delete_documents(ids)
        except Exception as exc:
            _logger().warning(
                'Meilisearch clear_documents failed for %s: %s', index_name, exc
            )

    def search(self, index_name, query, params=None):
        """Search *index_name* for *query*.

        Returns ``{'hits': []}`` when Meilisearch is unavailable or errors.
        """
        if not self.client:
            _logger().debug(
                'Meilisearch disabled; returning empty result for %s query=%r',
                index_name, query,
            )
            return {'hits': []}
        try:
            _logger().debug('Searching %s for query: %r', index_name, query)
            return self.client.index(index_name).search(query, params or {})
        except Exception as exc:
            _logger().warning(
                'Meilisearch search failed for %s query=%r: %s',
                index_name, query, exc,
            )
            return {'hits': []}

    def search_in_shop(self, shop_id, query, limit=20):
        """Search products within a single shop with automatic DB fallback.

        * When Meilisearch is available the result is Meilisearch-ranked.
        * When Meilisearch is unavailable (or returns no results) a simple
          ILIKE query against the database is used instead.
        """
        normalized_query = (query or '').strip()
        base_query = Product.query.filter(
            Product.shop_id == shop_id,
            Product.is_active.is_(True),
        )

        if not normalized_query:
            return base_query.order_by(Product.updated_at.desc()).limit(limit).all()

        product_ids = []
        if self.client:
            try:
                result = self.search(
                    'products',
                    normalized_query,
                    {
                        'limit': limit,
                        'filter': f'shop_id = {shop_id}',
                    },
                )
                product_ids = [
                    hit['id']
                    for hit in result.get('hits', [])
                    if hit.get('id') is not None
                ]
            except Exception:
                _logger().warning(
                    'Meilisearch shop search failed; falling back to DB search'
                )

        if product_ids:
            matched_products = Product.query.filter(
                Product.id.in_(product_ids),
                Product.shop_id == shop_id,
                Product.is_active.is_(True),
            ).all()
            by_id = {product.id: product for product in matched_products}
            return [by_id[pid] for pid in product_ids if pid in by_id]

        # DB fallback
        return base_query.filter(
            or_(
                Product.name.ilike(f'%{normalized_query}%'),
                Product.description.ilike(f'%{normalized_query}%'),
                Product.tags.ilike(f'%{normalized_query}%'),
            )
        ).order_by(Product.updated_at.desc()).limit(limit).all()

    # ------------------------------------------------------------------
    # Health / stats helpers
    # ------------------------------------------------------------------

    def is_available(self):
        """Return ``True`` when Meilisearch is reachable."""
        return self.client is not None

    def get_search_health(self):
        if not self.client:
            return {'healthy': False, 'reason': 'client not initialised'}
        try:
            self.client.health()
            return {'healthy': True}
        except Exception as exc:
            _logger().warning('Meilisearch health check failed: %s', exc)
            return {'healthy': False, 'error': str(exc)}

    def get_index_stats(self, index_name):
        if not self.client:
            return {}
        try:
            return self.client.index(index_name).get_stats()
        except Exception as exc:
            _logger().warning(
                'Meilisearch get_index_stats failed for %s: %s', index_name, exc
            )
            return {}
