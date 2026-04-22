"""
column_resolver.py — Saf Python kolon çözümleme katmanı.

Çözümleme zinciri (sırayla):
  1. Semantik alias tablosu (normalize edilmiş eşleşme)
  2. Türkçe suffix soyma → alias tablosu
  3. column_hint (varsa) → aynı zincir
  4. Fuzzy match (db_columns biliniyorsa)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_ALIAS_TABLE: Dict[str, List[str]] = {
    "RowAmount": [
        "tutar", "satistutar", "satistutari", "satis_tutar", "amount",
        "rowamount", "toplam", "toplamtutar", "totalamount", "revenue",
        "gelir", "ciro", "satis",
    ],
    "Quantity": ["miktar", "adet", "quantity", "qty", "sayi", "adet_miktari"],
    "DocumentDate": ["tarih", "tarihsaat", "date", "datetime", "documentdate"],
    "BranchName": ["sube", "subeadi", "sube_adi", "branch", "branchname"],
    "ProductName": ["urun", "urunadi", "urun_adi", "product", "productname", "urunlar"],
    "CategoryName": [
        "kategori", "kategoriadi", "kategori_adi", "category", "categoryname",
        "kategoriler",
    ],
    "BranchCityName": [
        "sehir", "sehiradi", "sehir_adi", "city", "cityname",
        "branchcity", "branchcityname", "il",
    ],
    "CustomerName": [
        "musteri", "musteriadi", "musteri_adi", "customer", "customername",
    ],
    "CashierName": ["kasiyer", "cashier", "cashiername"],
    "DiscountAmountTotal": [
        "indirim", "indirimtutar", "discount", "discountamounttotal",
    ],
}

_TR_SUFFIXES: List[str] = [
    "ındaki", "undaki", "undeki",
    "ndaki", "ndeki", "indeki",
    "sından", "sinden", "sundan", "sunden",
    "ndan", "nden", "tan", "ten", "dan", "den",
    "nına", "nine", "nuna", "nune",
    "nın", "nin", "nun",
    "sına", "sine", "suna", "sune",
    "nda", "nde",
    "ta", "te", "da", "de",
    "sı", "si", "su", "sü",
    "yı", "yi", "yu", "yü",
    "ın", "in", "un", "ün",
    "ya", "ye",
]

_MIN_STEM_LEN = 3

_TR_MAP = {
    "ı": "i", "İ": "i", "I": "i",
    "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u",
    "ş": "s", "Ş": "s",
    "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c",
}


def _normalize(text: str) -> str:
    text = text.lower()
    for tr, en in _TR_MAP.items():
        text = text.replace(tr, en)
    return text.replace("_", "").replace(" ", "")


def _strip_suffixes_intermediate(text: str) -> List[str]:
    """Return all intermediate stems produced by iterative suffix stripping."""
    results: List[str] = []
    for _ in range(4):
        lower = text.lower()
        stripped = False
        for suffix in _TR_SUFFIXES:
            if lower.endswith(suffix) and len(lower) - len(suffix) >= _MIN_STEM_LEN:
                text = text[: len(text) - len(suffix)]
                results.append(text)
                stripped = True
                break
        if not stripped:
            break
    return results


class ColumnResolver:
    """raw_text / column_hint → DB kolon adı çözümleyicisi."""

    def __init__(self, db_columns: Optional[List[str]] = None) -> None:
        self._lookup: Dict[str, str] = {}
        for db_col, aliases in _ALIAS_TABLE.items():
            for alias in aliases:
                self._lookup[_normalize(alias)] = db_col
            self._lookup[_normalize(db_col)] = db_col
        self._db_columns: List[str] = db_columns or []

    def resolve(
        self,
        raw_text: str,
        column_hint: Optional[str] = None,
    ) -> Optional[str]:
        # 1. Direct alias
        result = self._lookup.get(_normalize(raw_text))
        if result:
            logger.debug(f"[COL_RESOLVER] '{raw_text}' → '{result}' (alias)")
            return result

        # 2. Turkish suffix stripping — check every intermediate stem
        for stem in _strip_suffixes_intermediate(raw_text):
            result = self._lookup.get(_normalize(stem))
            if result:
                logger.debug(f"[COL_RESOLVER] '{raw_text}' → strip → '{stem}' → '{result}'")
                return result

        # 3. column_hint fallback
        if column_hint:
            result = self._lookup.get(_normalize(column_hint))
            if result:
                logger.debug(f"[COL_RESOLVER] '{raw_text}' unknown, hint '{column_hint}' → '{result}'")
                return result

        # 4. Fuzzy match (optional)
        if self._db_columns:
            try:
                from rapidfuzz import process, fuzz
            except ImportError:
                pass
            else:
                match = process.extractOne(
                    raw_text, self._db_columns, scorer=fuzz.ratio, score_cutoff=85
                )
                if match:
                    logger.debug(
                        f"[COL_RESOLVER] '{raw_text}' fuzzy → '{match[0]}' (score={match[1]})"
                    )
                    return match[0]

        logger.debug(f"[COL_RESOLVER] '{raw_text}' → unresolved")
        return None

    def with_db_columns(self, columns: List[str]) -> "ColumnResolver":
        return ColumnResolver(db_columns=columns)
