"""
Username generation utilities.

Auto-generates a username from a full name using the pattern:
  first_letter_of_first_name + last_name  (e.g. "John Doe" → "JDoe")

Collision strategy: append a random integer between 1–20 until unique.
Fallback (all 20 taken): append a random 4-digit suffix.
"""

import random
import re


def _sanitize_part(name_part: str) -> str:
    """Strip non-alphanumeric characters and title-case a name part."""
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', name_part)
    return cleaned.title() if cleaned else ''


def parse_full_name(full_name: str) -> tuple[str, str]:
    """
    Split a full name string into (first_name, last_name).
    For single-word names, last_name = first_name and first_name = first_name.
    For names with >2 parts, last part is last_name, first part is first_name.
    """
    parts = full_name.strip().split()
    if not parts:
        return ('', '')
    if len(parts) == 1:
        return (parts[0].strip(), parts[0].strip())
    return (parts[0].strip(), parts[-1].strip())


def build_base_username(first_name: str, last_name: str) -> str:
    """
    Build the base username: first letter of first_name + last_name.
    E.g. first_name='John', last_name='Doe' → 'JDoe'
    """
    first_initial = _sanitize_part(first_name[:1]).upper() if first_name else ''
    safe_last = _sanitize_part(last_name)
    if first_initial and safe_last:
        return f"{first_initial}{safe_last}"
    elif safe_last:
        return safe_last
    elif first_initial:
        return first_initial
    return 'user'


def generate_username(full_name: str) -> tuple[str, str, str]:
    """
    Generate a unique username from a full name.

    Imports the User model lazily (inside function) to avoid circular imports.

    Returns:
        (username, first_name, last_name) — all three derived from the full name.
    """
    from ..models.user_model import User

    first_name, last_name = parse_full_name(full_name)
    base = build_base_username(first_name, last_name)

    # Try exact base first
    if not User.query.filter_by(username=base).first():
        return base, first_name, last_name

    # Try random suffixes 1–20 (shuffled for fairness)
    suffixes = list(range(1, 21))
    random.shuffle(suffixes)
    for suffix in suffixes:
        candidate = f"{base}{suffix}"
        if not User.query.filter_by(username=candidate).first():
            return candidate, first_name, last_name

    # Fallback: 4-digit random suffix
    for _ in range(100):
        candidate = f"{base}{random.randint(1000, 9999)}"
        if not User.query.filter_by(username=candidate).first():
            return candidate, first_name, last_name

    # Absolute fallback (extremely unlikely)
    import secrets
    return f"{base}_{secrets.token_hex(3)}", first_name, last_name
