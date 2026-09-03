"""Tests for the Meilisearch optional-enhancement behaviour.

Scenarios covered
-----------------
1. App starts successfully when Meilisearch is unavailable (connection refused).
2. ``search_service.search()`` returns ``{'hits': []}`` when client is None.
3. ``search_service.ensure_indexes()`` returns without raising when client is None.
4. Normal search behaviour when a mocked Meilisearch client is present.
5. ``add_documents`` / ``delete_documents`` are no-ops when client is None.
6. The global ``search_service`` object is importable and not None after app init.

Run with:
    pytest tests/test_search.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Check whether the full app dependency stack is available.
# Tests that call create_app() are skipped when it isn't.
try:
    import flask_jwt_extended  # noqa: F401
    import flask_session  # noqa: F401
    import flask_msearch  # noqa: F401
    _FULL_DEPS = True
except ImportError:
    _FULL_DEPS = False

_requires_full_deps = pytest.mark.skipif(
    not _FULL_DEPS,
    reason="Full app deps (flask_jwt_extended, flask_session, flask_msearch) not installed",
)

# Ensure the backend dir is on the path.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_app(ms_url="http://127.0.0.1:9999",  # port that is almost certainly closed
               ms_key="testkey"):
    """Create a minimal Flask test app with search disabled (no real Meilisearch)."""
    from mw_app import create_app
    app = create_app()
    app.config.update(
        TESTING=True,
        MEILISEARCH_URL=ms_url,
        MEILISEARCH_MASTER_KEY=ms_key,
    )
    return app


@pytest.fixture()
def app_no_ms():
    """Flask app where Meilisearch is configured to an unreachable address."""
    # Patch meilisearch.Client.health to raise so init_app sees it as unavailable.
    with patch("meilisearch.Client.health", side_effect=ConnectionRefusedError("refused")):
        app = _make_app()
    return app


@pytest.fixture()
def service_no_client():
    """A bare SearchService with no client (simulates Meilisearch unavailable)."""
    from mw_app.search.service import SearchService
    svc = SearchService()  # no app → client stays None
    return svc


@pytest.fixture()
def service_with_mock_client():
    """A SearchService with a fully-mocked Meilisearch client."""
    from mw_app.search.service import SearchService
    svc = SearchService()
    mock_client = MagicMock()
    svc.client = mock_client
    return svc, mock_client


# ---------------------------------------------------------------------------
# 1. App startup – Meilisearch unavailable
# ---------------------------------------------------------------------------

@_requires_full_deps
class TestAppStartupWithoutMeilisearch:
    def test_create_app_does_not_raise(self):
        """create_app() must succeed even when Meilisearch is unreachable."""
        with patch("meilisearch.Client.health", side_effect=ConnectionRefusedError("refused")):
            app = _make_app()
        assert app is not None

    def test_search_service_registered_on_app(self):
        """search_service must be registered in app.extensions after startup."""
        with patch("meilisearch.Client.health", side_effect=ConnectionRefusedError("refused")):
            app = _make_app()
        with app.app_context():
            assert "search_service" in app.extensions

    def test_search_service_client_is_none_when_unavailable(self):
        """When Meilisearch is down the client attribute must be None."""
        with patch("meilisearch.Client.health", side_effect=ConnectionRefusedError("refused")):
            app = _make_app()
        with app.app_context():
            svc = app.extensions["search_service"]
            assert svc.client is None

    def test_is_available_returns_false_when_down(self):
        with patch("meilisearch.Client.health", side_effect=ConnectionRefusedError("refused")):
            app = _make_app()
        with app.app_context():
            svc = app.extensions["search_service"]
            assert svc.is_available() is False


# ---------------------------------------------------------------------------
# 2. search() returns empty hits when unavailable
# ---------------------------------------------------------------------------

class TestSearchWhenUnavailable:
    def test_search_returns_empty_hits(self, service_no_client):
        result = service_no_client.search("products", "shoes")
        assert result == {"hits": []}

    def test_search_with_params_returns_empty_hits(self, service_no_client):
        result = service_no_client.search("shops", "cafe", {"limit": 5})
        assert result == {"hits": []}

    def test_search_does_not_raise(self, service_no_client):
        """search() must never raise regardless of Meilisearch state."""
        try:
            service_no_client.search("products", "anything")
        except Exception as exc:
            pytest.fail(f"search() raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# 3. ensure_indexes() – safe when client is None
# ---------------------------------------------------------------------------

class TestEnsureIndexesWhenUnavailable:
    def test_ensure_indexes_does_not_raise(self, service_no_client, caplog):
        """ensure_indexes() must return without raising when client is None."""
        import logging
        with caplog.at_level(logging.WARNING):
            try:
                service_no_client.ensure_indexes()
            except Exception as exc:
                pytest.fail(f"ensure_indexes() raised: {exc}")

    def test_ensure_indexes_logs_warning(self, service_no_client, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            service_no_client.ensure_indexes()
        assert any("not initialised" in r.message.lower() or "skipping" in r.message.lower()
                   for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. Normal behaviour with mock client
# ---------------------------------------------------------------------------

class TestSearchWithMockClient:
    def test_search_delegates_to_client(self, service_with_mock_client):
        svc, mock_client = service_with_mock_client
        mock_index = MagicMock()
        mock_client.index.return_value = mock_index
        mock_index.search.return_value = {"hits": [{"id": 1, "name": "Test"}]}

        result = svc.search("products", "test", {"limit": 10})

        mock_client.index.assert_called_once_with("products")
        mock_index.search.assert_called_once_with("test", {"limit": 10})
        assert result["hits"][0]["id"] == 1

    def test_search_returns_empty_on_client_exception(self, service_with_mock_client):
        svc, mock_client = service_with_mock_client
        mock_client.index.side_effect = RuntimeError("boom")

        result = svc.search("products", "test")
        assert result == {"hits": []}

    def test_is_available_true_with_client(self, service_with_mock_client):
        svc, _ = service_with_mock_client
        assert svc.is_available() is True


# ---------------------------------------------------------------------------
# 5. add_documents / delete_documents – no-ops when client is None
# ---------------------------------------------------------------------------

class TestDocumentOpsWhenUnavailable:
    def test_add_documents_returns_none(self, service_no_client):
        result = service_no_client.add_documents("products", [{"id": 1}])
        assert result is None

    def test_delete_documents_returns_none(self, service_no_client):
        result = service_no_client.delete_documents("products", [1])
        assert result is None

    def test_clear_documents_does_not_raise(self, service_no_client):
        try:
            service_no_client.clear_documents("products")
        except Exception as exc:
            pytest.fail(f"clear_documents() raised: {exc}")


# ---------------------------------------------------------------------------
# 6. Global search_service importable
# ---------------------------------------------------------------------------

class TestGlobalSearchService:
    def test_module_level_search_service_importable(self):
        from mw_app.search import search_service
        # It may be None before create_app() is called in this process,
        # but the import itself must not fail.
        # We just verify the name resolves without ImportError.
        assert True  # import above would have raised if broken

    @_requires_full_deps
    def test_module_level_search_service_set_after_init(self):
        """After init_search is called, the module-level search_service must be set."""
        with patch("meilisearch.Client.health", side_effect=ConnectionRefusedError("refused")):
            app = _make_app()

        import mw_app.search as search_module
        assert search_module.search_service is not None


# ---------------------------------------------------------------------------
# 7. get_search_health degradation
# ---------------------------------------------------------------------------

class TestHealthWhenUnavailable:
    def test_health_returns_unhealthy_dict(self, service_no_client):
        result = service_no_client.get_search_health()
        assert result.get("healthy") is False
