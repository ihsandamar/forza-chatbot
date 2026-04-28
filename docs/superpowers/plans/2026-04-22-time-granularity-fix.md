# Time Granularity Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Aylık karşılaştır" gibi açık granülaritenin `time_granularity="monthly"` olarak QuerySchema'ya ulaşmasını garantile; şu an "yearly" (period biriminden türetilen) geliyor.

**Architecture:** İki katmanlı çözüm — (1) LLM katmanı: `SemanticTime`'a `granularity` alanı eklenir ve `SEMANTIC_EXTRACTOR_PROMPT`'a kural eklenir, böylece LLM "aylık" kelimesini `granularity="monthly"` olarak kodlar; (2) Python fallback katmanı: `schema_builder` `intent.raw_query`'yi tarar ve `_GRANULARITY_KEYWORDS` dict ile LLM'nin kaçırdığı granülaritenin üstüne yazar. `parse_semantic_time`, `st.granularity` varsa period-birim derivasyonunu atlar.

**Tech Stack:** Python, Pydantic, regex, pytest

---

## Dosya Haritası

| Dosya | Değişiklik |
|---|---|
| `src/graphs/report_agent/subagents/text2sql/semantic_models.py` | `SemanticTime`'a `granularity` alanı ekle (1 satır) |
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | `SEMANTIC_EXTRACTOR_PROMPT`'a `## time.granularity KURALI` bölümü ekle |
| `src/graphs/report_agent/subagents/text2sql/date_parser.py` | `_GRANULARITY_KEYWORDS` + `detect_granularity_from_query()` ekle; `parse_semantic_time` st.granularity'yi önceliklendir |
| `src/graphs/report_agent/subagents/text2sql/schema_builder.py` | time_breakdown override'ında granularity koru; Python fallback bloğu ekle |
| `tests/unit/text2sql/test_date_parser.py` | Granularity öncelik testleri ekle |
| `tests/unit/text2sql/test_schema_builder.py` | Python keyword fallback end-to-end testi ekle |
| `tests/unit/text2sql/test_semantic_extractor_node.py` | Prompt granularity kural testi ekle |

---

### Task 1: `SemanticTime.granularity` alanı + `SEMANTIC_EXTRACTOR_PROMPT` kuralı

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/semantic_models.py:20-22`
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:801-803`
- Test: `tests/unit/text2sql/test_semantic_extractor_node.py`

- [ ] **Step 1: Başarısız testi yaz**

`tests/unit/text2sql/test_semantic_extractor_node.py` dosyasına ekle:

```python
def test_semantic_time_accepts_granularity_field():
    """SemanticTime granularity alanını kabul etmeli."""
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 1 senede", breakdown=True, granularity="monthly")
    assert st.granularity == "monthly"


def test_semantic_time_granularity_defaults_to_none():
    """granularity verilmezse None olmalı (backward compat)."""
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 3 ay", breakdown=False)
    assert st.granularity is None


def test_prompt_contains_granularity_rule():
    """SEMANTIC_EXTRACTOR_PROMPT, 'aylık' → 'monthly' kuralını içermeli."""
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    prompt_lower = SEMANTIC_EXTRACTOR_PROMPT.lower()
    assert "granularity" in prompt_lower
    assert "monthly" in prompt_lower
    assert "weekly" in prompt_lower
    assert "aylık" in prompt_lower
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
python -m pytest tests/unit/text2sql/test_semantic_extractor_node.py::test_semantic_time_accepts_granularity_field tests/unit/text2sql/test_semantic_extractor_node.py::test_semantic_time_granularity_defaults_to_none tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_contains_granularity_rule -v
```

Beklenen: FAIL (`granularity` alanı yok, prompt'ta granularity kural yok)

- [ ] **Step 3: `SemanticTime`'a `granularity` alanı ekle**

`src/graphs/report_agent/subagents/text2sql/semantic_models.py` dosyasında:

Mevcut (satır 20-22):
```python
class SemanticTime(BaseModel):
    raw_text: str
    breakdown: bool  # True = GROUP BY kırılımı, False = WHERE filtresi
```

Yeni:
```python
class SemanticTime(BaseModel):
    raw_text: str
    breakdown: bool  # True = GROUP BY kırılımı, False = WHERE filtresi
    granularity: Optional[Literal[
        "monthly", "weekly", "daily", "yearly", "hourly",
        "hour_of_day", "day_of_week", "day_of_month",
    ]] = None  # LLM tarafından doldurulur ("aylık" → "monthly" vb.)
```

`from typing import` satırında `Literal` ve `Optional` zaten import edilmiş durumda — eklenmesi gerekmez. Kontrol et:
```bash
grep "^from typing import\|^import " src/graphs/report_agent/subagents/text2sql/semantic_models.py
```
Eğer `Literal` veya `Optional` eksikse ekle.

- [ ] **Step 4: `SEMANTIC_EXTRACTOR_PROMPT`'a granularity kuralı ekle**

`src/graphs/report_agent/subagents/text2sql/prompts.py` dosyasında:

Mevcut (satır 801-803):
```python
## time.breakdown KURALI
- **True** — Zaman KIRILIMı isteniyor: "aylık", "haftalık", "günlük", "yıllık" kırılım
- **False** — Sadece zaman FİLTRESİ: "son 3 ay", "bu yıl", "2024", "ocak 2024"
```

Yeni (aynı satırları şununla değiştir):
```python
## time.breakdown KURALI
- **True** — Zaman KIRILIMı isteniyor: "aylık", "haftalık", "günlük", "yıllık" kırılım
- **False** — Sadece zaman FİLTRESİ: "son 3 ay", "bu yıl", "2024", "ocak 2024"

## time.granularity KURALI (breakdown=True ise doldur, aksi halde null)
- "aylık", "her ay", "ay bazında", "aylık olarak"    → granularity: "monthly"
- "haftalık", "her hafta", "hafta bazında"            → granularity: "weekly"
- "günlük", "her gün", "gün bazında"                  → granularity: "daily"
- "yıllık", "her yıl", "yıl bazında"                  → granularity: "yearly"
- "saatlik", "saat bazında"                           → granularity: "hourly"
- "haftanın günlerine göre"                           → granularity: "day_of_week"
- "ayın günlerine göre"                               → granularity: "day_of_month"
- Açık granülarite kelimesi yoksa                     → granularity: null

**Örnekler:**
  "son 1 yılda aylık karşılaştır" → time: {raw_text: "son 1 yılda", breakdown: true, granularity: "monthly"}
  "son 3 ayda haftalık trend"     → time: {raw_text: "son 3 ayda", breakdown: true, granularity: "weekly"}
  "son 6 ayda satışlar"           → time: {raw_text: "son 6 ayda", breakdown: false, granularity: null}
```

- [ ] **Step 5: Testleri çalıştır — geçtiğini doğrula**

```
python -m pytest tests/unit/text2sql/test_semantic_extractor_node.py::test_semantic_time_accepts_granularity_field tests/unit/text2sql/test_semantic_extractor_node.py::test_semantic_time_granularity_defaults_to_none tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_contains_granularity_rule -v
```

Beklenen: 3 PASS

- [ ] **Step 6: Tüm text2sql testlerini çalıştır — regresyon yok**

```
python -m pytest tests/unit/text2sql/ -v --tb=short
```

Beklenen: Tümü PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/semantic_models.py src/graphs/report_agent/subagents/text2sql/prompts.py tests/unit/text2sql/test_semantic_extractor_node.py
git commit -m "feat(nlu): add SemanticTime.granularity field + SEMANTIC_EXTRACTOR_PROMPT rule"
```

---

### Task 2: `parse_semantic_time` `st.granularity`'yi önceliklendir + `schema_builder` override'ını koru

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/date_parser.py:52-130`
- Modify: `src/graphs/report_agent/subagents/text2sql/schema_builder.py:156-168`
- Test: `tests/unit/text2sql/test_date_parser.py`

**Neden:** `parse_semantic_time` şu an sadece `_GRAN_MAP.get(unit)` kullanıyor (period birimi → granülaritenin). "son 1 senede" → "yearly". `st.granularity="monthly"` varsa bunu öncelikli kullanmalı. Ayrıca `schema_builder`'daki `time_breakdown` override bloğu yeni `SemanticTime` oluştururken `granularity`'yi kopyalamalı.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/unit/text2sql/test_date_parser.py` dosyasına ekle:

```python
def test_granularity_field_overrides_period_unit():
    """st.granularity verilmişse period biriminden türetilen değer ezilmeli."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    # "son 1 senede" normalde yearly üretir — ama granularity="monthly" → monthly
    st = SemanticTime(raw_text="son 1 senede", breakdown=True, granularity="monthly")
    _, gran = parse_semantic_time(st, date(2026, 4, 22))
    assert gran == "monthly"


def test_granularity_field_overrides_for_gecen_yil():
    """'geçen yıl' normalde yearly — granularity='weekly' ile ezilmeli."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="geçen yıl", breakdown=True, granularity="weekly")
    _, gran = parse_semantic_time(st, date(2026, 4, 22))
    assert gran == "weekly"


def test_granularity_none_falls_back_to_period_unit():
    """granularity=None olduğunda mevcut period-birim davranışı korunmalı."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 1 senede", breakdown=True, granularity=None)
    _, gran = parse_semantic_time(st, date(2026, 4, 22))
    assert gran == "yearly"  # eski davranış korundu
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
python -m pytest tests/unit/text2sql/test_date_parser.py::test_granularity_field_overrides_period_unit tests/unit/text2sql/test_date_parser.py::test_granularity_field_overrides_for_gecen_yil -v
```

Beklenen: FAIL

- [ ] **Step 3: `parse_semantic_time`'da her `if st.breakdown:` bloğunu güncelle**

`src/graphs/report_agent/subagents/text2sql/date_parser.py` dosyasında:

Her `if st.breakdown: gran = _GRAN_MAP.get(unit)` satırını şununla değiştir:

```python
if st.breakdown:
    gran = st.granularity or _GRAN_MAP.get(unit)
```

Değiştirmen gereken yerler (satır 76-77, 85-86, 94-95, 111):

**Satır 76-77** (mevcut):
```python
        if st.breakdown:
            gran = _GRAN_MAP.get(unit)
```
Yeni:
```python
        if st.breakdown:
            gran = st.granularity or _GRAN_MAP.get(unit)
```

**Satır 85-86** (mevcut — `geçen yıl/ay` bloğu):
```python
        if st.breakdown:
            gran = _GRAN_MAP.get(unit)
```
Yeni:
```python
        if st.breakdown:
            gran = st.granularity or _GRAN_MAP.get(unit)
```

**Satır 94-95** (mevcut — `bu yıl/ay/gün/çeyrek` bloğu):
```python
        if st.breakdown:
            gran = _GRAN_MAP.get(period_key)
```
Yeni:
```python
        if st.breakdown:
            gran = st.granularity or _GRAN_MAP.get(period_key)
```

**Satır 111** (mevcut — `[ay adı] YYYY` bloğu):
```python
            gran = "monthly" if st.breakdown else None
```
Yeni:
```python
            gran = (st.granularity or "monthly") if st.breakdown else None
```

- [ ] **Step 4: `schema_builder.py`'de granularity'yi koru**

`src/graphs/report_agent/subagents/text2sql/schema_builder.py` dosyasında time_breakdown override bloğunu bul (satır ~163-168):

Mevcut:
```python
        if time_breakdown and not intent.time.breakdown:
            from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
            effective_st = SemanticTime(
                raw_text=intent.time.raw_text,
                breakdown=True,
            )
```

Yeni:
```python
        if time_breakdown and not intent.time.breakdown:
            from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
            effective_st = SemanticTime(
                raw_text=intent.time.raw_text,
                breakdown=True,
                granularity=intent.time.granularity,  # LLM-extracted granularity'yi koru
            )
```

- [ ] **Step 5: Testleri çalıştır — geçtiğini doğrula**

```
python -m pytest tests/unit/text2sql/test_date_parser.py -v
```

Beklenen: Tümü PASS (eskiler dahil)

- [ ] **Step 6: Tüm suite çalıştır**

```
python -m pytest tests/unit/text2sql/ -v --tb=short
```

Beklenen: Tümü PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/date_parser.py src/graphs/report_agent/subagents/text2sql/schema_builder.py tests/unit/text2sql/test_date_parser.py
git commit -m "fix(nlu): parse_semantic_time prioritizes st.granularity over period-unit derivation"
```

---

### Task 3: Python keyword fallback — `detect_granularity_from_query()` + `schema_builder` override

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/date_parser.py` (yeni fonksiyon + dict)
- Modify: `src/graphs/report_agent/subagents/text2sql/schema_builder.py` (~satır 184)
- Test: `tests/unit/text2sql/test_schema_builder.py`

**Neden:** LLM `st.granularity` alanını doldurmayı kaçırsa bile `intent.raw_query`'de "aylık" hâlâ mevcuttur. Deterministik Python keyword tarama, LLM granularity'yi ezecek (explicit > implicit).

- [ ] **Step 1: Başarısız testi yaz**

`tests/unit/text2sql/test_schema_builder.py` dosyasına ekle:

```python
def test_keyword_fallback_overrides_period_unit_gran_in_schema():
    """
    LLM granularity=None bıraksa bile raw_query'de 'aylık' varsa
    QuerySchema.time_granularity='monthly' olmalı (yearly değil).
    """
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticTime, SemanticMetric,
    )
    intent = SemanticIntent(
        time=SemanticTime(raw_text="son 1 senede", breakdown=True, granularity=None),
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="son 1 senede espresso kategorisindeki satışları aylık karşılaştır",
    )
    term_resolution = {"ciro": {"column_name": "RowAmount", "filter_structured": None, "specificity": 1.0, "similarity": 1.0}}
    schema = build_query_schema(intent, term_resolution, "TIME_SERIES_COMPARISON", time_breakdown=True)
    assert schema.time_granularity == "monthly", (
        f"Expected 'monthly' (aylık in raw_query) but got '{schema.time_granularity}'"
    )


def test_keyword_fallback_haftalık():
    """'haftalık' → 'weekly' override."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticTime, SemanticMetric,
    )
    intent = SemanticIntent(
        time=SemanticTime(raw_text="son 3 ayda", breakdown=True, granularity=None),
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="son 3 ayda haftalık satış trendi",
    )
    term_resolution = {"ciro": {"column_name": "RowAmount", "filter_structured": None, "specificity": 1.0, "similarity": 1.0}}
    schema = build_query_schema(intent, term_resolution, "TIME_SERIES", time_breakdown=True)
    assert schema.time_granularity == "weekly"


def test_no_keyword_keeps_period_unit_gran():
    """Açık granülarite kelimesi yoksa period-birim davranışı korunmalı."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticTime, SemanticMetric,
    )
    intent = SemanticIntent(
        time=SemanticTime(raw_text="son 1 yılda", breakdown=True, granularity=None),
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="son 1 yılda satışlar",  # no granularity keyword
    )
    term_resolution = {"ciro": {"column_name": "RowAmount", "filter_structured": None, "specificity": 1.0, "similarity": 1.0}}
    schema = build_query_schema(intent, term_resolution, "TIME_SERIES", time_breakdown=True)
    assert schema.time_granularity == "yearly"  # period biriminden


def test_detect_granularity_from_query():
    """detect_granularity_from_query doğru keyword→gran eşleştirmesi yapmalı."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import detect_granularity_from_query
    assert detect_granularity_from_query("aylık karşılaştır") == "monthly"
    assert detect_granularity_from_query("haftalık trend") == "weekly"
    assert detect_granularity_from_query("günlük satış") == "daily"
    assert detect_granularity_from_query("yıllık büyüme") == "yearly"
    assert detect_granularity_from_query("toplam ciro") is None
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
python -m pytest tests/unit/text2sql/test_schema_builder.py::test_keyword_fallback_overrides_period_unit_gran_in_schema tests/unit/text2sql/test_schema_builder.py::test_detect_granularity_from_query -v
```

Beklenen: FAIL (`detect_granularity_from_query` yok, schema hâlâ "yearly" üretiyor)

- [ ] **Step 3: `date_parser.py`'e `_GRANULARITY_KEYWORDS` ve `detect_granularity_from_query()` ekle**

`src/graphs/report_agent/subagents/text2sql/date_parser.py` dosyasında `_GRAN_MAP` bloğundan HEMEN SONRA (satır 35'ten sonra) ekle:

```python
_GRANULARITY_KEYWORDS = {
    # Monthly
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


def detect_granularity_from_query(raw_query: str) -> Optional[str]:
    """Scan raw_query for explicit granularity keywords (longest match first)."""
    q = raw_query.lower()
    for keyword, gran in _GRANULARITY_KEYWORDS.items():
        if keyword in q:
            return gran
    return None
```

**Not:** `_GRANULARITY_KEYWORDS` dict'teki sıraya dikkat — uzun keyword'ler önce (örn. "ay bazında" > "aylık"). Dict Python 3.7+'da insertion-ordered.

- [ ] **Step 4: `schema_builder.py`'e Python fallback bloğunu ekle**

`src/graphs/report_agent/subagents/text2sql/schema_builder.py` dosyasındaki import bloğuna ekle:

```python
from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time, detect_granularity_from_query
```

(Mevcut import'u genişlet — `parse_semantic_time` zaten import edilmişse sadece `, detect_granularity_from_query` ekle)

Sonra `if gran is not None: time_granularity = gran` satırından SONRA (satır ~184) şunu ekle:

```python
        # Python keyword fallback: override gran when raw_query has explicit granularity keyword.
        # Runs when time_breakdown=True — explicit user keyword ("aylık") > period-unit derivation.
        if time_breakdown and intent.raw_query:
            keyword_gran = detect_granularity_from_query(intent.raw_query)
            if keyword_gran:
                gran = keyword_gran
                time_granularity = gran
```

Tam bağlam için `schema_builder.py` satır ~155-190 şöyle görünmeli:

```python
    if intent.time is not None:
        effective_st = intent.time
        if time_breakdown and not intent.time.breakdown:
            from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
            effective_st = SemanticTime(
                raw_text=intent.time.raw_text,
                breakdown=True,
                granularity=intent.time.granularity,
            )

        try:
            date_descriptor, gran = parse_semantic_time(effective_st, today)
        except SemanticExtractionError as exc:
            raise SchemaBuilderError(...) from exc

        if date_descriptor is not None:
            filters.append(SchemaFilter(...))

        if gran is not None:
            time_granularity = gran

        # Python keyword fallback — explicit keyword overrides period-unit derivation
        if time_breakdown and intent.raw_query:
            keyword_gran = detect_granularity_from_query(intent.raw_query)
            if keyword_gran:
                gran = keyword_gran
                time_granularity = gran
```

- [ ] **Step 5: Tüm yeni testleri çalıştır**

```
python -m pytest tests/unit/text2sql/test_schema_builder.py::test_keyword_fallback_overrides_period_unit_gran_in_schema tests/unit/text2sql/test_schema_builder.py::test_keyword_fallback_haftalık tests/unit/text2sql/test_schema_builder.py::test_no_keyword_keeps_period_unit_gran tests/unit/text2sql/test_schema_builder.py::test_detect_granularity_from_query -v
```

Beklenen: 4 PASS

- [ ] **Step 6: Tüm text2sql testlerini çalıştır**

```
python -m pytest tests/unit/text2sql/ -v --tb=short
```

Beklenen: Tümü PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/date_parser.py src/graphs/report_agent/subagents/text2sql/schema_builder.py tests/unit/text2sql/test_schema_builder.py
git commit -m "fix(nlu): add Python keyword fallback for time granularity in schema_builder"
```
