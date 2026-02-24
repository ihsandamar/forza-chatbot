# Term Resolver Architectural Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** term_resolver'ı tablo-bağımsız, Python-garantili WHERE filter üreten bir bileşene dönüştür; LLM'in yanlış uyguladığı iş terimlerini Python katmanı garantiler.

**Architecture:**
```
business_rules(query) → auto_rules  ──────────────→ sql_builder (Python ✅)
term_resolver(query)  → term_filters ─→ sql_generator (Python garantili ✅, override LLM)
                      → term_hints   ─→ sql_architect prompt (LLM advisory, col names only)
sql_architect(LLM)    → QuerySchema  ─→ sql_generator (field mapping: agg/groupby/dates)
```

term_resolver iki çıktı üretir:
- `term_filters`: SchemaFilter-uyumlu dict listesi — Python tarafından QuerySchema'ya merge edilir, LLM'in ürettiği çakışan filtreler OVERRIDE edilir
- `term_hints`: LLM'e sadece kolon adı yönlendirmesi (GROUP BY, aggregation için)

Belirsiz (ambiguous) terimler için `interrupt()` ile kullanıcıya sorulur.

**Tespit edilen 4 bug (root cause):**
1. `"son 1 senede"` → `current_period:month` (prompt KURAL 2'de "sene" yok)
2. `IsTableActive = 1` (LLM term_hint'i yoksaydı → artık Python garantili)
3. `GROUP BY ProductName` (term_dict'te "kategori" → CategoryName yok)
4. `TOP 10` (KURAL 4 tekil isim için limit=1 tanımlamamış)

**Tech Stack:** Python 3.12, Pydantic, LangGraph interrupt(), dataclasses, rapidfuzz

**Referans dosyalar:**
- `src/graphs/report_agent/subagents/text2sql/term_resolver.py`
- `src/graphs/report_agent/subagents/text2sql/term_dictionary.json`
- `src/graphs/report_agent/subagents/text2sql/state.py`
- `src/graphs/report_agent/subagents/text2sql/nodes.py`
- `src/graphs/report_agent/subagents/text2sql/graph.py`
- `src/graphs/report_agent/subagents/text2sql/prompts.py`

---

## Task 1: term_dictionary.json — `filter_structured` ekle + eksik terimler

**File:** `src/graphs/report_agent/subagents/text2sql/term_dictionary.json`

**Step 1: Her filter entry'e `filter_structured` ekle, eksik terimleri ekle**

Tüm dosyayı şununla değiştir:

```json
{
  "version": "1.1",
  "description": "Türkçe iş terimi → DB kolon/değer eşleştirme sözlüğü. Tablo bağımsız.",
  "terms": [
    {
      "term": "ciro",
      "aliases": ["satış tutarı", "gelir", "revenue", "tutar", "satış", "kazanç", "hasılat"],
      "column": "RowAmount",
      "hint": "Satış tutarını temsil eder → aggregations: SUM([RowAmount]) kullan"
    },
    {
      "term": "adet",
      "aliases": ["miktar", "quantity", "satış adedi", "satılan", "kaç tane"],
      "column": "Quantity",
      "hint": "Satış adedini temsil eder → aggregations: SUM([Quantity]) kullan"
    },
    {
      "term": "ödemesi alınan masa",
      "aliases": ["kapalı masa", "tamamlanan masa", "biten masa", "ödeme alındı", "ödemesi alınan"],
      "column": "IsTableActive",
      "filter": "IsTableActive = 0",
      "filter_structured": {"column": "IsTableActive", "operator": "=", "value": "0"},
      "hint": "[IsTableActive] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "açık masa",
      "aliases": ["aktif masa", "ödemesi alınmamış masa", "masada oturan"],
      "column": "IsTableActive",
      "filter": "IsTableActive = 1",
      "filter_structured": {"column": "IsTableActive", "operator": "=", "value": "1"},
      "hint": "[IsTableActive] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "normal satış",
      "aliases": ["standart satış", "ikram değil", "zayi değil", "iptal değil"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "filter": "DocumentDetailIsTreatWasteCancel IS NULL",
      "filter_structured": {"column": "DocumentDetailIsTreatWasteCancel", "operator": "IS NULL"},
      "hint": "[DocumentDetailIsTreatWasteCancel] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "ikram",
      "aliases": ["bedava", "ikram edilen", "ücretsiz"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "filter": "DocumentDetailIsTreatWasteCancel = 1",
      "filter_structured": {"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
      "hint": "[DocumentDetailIsTreatWasteCancel] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "iade",
      "aliases": ["iade satış", "geri iade", "return"],
      "column": "DocumentTypeIsReturn",
      "filter": "DocumentTypeIsReturn = 1",
      "filter_structured": {"column": "DocumentTypeIsReturn", "operator": "=", "value": "1"},
      "hint": "[DocumentTypeIsReturn] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "paket servis",
      "aliases": ["paket", "delivery", "eve teslim", "online sipariş"],
      "column": "DocumentKindName",
      "filter": "DocumentKindName = 'Paket Servis'",
      "filter_structured": {"column": "DocumentKindName", "operator": "=", "value": "Paket Servis"},
      "hint": "[DocumentKindName] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "masa siparişi",
      "aliases": ["masada yeme", "restoran", "masa satışı"],
      "column": "DocumentKindName",
      "filter": "DocumentKindName = 'Masa'",
      "filter_structured": {"column": "DocumentKindName", "operator": "=", "value": "Masa"},
      "hint": "[DocumentKindName] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "ana ürün",
      "aliases": ["menü dışı", "bağımsız ürün", "seçenek değil"],
      "column": "MenuId",
      "filter": "MenuId IS NULL",
      "filter_structured": {"column": "MenuId", "operator": "IS NULL"},
      "hint": "[MenuId] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME"
    },
    {
      "term": "indirim",
      "aliases": ["iskonto", "indirim tutarı", "discount"],
      "column": "DiscountAmountTotal",
      "hint": "İndirim tutarı → aggregations: SUM([DiscountAmountTotal]) veya AVG([DiscountAmountTotal]) kullan"
    },
    {
      "term": "adisyon",
      "aliases": ["fiş", "sipariş", "belge", "document"],
      "column": "DocumentId",
      "hint": "Adisyon sayısı için → aggregations: COUNT(DISTINCT [DocumentId]) kullan"
    },
    {
      "term": "kategori",
      "aliases": ["kategoriler", "kategoriye göre", "kategorilere göre", "kategoride", "ürün kategorisi"],
      "column": "CategoryName",
      "hint": "Kategori kolonu → group_by veya select: [CategoryName] kullan"
    },
    {
      "term": "ürün",
      "aliases": ["ürünler", "ürüne göre", "ürünlere göre", "ürün adı", "menü ürünü"],
      "column": "ProductName",
      "hint": "Ürün kolonu → group_by veya select: [ProductName] kullan"
    },
    {
      "term": "şube",
      "aliases": ["şubeler", "şubeye göre", "şubelere göre", "şubede", "lokasyon"],
      "column": "BranchName",
      "hint": "Şube kolonu → group_by veya select: [BranchName] kullan"
    },
    {
      "term": "kasiyer",
      "aliases": ["kasiyerler", "kasiyere göre", "kasiyerlere göre", "kasiyer adı"],
      "column": "CashierName",
      "hint": "Kasiyer kolonu → group_by veya select: [CashierName] kullan"
    },
    {
      "term": "masa",
      "aliases": ["masa numarası", "masa no", "table no", "masalar"],
      "column": "TableNo",
      "hint": "Masa numarası kolonu → group_by veya select: [TableNo] kullan"
    },
    {
      "term": "şehir",
      "aliases": ["şehirler", "şehre göre", "şehirlere göre", "il"],
      "column": "BranchCityName",
      "hint": "Şehir kolonu → group_by veya select: [BranchCityName] kullan"
    }
  ]
}
```

**Step 2: Verify JSON geçerli**

```bash
python -c "import json; d=json.load(open('src/graphs/report_agent/subagents/text2sql/term_dictionary.json', encoding='utf-8')); print(f'OK: {len(d[\"terms\"])} terms')"
```

Beklenen: `OK: 18 terms`

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_dictionary.json
git commit -m "feat(term-dict): add filter_structured to all filter terms, add missing column hints (kategori, ürün, şube, kasiyer, masa, şehir)"
```

---

## Task 2: term_resolver.py — TermResolverOutput + resolve_terms_structured

**File:** `src/graphs/report_agent/subagents/text2sql/term_resolver.py`

**Step 1: Tüm dosyayı yeniden yaz**

```python
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
```

**Step 2: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms_structured, TermResolverOutput; print('OK')"
```

**Step 3: Hızlı smoke test**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms_structured

q = 'Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori nedir?'
r = resolve_terms_structured(q)
print('term_filters:', r.term_filters)
print('hints:', r.hints_text)

# Garantiler
tf_cols = [f['column'] for f in r.term_filters]
assert 'IsTableActive' in tf_cols, 'IsTableActive filter yok!'
tf_ita = next(f for f in r.term_filters if f['column'] == 'IsTableActive')
assert tf_ita['value'] == '0', f'IsTableActive değeri yanlış: {tf_ita[\"value\"]}'
assert 'CategoryName' in r.hints_text, 'CategoryName hint yok!'
assert 'RowAmount' in r.hints_text, 'ciro/RowAmount hint yok!'
print('PASS')
"
```

Beklenen:
```
term_filters: [{'column': 'IsTableActive', 'operator': '=', 'value': '0', 'logical_operator': 'AND'}]
hints: ...
PASS
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_resolver.py
git commit -m "refactor(term-resolver): add TermResolverOutput + resolve_terms_structured — Python-guaranteed filters + LLM advisory hints"
```

---

## Task 3: state.py — term_filters + term_hints ekle

**File:** `src/graphs/report_agent/subagents/text2sql/state.py`

**Step 1: Yeni alanları ekle**

```python
    # --- Internal ---
    query_schema: Optional[Dict[str, Any]]       # QuerySchema.model_dump()
    auto_rules:   Optional[List[Dict[str, Any]]] # ChromaDB'den bulunan rules — sql_generator uygular
    term_filters: Optional[List[Dict[str, Any]]] # term_resolver → sql_generator (Python garantili WHERE)
    term_hints:   Optional[str]                  # term_resolver → sql_architect LLM prompt (col name hints)
    retry_count:  int                            # 0 | 1 | 2
    sql_error:    Optional[str]                  # Son SQL hata mesajı (retry için)
    # business_rules_context KALDIRILDI — LLM artık kuralları görmüyor
```

Ayrıca docstring'i güncelle:
```python
    Internal keys (sadece bu subgraph içinde kullanılır):
        query_schema, auto_rules, term_filters, term_hints, retry_count, sql_error
```

**Step 2: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState; assert 'term_filters' in Text2SQLState.__annotations__; assert 'term_hints' in Text2SQLState.__annotations__; print('OK')"
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/state.py
git commit -m "feat(state): add term_filters and term_hints to Text2SQLState"
```

---

## Task 4: nodes.py — create_term_resolver_node ekle

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: resolve_terms import'unu güncelle**

Dosyanın import bölümünde şu satırı değiştir:
```python
# ESKİ:
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms

# YENİ:
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms_structured
```

**Step 2: MODULE DOCSTRING'e term_resolver node'u ekle**

```python
"""
Text2SQL Subagent Nodes (v2)

8 node:
    create_table         - Pure Python: tablo oluştur (no-op if no query config)
    business_rules       - Pure Python: ChromaDB semantic search → auto_rules
    term_resolver        - Pure Python + interrupt(): term_dict match → term_filters (guaranteed) + term_hints (LLM advisory)
    sql_architect        - LLM (STRUCTURED OUTPUT): user_query → QuerySchema (field mapping only)
    value_resolver       - Pure Python: fuzzy match + interrupt() if low confidence
    sql_generator        - Pure Python: QuerySchema + term_filters + auto_rules → T-SQL (NO LLM)
    sql_executor         - Pure Python: SQL çalıştır, hata → retry
    cleanup_table        - Pure Python: tabloyu drop et (no-op if no query config)
"""
```

**Step 3: `create_term_resolver_node` fonksiyonunu NODE 3 olarak BUSINESS RULES'dan sonra ekle**

```python
# =============================================================================
# NODE 3: TERM RESOLVER
# =============================================================================

def create_term_resolver_node() -> Callable:
    """
    Pure Python + optional interrupt():
    user_query → term_filters (Python-guaranteed WHERE filters)
               + term_hints (LLM advisory column name hints)

    Ambiguous terms (ambiguous_columns alanı olan terimler) → interrupt() ile
    kullanıcıya hangi kolon sorulur.

    term_filters: sql_generator'da QuerySchema'ya merge edilir, LLM override edilir.
    term_hints:   sql_architect prompt'una inject edilir (sadece kolon adı yönlendirmesi).
    """

    async def term_resolver_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        result = resolve_terms_structured(user_query)

        term_filters = list(result.term_filters)  # kopyasını al

        # --- Ambiguous terms: kullanıcıya sor ---
        for amb in result.ambiguous:
            option_labels = [
                f"{opt['column']}: {opt.get('description', '')}"
                for opt in amb.options
            ]
            answer = interrupt({
                "type": "choice",
                "question": (
                    f'"{amb.term}" ifadesi birden fazla kolona karşılık gelebilir. '
                    f'Hangi kolonu kastetdiniz?'
                ),
                "options": option_labels,
            })
            # Seçilen option'ı bul ve filter_structured varsa term_filters'a ekle
            for opt in amb.options:
                key = f"{opt['column']}: {opt.get('description', '')}"
                if key == answer and opt.get("filter_structured"):
                    fs = dict(opt["filter_structured"])
                    fs.setdefault("logical_operator", "AND")
                    term_filters.append(fs)
                    break

        logger.info(
            f"[TERM_RESOLVER] {len(term_filters)} term_filter(s) set: "
            f"{[f['column'] for f in term_filters]}"
        )
        return {
            "term_filters": term_filters,
            "term_hints":   result.hints_text,
        }

    return term_resolver_node
```

**Step 4: Mevcut NODE numaralarını güncelle (yorum satırlarında)**

- NODE 1: SQL ARCHITECT → aynı kalır (VALUE_RESOLVER, BUSINESS_RULES numaraları değişmez, sadece yorum)

**Step 5: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node; print('OK')"
```

**Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(nodes): add create_term_resolver_node — Python-guaranteed term filters + ambiguous interrupt()"
```

---

## Task 5: nodes.py — sql_architect_node'u term_hints okuyacak şekilde güncelle

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: `create_sql_architect_node` içinde term_hints'i state'ten oku**

`sql_architect_node` async fonksiyonunun başında şu satırı değiştir:

```python
# ESKİ (resolve_terms doğrudan çağrılıyor):
term_hints = resolve_terms(user_query)

# YENİ (state'ten oku — term_resolver_node zaten yazdı):
term_hints = state.get("term_hints") or "Özel terim eşleşmesi bulunamadı."
```

**Step 2: İmport'tan `resolve_terms_structured` kullanımını kaldır**

`create_sql_architect_node` artık term_resolver import etmez. `resolve_terms_structured` import'u sadece `create_term_resolver_node` için gerekli — bu zaten modules scope'unda.

**Step 3: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_architect_node; print('OK')"
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "refactor(sql-architect): read term_hints from state instead of calling resolve_terms inline"
```

---

## Task 6: nodes.py — sql_generator_node'a term_filters merge ekle

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: `create_sql_generator_node` içinde term_filters merge'ı ekle**

```python
def create_sql_generator_node(
    default_table_name: str,
) -> Callable:
    """
    Pure Python: QuerySchema + state.auto_rules + state.term_filters → T-SQL. LLM kullanmaz.

    term_filters: term_resolver tarafından Python-garantili üretilmiş WHERE filtreler.
    Eğer term_filters ile LLM'in ürettiği QuerySchema'da aynı kolon varsa → term_filter WINS.
    """

    async def sql_generator_node(state: dict, *, config: RunnableConfig = None) -> dict:
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {"error": "QuerySchema bulunamadı", "results": []}

        table_name  = _get_configurable(config, "table_name", default_table_name)
        auto_rules  = state.get("auto_rules") or []
        term_filters = state.get("term_filters") or []
        today       = date.today()

        # --- term_filters merge: Python garantili filtreler LLM'i override eder ---
        if term_filters:
            schema_filters  = list(raw_schema.get("filters", []))
            override_cols   = {tf["column"] for tf in term_filters}
            # Aynı kolondaki LLM filterlerini kaldır
            schema_filters  = [f for f in schema_filters if f.get("column") not in override_cols]
            # Garantili filtreleri ekle
            schema_filters.extend(term_filters)
            raw_schema = {**raw_schema, "filters": schema_filters}
            logger.info(
                f"[SQL_GENERATOR] term_filters merged: {[tf['column'] for tf in term_filters]}"
            )

        try:
            sql = generate_sql(raw_schema, table_name, auto_rules, today)
            logger.info(f"[SQL_GENERATOR] SQL ready: {sql[:200]}")
            return {"sql_queries": [sql]}
        except Exception as e:
            logger.error(f"[SQL_GENERATOR] Build error: {e}")
            return {"error": f"SQL oluşturulamadı: {e}", "results": []}

    return sql_generator_node
```

**Step 2: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_generator_node; print('OK')"
```

**Step 3: Smoke test — term_filter override**

```bash
python -c "
import asyncio
from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_generator_node

node = create_sql_generator_node('TestTable')

# LLM yanlış IsTableActive=1 üretmiş ama term_filter IsTableActive=0 var
state = {
    'query_schema': {
        'description': 'test',
        'select_columns': [],
        'filters': [
            {'column': 'IsTableActive', 'operator': '=', 'value': '1', 'logical_operator': 'AND'},
        ],
        'aggregations': [{'function': 'SUM', 'column': 'RowAmount', 'alias': 'Ciro'}],
        'group_by': ['CategoryName'],
        'order_by_column': 'Ciro',
        'order_by_direction': 'DESC',
        'limit': 1,
    },
    'auto_rules': [],
    'term_filters': [
        {'column': 'IsTableActive', 'operator': '=', 'value': '0', 'logical_operator': 'AND'}
    ],
}
result = asyncio.run(node(state))
sql = result['sql_queries'][0]
print(sql)
assert '[IsTableActive] = 0' in sql, 'term_filter override çalışmadı!'
assert '[IsTableActive] = 1' not in sql, 'LLM filtri hala var!'
print('PASS')
"
```

Beklenen:
```sql
SELECT TOP 1 [CategoryName],
       SUM([RowAmount]) AS [Ciro]
FROM [TestTable]
WHERE [IsTableActive] = 0
GROUP BY [CategoryName]
ORDER BY [Ciro] DESC
PASS
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(sql-generator): merge term_filters into QuerySchema — term_filters override LLM filters for same column"
```

---

## Task 7: graph.py — term_resolver_node'u grafa ekle

**File:** `src/graphs/report_agent/subagents/text2sql/graph.py`

**Step 1: Docstring'i güncelle**

```python
"""
Text2SQL Subagent Graph (v2)

START → create_table → business_rules → term_resolver → sql_architect → value_resolver
        → sql_generator → sql_executor ──────────────────────────────────────────────┐
                               ↑ (retry, max 2)                                       │
                               └──────────────────────────────────────────────────────┘
                                                                                       ↓
                                                                            cleanup_table → END

create_table / cleanup_table: runtime config'te query varsa çalışır, yoksa no-op.
term_resolver: Deterministik — term_filters (Python garantili) + term_hints (LLM advisory)
sql_architect: TEK LLM çağrısı. Retry'da sql_error bağlamıyla yeniden çağrılır.
sql_generator: Pure Python. term_filters + auto_rules merge eder, LLM yok.
"""
```

**Step 2: Import ekle**

```python
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_sql_architect_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,      # YENİ
    create_value_resolver_node,
)
```

**Step 3: Node factory'e term_resolver ekle**

```python
    # --- Node factories ---
    create_table        = create_create_table_node(connection_string, table_name)
    business_rules      = create_business_rules_node(vector_store)
    term_resolver       = create_term_resolver_node()                    # YENİ
    sql_architect       = create_sql_architect_node(llm, column_metadata)
    value_resolver_node = create_value_resolver_node(value_resolver)
    sql_generator       = create_sql_generator_node(table_name)
    sql_executor        = create_sql_executor_node(connection_string)
    cleanup_table       = create_cleanup_table_node(connection_string, table_name)
```

**Step 4: Graph'a node + edge ekle**

```python
    graph.add_node("create_table",   create_table)
    graph.add_node("business_rules", business_rules)
    graph.add_node("term_resolver",  term_resolver)           # YENİ
    graph.add_node("sql_architect",  sql_architect)
    graph.add_node("value_resolver", value_resolver_node)
    graph.add_node("sql_generator",  sql_generator)
    graph.add_node("sql_executor",   sql_executor)
    graph.add_node("cleanup_table",  cleanup_table)

    graph.add_edge(START,             "create_table")
    graph.add_edge("create_table",    "business_rules")
    graph.add_edge("business_rules",  "term_resolver")         # DEĞİŞTİ
    graph.add_edge("term_resolver",   "sql_architect")         # YENİ
    graph.add_edge("sql_architect",   "value_resolver")
    graph.add_edge("value_resolver",  "sql_generator")
    graph.add_edge("sql_generator",   "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"sql_architect": "sql_architect", "cleanup_table": "cleanup_table"},
    )
    graph.add_edge("cleanup_table",   END)
```

**Step 5: Log mesajını güncelle**

```python
    logger.info(
        "[TEXT2SQL] Subgraph v2 built: "
        "create_table → business_rules → term_resolver → sql_architect → value_resolver "
        "→ sql_generator → sql_executor → cleanup_table (max 2 retry)"
    )
```

**Step 6: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph; print('OK')"
```

**Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "feat(graph): insert term_resolver_node between business_rules and sql_architect"
```

---

## Task 8: prompts.py — KURAL 2 (sene) + KURAL 4 (limit=1)

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

**Step 1: KURAL 2'ye "sene" sinonimi ve ek örnekler ekle**

```python
### KURAL 2 — Tarih Filtreleri (DateDescriptor ZORUNLU)
Sorguda tarih ifadesi varsa ("son 3 ay", "bu yıl", "ocak 2024", "son 1 sene" gibi):
  date_descriptor alanını doldur — value alanını KULLANMA.

ÖNEMLİ: "sene" = "yıl" (Türkçe sinonim). İkisi de aynı DateDescriptor'ı üretir.

Örnekler:
  "son 3 ay"          → {{"type":"relative","unit":"month","amount":-3}},   operator: ">="
  "son 7 gün"         → {{"type":"relative","unit":"day","amount":-7}},     operator: ">="
  "son 1 yıl"         → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "son 1 sene"        → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="  ← "sene"="yıl"
  "son 1 senede"      → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "son 2 yılda"       → {{"type":"relative","unit":"year","amount":-2}},    operator: ">="
  "bu yıl"            → {{"type":"current_period","period":"year"}},        operator: ">="
  "bu ay"             → {{"type":"current_period","period":"month"}},       operator: ">="
  "bugün"             → {{"type":"current_period","period":"day"}},         operator: ">="
  "bu çeyrek"         → {{"type":"current_period","period":"quarter"}},     operator: ">="
  "15 ocak"           → {{"type":"exact","value":"{current_year}-01-15"}},  operator: "="
  "ocak 2024"         → iki filter: >= {{"type":"exact","value":"2024-01-01"}}
                                   ve <= {{"type":"exact","value":"2024-01-31"}}, logical_operator: "AND"

Tarih filtresi için value alanını KULLANMA — date_descriptor kullan.
```

**Step 2: KURAL 4'ü limit=1 için güncelle**

```python
### KURAL 4 — RANKING Sorguları
"Top 10 / en çok / en az / sıralama" → limit + order_by_column + en az 1 aggregation ZORUNLU.

Limit değeri:
  - Soruda SAYI varsa → o sayıyı kullan: "en çok satan 10 ürün" → limit=10
  - Soruda SAYI YOK, TEKİL isim var → limit=1: "en çok satan ürün" → limit=1
  - "en çok ... kategorisi", "en az ... şube", "bir numaralı ürün" → limit=1
  - "top 5", "ilk 10", "en yüksek 3" → sayıyı kullan

Örnek:
  "en çok satan 10 ürün" → aggregations=[SUM(Quantity)], group_by=["ProductName"],
                            order_by_column="TotalQty", order_by_direction="DESC", limit=10
  "en çok ciro yapan kategori" → aggregations=[SUM(RowAmount)], group_by=["CategoryName"],
                                  order_by_column="ToplamCiro", order_by_direction="DESC", limit=1
  "en az satan ürün" → aggregations=[SUM(Quantity)], group_by=["ProductName"],
                        order_by_column="TotalQty", order_by_direction="ASC", limit=1
```

**Step 3: Format test**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.prompts import SQL_ARCHITECT_PROMPT
result = SQL_ARCHITECT_PROMPT.format(
    term_hints='test', user_query='test', query_type='SINGLE',
    today_date='2026-02-24', current_year=2026, current_month=2, current_quarter=1,
    column_metadata='{}', conversation_context='yok', sql_error='Yok',
)
assert 'sene' in result, 'sene keyword yok!'
assert 'limit=1' in result or 'limit=1' in result, 'limit=1 yok!'
assert 'TEKİL' in result or 'tekil' in result.lower(), 'TEKİL açıklama yok!'
print('Prompt format OK')
"
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "fix(prompt): KURAL 2 add sene=yil synonym + more date examples; KURAL 4 add limit=1 for singular noun"
```

---

## Task 9: Uçtan uca doğrulama

**Step 1: Tüm imports**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms_structured, TermResolverOutput
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.nodes import (
    create_term_resolver_node,
    create_sql_architect_node,
    create_sql_generator_node,
)
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
print('All imports OK')
assert 'term_filters' in Text2SQLState.__annotations__
assert 'term_hints' in Text2SQLState.__annotations__
print('State fields OK')
"
```

**Step 2: Term resolver end-to-end test (test query)**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms_structured

# Hatalı SQL üreten sorgu
q = 'Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori nedir?'
r = resolve_terms_structured(q)

print('term_filters:', r.term_filters)
print('hints:', r.hints_text)
print()

# Kontroller
tf_cols = [f['column'] for f in r.term_filters]
assert 'IsTableActive' in tf_cols, 'IsTableActive eksik!'
ita = next(f for f in r.term_filters if f['column'] == 'IsTableActive')
assert ita['value'] == '0', f'IsTableActive=0 olmalı, got {ita[\"value\"]}'
assert 'CategoryName' in r.hints_text, 'CategoryName hint eksik!'
assert 'RowAmount' in r.hints_text, 'RowAmount hint eksik!'
print('All term resolver checks PASS')
"
```

**Step 3: sql_generator term_filter override testi**

```bash
python -c "
import asyncio
from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_generator_node
from datetime import date

node = create_sql_generator_node('MasterReportDocumentTable')
state = {
    'query_schema': {
        'description': 'test',
        'select_columns': [],
        'filters': [
            # LLM yanlış üretmiş: IsTableActive=1
            {'column': 'IsTableActive', 'operator': '=', 'value': '1', 'logical_operator': 'AND'},
            # LLM doğru tarihi üretmiş
            {'column': 'DocumentDate', 'operator': '>=', 'date_descriptor': {'type': 'relative', 'unit': 'year', 'amount': -1}, 'logical_operator': 'AND'},
        ],
        'aggregations': [{'function': 'SUM', 'column': 'RowAmount', 'alias': 'ToplamCiro'}],
        'group_by': ['CategoryName'],
        'order_by_column': 'ToplamCiro',
        'order_by_direction': 'DESC',
        'limit': 1,
    },
    'auto_rules': [{'id': 'iade_dusulmus', 'sql': {
        'aggregation': 'SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)',
        'filter': None, 'group_by': None
    }, 'is_default': True}],
    # term_filters: IsTableActive=0 (Python garantili, LLM'i override eder)
    'term_filters': [{'column': 'IsTableActive', 'operator': '=', 'value': '0', 'logical_operator': 'AND'}],
}
result = asyncio.run(node(state))
sql = result['sql_queries'][0]
print(sql)
print()
assert '[IsTableActive] = 0' in sql, 'IsTableActive=0 yok!'
assert '[IsTableActive] = 1' not in sql, 'Yanlış LLM filtresi hala var!'
assert 'CASE WHEN' in sql, 'Business rule uygulanmadı!'
assert 'DATEADD(YEAR' in sql, 'Tarih filtresi yok!'
print('PASS')
"
```

Beklenen SQL:
```sql
SELECT TOP 1 [CategoryName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-24')
  AND [IsTableActive] = 0
GROUP BY [CategoryName]
ORDER BY [ToplamCiro] DESC
PASS
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(text2sql): term resolver architecture complete — Python-guaranteed term filters, LLM advisory hints, ambiguous interrupt support"
```
