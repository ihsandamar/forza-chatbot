# Multi-Turn Conversation Accuracy Design

**Tarih:** 2026-04-27  
**Durum:** Draft — Düzeltildi

---

## Sorun Özeti

Multi-turn konuşmalarda 3 kategori accuracy hatası:

| # | Hata | Örnek |
|---|---|---|
| A | MODIFY_QUERY'de filtreler düşüyor | Kategori filtrelenmiş SQL → "tarihe göre sırala" → kategori WHERE'den kayboluyor |
| B | Zamir referansları çözülemiyor | "bu ürün için detay", "bunu aylık kır" → yanlış entity veya boş |
| C | Granularity-only sorgu crash'e yol açıyor | "bunu gün bazında kır" → `raw_text="gün"` → `date_parser` crash |

**Root Cause:** Sistem context'i var (`active_sql`, `active_results`, `active_filters`) ama bunları LLM'e iletmiyor ya da LLM'in çıktısını deterministik olarak uygulamıyor.

---

## Mimari Prensip

```
LLM'in işi:   Konuşmanın semantiğini anlamak — ne değişsin, kim "bu ürün", hangi filtre korunmalı
Python'ın işi: LLM çıktısını active_sql'e deterministik uygulamak — SQL parsing değil struct→SQL
```

---

## Katman Bağımlılıkları ve Uygulama Sırası

```
K1 (Crash fix)   → Bağımsız. İlk implement edilir.
K2 (Delta SQL)   → Bağımsız. K1 ile eş zamanlı başlanabilir.
K3 (Context)     → context_builder.py K2'den bağımsız.
                   modify_sql_node ve semantic_extractor_node değişiklikleri
                   K2 + K3 birlikte tek commit'te yapılmalı (KeyError riski).
```

**Önerilen sıra:** K1 → K2 (sql_delta.py + model) → K3 (context_builder) → K2+K3 birleşik node commit

---

## Katman 1 — Prompt Düzeltmesi + Schema Builder Guard (Crash Elimination)

### Sorun

`semantic_extractor_node` LLM'i "bunu gün bazında kır" için şu çıktıyı üretiyor:
```python
time: {raw_text: "gün", breakdown: True, granularity: "daily"}
```
`date_parser.parse_semantic_time("gün")` → 6 regex pattern'a uymaz → `SemanticExtractionError` → `SchemaBuilderError("DATE_PARSE_ERROR")` → pipeline crash.

### Çözüm: İki Noktalı Fix

**1a. `SEMANTIC_EXTRACTOR_PROMPT` güncelleme** (`text2sql/prompts.py`)

`time.raw_text` için yeni kural ekle (mevcut `time` kurallarının hemen ardına):

```
## time.raw_text KURALI (KRİTİK)
raw_text YALNIZCA date_parser'ın çözebileceği bir tarih aralığı ifadesi olmalıdır.
Granularity kelimesi ("gün", "ay", "hafta", "yıl") tek başına raw_text OLAMAZ.

DOĞRU:
  "bunu gün bazında kır"          → time: {raw_text: null, breakdown: true,  granularity: "daily"}
  "bunu aylık göster"             → time: {raw_text: null, breakdown: true,  granularity: "monthly"}
  "son 1 yılda aylık karşılaştır" → time: {raw_text: "son 1 yılda", breakdown: true, granularity: "monthly"}
  "son 3 ayda satışlar"           → time: {raw_text: "son 3 ayda", breakdown: false, granularity: null}

YANLIŞ:
  "bunu gün bazında kır" → time: {raw_text: "gün", ...}   ← CRASH YARATIR, YAPMA
  "aylık göster"         → time: {raw_text: "aylık", ...}  ← CRASH YARATIR, YAPMA

Kural: Sorguda açık bir tarih aralığı yoksa → raw_text: null
```

**1b. `schema_builder.py` guard** (`schema_builder.py:162-202`)

Mevcut kod:
```python
if intent.time is not None:
    effective_st = intent.time
    if time_breakdown and not intent.time.breakdown:
        ...  # SemanticTime patch
    try:
        date_descriptor, gran = parse_semantic_time(effective_st, today)
    except SemanticExtractionError as exc:
        raise SchemaBuilderError(...) from exc
```

Güncelleme — `parse_semantic_time` çağrısını `if/else` ile sar:
```python
if intent.time is not None:
    effective_st = intent.time
    if time_breakdown and not intent.time.breakdown:
        ...  # SemanticTime patch — değişmez

    if not effective_st.raw_text:              # ← YENİ GUARD
        date_descriptor = None
        gran = effective_st.granularity        # sadece granularity al
    else:
        try:
            date_descriptor, gran = parse_semantic_time(effective_st, today)
        except SemanticExtractionError as exc:
            raise SchemaBuilderError(...) from exc
    # Aşağısı değişmez: if date_descriptor is not None: filters.append(...)
```

**✅ `date_descriptor = None` güvenli:** `schema_builder.py:182` zaten `if date_descriptor is not None:` kontrolü yapıyor.

### Ne Değişmez

`date_parser.py` değişmez — gelen input'un doğru olduğu varsayımı korunur.

---

## Katman 2 — Delta-Based SQL Modification

### Sorun

Şu an `modify_sql_node`:
```
LLM input:  active_sql (tam SQL string) + modification_request
LLM output: modified_sql (tam SQL string) → filtreler düşebiliyor
```

LLM'in SQL'i **yeniden yazmak** yerine **ne değişsin** demesi yeterli — SQL uygulaması Python'ın işi.

### Model Migration: `SqlModificationResult` → `SqlDelta`

**Mevcut model** (`src/graphs/report_agent/prompts.py:58-64`):
```python
class SqlModificationResult(BaseModel):
    modified_sql: str
    explanation: str
    confidence: float
    modification_hints: List[ModificationHint] = []
```

**`SqlModificationResult` silinir.** `ModificationHint` modeli korunur (value_resolver_node okur).

**Yeni modeller** (`src/graphs/report_agent/prompts.py`'e eklenir):
```python
class FilterDelta(BaseModel):
    column: str       # DB kolon adı: "BranchName", "CategoryName", "DocumentDate"
    operator: Literal["=", "!=", "LIKE", "NOT LIKE", ">", "<", ">=", "<=", "BETWEEN"]
    value: str        # SQL-ready değer: "'Ankara'", "'2024-01-01'", "DATEADD(month,-1,GETDATE())"

class SqlDelta(BaseModel):
    add_filters:           List[FilterDelta] = []   # WHERE'e eklenecek yeni koşullar
    remove_filter_columns: List[str] = []            # WHERE'den çıkarılacak kolon adları
    change_limit:          Optional[int] = None      # TOP N değişikliği
    change_orderby:        Optional[str] = None      # "RowAmount DESC"
    change_groupby:        Optional[str] = None      # "BranchName, CategoryName"
    change_select:         Optional[str] = None      # Tam yeni SELECT kolonu listesi
    explanation:           str
    confidence:            float   # < 0.5 → mevcut interrupt mekanizması tetiklenir
```

**Blast radius:** 1 tanım (prompts.py:58-64), 1 import (nodes.py:13), 1 kullanım (modify_sql_node ~90 satır), 1 test dosyası (test_modify_sql_results_context.py).

**⚠️ `modification_hints` KALDIRILMAZ — türetilir:**
`value_resolver_node` (`text2sql/nodes.py:676-750`) bu field'ı okur; kaldırmak resolver'ı kırar.

`modify_sql_node` `SqlDelta`'dan türetir:
```python
modification_hints = [
    {"column": f.column, "embedded_value": f.value.strip("'")}
    for f in delta.add_filters
    if f.operator == "="
]
return {
    "pre_built_sql": modified_sql,
    "modification_hints": modification_hints,
}
```

### Python SQL Delta Applicator

`src/graphs/report_agent/subagents/text2sql/sql_delta.py` (yeni dosya):

```python
import re
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.graphs.report_agent.prompts import FilterDelta, SqlDelta


class SqlDeltaApplicator:
    """
    LLM'den gelen SqlDelta'yı active_sql'e deterministik uygular.
    SQL string manipülasyonu yapar, validation yapmaz — input doğru varsayılır.
    """

    # Mevcut modify_sql_node post-processing korunur (DocumentDate güvenlik kuralı)
    _DATE_CAST_RE = re.compile(
        r"\[DocumentDate\]\s*(>=?|<=?|=)\s*'([^']+)'",
        re.IGNORECASE,
    )

    def apply(self, original_sql: str, delta: "SqlDelta") -> str:
        sql = original_sql
        if delta.remove_filter_columns:
            sql = self._remove_filters(sql, delta.remove_filter_columns)
        if delta.add_filters:
            sql = self._add_filters(sql, delta.add_filters)
        if delta.change_select is not None:
            sql = self._change_select(sql, delta.change_select)
        if delta.change_limit is not None:
            sql = self._change_limit(sql, delta.change_limit)
        if delta.change_groupby is not None:
            sql = self._change_groupby(sql, delta.change_groupby)
        if delta.change_orderby is not None:
            sql = self._change_orderby(sql, delta.change_orderby)
        sql = self._ensure_date_cast(sql)   # her zaman son adım
        return sql

    def _add_filters(self, sql: str, filters: list["FilterDelta"]) -> str:
        """WHERE varsa AND ekler; yoksa ORDER BY / GROUP BY öncesine WHERE ekler."""
        new_clause = " AND ".join(f"[{f.column}] {f.operator} {f.value}" for f in filters)
        tail_re = re.compile(r"\b(ORDER\s+BY|GROUP\s+BY|HAVING)\b", re.IGNORECASE)
        tail_match = tail_re.search(sql)
        insert_pos = tail_match.start() if tail_match else len(sql)

        if re.search(r"\bWHERE\b", sql, re.IGNORECASE):
            return sql[:insert_pos].rstrip() + f" AND {new_clause} " + sql[insert_pos:]
        else:
            return sql[:insert_pos].rstrip() + f" WHERE {new_clause} " + sql[insert_pos:]

    def _remove_filters(self, sql: str, columns: list[str]) -> str:
        """WHERE koşulunu kolon adına göre kaldırır. AND/OR kenar durumlarını handle eder."""
        for col in columns:
            esc = re.escape(col)
            # Koşul pattern'i: isteğe bağlı CAST(...) + operatör + değer
            cond = (
                r"(?:CAST\s*\(\s*)?"
                rf"\[{esc}\][^)]*\)?"
                r"\s*(?:NOT\s+)?(?:LIKE|=|!=|>=|<=|>|<)\s*"
                r"(?:'[^']*'|[\w.(),-]+)"
            )
            # Case 1: ... AND {koşul} — ortada veya sonda
            sql = re.sub(r"\s+AND\s+" + cond, "", sql, flags=re.IGNORECASE)
            # Case 2: {koşul} AND ... — başta
            sql = re.sub(cond + r"\s+AND\s+", "", sql, flags=re.IGNORECASE)
            # Case 3: WHERE {koşul} — tek koşul kaldı, WHERE'i de temizle
            sql = re.sub(
                r"\bWHERE\s+" + cond + r"(?=\s+(?:ORDER|GROUP|HAVING)|\s*$)",
                "",
                sql,
                flags=re.IGNORECASE,
            )
        return sql.strip()

    def _change_limit(self, sql: str, n: int) -> str:
        return re.sub(r"\bTOP\s+\d+\b", f"TOP {n}", sql, flags=re.IGNORECASE)

    def _change_orderby(self, sql: str, orderby: str) -> str:
        return re.sub(
            r"\bORDER\s+BY\b.*$", f"ORDER BY {orderby}", sql, flags=re.IGNORECASE | re.DOTALL
        )

    def _change_groupby(self, sql: str, groupby: str) -> str:
        # GROUP BY ... — ORDER BY öncesine kadar değiştir
        return re.sub(
            r"\bGROUP\s+BY\b.*?(?=\s+(?:ORDER\s+BY|HAVING)|\s*$)",
            f"GROUP BY {groupby} ",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _change_select(self, sql: str, select_list: str) -> str:
        """SELECT [TOP N] <eski_kolonlar> FROM → SELECT [TOP N] <select_list> FROM."""
        def replacer(m: re.Match) -> str:
            top_clause = m.group(1) or ""
            return f"SELECT{top_clause} {select_list} FROM"

        return re.sub(
            r"\bSELECT\b(\s+TOP\s+\d+)?\s+.+?\s+\bFROM\b",
            replacer,
            sql,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _ensure_date_cast(self, sql: str) -> str:
        """DocumentDate karşılaştırmalarını CAST ile sarar — mevcut davranış korunur."""
        return self._DATE_CAST_RE.sub(
            r"CAST([DocumentDate] AS DATE) \1 CAST('\2' AS DATE)",
            sql,
        )
```

**`change_select` kullanım örneği — "bunu aylık kır":**
```python
# LLM SqlDelta çıktısı:
SqlDelta(
    change_select="DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS TotalAmount",
    change_groupby="DATEPART(month, [DocumentDate])",
    change_orderby="Month ASC",
    explanation="Aylık granularity için SELECT/GROUP BY/ORDER BY değişti",
    confidence=0.9,
)
# Python apply() sonucu:
# SELECT TOP 100 DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS TotalAmount
# FROM ... WHERE ...
# GROUP BY DATEPART(month, [DocumentDate])
# ORDER BY Month ASC
```

### modify_sql_node Yeni Akışı

```
modify_sql_node:
  1. build_query_context_summary(active_results, active_filters) → context_str  [Python, K3]
  2. LLM(SQL_MODIFIER_PROMPT, structured=SqlDelta) → delta                       [LLM]
  3. if delta.confidence < 0.5: interrupt (mevcut davranış korunur)
  4. SqlDeltaApplicator().apply(active_sql, delta) → modified_sql                [Python]
  5. modification_hints = derive_hints(delta.add_filters)                         [Python]
  6. return {"pre_built_sql": modified_sql, "modification_hints": modification_hints}
```

**Kaldırılan:** LLM'in full SQL üretmesi, mevcut DocumentDate CAST regex post-processing
(artık `SqlDeltaApplicator._ensure_date_cast` içinde).

### SQL_MODIFIER_PROMPT Değişikliği

Full SQL döndürme talimatı kaldırılır. Mevcut `{active_results}` placeholder'ı `{query_context}` olur.

```
## GÖREV
Kullanıcının isteğini anlayıp SADECE ne değişmesi gerektiğini SqlDelta formatında döndür.
SQL yazmana gerek yok — değişiklikleri struct olarak belirt, Python uygulayacak.

## AKTİF SQL
{active_sql}

## AKTİF BAĞLAM
{query_context}

Aktif filtreler zaten SQL'de var — bunları add_filters'a EKLEME.
Sadece kullanıcının talep ettiği YENİ değişiklikleri yaz.

## KOLON METAVERİSİ
{column_metadata}

## KULLANICI İSTEĞİ
{modification_request}
```

**⚠️ Atomik değişiklik:** `SQL_MODIFIER_PROMPT`'ta `{active_results}` → `{query_context}` yeniden adlandırması ve `modify_sql_node`'daki `.format()` güncellemesi **aynı commit'te** yapılmalı — aksi hâlde `KeyError`.

---

## Katman 3 — Context Injection: LLM Referansları Görerek Anlasın

### Sorun

`semantic_extractor_node` ve `modify_sql_node` LLM'leri şu an görmüyor:
- `active_results`: önceki sorguda hangi değerler döndü (`Optional[List[Dict[str, Any]]]`)
- `active_filters`: şu an hangi filtreler aktif (`Optional[List[Dict[str, Any]]]`, her dict `field`+`value` key'leri içerir)

Bu olmadan "bu ürün", "bunu", "bu şube" referansları çözülemiyor.

### Python Context Builder

`src/graphs/report_agent/context_builder.py` (yeni dosya):

```python
def build_query_context_summary(
    active_results: list[dict] | None,
    active_filters: list[dict] | None,
    max_rows: int = 10,
    max_values_per_col: int = 5,
) -> str:
    """
    active_results + active_filters → LLM-readable context string.
    Yeni LLM çağrısı yok — pure Python, deterministik.
    Sayısal değerler ve None'lar dahil edilmez — LLM yalnızca entity değerleri görür.
    """
    parts = []

    if active_filters:
        filter_strs = [
            f"{f['field']} = '{f['value']}'"
            for f in active_filters
            if f.get("field") and f.get("value")
        ]
        if filter_strs:
            parts.append(f"Aktif filtreler: {', '.join(filter_strs)}")

    if active_results:
        col_values: dict[str, list] = {}
        for row in active_results[:max_rows]:
            for col, val in row.items():
                if isinstance(val, str) and val:
                    col_values.setdefault(col, [])
                    if val not in col_values[col]:
                        col_values[col].append(val)

        entity_lines = [
            f"  - {col}: {vals[:max_values_per_col]}"
            for col, vals in col_values.items()
        ]
        if entity_lines:
            parts.append("Önceki sonuçlardaki değerler:\n" + "\n".join(entity_lines))

    return "\n".join(parts) if parts else "Önceki bağlam yok."
```

### Injection Noktaları

**`semantic_extractor_node`** (`text2sql/nodes.py`) — SEMANTIC_EXTRACTOR_PROMPT'a yeni bölüm:

```
## ÖNCEKİ SORGU BAĞLAMI
{query_context}

Kullanıcı "bu ürün", "bu şube", "bunu", "şunu" gibi referans kullanıyorsa →
yukarıdaki değerlerden en uygununu seç, direkt isme çevir.

Örnek: "bu ürün için detay" + bağlamda ProductName: ["Latte", "Espresso"]
→ entity: {raw_text: "Latte", entity_type: "filter_value", column_hint: "ProductName"}
```

**`semantic_extractor_node` node güncellemesi** (`text2sql/nodes.py:1377-1383`):
```python
query_context = build_query_context_summary(
    state.get("active_results"),
    state.get("active_filters"),
)
prompt = SEMANTIC_EXTRACTOR_PROMPT.format(
    user_query=user_query,
    query_type=query_type,
    column_names=column_names,
    conversation_context=conversation_context,
    sql_error=sql_error,
    query_context=query_context,    # YENİ
)
```

**`modify_sql_node` node güncellemesi** (`nodes.py`):
```python
query_context = build_query_context_summary(
    state.get("active_results"),
    state.get("active_filters"),
)
prompt = SQL_MODIFIER_PROMPT.format(
    active_sql=active_sql,
    query_context=query_context,        # {active_results} raw JSON'ın yerine
    column_metadata=column_metadata,
    modification_request=user_query,
)
```

---

## Test Stratejisi

### Yeni test dosyaları

**`tests/unit/text2sql/test_sql_delta_applicator.py`**

```python
from src.graphs.report_agent.subagents.text2sql.sql_delta import SqlDeltaApplicator
from src.graphs.report_agent.prompts import FilterDelta, SqlDelta

BASE_SQL = (
    "SELECT TOP 10 [BranchName], SUM([RowAmount]) AS Total "
    "FROM [MasterReportDocumentTable] "
    "WHERE [CategoryName] = 'Kahve' "
    "ORDER BY Total DESC"
)

def test_add_filter_appends_to_existing_where():
    delta = SqlDelta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")], explanation="", confidence=0.9)
    result = SqlDeltaApplicator().apply(BASE_SQL, delta)
    assert "[CategoryName] = 'Kahve'" in result
    assert "[BranchName] = 'Ankara'" in result

def test_add_filter_creates_where_when_absent():
    sql = "SELECT TOP 10 [BranchName] FROM [MasterReportDocumentTable] ORDER BY [BranchName]"
    delta = SqlDelta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")], explanation="", confidence=0.9)
    result = SqlDeltaApplicator().apply(sql, delta)
    assert "WHERE [BranchName] = 'Ankara'" in result
    assert result.index("WHERE") < result.index("ORDER BY")

def test_add_filter_inserts_before_order_by():
    delta = SqlDelta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'İzmir'")], explanation="", confidence=0.9)
    result = SqlDeltaApplicator().apply(BASE_SQL, delta)
    assert result.index("AND [BranchName]") < result.index("ORDER BY")

def test_remove_filter_middle_condition():
    sql = "SELECT TOP 5 * FROM T WHERE [A] = '1' AND [B] = '2' AND [C] = '3'"
    result = SqlDeltaApplicator().apply(sql, SqlDelta(remove_filter_columns=["B"], explanation="", confidence=0.9))
    assert "[B]" not in result
    assert "[A] = '1'" in result
    assert "[C] = '3'" in result

def test_remove_filter_first_condition():
    sql = "SELECT * FROM T WHERE [CategoryName] = 'Kahve' AND [BranchName] = 'Ankara' ORDER BY x"
    result = SqlDeltaApplicator().apply(sql, SqlDelta(remove_filter_columns=["CategoryName"], explanation="", confidence=0.9))
    assert "[CategoryName]" not in result
    assert "[BranchName] = 'Ankara'" in result

def test_remove_filter_only_condition_removes_where():
    sql = "SELECT * FROM T WHERE [CategoryName] = 'Kahve' ORDER BY x"
    result = SqlDeltaApplicator().apply(sql, SqlDelta(remove_filter_columns=["CategoryName"], explanation="", confidence=0.9))
    assert "WHERE" not in result
    assert "ORDER BY" in result

def test_change_limit():
    result = SqlDeltaApplicator().apply(BASE_SQL, SqlDelta(change_limit=50, explanation="", confidence=0.9))
    assert "TOP 50" in result
    assert "TOP 10" not in result

def test_change_orderby():
    result = SqlDeltaApplicator().apply(BASE_SQL, SqlDelta(change_orderby="Total ASC", explanation="", confidence=0.9))
    assert "ORDER BY Total ASC" in result
    assert "ORDER BY Total DESC" not in result

def test_change_groupby():
    sql = "SELECT [BranchName], SUM([RowAmount]) FROM T GROUP BY [BranchName] ORDER BY 1"
    result = SqlDeltaApplicator().apply(sql, SqlDelta(change_groupby="[BranchName], [CategoryName]", explanation="", confidence=0.9))
    assert "GROUP BY [BranchName], [CategoryName]" in result

def test_change_select_preserves_top_n():
    result = SqlDeltaApplicator().apply(
        BASE_SQL,
        SqlDelta(change_select="DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS Total", explanation="", confidence=0.9),
    )
    assert "TOP 10" in result
    assert "DATEPART(month, [DocumentDate]) AS Month" in result
    assert "FROM [MasterReportDocumentTable]" in result

def test_ensure_date_cast_on_add_filter():
    sql = "SELECT * FROM T WHERE [DocumentDate] >= '2024-01-01'"
    result = SqlDeltaApplicator().apply(sql, SqlDelta(explanation="", confidence=0.9))
    assert "CAST([DocumentDate] AS DATE)" in result
```

**`tests/unit/report/test_context_builder.py`**

```python
from src.graphs.report_agent.context_builder import build_query_context_summary

def test_empty_inputs_return_default_message():
    assert build_query_context_summary(None, None) == "Önceki bağlam yok."

def test_filters_appear_in_output():
    result = build_query_context_summary(None, [{"field": "CategoryName", "value": "Kahve"}])
    assert "CategoryName = 'Kahve'" in result

def test_string_values_from_results_appear():
    rows = [{"ProductName": "Latte"}, {"ProductName": "Espresso"}]
    result = build_query_context_summary(rows, None)
    assert "Latte" in result
    assert "Espresso" in result

def test_numeric_values_excluded():
    rows = [{"ProductName": "Latte", "RowAmount": 100.0}]
    result = build_query_context_summary(rows, None)
    assert "100" not in result
    assert "Latte" in result

def test_deduplicates_values():
    rows = [{"ProductName": "Latte"}, {"ProductName": "Latte"}, {"ProductName": "Latte"}]
    result = build_query_context_summary(rows, None)
    assert result.count("Latte") == 1

def test_max_rows_respected():
    rows = [{"Col": f"Val{i}"} for i in range(20)]
    result = build_query_context_summary(rows, None, max_rows=3)
    assert "Val3" not in result   # 4th row excluded
    assert "Val0" in result
```

### Güncellenmesi gereken mevcut testler

| Dosya | Güncelleme |
|---|---|
| `tests/graphs/report/test_modify_sql_results_context.py` | `SqlModificationResult` → `SqlDelta`; mock LLM structured output'u güncelle |
| `tests/unit/text2sql/test_schema_builder.py` | `raw_text=None` + `granularity="daily"` → crash yok, `date_descriptor=None` testi ekle |
| `tests/unit/text2sql/test_semantic_extractor_node.py` | `query_context` format parametresi `SEMANTIC_EXTRACTOR_PROMPT`'a eklendi — mevcut `.format()` çağrısını güncelle |

---

## Değişen / Eklenen Dosyalar

| Dosya | İşlem | Katman |
|---|---|---|
| `src/graphs/report_agent/context_builder.py` | **Yeni** | K3 |
| `src/graphs/report_agent/subagents/text2sql/sql_delta.py` | **Yeni** | K2 |
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | Güncelle — `time.raw_text` kuralı eklenir | K1 |
| `src/graphs/report_agent/subagents/text2sql/schema_builder.py` | Güncelle — null guard (5 satır) | K1 |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | Güncelle — `semantic_extractor_node` + `{query_context}` | K3 |
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | Güncelle — `SEMANTIC_EXTRACTOR_PROMPT` yeni bölüm | K3 |
| `src/graphs/report_agent/prompts.py` | Güncelle — `SqlModificationResult` sil, `FilterDelta` + `SqlDelta` ekle | K2 |
| `src/graphs/report_agent/nodes.py` | Güncelle — `modify_sql_node` delta flow + K3 inject | K2 + K3 |

**Değişmeyen dosyalar:** `date_parser.py`, `state.py`, graph routing, `sql_generator_node`, `value_resolver_node`

---

## Scope Dışı (Bu Spec'te Yok)

- Intent classification accuracy (ayrı konu)
- Fuzzy matching threshold değişikliği
- Retry sayısı artırma
- `active_filters` veri yapısı değişikliği
- Frontend / API katmanı

---

## Başarı Kriterleri

1. "bunu gün bazında kır" → crash yok, `time.raw_text=null` → mevcut date range korunur
2. "kategoriye filtrele → tarihe göre sırala" → kategori WHERE koşulu modified_sql'de kalır
3. "bu ürün için detay" → `active_results`'taki ilk ürün adı entity olarak çözülür
4. Mevcut testler kırılmaz
5. `test_sql_delta_applicator.py` 11 test → tamamı yeşil
6. `test_context_builder.py` 6 test → tamamı yeşil
