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


def _quarter_range(year: int, quarter: int) -> tuple[str, str]:
    """Returns (start_date, exclusive_end_date) for a given quarter."""
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 3
    start = f"{year}-{start_month:02d}-01"
    end = f"{year + 1}-01-01" if quarter == 4 else f"{year}-{end_month:02d}-01"
    return start, end


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

    # "YYYY [ay adı]" — yıl önce ay sonra (ör. "2025 aralık")
    for month_name, month_num in _TR_MONTH_MAP.items():
        m = re.match(rf"(\d{{4}})\s+{re.escape(month_name)}", text)
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

    # --- Çeyrek (quarter) ifadeleri ---

    # "YYYY son çeyrek[...]" — o yılın Q4'ü
    m = re.match(r"(\d{4})\s+son\s+çeyrek", text)
    if m:
        year_int = int(m.group(1))
        start, end = _quarter_range(year_int, 4)
        return DateDescriptor(type="exact", value=start, end_value=end), None

    # "son çeyrek YYYY" — tersine sıra
    m = re.match(r"son\s+çeyrek\s+(\d{4})", text)
    if m:
        year_int = int(m.group(1))
        start, end = _quarter_range(year_int, 4)
        return DateDescriptor(type="exact", value=start, end_value=end), None

    # "YYYY ilk çeyrek[...]" — o yılın Q1'i
    m = re.match(r"(\d{4})\s+ilk\s+çeyrek", text)
    if m:
        year_int = int(m.group(1))
        start, end = _quarter_range(year_int, 1)
        return DateDescriptor(type="exact", value=start, end_value=end), None

    # "YYYY N. çeyrek[...]" — belirli çeyrek (ör. "2025 4. çeyreği")
    m = re.match(r"(\d{4})\s+([1-4])\.?\s*çeyrek", text)
    if m:
        year_int, quarter = int(m.group(1)), int(m.group(2))
        start, end = _quarter_range(year_int, quarter)
        return DateDescriptor(type="exact", value=start, end_value=end), None

    # "N. çeyrek YYYY" — tersine sıra (ör. "4. çeyrek 2025")
    m = re.match(r"([1-4])\.?\s*çeyrek\s+(\d{4})", text)
    if m:
        quarter, year_int = int(m.group(1)), int(m.group(2))
        start, end = _quarter_range(year_int, quarter)
        return DateDescriptor(type="exact", value=start, end_value=end), None

    # "son çeyrek" yıl belirtilmemiş — en son tamamlanan çeyrek
    m = re.match(r"son\s+çeyrek", text)
    if m:
        current_q = (today.month - 1) // 3 + 1
        prev_q = current_q - 1 if current_q > 1 else 4
        prev_year = today.year if current_q > 1 else today.year - 1
        start, end = _quarter_range(prev_year, prev_q)
        return DateDescriptor(type="exact", value=start, end_value=end), None

    raise SemanticExtractionError(
        f"Tanımlanamayan tarih formatı: {st.raw_text!r}",
        error_code="UNKNOWN_DATE_FORMAT",
        context={"raw_text": st.raw_text},
    )
