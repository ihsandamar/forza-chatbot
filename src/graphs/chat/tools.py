"""
Chat Graph Tools - LangChain Compatible.

Three tools for the chat agent:
- get_date: Returns today's date in Turkish format
- check_holidays: Returns Turkish holidays for a given month/year
- check_holiday: Checks if a given date is a holiday
"""

from datetime import datetime
from typing import Dict, Any, Optional
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Turkish day names
TURKISH_DAYS = {
    0: "Pazartesi",
    1: "Salı",
    2: "Çarşamba",
    3: "Perşembe",
    4: "Cuma",
    5: "Cumartesi",
    6: "Pazar"
}

# Turkish month names
TURKISH_MONTHS = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık"
}

# Turkish holidays
FALLBACK_HOLIDAYS = {
    (1, 1): {"name": "Yeni Yılın Günü", "type": "national_holiday"},
    (4, 23): {"name": "Ulusal Egemenlik ve Çocuk Bayramı", "type": "national_holiday"},
    (5, 1): {"name": "Emek ve Dayanışma Günü", "type": "national_holiday"},
    (7, 15): {"name": "Demokrasi ve Milli Birlik Günü", "type": "national_holiday"},
    (8, 30): {"name": "Zafer Bayramı", "type": "national_holiday"},
    (10, 29): {"name": "Cumhuriyet Bayramı", "type": "national_holiday"},
}


@tool
def get_date() -> Dict[str, Any]:
    """Get today's date in Turkish format."""
    now = datetime.now()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "day": TURKISH_DAYS[now.weekday()],
        "month": TURKISH_MONTHS[now.month],
        "formatted": f"{now.day} {TURKISH_MONTHS[now.month]} {now.year} {TURKISH_DAYS[now.weekday()]}"
    }


@tool
def check_holidays(year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
    """Get Turkish holidays for a given month/year."""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month

    holidays = []
    for (h_month, h_day), holiday_info in FALLBACK_HOLIDAYS.items():
        if h_month == month:
            holiday_copy = holiday_info.copy()
            holiday_copy["date"] = f"{year}-{h_month:02d}-{h_day:02d}"
            holidays.append(holiday_copy)

    return {
        "month": month,
        "year": year,
        "holidays": holidays,
        "total": len(holidays)
    }


@tool
def check_holiday(date_str: str) -> Dict[str, Any]:
    """Check if a given date is a holiday in Turkey."""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        if (month, day) in FALLBACK_HOLIDAYS:
            holiday_info = FALLBACK_HOLIDAYS[(month, day)]
            return {
                "is_holiday": True,
                "date": date_str,
                "name": holiday_info["name"],
                "type": holiday_info["type"]
            }

        return {
            "is_holiday": False,
            "date": date_str
        }

    except ValueError:
        return {
            "error": "Geçersiz tarih formatı. YYYY-MM-DD formatını kullanınız.",
            "date": date_str
        }


# Toolkit for agent
CHAT_TOOLS = [get_date, check_holidays, check_holiday]

# For backward compatibility
AVAILABLE_TOOLS = {
    "get_current_date": {"function": get_date},
    "get_holidays": {"function": check_holidays},
    "is_holiday": {"function": check_holiday},
}
