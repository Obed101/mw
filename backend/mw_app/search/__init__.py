import click

# Expose search_service for easy import elsewhere
from .service import SearchService

search_service = None

def init_search(app):
    """Initialize the search service, ensure indexes, register sync listeners, and register CLI command.

    This is the primary entry point used by the application factory.
    """
    global search_service
    search_service = SearchService(app)
    search_service.ensure_indexes()
    # Register SQLAlchemy event listeners for auto-sync
    from .sync import _register_sync_listeners
    _register_sync_listeners()
    # Register CLI command
    @app.cli.command('search-rebuild')
    def search_rebuild():
        """Rebuild products, shops, and categories indexes. Safe to run repeatedly."""
        from .sync import rebuild_products, rebuild_shops, rebuild_categories
        click.echo('Rebuilding product index...')
        rebuild_products()
        click.echo('Rebuilding shop index...')
        rebuild_shops()
        click.echo('Rebuilding categories index...')
        rebuild_categories()
        click.echo('Search indexes rebuilt.')


def init_app(app):
    """Compatibility wrapper for older code expecting `search.init_app(app)`."""
    init_search(app)
    click.echo('Search indexes rebuilt.')
