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
            gran = _GRAN_MAP.get(unit)
        return dd, gran

    # "geçen yıl/ay"
    m = re.match(r"geçen\s*(yıl|ay)", text)
    if m:
        unit = m.group(1)
        dd = DateDescriptor(type="relative", unit=_UNIT_MAP[unit], amount=-1)
        if st.breakdown:
            gran = _GRAN_MAP.get(unit)
        return dd, gran

    # "bu yıl/ay/gün/çeyrek"
    m = re.match(r"bu\s*(yıl|ay|gün|çeyrek)", text)
    if m:
        period_key = m.group(1)
        dd = DateDescriptor(type="current_period", period=_PERIOD_MAP[period_key])
        if st.breakdown:
            gran = _GRAN_MAP.get(period_key)
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
            year = m.group(1)
            dd = DateDescriptor(type="exact", value=f"{year}-{month_num:02d}-01")
            gran = "monthly" if st.breakdown else None
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
