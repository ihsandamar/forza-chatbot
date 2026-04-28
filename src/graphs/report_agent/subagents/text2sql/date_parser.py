"""
SemanticTime → DateDescriptor converter.
Pure Python, no LLM, deterministic.
Raises SemanticExtractionError for unrecognized patterns.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

from src.graphs.report_agent.subagents.text2sql.exceptions import SemanticExtractionError
from src.graphs.report_agent.subagents.text2sql.prompts import DateDescriptor
from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime

_UNIT_MAP = {
    "ay": "month",
    "gün": "day",
    "yıl": "year",
    "sene": "year",
    "hafta": "week",
}
_PERIOD_MAP = {
    "yıl": "year",
    "ay": "month",
    "gün": "day",
    "çeyrek": "quarter",
}
_GRAN_MAP = {
    "ay": "monthly",
    "yıl": "yearly",
    "sene": "yearly",
    "gün": "daily",
    "hafta": "weekly",
}
_GRANULARITY_KEYWORDS = {
    # Monthly — longer phrases first (insertion order matters for first-match)
    "ay bazında": "monthly",
    "ay kırılımı": "monthly",
    "her ay": "monthly",
    "aylık": "monthly",
    # Weekly
    "hafta bazında": "weekly",
    "haftalık": "weekly",
    "her hafta": "weekly",
    # Daily
    "gün bazında": "daily",
    "günlük": "daily",
    "her gün": "daily",
    # Yearly
    "yıl bazında": "yearly",
    "yıllık": "yearly",
    "her yıl": "yearly",
    # Hourly
    "saat bazında": "hourly",
    "saatlik": "hourly",
    # Special
    "haftanın günlerine": "day_of_week",
    "ayın günlerine": "day_of_month",
}


def _next_month_start(year: int, month: int) -> str:
    """Verilen ay-yılın bir sonraki ayının ilk gününü 'YYYY-MM-01' olarak döndürür."""
    if month == 12:
        return f"{year + 1}-01-01"
    return f"{year}-{month + 1:02d}-01"


def detect_granularity_from_query(raw_query: str) -> Optional[str]:
    """Scan raw_query for explicit granularity keywords. Returns first match or None."""
    q = raw_query.lower()
    for keyword, gran in _GRANULARITY_KEYWORDS.items():
        if keyword in q:
            return gran
    return None


_TR_MONTH_MAP = {
    "ocak": 1,
    "şubat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "eylül": 9,
    "ekim": 10,
    "kasım": 11,
    "aralık": 12,
}


def parse_semantic_time(
    st: SemanticTime, today: date
) -> Tuple[Optional[DateDescriptor], Optional[str]]:
    """Parse SemanticTime.raw_text → (DateDescriptor, time_granularity).

    Args:
        st:    SemanticTime with raw_text (Turkish date expression) and breakdown flag.
        today: Reference date used for exact date resolution (e.g. "15 mart").

    Returns:
        A tuple of (DateDescriptor, time_granularity).
        time_granularity is non-None only when st.breakdown is True.

    Raises:
        SemanticExtractionError: When raw_text does not match any recognized pattern.
    """
    text = st.raw_text.lower().strip()
    gran: Optional[str] = None

    # "son N ay/gün/yıl/sene/hafta"
    m = re.match(r"son\s+(\d+)\s*(ay|gün|yıl|sene|hafta)", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        dd = DateDescriptor(type="relative", unit=_UNIT_MAP[unit], amount=-n)
        if st.breakdown:
            gran = st.granularity or _GRAN_MAP.get(unit)
        return dd, gran

    # "geçen/geçtiğimiz yıl/ay"
    m = re.match(r"(?:geçen|geçtiğimiz)\s*(yıl|ay)$", text)
    if m:
        unit = m.group(1)
        dd = DateDescriptor(type="relative", unit=_UNIT_MAP[unit], amount=-1)
        if st.breakdown:
            gran = st.granularity or _GRAN_MAP.get(unit)
        return dd, gran

    # "geçtiğimiz [ay_adı] [ayı]" — en son geçmiş o ay (ör. "geçtiğimiz aralık ayı")
    m = re.match(r"geçtiğimiz\s+(\S+?)(?:\s+ay[ıi]?)?$", text)
    if m:
        month_name = m.group(1).lower()
        month_num = _TR_MONTH_MAP.get(month_name)
        if month_num is not None:
            year = today.year if month_num < today.month else today.year - 1
            dd = DateDescriptor(
                type="exact",
                value=f"{year}-{month_num:02d}-01",
                end_value=_next_month_start(year, month_num),
            )
            gran = (st.granularity or "monthly") if st.breakdown else None
            return dd, gran

    # "bu yıl/ay/gün/çeyrek"
    m = re.match(r"bu\s*(yıl|ay|gün|çeyrek)", text)
    if m:
        period_key = m.group(1)
        dd = DateDescriptor(type="current_period", period=_PERIOD_MAP[period_key])
        if st.breakdown:
            gran = st.granularity or _GRAN_MAP.get(period_key)
        return dd, gran

    # "YYYY" exact year
    m = re.fullmatch(r"(\d{4})", text)
    if m:
        year = m.group(1)
        dd = DateDescriptor(type="exact", value=f"{year}-01-01")
        return dd, None

    # "[ay adı] YYYY"
    for month_name, month_num in _TR_MONTH_MAP.items():
        m = re.match(rf"{re.escape(month_name)}\s+(\d{{4}})", text)
        if m:
            year_int = int(m.group(1))
            dd = DateDescriptor(
                type="exact",
                value=f"{year_int}-{month_num:02d}-01",
                end_value=_next_month_start(year_int, month_num),
            )
            gran = (st.granularity or "monthly") if st.breakdown else None
            return dd, gran

    # "DD [ay adı]"
    for month_name, month_num in _TR_MONTH_MAP.items():
        m = re.match(rf"(\d{{1,2}})\s+{re.escape(month_name)}", text)
        if m:
            day = int(m.group(1))
            dd = DateDescriptor(
                type="exact",
                value=f"{today.year}-{month_num:02d}-{day:02d}",
            )
            return dd, None

    raise SemanticExtractionError(
        f"Tanımlanamayan tarih formatı: {st.raw_text!r}",
        error_code="UNKNOWN_DATE_FORMAT",
        context={"raw_text": st.raw_text},
    )
