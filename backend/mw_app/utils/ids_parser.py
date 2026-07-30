"""Instant Data Scraper parser for Google Maps CSV exports.

The parser is content-driven:
- it inspects every cell in the row
- it does not depend on IDS header names
- it returns a plain dictionary that can be validated and imported later
"""

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
_REVIEW_COUNT_RE = re.compile(r"\((\d{1,5})\)")
_GPS_RE = re.compile(r"(?<!\d)(-?\d{1,2}\.\d+)\s*[, ]\s*(-?\d{1,3}\.\d+)(?!\d)")
_TIME_RANGE_RE = re.compile(
    r"(?i)\b(?:"
    r"open\s*24\s*hours|"
    r"open\s*now|"
    r"temporarily\s*closed|"
    r"closed|"
    r"opens?\s+at|"
    r"closes?\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*[-\u2013]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
    r")\b"
)
_GOOGLE_MAPS_URL_RE = re.compile(
    r"(?i)\bhttps?://(?:www\.)?(?:google\.[^/\s]+/maps|maps\.google\.[^/\s]+|maps\.app\.goo\.gl|goo\.gl/maps|google\.com/maps)[^\s]*"
)
_GOOGLE_IMAGE_URL_RE = re.compile(
    r"(?i)\bhttps?://[^\s\"']*(?:googleusercontent\.com|maps/vt/data)[^\s\"']*"
)
_SEPARATOR_RE = re.compile(r"\s*(?:\u00b7|\u2022|\||/)\s*")
_MULTISPACE_RE = re.compile(r"\s+")

_ADDRESS_HINTS = (
    "street",
    "st",
    "road",
    "rd",
    "avenue",
    "ave",
    "lane",
    "ln",
    "close",
    "crescent",
    "estate",
    "highway",
    "boulevard",
    "blvd",
    "building",
    "bldg",
    "floor",
    "suite",
    "box",
    "p.o. box",
    "po box",
    "plot",
    "opposite",
    "near",
    "beside",
    "behind",
    "next to",
    "adjacent to",
    "across from",
    "junction",
    "roundabout",
    "close to",
    "opposite to",
    "around",
)
_LANDMARK_HINTS = (
    "opposite",
    "near",
    "beside",
    "behind",
    "next to",
    "adjacent to",
    "across from",
    "junction",
    "roundabout",
    "close to",
    "opposite to",
    "around",
)
_DESCRIPTION_PHRASE_HINTS = (
    "customer service",
    "quality service",
    "one-stop",
    "one stop",
    "our products",
    "our services",
)
_DESCRIPTION_WORD_HINTS = {
    "we",
    "our",
    "us",
    "sell",
    "selling",
    "offer",
    "offering",
    "providing",
    "buy",
    "visit",
    "come",
    "experience",
    "quality",
    "affordable",
    "cheap",
    "best",
    "good",
    "excellent",
    "professional",
    "friendly",
    "services",
    "products",
    "items",
    "available",
    "fresh",
    "wholesale",
    "retail",
    "original",
    "genuine",
    "trusted",
    "modern",
    "clean",
    "comfortable",
    "reliable",
    "guaranteed",
    "satisfaction",
    "variety",
    "everything",
    "all",
    "prices",
    "discount",
    "welcome",
    "special",
    "top",
    "leading",
    "premier",
    "expert",
    "fast",
    "quick",
    "your",
    "needs",
}
_SERVICE_PHRASES = {
    "delivery": "Delivery",
    "takeaway": "Takeaway",
    "take away": "Takeaway",
    "in-store shopping": "In-store shopping",
    "in store shopping": "In-store shopping",
    "curbside pickup": "Curbside pickup",
    "dine-in": "Dine-in",
    "dine in": "Dine-in",
    "pickup": "Pickup",
    "pick-up": "Pickup",
    "online service": "Online service",
    "consultation": "Consultation",
    "repair service": "Repair service",
    "home delivery": "Home delivery",
}
_SERVICE_BUSINESS_HINTS = (
    "barber",
    "salon",
    "clinic",
    "hospital",
    "pharmacy",
    "lawyer",
    "legal",
    "accountant",
    "consultant",
    "repair",
    "repairs",
    "laundry",
    "tailor",
    "tailoring",
    "mechanic",
    "plumber",
    "electrician",
    "cafe",
    "restaurant",
    "hotel",
    "guest house",
    "school",
    "church",
    "mosque",
    "bank",
    "insurance",
    "gym",
    "spa",
)
_STANDALONE_CATEGORY_PHRASES = {
    "shop",
    "retail store",
    "provision store",
    "store",
    "organic food store",
    "natural goods store",
    "market",
    "supermarket",
    "grocery",
    "grocery store",
    "mart",
    "boutique",
    "wholesale",
    "salon",
    "barber",
    "restaurant",
    "cafe",
    "hotel",
    "guest house",
    "pharmacy",
    "clinic",
    "station",
    "hardware",
    "hardware store",
    "electronics",
    "electronics store",
    "furniture",
    "furniture store",
    "fashion",
    "fashion store",
    "bakery",
    "butcher",
    "tailor",
    "repair",
}


@dataclass(frozen=True)
class _Cell:
    raw: Any
    text: str
    lower: str


class IDSParser:
    """Parse a single IDS row into the Market Window import schema."""

    def parse_row(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> dict[str, Any]:
        """Return a clean dictionary for one CSV row."""

        maps_url = self.extract_maps_url(row)
        image_url = self.extract_image_url(row)
        phone = self.extract_phone(row)
        email = self.extract_email(row)
        plus_code = self.extract_plus_code(row)
        gps = self.extract_gps(row)
        rating = self.extract_rating(row)
        review_count = self.extract_review_count(row)
        opening_hours = self.extract_opening_hours(row)
        services = self.extract_services(row)
        google_category = self.extract_google_category(row)
        address = self.extract_address(row)
        landmark = self.extract_landmark(row)
        town = self.extract_town(row)
        district = self.extract_district(row)
        region = self.extract_region(row)
        description = self.extract_description(row)
        name = self.extract_name(row)
        business_type = self.extract_business_type(name, google_category, services)

        result = {
            "name": name,
            "description": description,
            "business_type": business_type,
            "phone": phone,
            "email": email,
            "address": address,
            "landmark": landmark,
            "town": town,
            "district": district,
            "region": region,
            "gps": gps,
            "plus_code": plus_code,
            "google_category": google_category,
            "image_url": image_url,
            "maps_url": maps_url,
            "rating": rating,
            "review_count": review_count,
            "opening_hours": opening_hours,
            "services": services,
            "source": "google",
            "source_reference": maps_url or self.extract_source_reference(row),
            "warnings": [],
        }
        result["warnings"] = self._build_warnings(result)
        return result

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
        for value in values:
            text = self._clean_text(value)
            if text:
                cells.append(_Cell(raw=value, text=text, lower=text.lower()))
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
        cleaned = text
        cleaned = re.sub(_GOOGLE_MAPS_URL_RE, "", cleaned).strip()
        cleaned = re.sub(_GOOGLE_IMAGE_URL_RE, "", cleaned).strip()
        cleaned = re.sub(_PHONE_RE, "", cleaned).strip()
        cleaned = re.sub(_PLUS_CODE_RE, "", cleaned).strip()
        cleaned = re.sub(_EMAIL_RE, "", cleaned).strip()
        cleaned = re.sub(_GPS_RE, "", cleaned).strip()
        cleaned = cleaned.strip(" ,;:-")
        cleaned = _MULTISPACE_RE.sub(" ", cleaned).strip()
        return cleaned

    def _matches_any(self, text: str, hints: Sequence[str]) -> bool:
        lower = text.lower()
        return any(hint in lower for hint in hints)

    def _is_noise(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if stripped in {"-", "\u2014", "\u2013", "N/A", "na", "NA"}:
            return True
        if len(stripped) == 1 and not stripped.isalnum():
            return True
        return False

    def _looks_like_opening_hours(self, text: str) -> bool:
        lowered = text.lower()
        return bool(_TIME_RANGE_RE.search(text) or any(term in lowered for term in ("open", "closed", "hours", "temporarily closed")))

    def _looks_like_region_or_district(self, text: str) -> bool:
        lowered = text.lower()
        return any(key in lowered for key in ("region", "district", "municipality", "metropolitan", "metro"))

    def _looks_like_address(self, text: str) -> bool:
        lowered = text.lower()
        if self._looks_like_region_or_district(text):
            return False
        if self._matches_any(lowered, _LANDMARK_HINTS):
            return False
        return any(hint in lowered for hint in _ADDRESS_HINTS)

    def _looks_like_landmark(self, text: str) -> bool:
        lowered = text.lower()
        if self._looks_like_region_or_district(text):
            return False
        return any(hint in lowered for hint in _LANDMARK_HINTS)

    def _looks_like_address_like(self, text: str) -> bool:
        return bool(re.search(r"\d", text)) and any(ch.isalpha() for ch in text) and not self._looks_like_landmark(text)

    def _looks_like_landmark_like(self, text: str) -> bool:
        if self._looks_like_address(text):
            return False
        return len(text.split()) <= 6 and any(ch.isalpha() for ch in text)

    def _split_location_cell(self, text: str) -> tuple[str | None, str | None]:
        cleaned = self._strip_known_fragments(text)
        if not cleaned:
            return None, None

        segments = [segment.strip() for segment in _SEPARATOR_RE.split(cleaned) if segment.strip()]
        if not segments:
            segments = [cleaned]

        address = None
        landmark = None
        for segment in segments:
            if self._looks_like_address(segment):
                address = address or segment
                continue
            if self._looks_like_landmark(segment):
                landmark = landmark or segment
                continue
            if self._looks_like_region_or_district(segment):
                continue
            if not address and self._looks_like_address_like(segment):
                address = segment
                continue
            if not landmark and self._looks_like_landmark_like(segment):
                landmark = segment
                continue

            if not address and len(segment.split()) >= 2 and not self._looks_like_opening_hours(segment):
                address = segment
            elif not landmark and len(segment.split()) <= 6:
                landmark = segment

        return address, landmark

    def _extract_admin_area(self, text: str, keywords: Sequence[str]) -> str | None:
        lowered = text.lower()
        for keyword in keywords:
            if keyword in lowered:
                cleaned = re.sub(r"(?i)\b(town|city|district|municipality|metropolitan|metro|region)\b[:\-]?", "", text)
                cleaned = self._strip_known_fragments(cleaned)
                cleaned = cleaned.strip(" ,;:-")
                return cleaned or self._titleish(text)
        return None

    def _extract_gps_from_text(self, text: str) -> str | None:
        match = _GPS_RE.search(text)
        if match:
            lat = float(match.group(1))
            lng = float(match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return f"{lat},{lng}"

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
        best_value = None
        best_score = 0.0
        for index, cell in enumerate(cells):
            score = self._name_score(cell.text, index)
            if score > best_score:
                best_score = score
                best_value = cell.text
        return best_value if best_score >= 3.5 else None

    def extract_phone(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _PHONE_RE.search(cell.text)
            if not match:
                continue
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("233") and len(digits) == 12:
                return f"+233{digits[3:]}"
            if digits.startswith("0") and len(digits) == 10:
                return f"+233{digits[1:]}"
            if len(digits) == 9:
                return f"+233{digits}"
        return None

    def extract_email(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _EMAIL_RE.search(cell.text)
            if match:
                return match.group(0)
        return None

    def extract_address(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            address, _ = self._split_location_cell(cell.text)
            if address:
                return address
        return None

    def extract_landmark(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            _, landmark = self._split_location_cell(cell.text)
            if landmark:
                return landmark
        return None

    def extract_town(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            town = self._extract_admin_area(cell.text, ("town", "city"))
            if town:
                return town
            if "," in cell.text:
                parts = [part.strip() for part in cell.text.split(",") if part.strip()]
                if len(parts) >= 2 and self._looks_like_region_or_district(parts[-1]) and not self._looks_like_address(parts[0]):
                    return parts[0]
        return None

    def extract_district(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            district = self._extract_admin_area(cell.text, ("district", "municipality", "metropolitan", "metro"))
            if district:
                return district
        return None

    def extract_region(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            region = self._extract_admin_area(cell.text, ("region",))
            if region:
                return region
        return None

    def extract_gps(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            gps = self._extract_gps_from_text(cell.text)
            if gps:
                return gps
        return None

    def extract_plus_code(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _PLUS_CODE_RE.search(cell.text.upper())
            if match:
                return match.group(0).upper()
        return None

    def extract_google_category(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            candidate = self._category_candidate(cell.text)
            if candidate:
                return candidate
        return None

    def extract_image_url(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _GOOGLE_IMAGE_URL_RE.search(cell.text)
            if match:
                return match.group(0)
        return None

    def extract_maps_url(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            match = _GOOGLE_MAPS_URL_RE.search(cell.text)
            if match:
                return match.group(0)
        return None

    def extract_rating(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> float | None:
        for cell in self._cells(row):
            rating = self._rating_from_text(cell.text)
            if rating is not None:
                return rating
        return None

    def extract_review_count(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> int | None:
        for cell in self._cells(row):
            review_count = self._review_count_from_text(cell.text)
            if review_count is not None:
                return review_count
        return None

    def extract_opening_hours(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            opening_hours = self._opening_hours_from_text(cell.text)
            if opening_hours:
                return opening_hours
        return None

    def extract_services(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> list[str]:
        services: list[str] = []
        seen: set[str] = set()
        for cell in self._cells(row):
            lower = cell.lower
            for needle, canonical in _SERVICE_PHRASES.items():
                if needle in lower and canonical not in seen:
                    services.append(canonical)
                    seen.add(canonical)
        return services

    def extract_description(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        cells = self._cells(row)
        best_value = None
        best_score = 0.0
        for index, cell in enumerate(cells):
            score = self._description_score(cell.text, index)
            if score > best_score:
                best_score = score
                best_value = cell.text
        return best_value if best_score >= 3.0 else None

    def extract_source_reference(self, row: Mapping[str, Any] | Sequence[Any] | Any) -> str | None:
        for cell in self._cells(row):
            maps_match = _GOOGLE_MAPS_URL_RE.search(cell.text)
            if maps_match:
                return maps_match.group(0)
            if "place_id=" in cell.lower or "cid=" in cell.lower:
                return cell.text
        return None

    def extract_business_type(
        self,
        name: str | None,
        google_category: str | None,
        services: Sequence[str] | None,
    ) -> str:
        """Infer business type without Flask or SQLAlchemy dependencies."""

        haystacks = [name or "", google_category or ""]
        haystacks.extend(services or [])
        combined = " | ".join(haystacks).lower()

        service_hits = sum(1 for hint in _SERVICE_BUSINESS_HINTS if hint in combined)
        retail_hits = sum(1 for hint in _STANDALONE_CATEGORY_PHRASES if hint in combined)

        if service_hits and retail_hits:
            return "both"
        if service_hits:
            return "service"
        return "sales"

    # ------------------------------------------------------------------
    # Scoring and classification
    # ------------------------------------------------------------------

    def _name_score(self, text: str, index: int) -> float:
        if self._is_noise(text):
            return 0.0
        if self._looks_like_opening_hours(text):
            return 0.0
        if self._looks_like_address(text) or self._looks_like_landmark(text):
            return 0.0
        if _GOOGLE_MAPS_URL_RE.search(text) or _GOOGLE_IMAGE_URL_RE.search(text):
            return 0.0
        if _PHONE_RE.search(text) or _EMAIL_RE.search(text) or _PLUS_CODE_RE.search(text.upper()) or _GPS_RE.search(text):
            return 0.0
        if self._looks_like_category(text):
            return 0.5

        words = text.split()
        score = 0.0
        if 1 <= len(words) <= 7:
            score += 3.0
        if 2 <= len(text) <= 60:
            score += 1.0
        if any(ch.isalpha() for ch in text):
            score += 1.0
        if text[:1].isupper():
            score += 0.5
        if any(part[:1].isupper() for part in words if part):
            score += 0.5
        if text.isupper():
            score -= 0.5
        if any(ch.isdigit() for ch in text):
            score -= 1.5
        if index > 0:
            score -= min(index * 0.2, 1.0)
        return score

    def _description_score(self, text: str, index: int) -> float:
        if self._is_noise(text):
            return 0.0
        if self._looks_like_address(text) or self._looks_like_landmark(text) or self._looks_like_category(text):
            return 0.0
        if self._looks_like_opening_hours(text):
            return 0.0
        if _GOOGLE_MAPS_URL_RE.search(text) or _GOOGLE_IMAGE_URL_RE.search(text):
            return 0.0
        if _PHONE_RE.search(text) or _EMAIL_RE.search(text) or _PLUS_CODE_RE.search(text.upper()) or _GPS_RE.search(text):
            return 0.0

        words = text.split()
        score = 0.0
        if len(words) >= 6:
            score += 2.0
        if len(words) >= 10:
            score += 1.0
        if text.endswith((".", "!", "?")):
            score += 2.0
        if self._has_description_hint(text):
            score += 0.5
        if text[:1].isupper():
            score += 0.5
        if any(ch.isdigit() for ch in text):
            score -= 0.5
        if index > 0:
            score -= min(index * 0.1, 0.5)
        return score

    def _has_description_hint(self, text: str) -> bool:
        lowered = text.lower()
        if any(phrase in lowered for phrase in _DESCRIPTION_PHRASE_HINTS):
            return True

        tokens = set(re.findall(r"[a-z]+(?:-[a-z]+)?", lowered))
        return any(word in tokens for word in _DESCRIPTION_WORD_HINTS)

    def _looks_like_category(self, text: str) -> bool:
        if self._is_noise(text):
            return False
        return self._is_standalone_category_phrase(text)

    def _category_candidate(self, text: str) -> str | None:
        if self._is_noise(text):
            return None
        if self._looks_like_opening_hours(text) or self._looks_like_address(text) or self._looks_like_landmark(text):
            return None
        if _GOOGLE_MAPS_URL_RE.search(text) or _GOOGLE_IMAGE_URL_RE.search(text):
            return None
        if _PHONE_RE.search(text) or _EMAIL_RE.search(text) or _PLUS_CODE_RE.search(text.upper()) or _GPS_RE.search(text):
            return None
        if len(text.split()) > 4 or len(text) > 30:
            return None

        if self._is_standalone_category_phrase(text):
            return self._titleish(text)
        return None

    def _is_standalone_category_phrase(self, text: str) -> bool:
        """Return True only when the full text is an exact category phrase."""

        normalized = self._clean_text(text).lower()
        return normalized in _STANDALONE_CATEGORY_PHRASES

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

    def _review_count_from_text(self, text: str) -> int | None:
        match = _REVIEW_COUNT_RE.search(text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

        lowered = text.lower()
        if "review" in lowered:
            number_match = re.search(r"(?<!\d)(\d{1,5})(?!\d)", text)
            if number_match:
                try:
                    return int(number_match.group(1))
                except ValueError:
                    return None
        return None

    def _opening_hours_from_text(self, text: str) -> str | None:
        if not self._looks_like_opening_hours(text):
            return None

        lowered = text.lower()
        if "temporarily closed" in lowered:
            return "Temporarily closed"
        if "open 24 hours" in lowered:
            return "Open 24 hours"
        if "open now" in lowered:
            return "Open now"
        if lowered.strip() == "closed":
            return "Closed"
        return self._clean_text(text)

    def _titleish(self, text: str) -> str:
        cleaned = self._strip_known_fragments(text)
        return cleaned or text.strip()

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------

    def _build_warnings(self, result: Mapping[str, Any]) -> list[str]:
        warnings: list[str] = []
        checks = [
            ("name", "Shop name not found"),
            ("phone", "Phone number not found"),
            ("address", "Address not found"),
            ("gps", "GPS not found"),
            ("plus_code", "Plus code not found"),
            ("google_category", "Google category not found"),
            ("image_url", "Image URL not found"),
            ("maps_url", "Maps URL not found"),
            ("rating", "Rating not found"),
            ("review_count", "Review count not found"),
            ("opening_hours", "Opening hours not found"),
        ]
        for field, message in checks:
            if result.get(field) in (None, "", []):
                warnings.append(message)
        return warnings
