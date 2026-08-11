"""
Timezone utilities for Market Window.

Provides timezone conversion functions for displaying timestamps in local timezones.
All internal timestamps are stored in UTC and converted to display timezones at the presentation layer.

Note: Ghana is in UTC+0 timezone, so UTC and Ghana time are the same.
This module provides consistency and future-proofing if the application expands to other timezones.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

# Ghana is UTC+0, so Ghana timezone is the same as UTC
# This is defined for consistency and future expansion
GHANA_TZ = timezone.utc


def utc_to_ghana(utc_datetime: Optional[datetime]) -> Optional[datetime]:
    """
    Convert UTC datetime to Ghana time for display.
    
    Since Ghana is UTC+0, this function ensures the datetime is timezone-aware and in UTC.
    
    Args:
        utc_datetime: UTC datetime object (can be timezone-aware or naive)
        
    Returns:
        DateTime object in UTC timezone (same as Ghana time), or None if input is None
        
    Example:
        >>> from datetime import datetime, timezone
        >>> utc_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        >>> ghana_time = utc_to_ghana(utc_time)
        >>> print(ghana_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
        '2024-01-01 12:00:00 UTC'
    """
    if utc_datetime is None:
        return None
    
    # Ensure the datetime is timezone-aware as UTC
    if utc_datetime.tzinfo is None:
        utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)
    elif utc_datetime.tzinfo != timezone.utc:
        # Convert to UTC if it's in another timezone
        utc_datetime = utc_datetime.astimezone(timezone.utc)
    
    # Ghana is UTC+0, so return UTC time
    return utc_datetime


def format_ghana_datetime(utc_datetime: Optional[datetime], format_str: str = '%Y-%m-%d %H:%M:%S') -> Optional[str]:
    """
    Format UTC datetime as string in Ghana timezone.
    
    Args:
        utc_datetime: UTC datetime object (can be timezone-aware or naive)
        format_str: strftime format string
        
    Returns:
        Formatted string in Ghana timezone (UTC), or None if input is None
        
    Example:
        >>> from datetime import datetime, timezone
        >>> utc_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        >>> formatted = format_ghana_datetime(utc_time, '%Y-%m-%d %H:%M')
        >>> print(formatted)
        '2024-01-01 12:00'
    """
    ghana_time = utc_to_ghana(utc_datetime)
    if ghana_time is None:
        return None
    return ghana_time.strftime(format_str)


def get_current_ghana_time() -> datetime:
    """
    Get current time in Ghana timezone.
    
    Returns:
        Current datetime in UTC (same as Ghana time)
        
    Example:
        >>> now = get_current_ghana_time()
        >>> print(now.tzinfo)
        UTC
    """
    return datetime.now(timezone.utc)


def ghana_to_utc(ghana_datetime: datetime) -> datetime:
    """
    Convert Ghana datetime to UTC.
    
    Since Ghana is UTC+0, this function ensures the datetime is timezone-aware and in UTC.
    
    Args:
        ghana_datetime: DateTime object (can be timezone-aware or naive, will be treated as UTC)
        
    Returns:
        DateTime object in UTC timezone
        
    Example:
        >>> from datetime import datetime
        >>> ghana_time = datetime(2024, 1, 1, 12, 0, 0)
        >>> utc_time = ghana_to_utc(ghana_time)
        >>> print(utc_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
        '2024-01-01 12:00:00 UTC'
    """
    if ghana_datetime.tzinfo is None:
        # Assume naive datetime is in UTC (Ghana time)
        ghana_datetime = ghana_datetime.replace(tzinfo=timezone.utc)
    
    return ghana_datetime.astimezone(timezone.utc)