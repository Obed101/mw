# Market Window Search Package

This directory contains the **centralized Meilisearch integration** for the Market Window application.

## Overview
- All search‑related logic lives here, providing a single source of truth.
- The package exposes a singleton `search_service` that wraps a `meilisearch.Client`.
- Index definitions and settings are declared in `indexes.py`.
- The Flask app initializes the service via `search.init_search(app)` (see `mw_app/__init__.py`).

## Files
- `__init__.py` – creates the global `search_service` instance, registers the `search-rebuild` CLI command and calls `ensure_indexes()` on startup.
- `indexes.py` – defines `SEARCH_INDEXES` with searchable & filterable attributes for `products` and `shops`.
- `service.py` – the `SearchService` class with helpers:
  - `ensure_indexes()` – creates missing indexes and applies settings.
  - `search(index_name, query, params=None)` – typo‑tolerant search.
  - `add_documents`, `delete_documents`, `clear_documents`.
  - `get_search_health()` and `get_index_stats(name)`.
- `sync.py` – (imported by the CLI) provides bulk rebuild functions for products and shops.

## Usage in the application
```python
from flask import current_app
# Access the service anywhere in a request
results = current_app.extensions['search_service'].search('products', q, {'limit': 20})
```
Or, after initialization you can import the singleton directly:
```python
from mw_app.search import search_service
results = search_service.search('shops', query)
```

## CLI Command
Run the following to rebuild both indexes (safe to run repeatedly):
```bash
flask search-rebuild
```
The command prints progress messages and uses the `rebuild_products` / `rebuild_shops` helpers.

## Configuration
The service reads the following environment variables (or Flask config keys):
- `MEILI_HOST` / `MEILISEARCH_URL`
- `MEILI_MASTER_KEY` / `MEILISEARCH_MASTER_KEY`
If they are missing, the service disables search but the rest of the app continues to work.

## Extending the package
1. Add a new entry to `SEARCH_INDEXES` in `indexes.py`.
2. Update `sync.py` to populate documents for the new index.
3. Call `search_service.ensure_indexes()` (automatically on app start) to create it.

---
*This README was added to document the new production‑ready search architecture.*
