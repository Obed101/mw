"""Parser for the standardized Instant Data Scraper CSV export."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

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

    REQUIRED_HEADERS = ("name", "category", "address")
    OPTIONAL_HEADERS = ("rating", "links", "delivery", "time")
    ALL_HEADERS = REQUIRED_HEADERS + OPTIONAL_HEADERS

    @classmethod
    def resolve_headers(cls, headers: Iterable[Any]) -> dict[str, str]:
        """Resolve CSV headers to standard names or reject the file."""
        resolved: dict[str, str] = {}
        normalized = {}
        for header in headers:
            original = str(header).strip()
            if original:
                normalized[original.casefold()] = original

        for expected in cls.ALL_HEADERS:
            actual = normalized.get(expected.casefold())
            if actual is not None:
                resolved[expected] = actual

        missing = [header for header in cls.REQUIRED_HEADERS if header not in resolved]
        if missing:
            raise ValueError(
                "Missing required CSV header(s): " + ", ".join(missing)
            )
        return resolved

    def parse_row(
        self,
        row: Mapping[str, Any] | Sequence[Any] | Any,
        headers: Mapping[str, str] | Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        """Return a clean dictionary for one CSV row."""

        if isinstance(row, Mapping):
            header_map = self.resolve_headers(row.keys()) if headers is None else dict(headers)
            values = {
                field: row.get(source, "")
                for field, source in header_map.items()
                if isinstance(source, str)
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
                    field: raw_headers.index(source)
                    for field, source in resolved.items()
                }
            row_values = list(row) if isinstance(row, Sequence) and not isinstance(row, str) else [row]
            values = {
                field: row_values[index]
                for field, index in header_map.items()
                if isinstance(index, int) and index < len(row_values)
            }

        address_value = values.get("address", "")
        links_value = values.get("links", "")
        time_value = values.get("time", "")

        image_url = self.extract_image_url({"links": links_value})
        phone = self.extract_phone({"address": address_value})
        plus_code = self.extract_plus_code({"address": address_value})
        rating = self.extract_rating({"rating": values.get("rating", "")})
        time = self._clean_text(time_value) or None
        google_category = self._normalize_category(values.get("category", ""))
        address = self.extract_address({"address": address_value})
        name = self._clean_name(values.get("name", ""))
        delivery = self._has_delivery(values.get("delivery", ""))
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

    def persist_imports(self, parsed_rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        """Stage parsed rows in ``ShopImport`` and commit them once.

        Rows with a phone number already present in the staging table, or
        repeated earlier in this batch, are skipped. Rows without a phone
        number cannot be deduplicated by phone and are retained.
        """
        from ..extensions import db
        from ..models.shop_model import ShopImport

        existing_phone_keys = {
            phone_key
            for phone_key in (self._phone_key(item.phone_number) for item in ShopImport.query.all())
            if phone_key
        }
        seen_phone_keys = set(existing_phone_keys)
        staged_count = 0
        duplicate_count = 0
        skipped_count = 0

        for data in parsed_rows:
            name = self._clean_name(data.get("name"))
            if not name:
                skipped_count += 1
                continue

            phone_number = data.get("phone")
            phone_key = self._phone_key(phone_number)
            if phone_key and phone_key in seen_phone_keys:
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
                )
            )
            staged_count += 1
            if phone_key:
                seen_phone_keys.add(phone_key)

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
        cleaned = self._clean_text(value)
        cleaned = re.sub(r"^[^\w]+", "", cleaned, flags=re.UNICODE).strip()
        return cleaned or None

    def _has_delivery(self, value: Any) -> bool:
        return "delivery" in self._clean_text(value).casefold()

    # ------------------------------------------------------------------
    # Cell normalization
    # ------------------------------------------------------------------

    def _cells(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> list[_Cell]:
        if row is None:
            return []

        if isinstance(row, str):
            values: Iterable[Any] = [row]
        elif isinstance(row, Mapping):
            values = row.values()
        elif hasattr(row, "values") and callable(getattr(row, "values")):
            values = row.values()
        elif isinstance(row, Sequence):
            values = row
        else:
            values = [row]

        cells: list[_Cell] = []
        if isinstance(row, Mapping):
            items = row.items()
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

        lower = text.lower()
        if "@" in text and "google" in lower:
            at_match = re.search(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)", text)
            if at_match:
                lat = float(at_match.group(1))
                lng = float(at_match.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                    return f"{lat},{lng}"

        latlng_match = re.search(r"(?i)!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)", text)
        if latlng_match:
            lat = float(latlng_match.group(1))
            lng = float(latlng_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return f"{lat},{lng}"
        return None

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

    def extract_image_url(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            data_match = _DATA_IMAGE_URL_RE.search(cell.text)
            if data_match:
                return data_match.group(0)
            match = _GOOGLE_IMAGE_URL_RE.search(cell.text)
            if match:
                return match.group(0)
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
