import click

# Expose search_service for easy import elsewhere
from .service import SearchService

search_service = None

def init_search(app):
    """Initialize the search service, ensure indexes, and register CLI command.

    This is the primary entry point used by the application factory.
    """
    global search_service
    search_service = SearchService(app)
    search_service.ensure_indexes()
    # Register CLI command
    @app.cli.command('search-rebuild')
    def search_rebuild():
        """Rebuild products and shops indexes. Safe to run repeatedly."""
        from .sync import rebuild_products, rebuild_shops
        click.echo('Rebuilding product index...')
        rebuild_products()
        click.echo('Rebuilding shop index...')
        rebuild_shops()
        click.echo('Search indexes rebuilt.')


def init_app(app):
    """Compatibility wrapper for older code expecting `search.init_app(app)`."""
    init_search(app)
    click.echo('Search indexes rebuilt.')
