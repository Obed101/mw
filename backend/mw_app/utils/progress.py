def get_shop_progress(shop):
    """Return a dict indicating completion of key shop setup steps.
    Steps:
    - shop created (always True when shop exists)
    - image uploaded (shop.image_urls and primary_image_url)
    - logo optional (not required)
    - at least 5 products
    - verification requested (shop.can_request_verification())
    """
    product_count = shop.products.count() if hasattr(shop, 'products') else 0
    progress = {
        'created': bool(shop.id),
        'image_uploaded': bool(shop.image_urls),
        'has_logo': bool(getattr(shop, 'logo_url', None)),
        'has_min_products': product_count >= 5,
        'verification_requested': shop.can_request_verification(),
    }
    return progress
