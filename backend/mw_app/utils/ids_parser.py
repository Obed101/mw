"""Parser for the standardized Instant Data Scraper CSV export."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
import time
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

import requests

__all__ = ["IDSParser"]


_PLUS_CODE_CHARS = "23456789CFGHJMPQRVWX"
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?233\s*|0)(?:[\s\-]*\d){9}(?!\d)")
_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
_PLUS_CODE_RE = re.compile(rf"\b[{_PLUS_CODE_CHARS}]{{4,8}}\+[{_PLUS_CODE_CHARS}]{{2,3}}\b")
_RATING_RE = re.compile(r"(?<!\d)([0-5](?:\.\d)?)\b")
_GOOGLE_IMAGE_URL_RE = re.compile(
    r"(?i)\bhttps?://[^\s\"']*(?:googleusercontent\.com|maps/vt/data)[^\s\"']*"
)
_DATA_IMAGE_URL_RE = re.compile(r"(?i)data:image[^\s\"']*")
_URL_RE = re.compile(r"(?i)https?://[^\s\"<>]+")
_GOOGLE_MAPS_COORDINATES_RE = re.compile(
    r"!3d([+-]?(?:\d+(?:\.\d*)?|\.\d+))!4d([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
)
_SEPARATOR_RE = re.compile(r"\s*(?:\u00b7|\u2022|\||/)\s*")
_MULTISPACE_RE = re.compile(r"\s+")

_ADDRESS_HINTS = (
    "street", "st",
    "road", "rd",
    "avenue", "ave",
    "lane", "ln",
    "close", "crescent", 
    "estate", "highway", 
    "boulevard", "blvd",
    "building", "bldg",
    "floor", "suite",
    "box", "p.o. box", "po box",
    "plot",
    "opposite", "near", "beside", "behind", 
    "next to", "adjacent to", "across from",
    "junction", "roundabout", "close to",
    "opposite to", "around",
    "station", "terminal",
    "market", "mall",
    "hospital", "clinic",
    "school", "university", "college",
    "church", "mosque",
    "pharmacy", "hotel",
    "bank", "office", "park",
    "zongo", "community",
    "lorry", "taxi",
    "square", "traffic",
)

_ADDRESS_HINTS = _ADDRESS_HINTS + (
    # Relative location
    "opposite", "near", "beside", "behind", "next to", "adjacent to",
    "across from", "close to", "opposite to", "around", "along",
    "before", "after", "past", "between", "in front of", "behind",
    "within", "off", "just off", "around the corner", "floor",

    # Roads and streets
    "street", "st", "road", "rd", "avenue", "ave", "lane", "drive",
    "highway", "motorway", "boulevard", "crescent", "way",

    # Junctions / transport / landmarks
    "junction", "roundabout", "interchange", "traffic light",
    "taxi rank", "lorry station", "bus station", "station", "terminal",
    "trotro", "transport station", "main station",

    # Commercial landmarks
    "market", "mall", "shopping centre", "shopping center", "plaza",
    "complex", "mini mall", "supermarket", "filling station",
    "fuel station", "shell", "goil", "total",

    # Institutions commonly used as Ghanaian landmarks
    "hospital", "clinic", "pharmacy", "school", "college", "university",
    "church", "mosque", "bank", "office", "hotel", "resort",
    "police station", "fire service", "post office",

    # Ghanaian locality/address terminology
    "community", "estate", "town", "village", "suburb", "area",
    "zone", "sector", "extension", "new site", "old site",
    "central", "main road", "main street",

    # Common directional/location wording
    "towards", "toward", "heading to", "on the way to", "road to",
    "en route", "corner of", "at the corner", "at", "within", "on top of",
)

@dataclass(frozen=True)
class _Cell:
    column: Any
    raw: Any
    text: str
    lower: str


class IDSParser:
    """Parse one row using only the standardized columns."""

    REQUIRED_HEADERS = ("name", "category", "address", "gps")
    OPTIONAL_HEADERS = ("phone", "rating", "links", "delivery", "time")
    ALL_HEADERS = REQUIRED_HEADERS + OPTIONAL_HEADERS

    NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
    NOMINATIM_USER_AGENT = "Market Window IDS parser/1.0 (+https://marketwindow.local)"
    NOMINATIM_MIN_INTERVAL = 1.0

    def __init__(self) -> None:
        self._last_nominatim_request = 0.0
        self._geocode_cache: dict[tuple[float, float], dict[str, str | None]] = {}

    @classmethod
    def resolve_headers(cls, headers: Iterable[Any]) -> dict[str, list[str]]:
        """Resolve CSV headers, retaining every matching column."""
        resolved: dict[str, list[str]] = {}
        normalized: dict[str, list[str]] = {}
        for header in headers:
            original = str(header).strip()
            if original:
                normalized.setdefault(original.casefold(), []).append(original)

        for expected in cls.ALL_HEADERS:
            matches = normalized.get(expected.casefold())
            if matches:
                resolved[expected] = matches

        missing = [header for header in cls.REQUIRED_HEADERS if header not in resolved]
        if missing:
            raise ValueError(
                "Missing required CSV header(s): " + ", ".join(missing)
            )
        return resolved

    def parse_row(
        self,
        row: Mapping[str, Any] | Sequence[Any] | Any,
        headers: Mapping[str, str | Sequence[Any]] | Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        """Return a clean dictionary for one CSV row."""

        if isinstance(row, Mapping):
            header_map = self.resolve_headers(row.keys()) if headers is None else dict(headers)
            values = {
                field: [row.get(source, "") for source in self._source_list(source)]
                for field, source in header_map.items()
                if source is not None
            }
        else:
            if headers is None:
                raise ValueError("CSV row headers are required for sequence rows.")
            if isinstance(headers, Mapping):
                header_map = dict(headers)
            else:
                raw_headers = list(headers)
                resolved = self.resolve_headers(raw_headers)
                header_map = {
                    field: [index for index, header in enumerate(raw_headers)
                            if str(header).strip().casefold() == field.casefold()]
                    for field, source in resolved.items()
                }
            row_values = list(row) if isinstance(row, Sequence) and not isinstance(row, str) else [row]
            values = {
                field: [row_values[index] for index in self._source_list(indexes)
                         if index < len(row_values)]
                for field, indexes in header_map.items()
            }

        address_values = values.get("address", [])
        phone_values = values.get("phone", [])
        links_values = values.get("links", [])

        image_url = self.extract_image_url({"links": links_values})
        phone = self.extract_phone({"phone": phone_values, "address": address_values})
        plus_code = self.extract_plus_code({"address": address_values})
        rating = self.extract_rating({"rating": values.get("rating", [])})
        time = self._first_clean_value(values.get("time", []))
        google_category = self._normalize_category(values.get("category", []))
        address = self.extract_address({"address": address_values})
        name = self._clean_name(self._first_clean_value(values.get("name", [])))
        delivery = self._has_delivery(values.get("delivery", []))
        coordinates = self.extract_gps({"gps": values.get("gps", [])})
        result = {
            "name": name,
            "google_category": google_category,
            "rating": rating,
            "phone": phone,
            "address": address,
            "plus_code": plus_code,
            "image_url": image_url,
            "delivery": delivery,
            "time": time,
            "latitude": coordinates[0] if coordinates else None,
            "longitude": coordinates[1] if coordinates else None,
            "town": None,
            "district": None,
            "region": None,
            "source": "google",
            "warnings": [],
        }
        result["warnings"] = self._build_warnings(result)
        return result

    @staticmethod
    def _phone_key(value: Any) -> str | None:
        """Normalize a phone value for duplicate detection."""
        digits = re.sub(r"\D", "", str(value or ""))
        if digits.startswith("233") and len(digits) == 12:
            return digits
        if digits.startswith("0") and len(digits) == 10:
            return "233" + digits[1:]
        if len(digits) == 9:
            return "233" + digits
        return None

    def _identity_key(self, value: Any) -> str | None:
        cleaned = self._clean_text(value).casefold()
        cleaned = re.sub(r"[^\w]+", " ", cleaned, flags=re.UNICODE)
        cleaned = _MULTISPACE_RE.sub(" ", cleaned).strip()
        return cleaned or None

    def _duplicate_keys(self, data: Mapping[str, Any]) -> tuple[tuple[str, str] | None, set[tuple[str, str]]]:
        name_key = self._identity_key(data.get("name"))
        phone_key = self._phone_key(data.get("phone"))
        phone_name_key = (phone_key, name_key) if phone_key and name_key else None
        attributes = {
            self._identity_key(data.get(field))
            for field in ("address", "google_category", "plus_code")
        }
        if data.get("latitude") is not None and data.get("longitude") is not None:
            attributes.add(f"{float(data['latitude']):.5f},{float(data['longitude']):.5f}")
        no_phone_keys = {
            (name_key, attribute)
            for attribute in attributes
            if name_key and attribute
        }
        return phone_name_key, no_phone_keys

    def persist_imports(
        self,
        parsed_rows: Iterable[Mapping[str, Any]],
        uploader_user_id: int | None = None,
        import_batch: str | None = None,
    ) -> dict[str, int]:
        """Stage parsed rows in ``ShopImport`` and commit them once.

        Rows with the same normalized phone and name are skipped. Rows
        without phones are skipped only when their normalized name and at
        least one other attribute also match.
        """
        from ..extensions import db
        from ..models.shop_model import ShopImport

        existing_phone_name_keys = set()
        existing_no_phone_keys = set()
        for item in ShopImport.query.filter(ShopImport.import_status != "rejected").all():
            phone_name_key, no_phone_keys = self._duplicate_keys({
                "name": item.name,
                "phone": item.phone_number,
                "address": item.address,
                "google_category": item.category,
                "plus_code": item.plus_code,
                "latitude": item.latitude,
                "longitude": item.longitude,
            })
            if phone_name_key:
                existing_phone_name_keys.add(phone_name_key)
            if not self._phone_key(item.phone_number):
                existing_no_phone_keys.update(no_phone_keys)
        staged_count = 0
        duplicate_count = 0
        skipped_count = 0

        for data in parsed_rows:
            name = self._clean_name(data.get("name"))
            if not name:
                skipped_count += 1
                continue

            phone_number = data.get("phone")
            phone_name_key, no_phone_keys = self._duplicate_keys(data)
            is_duplicate = (
                phone_name_key in existing_phone_name_keys
                if phone_name_key
                else bool(existing_no_phone_keys.intersection(no_phone_keys))
            )
            if is_duplicate:
                duplicate_count += 1
                continue

            db.session.add(
                ShopImport(
                    name=name,
                    category=data.get("google_category"),
                    rating=data.get("rating"),
                    address=data.get("address"),
                    phone_number=phone_number,
                    closing_time=data.get("time"),
                    plus_code=data.get("plus_code"),
                    image_url=data.get("image_url"),
                    delivery=bool(data.get("delivery", False)),
                    latitude=data.get("latitude"),
                    longitude=data.get("longitude"),
                    uploader_user_id=uploader_user_id,
                    import_batch=import_batch,
                )
            )
            staged_count += 1
            if phone_name_key:
                existing_phone_name_keys.add(phone_name_key)
            else:
                existing_no_phone_keys.update(no_phone_keys)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        return {
            "staged_count": staged_count,
            "duplicate_count": duplicate_count,
            "skipped_count": skipped_count,
        }

    def _clean_name(self, value: Any) -> str | None:
        cleaned = self._clean_text(value).strip(" '\"\u2018\u2019\u201c\u201d")
        return cleaned or None

    def _normalize_category(self, value: Any) -> str | None:
        for item in self._source_list(value):
            cleaned = self._clean_text(item)
            cleaned = re.sub(r"^[^\w]+", "", cleaned, flags=re.UNICODE).strip()
            if cleaned:
                return cleaned
        return None

    def _has_delivery(self, value: Any) -> bool:
        return any("delivery" in self._clean_text(item).casefold() for item in self._source_list(value))

    @staticmethod
    def _source_list(value: Any) -> list[Any]:
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]

    def _first_clean_value(self, value: Any) -> str | None:
        for item in self._source_list(value):
            cleaned = self._clean_text(item)
            if cleaned:
                return cleaned
        return None

    def _reverse_geocode(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, str | None]:
        cache_key = (round(float(latitude), 6), round(float(longitude), 6))
        if cache_key in self._geocode_cache:
            return self._geocode_cache[cache_key]

        elapsed = time.monotonic() - self._last_nominatim_request
        if elapsed < self.NOMINATIM_MIN_INTERVAL:
            time.sleep(self.NOMINATIM_MIN_INTERVAL - elapsed)

        self._last_nominatim_request = time.monotonic()
        response = requests.get(
            self.NOMINATIM_REVERSE_URL,
            params={
                "lat": cache_key[0],
                "lon": cache_key[1],
                "format": "jsonv2",
                "addressdetails": 1,
            },
            headers={
                "User-Agent": self.NOMINATIM_USER_AGENT,
                "Accept": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()

        payload = response.json() or {}
        address = payload.get("address") or {}
        location = {
            "town": address.get("town") or address.get("city") or address.get("village") or address.get("hamlet"),
            "district": address.get("county") or address.get("municipality") or address.get("state_district"),
            "region": address.get("state") or address.get("region"),
        }
        self._geocode_cache[cache_key] = location
        return location

    # ------------------------------------------------------------------
    # Cell normalization
    # ------------------------------------------------------------------

    def _cells(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> list[_Cell]:
        if row is None:
            return []

        if isinstance(row, str):
            values: Iterable[Any] = [row]
        elif isinstance(row, Mapping):
            values = (
                item
                for value in row.values()
                for item in self._source_list(value)
            )
        elif hasattr(row, "values") and callable(getattr(row, "values")):
            values = row.values()
        elif isinstance(row, Sequence):
            values = row
        else:
            values = [row]

        cells: list[_Cell] = []
        if isinstance(row, Mapping):
            items = (
                (column, item)
                for column, value in row.items()
                for item in self._source_list(value)
            )
        elif hasattr(row, "items") and callable(getattr(row, "items")):
            items = row.items()
        else:
            items = enumerate(values)

        for column, value in items:
            text = self._clean_text(value)
            if text:
                cells.append(_Cell(column=column, raw=value, text=text, lower=text.lower()))
        return cells

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value != value:
            return ""

        text = html.unescape(str(value))
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\xa0", " ")
        text = text.replace("\u00c2\u00b7", "\u00b7")
        text = text.replace("\u200b", "")
        text = _MULTISPACE_RE.sub(" ", text).strip()
        return text

    def _strip_known_fragments(self, text: str) -> str:
        cleaned = re.sub(_GOOGLE_IMAGE_URL_RE, "", text).strip()
        cleaned = re.sub(_PHONE_RE, "", cleaned).strip()
        cleaned = re.sub(_PLUS_CODE_RE, "", cleaned).strip()
        cleaned = re.sub(_EMAIL_RE, "", cleaned).strip()
        return _MULTISPACE_RE.sub(" ", cleaned.strip(" ,;:-")).strip()

    def _matches_any(self, text: str, hints: Sequence[str]) -> bool:
        lower = text.lower()
        return any(
            re.search(rf"(?<!\w){re.escape(hint.lower())}(?!\w)", lower)
            for hint in hints
        )

    def _looks_like_region_or_district(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            key in lowered
            for key in ("region", "district", "municipality", "metropolitan", "metro")
        )

    def _looks_like_address(self, text: str) -> bool:
        return self._matches_any(text, _ADDRESS_HINTS)

    def _looks_like_address_like(self, text: str) -> bool:
        return bool(re.search(r"\d", text)) and any(ch.isalpha() for ch in text)

    def _split_location_cell(self, text: str) -> str | None:
        cleaned = self._strip_known_fragments(text)
        if not cleaned:
            return None

        segments = [segment.strip() for segment in _SEPARATOR_RE.split(cleaned) if segment.strip()]
        location_segments = [
            segment
            for segment in segments
            if (
                self._looks_like_address(segment)
                or self._looks_like_address_like(segment)
                or self._looks_like_region_or_district(segment)
                or len(segments) == 1
            )
        ]
        return " · ".join(location_segments) or cleaned

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_name(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        cells = self._cells(row)
        return self._clean_name(cells[0].text) if cells else None

    def extract_phone(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _PHONE_RE.search(cell.text)
            if not match:
                continue
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("233") and len(digits) == 12:
                return f"233{digits[3:]}"
            if digits.startswith("0") and len(digits) == 10:
                return f"233{digits[1:]}"
            if len(digits) == 9:
                return f"233{digits}"
        return None


    def extract_address(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        cells = self._cells(row)
        return self._split_location_cell(cells[0].text) if cells else None

    def extract_plus_code(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _PLUS_CODE_RE.search(cell.text.upper())
            if match:
                return match.group(0).upper()
        return None

    def extract_google_category(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        cells = self._cells(row)
        return self._normalize_category(cells[0].text) if cells else None

    def extract_gps(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> tuple[float, float] | None:
        """Extract latitude and longitude from the named ``gps`` cell."""
        for cell in self._cells(row):
            match = _GOOGLE_MAPS_COORDINATES_RE.search(cell.text)
            if not match:
                continue

            latitude = float(match.group(1))
            longitude = float(match.group(2))
            if -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0:
                return latitude, longitude
        return None

    def extract_image_url(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            data_match = _DATA_IMAGE_URL_RE.search(cell.text)
            if data_match:
                return data_match.group(0)
            match = _GOOGLE_IMAGE_URL_RE.search(cell.text)
            if match:
                return match.group(0)
            match = _URL_RE.search(cell.text)
            if match:
                return match.group(0).rstrip('.,;)]}')
        return None

    def extract_rating(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> float | None:
        for cell in self._cells(row):
            rating = self._rating_from_text(cell.text)
            if rating is not None:
                return rating
        return None

    def _rating_from_text(self, text: str) -> float | None:
        lowered = text.lower()
        if "rating" not in lowered and "star" not in lowered and not re.fullmatch(r"[0-5](?:\.\d)?", text.strip()):
            return None
        match = _RATING_RE.search(text.strip())
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        return value if 0.0 <= value <= 5.0 else None

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------

    def _build_warnings(self, result: Mapping[str, Any]) -> list[str]:
        warnings: list[str] = []
        checks = [
            ("name", "Shop name not found"),
            ("phone", "Phone number not found"),
            ("address", "Address not found"),
            ("plus_code", "Plus code not found"),
            ("latitude", "GPS coordinates not found"),
            ("google_category", "Category not found"),
            ("image_url", "Image URL not found"),
            ("rating", "Rating not found"),
            ("delivery", "Delivery value not found"),
            ("time", "Time not found"),
        ]
        for field, message in checks:
            if result.get(field) in (None, "", []):
                warnings.append(message)
        return warnings
