"""
Date Tool
=========
LLM'in çağırdığı tool: Türkçe tarih ifadesi → T-SQL date expression.
LangChain @tool decorator ile tanımlanır.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Literal, Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Türkçe normalizer (tool içinde kullanılır)
def _n(text: str) -> str:
    return (
        text.lower()
        .replace("ı", "i").replace("İ", "i")
        .replace("ğ", "g").replace("Ğ", "g")
        .replace("ü", "u").replace("Ü", "u")
        .replace("ş", "s").replace("Ş", "s")
        .replace("ö", "o").replace("Ö", "o")
        .replace("ç", "c").replace("Ç", "c")
    )

_UNIT_MAP = {
    "gun": "DAY", "gün": "DAY",
    "hafta": "WEEK",
    "ay": "MONTH",
    "yil": "YEAR", "yıl": "YEAR", "sene": "YEAR",
}

_MONTH_MAP = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4,
    "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8,
    "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}


@tool
def resolve_date(expression: str) -> str:
    """
    Türkçe tarih ifadesini T-SQL date expression'a çevirir.

    Kullanım: Sorguda geçen her tarih ifadesi için bu tool'u çağır.
    Desteklenen ifadeler:
      - "son N gün/hafta/ay/yıl"  → DATEADD(...)
      - "N yıl/ay önce"           → DATEADD(...)
      - "geçen yıl / geçen ay"    → YEAR(col) = ...
      - "bu yıl / bu ay / bugün / bu çeyrek / bu hafta"
      - "ocak 2024" / "2024 ocak" → tarih aralığı
      - "2024-01-15"              → CAST(col AS DATE) = '2024-01-15'

    Returns:
        SQL fragment string.
        '{col}' placeholder'ı gerçek tarih kolonu adıyla değiştirilecektir.
        Operator bilgisi "OP:" prefix'iyle döner (ör: "OP:>= DATEADD(...)").
    """
    today = date.today()
    q = _n(expression.strip())

    # --- son N gün/hafta/ay/yıl ---
    m = re.search(r"son\s+(\d+)\s*(gun|hafta|ay|yil|sene)", q)
    if m:
        n, unit_key = int(m.group(1)), m.group(2)
        sql_unit = _UNIT_MAP.get(unit_key, "DAY")
        result = f"OP:>= DATEADD({sql_unit}, -{n}, '{today}')"
        logger.info(f"[DATE_TOOL] '{expression}' → {result}")
        return result

    # --- N yıl/ay/gün önce ---
    m = re.search(r"(\d+)\s*(gun|hafta|ay|yil|sene)\s+once", q)
    if m:
        n, unit_key = int(m.group(1)), m.group(2)
        sql_unit = _UNIT_MAP.get(unit_key, "DAY")
        result = f"OP:>= DATEADD({sql_unit}, -{n}, '{today}')"
        logger.info(f"[DATE_TOOL] '{expression}' → {result}")
        return result

    # --- geçen yıl ---
    if re.search(r"gecen\s*yil", q):
        result = f"YEAR({{col}}) = {today.year - 1}"
        logger.info(f"[DATE_TOOL] 'geçen yıl' → {result}")
        return result

    # --- geçen ay ---
    if re.search(r"gecen\s*ay", q):
        prev = (today.replace(day=1) - timedelta(days=1))
        result = f"YEAR({{col}}) = {prev.year} AND MONTH({{col}}) = {prev.month}"
        logger.info(f"[DATE_TOOL] 'geçen ay' → {result}")
        return result

    # --- bu yıl ---
    if re.search(r"bu\s*yil", q):
        result = f"YEAR({{col}}) = {today.year}"
        logger.info(f"[DATE_TOOL] 'bu yıl' → {result}")
        return result

    # --- bu ay ---
    if re.search(r"bu\s*ay", q):
        result = f"YEAR({{col}}) = {today.year} AND MONTH({{col}}) = {today.month}"
        logger.info(f"[DATE_TOOL] 'bu ay' → {result}")
        return result

    # --- bugün ---
    if re.search(r"bugun", q):
        result = f"CAST({{col}} AS DATE) = '{today}'"
        logger.info(f"[DATE_TOOL] 'bugün' → {result}")
        return result

    # --- bu çeyrek ---
    if re.search(r"bu\s*(ceyrek|cayrak)", q):
        q_num = (today.month - 1) // 3 + 1
        result = f"YEAR({{col}}) = {today.year} AND DATEPART(QUARTER, {{col}}) = {q_num}"
        logger.info(f"[DATE_TOOL] 'bu çeyrek' → {result}")
        return result

    # --- bu hafta ---
    if re.search(r"bu\s*hafta", q):
        monday = today - timedelta(days=today.weekday())
        result = f"CAST({{col}} AS DATE) >= '{monday}' AND CAST({{col}} AS DATE) <= '{today}'"
        logger.info(f"[DATE_TOOL] 'bu hafta' → {result}")
        return result

    # --- ocak 2024 / 2024 ocak ---
    for month_tr, month_no in _MONTH_MAP.items():
        m5 = re.search(rf"{month_tr}\s+(\d{{4}})", q) or re.search(rf"(\d{{4}})\s+{month_tr}", q)
        if m5:
            year = int(m5.group(1))
            # Son günü hesapla
            if month_no == 12:
                last_day = 31
            else:
                last_day = (date(year, month_no + 1, 1) - timedelta(days=1)).day
            result = (
                f"OP:BETWEEN '{year}-{month_no:02d}-01' "
                f"AND '{year}-{month_no:02d}-{last_day:02d}'"
            )
            logger.info(f"[DATE_TOOL] '{expression}' (ay-yıl) → {result}")
            return result

    # --- ISO tarih 2024-01-15 ---
    m6 = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", expression)
    if m6:
        iso = m6.group(1)
        result = f"OP:= '{iso}'"
        logger.info(f"[DATE_TOOL] ISO date '{iso}' → {result}")
        return result

    # Çözülemedi
    logger.warning(f"[DATE_TOOL] Could not resolve: '{expression}'")
    return f"UNRESOLVED: {expression}"
