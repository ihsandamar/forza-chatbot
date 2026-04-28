# Semantic / Deterministic Separation — Suffix Stripping Removal Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a clean semantic/deterministic boundary: LLM produces canonical raw_text + mandatory column_hint for all entity types; Python does only deterministic alias lookup + fuzzy match, zero morphology.

**Architecture:**
- **Semantic layer (LLM):** `semantic_extractor` understands Turkish, extracts root forms, maps entity → column via `column_hint`. This is the only place where language understanding happens.
- **Deterministic layer (Python):** `ColumnResolver` maps known canonical terms → DB columns via `_ALIAS_TABLE`, uses LLM-provided `column_hint` as primary for entities, fuzzy match as last resort. No morphological analysis.

Currently `column_hint` is only MANDATORY for `filter_value`. `dimension` and `comparison_value` show it in examples but declare no rule. Without the mandatory rule, removing suffix stripping would break resolution for those entity types.

**Tech Stack:** Python 3.11, pytest, `SEMANTIC_EXTRACTOR_PROMPT` string in `prompts.py`, `ColumnResolver` in `column_resolver.py`.

---

## File Map

| File | Change |
|---|---|
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | Add canonical raw_text rule; make column_hint MANDATORY for dimension + comparison_value |
| `src/graphs/report_agent/subagents/text2sql/column_resolver.py` | Remove `_TR_SUFFIXES`, `_MIN_STEM_LEN`, `_strip_suffixes_intermediate()`, step 2 in `resolve()` |
| `tests/unit/text2sql/test_semantic_extractor_node.py` | Add tests asserting prompt rules are present |
| `tests/unit/text2sql/test_column_resolver.py` | Delete suffix tests; add test asserting inflected forms → None |

**What stays in `column_resolver.py`:** `_TR_MAP` + `_normalize()` (charset normalization: ı→i, ş→s — not morphology), `_ALIAS_TABLE`, alias lookup, column_hint fallback, fuzzy match.

---

## Task 1: Strengthen SEMANTIC_EXTRACTOR_PROMPT — enforce semantic contract

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py` (~line 773)
- Modify: `tests/unit/text2sql/test_semantic_extractor_node.py`

The prompt must guarantee what the deterministic Python layer depends on:
1. `raw_text` is always the canonical root form (no Turkish inflections)
2. `column_hint` is mandatory for **all** entity types

- [ ] **Step 1a — Write failing tests for the new prompt rules**

Add to `tests/unit/text2sql/test_semantic_extractor_node.py`:

```python
def test_prompt_mandates_canonical_raw_text():
    """
    SEMANTIC_EXTRACTOR_PROMPT must contain an explicit rule that raw_text
    is the canonical root form for ALL entity types. Python does not strip suffixes.
    """
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "raw_text = KANONİK KÖK FORM" in SEMANTIC_EXTRACTOR_PROMPT
    # Negative example must be present so the LLM learns from contrast
    assert "platformlara" in SEMANTIC_EXTRACTOR_PROMPT
    assert "YASAK" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_mandates_column_hint_for_dimension():
    """
    column_hint must be declared ZORUNLU for dimension entities,
    not just shown in examples.
    """
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    # Find the dimension section and verify ZORUNLU appears there
    dim_idx = SEMANTIC_EXTRACTOR_PROMPT.find('"dimension"')
    assert dim_idx != -1
    # ZORUNLU must appear within 400 chars of the dimension heading
    dim_section = SEMANTIC_EXTRACTOR_PROMPT[dim_idx:dim_idx + 400]
    assert "ZORUNLU" in dim_section, "column_hint must be declared ZORUNLU for dimension entities"


def test_prompt_mandates_column_hint_for_comparison_value():
    """
    column_hint must be declared ZORUNLU for comparison_value entities.
    """
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    cv_idx = SEMANTIC_EXTRACTOR_PROMPT.find('"comparison_value"')
    assert cv_idx != -1
    cv_section = SEMANTIC_EXTRACTOR_PROMPT[cv_idx:cv_idx + 400]
    assert "ZORUNLU" in cv_section, "column_hint must be declared ZORUNLU for comparison_value entities"
```

- [ ] **Step 1b — Run tests to verify they FAIL**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_mandates_canonical_raw_text tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_mandates_column_hint_for_dimension tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_mandates_column_hint_for_comparison_value -v
```

Expected: 3 × FAIL

- [ ] **Step 1c — Update `SEMANTIC_EXTRACTOR_PROMPT` in `prompts.py`**

Find this block (around line 773):

```
## entity_type KURALLARI

**"filter_value"**: Sorguda filtre değeri olan spesifik kavram.
  KURAL 1 — raw_text = SAF DEĞER (Türkçe gramer ekleri dahil değil):
    "espresso kategorisi" → raw_text="espresso"     (NOT "espresso kategorisi")
    "Ankara şubesi"       → raw_text="Ankara"        (NOT "Ankara şubesi")
    "dürümler kategorisi" → raw_text="dürümler"      (NOT "dürümler kategorisi")
  KURAL 2 — column_hint = filter_value için ZORUNLU, MEVCUT KOLON ADLARI listesinden seç:
    "espresso kategorisi" → entity("espresso",  filter_value, column_hint="CategoryName")
    "Ankara şubesi"       → entity("Ankara",    filter_value, column_hint="BranchName")
    "dürümler kategorisi" → entity("dürümler",  filter_value, column_hint="CategoryName")
    "son 1 yılda"         → entity DEĞİL, time alanına yaz

**"dimension"**: Gruplama boyutu. "...e göre", "...lere göre", "bazında", "kırılımı" ile gelir.
  - "ürünlere göre"       → entity("ürün",      dimension, column_hint="ProductName")
  - "kategoriler bazında" → entity("kategori",  dimension, column_hint="CategoryName")

**"comparison_value"**: COMPARISON sorgusunda karşılaştırılan iki veya daha fazla spesifik değer.
  - "dürümler ve içecek karşılaştır" → entity("dürümler", comparison_value, column_hint="CategoryName") + entity("içecek", comparison_value, column_hint="CategoryName")
  - Her iki değer AYRI entity olarak yazılır
```

Replace with:

```
## entity_type KURALLARI

## raw_text = KANONİK KÖK FORM (TÜM entity tipleri — KRİTİK)
raw_text DAIMA sözlük/kök formunu içermeli. Türkçe çekim, çoğul, hal ekleri raw_text'e DAHİL EDİLMEZ.
Python suffix soyma YAPMAZ — kanonik form buradan gelmek zorunda.

✅ DOĞRU:   "platformlara göre"     → raw_text: "platform"
✅ DOĞRU:   "şubelerdeki satışlar"  → raw_text: "şube"
✅ DOĞRU:   "ürünlerin performansı" → raw_text: "ürün"
✅ DOĞRU:   "kategorisindeki"       → raw_text: "kategori"
❌ YASAK:   "platformlara göre"     → raw_text: "platformlara"
❌ YASAK:   "şubelerdeki satışlar"  → raw_text: "şubelerdeki"

**"filter_value"**: Sorguda filtre değeri olan spesifik kavram.
  KURAL 1 — raw_text = SAF DEĞER (Türkçe gramer ekleri dahil değil):
    "espresso kategorisi" → raw_text="espresso"     (NOT "espresso kategorisi")
    "Ankara şubesi"       → raw_text="Ankara"        (NOT "Ankara şubesi")
    "dürümler kategorisi" → raw_text="dürümler"      (NOT "dürümler kategorisi")
  KURAL 2 — column_hint = filter_value için ZORUNLU, MEVCUT KOLON ADLARI listesinden seç:
    "espresso kategorisi" → entity("espresso",  filter_value, column_hint="CategoryName")
    "Ankara şubesi"       → entity("Ankara",    filter_value, column_hint="BranchName")
    "dürümler kategorisi" → entity("dürümler",  filter_value, column_hint="CategoryName")
    "son 1 yılda"         → entity DEĞİL, time alanına yaz

**"dimension"**: Gruplama boyutu. "...e göre", "...lere göre", "bazında", "kırılımı" ile gelir.
  column_hint = dimension için ZORUNLU, MEVCUT KOLON ADLARI listesinden seç:
  - "ürünlere göre"       → entity("ürün",      dimension, column_hint="ProductName")
  - "kategoriler bazında" → entity("kategori",  dimension, column_hint="CategoryName")
  - "platformlara göre"   → entity("platform",  dimension, column_hint="DocumentKindName")
  - "şubelere göre"       → entity("şube",      dimension, column_hint="BranchName")

**"comparison_value"**: COMPARISON sorgusunda karşılaştırılan iki veya daha fazla spesifik değer.
  column_hint = comparison_value için ZORUNLU, MEVCUT KOLON ADLARI listesinden seç:
  - "dürümler ve içecek karşılaştır" → entity("dürümler", comparison_value, column_hint="CategoryName") + entity("içecek", comparison_value, column_hint="CategoryName")
  - Her iki değer AYRI entity olarak yazılır
```

- [ ] **Step 1d — Run tests to verify they PASS**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v --tb=short
```

Expected: all pass including the 3 new tests.

- [ ] **Step 1e — Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py \
        tests/unit/text2sql/test_semantic_extractor_node.py
git commit -m "feat(nlu): enforce semantic contract — canonical raw_text + mandatory column_hint for all entity types"
```

---

## Task 2: Remove suffix stripping from ColumnResolver

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/column_resolver.py`
- Modify: `tests/unit/text2sql/test_column_resolver.py`

With Task 1 complete, the LLM guarantees canonical raw_text + column_hint. Python no longer needs morphological analysis. Removing it makes the deterministic contract explicit.

- [ ] **Step 2a — Write failing test asserting inflected forms return None**

Add to `tests/unit/text2sql/test_column_resolver.py`:

```python
def test_inflected_forms_return_none(resolver):
    """
    ColumnResolver does NOT do suffix stripping.
    Inflected forms that are not in _ALIAS_TABLE directly → None.
    The LLM is responsible for providing canonical root forms.
    """
    assert resolver.resolve("kategorisindeki") is None
    assert resolver.resolve("platformlara") is None
    assert resolver.resolve("şubeden") is None
    assert resolver.resolve("ürünlerin") is None
```

- [ ] **Step 2b — Run test to verify it FAILS (suffix stripping still active)**

```
pytest tests/unit/text2sql/test_column_resolver.py::test_inflected_forms_return_none -v
```

Expected: FAIL — `assert 'CategoryName' is None`

- [ ] **Step 2c — Delete the 5 suffix-stripping tests from `test_column_resolver.py`**

Remove these entire test functions (they describe behavior being removed):

```python
# DELETE — suffix stripping no longer exists in ColumnResolver:
def test_strip_possessive_si(resolver): ...
def test_strip_possessive_si_with_locative(resolver): ...
def test_strip_ablative_den(resolver): ...
def test_strip_locative_de(resolver): ...
def test_resolve_platform_inflected(resolver): ...
```

- [ ] **Step 2d — Replace `column_resolver.py` with the suffix-free version**

Replace the entire file:

```python
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
```

- [ ] **Step 2e — Also update the docstring in `nodes.py` that mentions suffix stripping**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, find this docstring line (around line 416):

```python
                           has no ChromaDB match, resolves via alias table + Turkish
                           suffix stripping. Applies to both entities and metrics.
```

Replace with:

```python
                           has no ChromaDB match, resolves via alias table +
                           column_hint fallback. Applies to both entities and metrics.
```

- [ ] **Step 2f — Run failing test + full suite**

```
pytest tests/unit/text2sql/test_column_resolver.py -v --tb=short
```

Expected: `test_inflected_forms_return_none` now PASSES, all other tests pass (suffix tests were deleted in Step 2c).

Then full suite:

```
pytest tests/unit/text2sql/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 2g — Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/column_resolver.py \
        src/graphs/report_agent/subagents/text2sql/nodes.py \
        tests/unit/text2sql/test_column_resolver.py
git commit -m "refactor(nlu): remove suffix stripping from ColumnResolver — LLM owns morphology, Python is deterministic"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ canonical raw_text rule in prompt — Task 1
- ✅ column_hint ZORUNLU for dimension — Task 1
- ✅ column_hint ZORUNLU for comparison_value — Task 1
- ✅ suffix stripping removed from Python — Task 2
- ✅ inflected forms → None test (locks in the new contract) — Task 2
- ✅ docstring updated to not mention suffix stripping — Task 2

**2. Placeholder scan:** None found.

**3. Type consistency:** `ColumnResolver.resolve()` signature unchanged.

**4. Dependency order:** Task 1 (prompt) before Task 2 (Python) — correct. If Task 2 runs first without Task 1, existing queries with non-canonical raw_text would break silently. Task 1 first ensures the LLM contract is set before Python removes its safety net.
