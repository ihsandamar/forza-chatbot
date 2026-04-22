"""
column_resolver.py — Deterministic kolon çözümleme katmanı.

Çözümleme zinciri (sırayla):
  1. Semantik alias tablosu (normalize edilmiş eşleşme)
  2. column_hint (LLM tarafından sağlanır) → aynı zincir
  3. Fuzzy match (db_columns biliniyorsa)

Türkçe suffix soyma (morfoloji) bu katmanda YAPILMAZ.
LLM semantic_extractor kanonik kök formu + column_hint'i sağlamaktan sorumludur.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_ALIAS_TABLE: Dict[str, List[str]] = {
    # ---------- Metrics ----------
    "RowAmount": [
        "tutar", "satistutar", "satistutari", "satis_tutar", "amount",
        "rowamount", "toplam", "toplamtutar", "totalamount", "revenue",
        "gelir", "ciro", "satis",
    ],
    "Quantity": ["miktar", "adet", "quantity", "qty", "sayi", "adet_miktari"],
    "DiscountAmountTotal": [
        "indirim", "indirimtutar", "discount", "discountamounttotal",
    ],
    # ---------- Date / Time ----------
    "DocumentDate": ["tarih", "tarihsaat", "date", "datetime", "documentdate"],
    "DayOfWeek":    ["haftaningunu", "dayofweek"],
    "Hour":         ["saat", "hour"],
    # ---------- Location ----------
    "BranchName":     ["sube", "subeadi", "sube_adi", "branch", "branchname"],
    "BranchCityName": [
        "sehir", "sehiradi", "sehir_adi", "city", "cityname",
        "branchcity", "branchcityname", "il",
    ],
    "BranchTownName": ["ilce", "semt", "branchtownname"],
    # ---------- Product / Category ----------
    "ProductName": ["urun", "urunadi", "urun_adi", "product", "productname", "urunlar"],
    "CategoryName": [
        "kategori", "kategoriadi", "kategori_adi", "category", "categoryname",
        "kategoriler",
    ],
    # ---------- Sales channel ----------
    "DocumentKindName": [
        "platform", "kanal", "satiskanali", "kanaladi", "hizmettipi",
        "siparitipi", "documentkindname",
    ],
    "DocumentTypeName": [
        "belgetipi", "islemtipi", "belgead", "documenttypename",
    ],
    # ---------- Staff / People ----------
    "CashierName":      ["kasiyer", "cashier", "cashiername"],
    "DeliveryUserName": ["kurye", "teslimat", "deliveryuser", "deliveryusername"],
    "CustomerName": [
        "musteri", "musteriadi", "musteri_adi", "customer", "customername",
    ],
    # ---------- Table ----------
    "TableNo": ["masano", "masanumarasi", "tableno"],
}

# Turkish character normalization (charset only — not morphology).
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


class ColumnResolver:
    """Canonical raw_text / column_hint → DB column name.

    Expects canonical (root) forms in raw_text. No suffix stripping is done here —
    that responsibility belongs to the LLM semantic_extractor.
    """

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
        # 1. Direct alias lookup
        result = self._lookup.get(_normalize(raw_text))
        if result:
            logger.debug(f"[COL_RESOLVER] '{raw_text}' → '{result}' (alias)")
            return result

        # 2. column_hint — LLM-provided, primary for entity types
        if column_hint:
            result = self._lookup.get(_normalize(column_hint))
            if result:
                logger.debug(f"[COL_RESOLVER] '{raw_text}' unknown, hint '{column_hint}' → '{result}'")
                return result

        # 3. Fuzzy match on actual DB column names (last resort)
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
