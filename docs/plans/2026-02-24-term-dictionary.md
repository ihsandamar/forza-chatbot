# Term Dictionary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Türkçe iş terimlerini (`ciro`, `ödemesi alınan masa` vb.) DB kolon adlarına/değerlerine eşleştiren tablo-bağımsız bir sözlük; sql_architect prompt'una dinamik olarak inject edilir.

**Architecture:** `term_dictionary.json` → `term_resolver.py` (Python normalize+arama) → `sql_architect_node` prompt inject (`{term_hints}` placeholder). LLM token yükü minimum: sadece sorguyla eşleşen terimler eklenir.

**Tech Stack:** Python 3.12, rapidfuzz (zaten mevcut), json

**Design Kararları:**
- Sözlük tablo-bağımsız (sadece semantik iş terimleri → kolon eşleştirmesi)
- Prompt'a hardcode değil, runtime inject (bakım kolaylığı)
- Eşleşme: önce exact, sonra partial (rapidfuzz token_set_ratio ≥ 70)
- Birden fazla eşleşme → hepsi inject edilir
- Eşleşme yoksa `{term_hints}` → `"Özel terim eşleşmesi bulunamadı."`

---

## Referans Dosyalar

Yeni:
- `src/graphs/report_agent/subagents/text2sql/term_dictionary.json`
- `src/graphs/report_agent/subagents/text2sql/term_resolver.py`

Değiştirilecek:
- `src/graphs/report_agent/subagents/text2sql/prompts.py`
- `src/graphs/report_agent/subagents/text2sql/nodes.py`

---

## Task 1: term_dictionary.json oluştur

**File:** `src/graphs/report_agent/subagents/text2sql/term_dictionary.json`

**Step 1: Dosyayı oluştur**

```json
{
  "version": "1.0",
  "description": "Türkçe iş terimi → DB kolon/değer eşleştirme sözlüğü. Tablo bağımsız.",
  "terms": [
    {
      "term": "ciro",
      "aliases": ["satış tutarı", "gelir", "revenue", "tutar", "satış", "kazanç", "hasılat"],
      "column": "RowAmount",
      "hint": "Satış tutarını temsil eder → SUM([RowAmount]) kullan"
    },
    {
      "term": "adet",
      "aliases": ["miktar", "quantity", "satış adedi", "satılan", "kaç tane"],
      "column": "Quantity",
      "hint": "Satış adedini temsil eder → SUM([Quantity]) kullan"
    },
    {
      "term": "ödemesi alınan masa",
      "aliases": ["kapalı masa", "tamamlanan masa", "biten masa", "ödeme alındı"],
      "column": "IsTableActive",
      "filter": "IsTableActive = 0",
      "hint": "Ödemesi tamamlanmış masalar → WHERE [IsTableActive] = 0 filtresi ekle"
    },
    {
      "term": "açık masa",
      "aliases": ["aktif masa", "ödemesi alınmamış masa", "masada oturan"],
      "column": "IsTableActive",
      "filter": "IsTableActive = 1",
      "hint": "Henüz ödeme alınmamış aktif masalar → WHERE [IsTableActive] = 1 filtresi ekle"
    },
    {
      "term": "normal satış",
      "aliases": ["standart satış", "ikram değil", "zayi değil", "iptal değil"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "filter": "DocumentDetailIsTreatWasteCancel IS NULL",
      "hint": "Sadece normal satışlar → WHERE [DocumentDetailIsTreatWasteCancel] IS NULL"
    },
    {
      "term": "ikram",
      "aliases": ["bedava", "ikram edilen", "ücretsiz"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "filter": "DocumentDetailIsTreatWasteCancel = 1",
      "hint": "İkram kayıtları → WHERE [DocumentDetailIsTreatWasteCancel] = 1"
    },
    {
      "term": "iade",
      "aliases": ["iade satış", "geri iade", "return"],
      "column": "DocumentTypeIsReturn",
      "filter": "DocumentTypeIsReturn = 1",
      "hint": "İade işlemleri → WHERE [DocumentTypeIsReturn] = 1"
    },
    {
      "term": "paket servis",
      "aliases": ["paket", "delivery", "eve teslim", "online sipariş"],
      "column": "DocumentKindName",
      "filter": "DocumentKindName = 'Paket Servis'",
      "hint": "Paket servis kanalı → WHERE [DocumentKindName] = 'Paket Servis'"
    },
    {
      "term": "masa siparişi",
      "aliases": ["masada yeme", "restoran", "masa satışı"],
      "column": "DocumentKindName",
      "filter": "DocumentKindName = 'Masa'",
      "hint": "Masa kanalı → WHERE [DocumentKindName] = 'Masa'"
    },
    {
      "term": "ana ürün",
      "aliases": ["menü dışı", "bağımsız ürün", "seçenek değil"],
      "column": "MenuId",
      "filter": "MenuId IS NULL",
      "hint": "Menü seçeneği olmayan ana ürünler → WHERE [MenuId] IS NULL"
    },
    {
      "term": "indirim",
      "aliases": ["iskonto", "indirim tutarı", "discount"],
      "column": "DiscountAmountTotal",
      "hint": "İndirim tutarını temsil eder → SUM([DiscountAmountTotal]) veya AVG([DiscountAmountTotal]) kullan"
    },
    {
      "term": "adisyon",
      "aliases": ["fiş", "sipariş", "belge", "document"],
      "column": "DocumentId",
      "hint": "Adisyon sayısı için → COUNT(DISTINCT [DocumentId]) kullan"
    }
  ]
}
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_dictionary.json
git commit -m "feat(text2sql): add Turkish business term dictionary"
```

---

## Task 2: term_resolver.py oluştur

**File:** `src/graphs/report_agent/subagents/text2sql/term_resolver.py`

**Step 1: Dosyayı oluştur**

```python
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
import unicodedata
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
```

**Step 2: Smoke test (terminal'de)**

```python
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms

# Test 1: ciro + ödemesi alınan masa
print(resolve_terms("Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori"))
# Beklenen:
# - "ciro" → Satış tutarını temsil eder → SUM([RowAmount]) kullan
# - "ödemesi alınan masa" → Ödemesi tamamlanmış masalar → WHERE [IsTableActive] = 0 filtresi ekle

# Test 2: Eşleşme yok
print(resolve_terms("Merhaba nasılsın"))
# Beklenen: "Özel terim eşleşmesi bulunamadı."

# Test 3: Adet
print(resolve_terms("En çok satan ürün adedi"))
# Beklenen: "adet" → Satış adedini temsil eder → SUM([Quantity]) kullan
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_resolver.py
git commit -m "feat(text2sql): add term_resolver - Turkish business term matching"
```

---

## Task 3: prompts.py — {term_hints} placeholder ekle

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

**Step 1: SQL_ARCHITECT_PROMPT'a yeni bölüm ekle**

`## KULLANICI SORUSU` bölümünden önce şunu ekle:

```python
SQL_ARCHITECT_PROMPT = """Sen bir T-SQL sorgu mimarısın. ...

## SORGUDA TESPİT EDİLEN İŞ TERİMLERİ (Doğrudan Uygula)
{term_hints}

## BUGÜNÜN TARİHİ
...
```

Kurallar bölümüne de şunu ekle (KURAL 1'den önce):

```
### KURAL 0 — Terim Eşleştirmeleri (EN YÜKSEK ÖNCELİK)
"SORGUDA TESPİT EDİLEN İŞ TERİMLERİ" bölümündeki eşleştirmeleri MUTLAKA uygula.
Bu bölümdeki filtreler ve kolon seçimleri kesindir — column_metadata'dan bağımsız olarak geçerlidir.
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat(text2sql): add term_hints placeholder to SQL_ARCHITECT_PROMPT"
```

---

## Task 4: nodes.py — sql_architect_node'a term_resolver inject et

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: Import ekle (dosyanın import bölümüne)**

```python
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms
```

**Step 2: `create_sql_architect_node` içinde prompt.format() öncesine ekle**

`today = date.today()` satırından sonra:

```python
# Terim eşleştirme
term_hints = resolve_terms(user_query)
```

`prompt = SQL_ARCHITECT_PROMPT.format(...)` içine ekle:

```python
prompt = SQL_ARCHITECT_PROMPT.format(
    term_hints=term_hints,          # ← YENİ
    user_query=user_query,
    ...
)
```

**Step 3: Log güncelle**

```python
logger.info(f"[SQL_ARCHITECT] Planning: {user_query[:80]} (type={query_type}, terms={term_hints[:60]})")
```

**Step 4: Uçtan uca test**

LangGraph Studio'da:
```
"Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori nedir?"
```

Beklenen QuerySchema:
```json
{
  "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
  "filters": [
    {"column": "IsTableActive", "operator": "=", "value": "0"},
    {"column": "DocumentDate", "operator": ">=", "date_descriptor": {"type": "relative", "unit": "year", "amount": -1}}
  ],
  "group_by": ["CategoryName"],
  "order_by_column": "ToplamCiro",
  "order_by_direction": "DESC",
  "limit": 1
}
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(text2sql): inject term_hints into sql_architect prompt"
```
