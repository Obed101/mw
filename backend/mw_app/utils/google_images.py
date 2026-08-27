"""Display-time resizing for Google-hosted image URLs."""

import re
from urllib.parse import urlsplit


GOOGLE_IMAGE_SMALL = 138
GOOGLE_IMAGE_MEDIUM = 200
GOOGLE_IMAGE_LARGE = 500

_GOOGLE_HOST_SUFFIXES = ('.googleusercontent.com',)
_GOOGLE_SIZE_RE = re.compile(r'w(?P<width>\d+)-h(?P<height>\d+)')


def get_google_image_url(url, size):
    """Request a different Google image size without fetching or storing it."""
    if not url:
        return url

    try:
        parsed = urlsplit(str(url))
        hostname = (parsed.hostname or '').lower()
        requested_size = int(size)
    except (TypeError, ValueError):
        return url

    if (
        parsed.scheme not in {'http', 'https'}
        or not hostname.endswith(_GOOGLE_HOST_SUFFIXES)
        or requested_size <= 0
    ):
        return url

    # Keep every part of the URL intact and only replace an existing size.
    return _GOOGLE_SIZE_RE.sub(
        f'w{requested_size}-h{requested_size}',
        str(url),
        count=1,
    )
