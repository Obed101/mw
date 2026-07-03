def get_shop_progress(shop):
    """Return a dict indicating completion of key shop setup steps.
    Steps:
    - shop created (always True when shop exists)
    - image uploaded (shop.image_urls and primary_image_url)
    - logo optional (not required)
    - at least 5 products
    - verification requested (shop.can_request_verification())
    """
    product_count = len(shop.products) if hasattr(shop, 'products') else 0
    image_urls = list(shop.image_urls or [])
    progress = {
        'created': bool(shop.id),
        'front_image_added': bool(image_urls),
        'logo_added': bool(getattr(shop, 'logo_url', None) or image_urls[1:2]),
        'has_min_products': product_count >= 5,
        'verification_requested': shop.can_request_verification(),
    }
    return progress
