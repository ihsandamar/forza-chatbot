"""
Term Resolver
=============
Kullanıcı sorgusunda Türkçe iş terimlerini tespit eder ve
sql_architect prompt'una inject edilecek hint metni üretir.

LLM kullanmaz. Deterministik, hızlı, test edilebilir.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

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


def resolve_terms(user_query: str) -> str:
    """
    Kullanıcı sorgusundaki Türkçe iş terimlerini tespit et.

    Args:
        user_query: Kullanıcının doğal dil sorgusu

    Returns:
        Prompt'a inject edilecek hint metni.
        Eşleşme yoksa "Özel terim eşleşmesi bulunamadı." döner.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.warning("[TERM_RESOLVER] rapidfuzz not available, skipping term resolution")
        return "Özel terim eşleşmesi bulunamadı."

    terms = _load_dictionary()
    if not terms:
        return "Özel terim eşleşmesi bulunamadı."

    normalized_query = _normalize(user_query)
    matched: List[Dict[str, Any]] = []
    seen_columns: set[str] = set()  # Aynı kolon için tekrar eşleşme önle

    for entry in terms:
        column = entry.get("column", "")
        if column in seen_columns:
            continue

        # Tüm aday terimler: term + aliases
        candidates = [entry["term"]] + entry.get("aliases", [])

        best_score = 0
        for candidate in candidates:
            norm_candidate = _normalize(candidate)

            # Exact substring kontrolü (öncelikli)
            if norm_candidate in normalized_query:
                best_score = 100
                break

            # Fuzzy match
            score = fuzz.token_set_ratio(normalized_query, norm_candidate)
            if score > best_score:
                best_score = score

        if best_score >= _SCORE_THRESHOLD:
            matched.append({"entry": entry, "score": best_score})
            seen_columns.add(column)
            logger.debug(f"[TERM_RESOLVER] Match: '{entry['term']}' score={best_score}")

    if not matched:
        return "Özel terim eşleşmesi bulunamadı."

    # Hint metnini oluştur
    lines = []
    for m in sorted(matched, key=lambda x: -x["score"]):
        entry = m["entry"]
        lines.append(f'- "{entry["term"]}" → {entry["hint"]}')

    result = "\n".join(lines)
    logger.info(f"[TERM_RESOLVER] {len(matched)} term(s) matched: {[m['entry']['term'] for m in matched]}")
    return result
