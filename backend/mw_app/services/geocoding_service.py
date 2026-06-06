from functools import lru_cache

import requests
from flask import current_app


DEFAULT_NOMINATIM_USER_AGENT = 'Market Window/1.0 (+https://marketwindow.local)'
NOMINATIM_REVERSE_URL = 'https://nominatim.openstreetmap.org/reverse'


def _clean_location_value(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@lru_cache(maxsize=2048)
def _reverse_geocode_cached(latitude, longitude, user_agent):
    response = requests.get(
        NOMINATIM_REVERSE_URL,
        params={
            'lat': latitude,
            'lon': longitude,
            'format': 'jsonv2',
            'addressdetails': 1,
        },
        headers={
            'User-Agent': user_agent,
            'Accept': 'application/json',
        },
        timeout=10,
    )
    response.raise_for_status()

    payload = response.json() or {}
    address = payload.get('address') or {}
    if not isinstance(address, dict):
        address = {}

    town = (
        address.get('town')
        or address.get('city')
        or address.get('village')
        or address.get('hamlet')
    )
    district = (
        address.get('county')
        or address.get('municipality')
        or address.get('state_district')
    )
    region = address.get('state') or address.get('region')

    return {
        'region': _clean_location_value(region),
        'district': _clean_location_value(district),
        'town': _clean_location_value(town),
    }


def reverse_geocode(latitude: float, longitude: float) -> dict:
    """
    Reverse geocode coordinates into shop location fields.

    Returns:
    {
        "region": "...",
        "district": "...",
        "town": "..."
    }
    """
    lat = round(float(latitude), 6)
    lng = round(float(longitude), 6)
    user_agent = current_app.config.get('NOMINATIM_USER_AGENT', DEFAULT_NOMINATIM_USER_AGENT)
    return dict(_reverse_geocode_cached(lat, lng, user_agent))
