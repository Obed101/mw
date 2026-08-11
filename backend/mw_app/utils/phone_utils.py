import re

def normalize_ghana_phone(phone_str: str | None, raise_on_error: bool = False) -> str | None:
    """
    Normalizes Ghanaian phone numbers into canonical format: 233XXXXXXXXX.
    
    Examples:
        0553995047       -> 233553995047
        +233553995047    -> 233553995047
        233553995047     -> 233553995047
        553995047        -> 233553995047
        055 399-5047     -> 233553995047

    Returns:
        Canonical string '233XXXXXXXXX' if valid, or None (or raises ValueError if raise_on_error=True).
    """
    if not phone_str:
        if raise_on_error:
            raise ValueError("Phone number string cannot be empty")
        return None

    # Remove all non-digit characters
    digits = re.sub(r'\D', '', str(phone_str))

    # Convert to 233 format based on initial digits
    if digits.startswith('233') and len(digits) == 12:
        normalized = digits
    elif digits.startswith('0') and len(digits) == 10:
        normalized = '233' + digits[1:]
    elif len(digits) == 9:
        normalized = '233' + digits
    else:
        normalized = digits

    if validate_ghana_phone(normalized):
        return normalized

    if raise_on_error:
        raise ValueError(f"Invalid Ghanaian phone number format: '{phone_str}'")
    return None


def validate_ghana_phone(phone_str: str | None) -> bool:
    """
    Validates if a phone string matches canonical 233XXXXXXXXX format.
    Expects 12 digits total starting with '233'.
    Valid Ghanaian mobile/landline network prefixes start with 233 followed by valid area/network digits.
    """
    if not phone_str:
        return False
    
    # Must be exactly 12 digits, starting with 233
    pattern = r'^233\d{9}$'
    return bool(re.match(pattern, str(phone_str)))


def mask_phone_number(phone_str: str | None) -> str:
    """
    Masks phone number for privacy presentation.
    e.g. 233553995047 -> +233 55 *** 5047
    """
    normalized = normalize_ghana_phone(phone_str)
    if not normalized:
        return phone_str or ''
    # 233 (3) 55 (2) 3995047 (7)
    return f"+233 {normalized[3:5]} *** {normalized[-4:]}"
