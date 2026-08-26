"""Validated, optimized Cloudinary image uploads."""

from io import BytesIO
import os

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 8 * 1024 * 1024
_ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def _cloudinary():
    import cloudinary

    cloudinary.config(
        cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
        api_key=os.getenv('CLOUDINARY_API_KEY'),
        api_secret=os.getenv('CLOUDINARY_API_SECRET'),
        secure=True,
    )
    return cloudinary


def process_and_upload_image(file_storage, folder, max_dimensions=(1600, 1200), entity_type='image', entity_id=None):
    """Validate, resize, compress to WEBP, and upload one image."""
    if not file_storage or not getattr(file_storage, 'stream', None):
        raise ValueError('Please choose an image.')

    file_storage.stream.seek(0)
    raw = file_storage.stream.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Image is too large. Use an image under 8MB.')

    try:
        image = Image.open(BytesIO(raw))
        image.verify()
        image = Image.open(BytesIO(raw))
    except (UnidentifiedImageError, OSError):
        raise ValueError('Invalid or corrupt image.')

    if image.format not in _ALLOWED_FORMATS:
        raise ValueError('Unsupported image format. Use JPG, PNG, or WEBP.')

    image.thumbnail(max_dimensions, Image.Resampling.LANCZOS)
    if image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')

    optimized = BytesIO()
    image.save(optimized, format='WEBP', quality=82, method=6, optimize=True)
    optimized.seek(0)

    try:
        result = _cloudinary().uploader.upload(
            optimized,
            folder=folder,
            resource_type='image',
            format='webp',
            unique_filename=True,
            use_filename=False,
        )
    except Exception as exc:
        raise RuntimeError(f'Cloudinary upload failed for {entity_type} {entity_id or "unknown"}') from exc

    return {
        'secure_url': result['secure_url'],
        'public_id': result['public_id'],
        'bytes': len(optimized.getvalue()),
        'format': 'webp',
        'width': image.width,
        'height': image.height,
    }


def delete_image(public_id):
    if not public_id:
        return
    try:
        _cloudinary().uploader.destroy(public_id, resource_type='image', invalidate=True)
    except Exception:
        # Cleanup must not break a successful database update.
        return


def replace_image(new_file, old_public_id, folder, max_dimensions=(1600, 1200), entity_type='image', entity_id=None):
    result = process_and_upload_image(
        new_file,
        folder,
        max_dimensions=max_dimensions,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    delete_image(old_public_id)
    return result
