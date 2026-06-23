import os
import meilisearch
from flask import current_app
from sqlalchemy import or_

from ..extensions import db
from ..models import Product
from .indexes import SEARCH_INDEXES

class SearchService:
    """Centralized Meilisearch service used throughout the application.

    The service is instantiated once per Flask app via ``init_search(app)``.  It
    reads the existing ``MEILISEARCH_URL`` and ``MEILISEARCH_MASTER_KEY``
    environment variables (or corresponding Flask config values) and creates a
    ``meilisearch.Client``.  All index definitions live in ``SEARCH_INDEXES``.
    """

    def __init__(self, app=None):
        self.client = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize the Meilisearch client using Flask configuration.

        Expected config keys (fallback to environment variables):
        * ``MEILISEARCH_URL`` – e.g. ``http://127.0.0.1:7700``
        * ``MEILISEARCH_MASTER_KEY`` – the master key for the instance
        """
        ms_url = app.config.get('MEILISEARCH_URL', 'http://127.0.0.1:7700')
        ms_key = app.config.get('MEILISEARCH_MASTER_KEY', 'masterKey')
        if not ms_url or not ms_key:
            # Fail gracefully – the rest of the app can continue without search.
            app.logger.error('Meilisearch configuration missing; search disabled')
            return
        # Store app reference for later logger usage
        self.app = app
        self.client = meilisearch.Client(ms_url, ms_key)
        # expose on app for easy access elsewhere
        app.extensions['search_service'] = self

    # ---------------------------------------------------------------------
    # Index management
    # ---------------------------------------------------------------------
    def ensure_indexes(self):
        """Create any missing indexes defined in ``SEARCH_INDEXES``.

        This method is idempotent – calling it repeatedly is safe.
        """
        if not self.client:
            self.app.logger.warning('Search client not initialised; cannot ensure indexes')
            return
        for name, cfg in SEARCH_INDEXES.items():
            try:
                # ``create_index`` raises an error if the index already exists.
                self.client.create_index(uid=name, options={"primaryKey": cfg["primary_key"]})
                self.app.logger.info(f'Created search index: {name}')
            except meilisearch.errors.MeilisearchApiError as e:
                if e.error_code == 'index_already_exists':
                    # Index exists – just update settings.
                    pass
                else:
                    self.app.logger.exception(e)
            # Apply searchable / filterable attributes (idempotent).
            idx = self.client.index(name)
            idx.update_searchable_attributes(cfg.get('searchable_attributes', []))
            idx.update_filterable_attributes(cfg.get('filterable_attributes', []))

    # ---------------------------------------------------------------------
    # Document operations
    # ---------------------------------------------------------------------
    def add_documents(self, index_name, documents):
        if not self.client:
            current_app.logger.warning('Search client not initialised; cannot add documents')
            return
        return self.client.index(index_name).add_documents(documents)

    def delete_documents(self, index_name, ids):
        if not self.client:
            current_app.logger.warning('Search client not initialised; cannot delete documents')
            return
        return self.client.index(index_name).delete_documents(ids)

    def clear_documents(self, index_name):
        """Delete *all* documents from an index.

        Meilisearch does not provide a direct ``clear`` call; we delete by
        fetching all document IDs first.
        """
        if not self.client:
            current_app.logger.warning('Search client not initialised; cannot clear documents')
            return
        idx = self.client.index(index_name)
        # Retrieve IDs – limited to 1000 for safety (production would page).
        stats = idx.get_stats()
        total = stats.get('numberOfDocuments', 0)
        if total == 0:
            return
        # Simple approach: fetch all docs with a wildcard query.
        res = idx.search('', {"limit": total, "attributesToRetrieve": ["id"]})
        ids = [hit["id"] for hit in res.get('hits', [])]
        if ids:
            idx.delete_documents(ids)

    def search(self, index_name, query, params=None):
        self.app.logger.info(f'Searching {index_name} for query: {query}')
        if not self.client:
            self.app.logger.warning('Search client not initialised; returning empty result')
            return {'hits': []}
        return self.client.index(index_name).search(query, params or {})

    def search_in_shop(self, shop_id, query, limit=20):
        """Search products within a single shop with Meilisearch fallback."""
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
                product_ids = [hit['id'] for hit in result.get('hits', []) if hit.get('id') is not None]
            except Exception:
                current_app.logger.exception('Meilisearch shop search failed; falling back to DB search')

        if product_ids:
            matched_products = Product.query.filter(
                Product.id.in_(product_ids),
                Product.shop_id == shop_id,
                Product.is_active.is_(True),
            ).all()
            by_id = {product.id: product for product in matched_products}
            return [by_id[product_id] for product_id in product_ids if product_id in by_id]

        return base_query.filter(
            or_(
                Product.name.ilike(f'%{normalized_query}%'),
                Product.description.ilike(f'%{normalized_query}%'),
                Product.tags.ilike(f'%{normalized_query}%'),
            )
        ).order_by(Product.updated_at.desc()).limit(limit).all()

    # ---------------------------------------------------------------------
    # Health / stats helpers
    # ---------------------------------------------------------------------
    def get_search_health(self):
        if not self.client:
            return {'healthy': False}
        try:
            # Ping endpoint – raises if unavailable.
            self.client.health()
            return {'healthy': True}
        except Exception as e:
            current_app.logger.exception(e)
            return {'healthy': False, 'error': str(e)}

    def get_index_stats(self, index_name):
        if not self.client:
            return {}
        try:
            return self.client.index(index_name).get_stats()
        except Exception as e:
            current_app.logger.exception(e)
            return {}
