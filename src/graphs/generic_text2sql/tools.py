from langchain_core.tools import BaseTool, tool
from datetime import datetime, date


@tool
def get_today_date() -> str:
    """
    Bugünün tarihini döndürür.

    Returns:
        str: Bugünün tarihi YYYY-MM-DD formatında (örnek: 2024-01-15)
    """
    return date.today().isoformat()


@tool
def get_current_datetime() -> str:
    """
    Şu anki tarih ve saati döndürür.

    Returns:
        str: Şu anki tarih ve saat ISO formatında (örnek: 2024-01-15T14:30:00)
    """
    return datetime.now().isoformat()


@tool
def get_current_year() -> int:
    """
    Şu anki yılı döndürür.

    Returns:
        int: Şu anki yıl (örnek: 2024)
    """
    return date.today().year


@tool
def get_current_month() -> int:
    """
    Şu anki ayı döndürür.

    Returns:
        int: Şu anki ay (1-12 arası)
    """
    return date.today().month


@tool
def get_current_day() -> int:
    """
    Ayın bugünkü gününü döndürür.

    Returns:
        int: Ayın günü (1-31 arası)
    """
    return date.today().day


# Tool'ları export et
GENERIC_TEXT2SQL_TOOLS = [
    get_today_date,
    get_current_datetime,
    get_current_year,
    get_current_month,
    get_current_day,
]
