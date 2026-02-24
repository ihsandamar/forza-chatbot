"""
Term Resolver
=============
Kullanıcı sorgusunda Türkçe iş terimlerini tespit eder ve iki çıktı üretir:
  1. term_filters  — SchemaFilter-uyumlu dict listesi (Python garantili, LLM yok)
  2. hints_text    — LLM prompt'una inject edilecek kolon adı yönlendirmesi

LLM kullanmaz. Deterministik, hızlı, test edilebilir.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DICTIONARY_PATH = Path(__file__).parent / "term_dictionary.json"
_SCORE_THRESHOLD = 70  # rapidfuzz token_set_ratio minimum


def _normalize(text: str) -> str:
    """Türkçe karakterleri ASCII'ye çevir, küçük harfe al."""
    tr_map = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iIgGuUsSoOcC")
    return text.translate(tr_map).lower().strip()


def _load_dictionary() -> List[Dict[str, Any]]:
    """term_dictionary.json'u yükle."""
    try:
        with open(_DICTIONARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("terms", [])
    except Exception as e:
        logger.warning(f"[TERM_RESOLVER] Dictionary load failed: {e}")
        return []


@dataclass
class AmbiguousMatch:
    """Kullanıcıya sorulması gereken belirsiz terim."""
    term: str           # Eşleşen terim ("tarih" gibi)
    user_query: str     # Orijinal sorgu
    options: List[Dict[str, Any]]  # [{"column": "...", "description": "...", "filter_structured": {...}}]


@dataclass
class TermResolverOutput:
    """
    resolve_terms_structured() dönüş tipi.

    term_filters: Python katmanı tarafından QuerySchema'ya garantili merge edilir.
                  LLM'in ürettiği aynı kolondaki filtreler OVERRIDE edilir.

    hints_text:   LLM prompt'una inject edilir — sadece kolon adı yönlendirmesi.
                  filter_structured olan terimler için "Python uyguluyor" yazılır.

    ambiguous:    interrupt() ile kullanıcıya sorulması gereken terimler.
                  Her AmbiguousMatch için options listesinden seçim beklenir.
    """
    term_filters: List[Dict[str, Any]] = field(default_factory=list)
    hints_text: str = "Özel terim eşleşmesi bulunamadı."
    ambiguous: List[AmbiguousMatch] = field(default_factory=list)


def resolve_terms_structured(user_query: str) -> TermResolverOutput:
    """
    Kullanıcı sorgusundaki Türkçe iş terimlerini tespit et.

    Matching sırası (öncelik sırasına göre):
      1. Exact substring match (score=100)
      2. rapidfuzz token_set_ratio >= 70

    Her eşleşen entry için:
      - filter_structured varsa   → term_filters'a ekle (Python garantili)
      - ambiguous_columns varsa   → ambiguous listesine ekle (interrupt gerekli)
      - hint varsa                → hints_text'e ekle (LLM advisory)

    Returns:
        TermResolverOutput
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.warning("[TERM_RESOLVER] rapidfuzz not available, skipping term resolution")
        return TermResolverOutput()

    terms = _load_dictionary()
    if not terms:
        return TermResolverOutput()

    normalized_query = _normalize(user_query)
    matched: List[Dict[str, Any]] = []       # {"entry": ..., "score": ...}
    seen_columns: set[str] = set()           # Aynı kolonu iki kez eşleştirme

    for entry in terms:
        column = entry.get("column") or "__ambiguous__"
        if column in seen_columns:
            continue

        candidates = [entry["term"]] + entry.get("aliases", [])

        best_score = 0
        for candidate in candidates:
            norm_candidate = _normalize(candidate)
            if norm_candidate in normalized_query:
                best_score = 100
                break
            score = fuzz.token_set_ratio(normalized_query, norm_candidate)
            if score > best_score:
                best_score = score

        if best_score >= _SCORE_THRESHOLD:
            matched.append({"entry": entry, "score": best_score})
            seen_columns.add(column)
            logger.debug(f"[TERM_RESOLVER] Match: '{entry['term']}' score={best_score}")

    if not matched:
        logger.info("[TERM_RESOLVER] No terms matched")
        return TermResolverOutput()

    output = TermResolverOutput()
    hint_lines: List[str] = []

    for m in sorted(matched, key=lambda x: -x["score"]):
        entry = m["entry"]
        term = entry["term"]

        # --- Ambiguous: kullanıcıya sor ---
        if entry.get("ambiguous_columns"):
            output.ambiguous.append(AmbiguousMatch(
                term=term,
                user_query=user_query,
                options=entry["ambiguous_columns"],
            ))
            hint_lines.append(f'- "{term}" → belirsiz kolon, kullanıcıya sorulacak')
            continue

        # --- filter_structured: Python garantili filtre ---
        if entry.get("filter_structured"):
            fs = dict(entry["filter_structured"])
            fs.setdefault("logical_operator", "AND")
            output.term_filters.append(fs)
            hint_lines.append(f'- "{term}" → {entry.get("hint", "")}')
            continue

        # --- Sadece hint (aggregation / column name yönlendirmesi) ---
        if entry.get("hint"):
            hint_lines.append(f'- "{term}" → {entry["hint"]}')

    output.hints_text = "\n".join(hint_lines) if hint_lines else "Özel terim eşleşmesi bulunamadı."
    logger.info(
        f"[TERM_RESOLVER] {len(matched)} match(es): "
        f"{len(output.term_filters)} filter(s), "
        f"{len(output.ambiguous)} ambiguous"
    )
    return output


def resolve_terms(user_query: str) -> str:
    """Backward compatibility: sadece hints_text döndür."""
    return resolve_terms_structured(user_query).hints_text
