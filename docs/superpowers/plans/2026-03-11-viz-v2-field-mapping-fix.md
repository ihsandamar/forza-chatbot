# Visualization V2 — Field Mapping & Context Fix

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix visualization_v2 so multi-dimensional data (ProductName × Hafta × Yil × ToplamSatis) produces correctly grouped, multi-trace charts instead of a single unreadable zigzag line.

**Architecture:** Remove TIME_SERIES_COMPARISON from rule-based fast path so the LLM decides field mapping. Enrich the LLM prompt with conversation history (messages) and composite time column guidance. Add validator safety nets for series_field completion and composite time preprocessing. Fix data_analyzer time column granularity ranking.

**Tech Stack:** Python, LangGraph, Plotly, Pydantic, pandas

---

## Root Cause Chain (Bu Senaryoda)

```
SQL sonucu: [ProductName, Yil, Hafta, ToplamSatis] (406 satır, 20 ürün)
      ↓
data_analyzer: time_column = "Yil" (Hafta yerine — iteration order'a göre)
      ↓
rule-based fast path: TIME_SERIES_COMPARISON → line_chart, x/y/series = None
      ↓  ← LLM ASLA ÇAĞRILMIYOR
spec_validator: x_field="Yil", y_field="ToplamSatis", series_field=None
      ↓
_build_line(): tek trace, x=Yil (sadece 2025/2026), tüm ürünler tek çizgide
```

## 5 Kök Sorun

| # | Sorun | Dosya | Satır |
|---|-------|-------|-------|
| 1 | Rule-based path TIME_SERIES_COMPARISON'ı yakalar, LLM'i bypass eder | `nodes.py` | 162-167 |
| 2 | data_analyzer multiple TIME kolonlarında en granüler olanı seçmiyor | `data_analyzer.py` | 142-149 |
| 3 | Validator series_field'ı hiç doldurmaz | `validator.py` | 92-108 |
| 4 | Composite time axis desteği yok (Yil+Hafta → "2025-W40") | `chart_renderer.py` | 118-138 |
| 5 | LLM prompt'a conversation context (messages) gitmiyor | `nodes.py`, `prompts.py`, `state.py` | - |

## File Structure

```
src/graphs/report_agent/subagents/visualization_v2/
├── state.py          — MODIFY: messages field ekle
├── data_analyzer.py  — MODIFY: time granularity ranking + composite time detection
├── nodes.py          — MODIFY: rule-based selectivity + messages context
├── prompts.py        — MODIFY: conversation context + composite time guidance
├── validator.py      — MODIFY: series_field completion + composite time handling
├── chart_renderer.py — MODIFY: composite time preprocessing
└── models.py         — NO CHANGE (ChartSpec zaten series_field var)

tests/
└── test_viz_v2_field_mapping.py — CREATE: tüm fix'ler için test
```

---

## Chunk 1: Data Analyzer — Time Granularity Fix

### Task 1: data_analyzer — Time Column Granularity Ranking

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py:142-149`
- Modify: `src/graphs/report_agent/subagents/visualization/state.py:37-47` (DataProfile)
- Test: `tests/test_viz_v2_field_mapping.py`

**Problem:** Multiple TIME column'ları olduğunda (`Yil`, `Hafta`), her ikisi de NUMERIC type'ında. `date_typed` listesi boş kalıyor ve `time_candidates[0]` iteration order'a göre seçiliyor (Yil). Hafta daha granüler ama ikinci sırada.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viz_v2_field_mapping.py
import pytest
from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer


class TestTimeColumnGranularity:
    """data_analyzer birden fazla TIME kolonu olduğunda en granüler olanı seçmeli."""

    def test_hafta_preferred_over_yil(self):
        """Hafta (week), Yil (year)'dan daha granüler — time_column=Hafta olmalı."""
        data = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 40, "ToplamSatis": 73360.02},
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 41, "ToplamSatis": 140550},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 40, "ToplamSatis": 28132.72},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]

        assert profile["time_column"] == "Hafta"
        # Yil hala time_columns listesinde olmalı (composite için)
        assert "Yil" in profile.get("time_columns", [])

    def test_ay_preferred_over_yil(self):
        """Ay (month), Yil (year)'dan daha granüler."""
        data = [
            {"Yil": 2025, "Ay": 1, "Tutar": 100},
            {"Yil": 2025, "Ay": 2, "Tutar": 200},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]

        assert profile["time_column"] == "Ay"

    def test_single_time_column_unchanged(self):
        """Tek TIME kolon varsa davranış değişmemeli."""
        data = [
            {"ProductName": "LATTE", "Hafta": 40, "ToplamSatis": 100},
            {"ProductName": "LATTE", "Hafta": 41, "ToplamSatis": 200},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]

        assert profile["time_column"] == "Hafta"

    def test_date_type_still_preferred_over_numeric_time(self):
        """DATE type her zaman NUMERIC time'dan öncelikli (mevcut davranış)."""
        data = [
            {"Tarih": "2025-01-15", "Yil": 2025, "Tutar": 100},
            {"Tarih": "2025-02-15", "Yil": 2025, "Tutar": 200},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]

        # DATE type her zaman kazanır
        assert profile["time_column"] == "Tarih"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestTimeColumnGranularity -v`
Expected: FAIL — `Hafta` yerine `Yil` seçiliyor, `time_columns` key yok.

- [ ] **Step 3: Add time_columns to DataProfile**

`src/graphs/report_agent/subagents/visualization/state.py` — DataProfile'a `time_columns` ekle:

```python
class DataProfile(TypedDict, total=False):
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    dimension_columns: List[str]
    metric_columns: List[str]
    time_column: Optional[str]          # en granüler time kolonu (x-axis için)
    time_columns: Optional[List[str]]   # tüm time kolonları sıralı (composite axis için)
    has_time_series: bool
    has_multiple_dimensions: bool
    is_aggregated: bool
    sample_rows: List[Dict[str, Any]]
```

- [ ] **Step 4: Implement time granularity ranking in data_analyzer**

`src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py` — `_create_profile` metodunda `time_candidates` seçim mantığını değiştir:

```python
    # --- Class level constant (TIME_COLUMN_PATTERNS'ın altına ekle) ---

    # Time granularity ranking: lower = more granular = preferred for x-axis
    TIME_GRANULARITY = {
        "hour": 1, "saat": 1, "minute": 1, "dakika": 1,
        "day": 2, "gun": 2, "dayofweek": 2,
        "week": 3, "hafta": 3,
        "month": 4, "ay": 4,
        "quarter": 5, "ceyrek": 5,
        "year": 6, "yil": 6,
        "date": 2, "tarih": 2, "time": 1, "zaman": 1,
        "donem": 5, "period": 5,
    }
```

`_create_profile` metodu (satır ~142-149 arasını DEĞİŞTİR):

```python
        # Select best time column
        # Priority: 1) DATE/DATETIME type, 2) most granular numeric time
        all_time_names: List[str] = []
        if time_candidates:
            date_typed = [c for c in time_candidates if c["type"] in (ColumnType.DATE, ColumnType.DATETIME)]
            if date_typed:
                time_column = date_typed[0]["name"]
            else:
                # Sort by granularity: lower = more granular = preferred
                sorted_candidates = sorted(
                    time_candidates,
                    key=lambda c: self._get_time_granularity(c["name"]),
                )
                time_column = sorted_candidates[0]["name"]

            # All time column names (granularity order), for composite axis
            all_time_names = [c["name"] for c in sorted(
                time_candidates,
                key=lambda c: self._get_time_granularity(c["name"]),
            )]

            # Non-primary time columns go to dimensions (still useful for grouping)
            for tc in time_candidates:
                if tc["name"] != time_column:
                    dimension_columns.append(tc["name"])
```

Ve `_create_profile` return kısmında `time_columns` ekle:

```python
        return DataProfile(
            row_count=row_count,
            column_count=column_count,
            columns=column_infos,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            time_column=time_column,
            time_columns=all_time_names if all_time_names else None,
            has_time_series=has_time_series,
            has_multiple_dimensions=has_multiple_dimensions,
            is_aggregated=is_aggregated,
            sample_rows=sample_rows
        )
```

Yeni helper method (class'a ekle):

```python
    def _get_time_granularity(self, col_name: str) -> int:
        """Return granularity rank for a time column name. Lower = more granular."""
        col_lower = col_name.lower()
        for pattern, rank in self.TIME_GRANULARITY.items():
            if pattern in col_lower:
                return rank
        return 99  # unknown → least preferred
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestTimeColumnGranularity -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_viz_v2_field_mapping.py \
  src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py \
  src/graphs/report_agent/subagents/visualization/state.py
git commit -m "fix(viz-v2): prefer most granular time column (Hafta > Yil)"
```

---

## Chunk 2: Rule-Based Path Selectivity + Validator Series Field

### Task 2: Rule-based path — Don't handle TIME_SERIES_COMPARISON

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py:129-183`
- Test: `tests/test_viz_v2_field_mapping.py`

**Problem:** `_rule_based_decision()` TIME_SERIES_COMPARISON'ı yakalayıp `x/y/series=None` ile dönüyor. Bu durumda LLM asla çağrılmıyor ve validator yetersiz kalıyor.

**Çözüm:** Rule-based path sadece basit (tek dimension) senaryolarda field mapping'i atlamalı. Multi-dimensional data varsa LLM'e düşmeli.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viz_v2_field_mapping.py'e ekle

class TestRuleBasedDecision:
    """Rule-based path multi-dim data'da LLM'e düşmeli."""

    def test_time_series_comparison_falls_to_llm(self):
        """TIME_SERIES_COMPARISON + 2+ dimension → rule-based None dönmeli (LLM fallback)."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "time_columns": ["Hafta", "Yil"],
            "dimension_columns": ["ProductName", "Yil"],
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
        )
        # Multi-dim → LLM'e düşmeli
        assert result is None

    def test_simple_time_series_still_rule_based(self):
        """TIME_SERIES + tek dimension → rule-based hala çalışmalı."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "dimension_columns": [],
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES",
            wants_viz=True,
            profile=profile,
        )
        assert result is not None
        assert result["chart_type"] == "line_chart"

    def test_ranking_still_rule_based(self):
        """RANKING her zaman rule-based."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "metric_columns": ["ToplamSatis"],
            "time_column": None,
            "dimension_columns": ["ProductName"],
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="RANKING",
            wants_viz=True,
            profile=profile,
        )
        assert result is not None
        assert result["chart_type"] == "bar_chart"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestRuleBasedDecision -v`
Expected: `test_time_series_comparison_falls_to_llm` FAIL (rule-based sonuç dönüyor)

- [ ] **Step 3: Update `_rule_based_decision`**

`nodes.py` satır 162-167 — TIME_SERIES_COMPARISON bloğunu değiştir:

```python
    if query_type == "TIME_SERIES":
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Time series -> line chart",
        }

    if query_type == "TIME_SERIES_COMPARISON":
        # Multi-dimensional comparison → LLM handles field mapping
        has_multi_dim = profile.get("has_multiple_dimensions", False)
        dim_count = len(profile.get("dimension_columns", []))
        if has_multi_dim or dim_count >= 1:
            return None  # → LLM fallback
        # Basit (tek metric, zaman kolonu) → rule-based yeterli
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Simple time series comparison -> line chart",
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestRuleBasedDecision -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py \
  tests/test_viz_v2_field_mapping.py
git commit -m "fix(viz-v2): route TIME_SERIES_COMPARISON to LLM for field mapping"
```

---

### Task 3: Validator — series_field Completion (Rule 6)

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/validator.py:108-123`
- Test: `tests/test_viz_v2_field_mapping.py`

**Problem:** Validator x_field ve y_field dolduruyor ama series_field'ı hiç doldurmuyor. LLM series_field'ı set etmezse grafik tek trace olarak çiziliyor.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viz_v2_field_mapping.py'e ekle
from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec


class TestValidatorSeriesField:
    """Validator series_field'ı otomatik doldurmalı."""

    def test_auto_fill_series_field_for_multi_dim(self):
        """x ve y set ama series yok + kalan dimension var → series otomatik dolmalı."""
        spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": None,
        }
        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 40, "ToplamSatis": 100},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 40, "ToplamSatis": 200},
        ]
        profile = {
            "dimension_columns": ["ProductName", "Yil"],
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "columns": [
                {"name": "ProductName", "role": "dimension", "type": "text"},
                {"name": "Yil", "role": "time", "type": "numeric"},
                {"name": "Hafta", "role": "time", "type": "numeric"},
                {"name": "ToplamSatis", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)

        assert validated["series_field"] == "ProductName"

    def test_no_auto_fill_when_series_already_set(self):
        """series_field zaten set ise dokunma."""
        spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": "Yil",
        }
        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 40, "ToplamSatis": 100},
        ]
        profile = {
            "dimension_columns": ["ProductName", "Yil"],
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "columns": [
                {"name": "ProductName", "role": "dimension", "type": "text"},
                {"name": "Yil", "role": "time", "type": "numeric"},
                {"name": "Hafta", "role": "time", "type": "numeric"},
                {"name": "ToplamSatis", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)

        assert validated["series_field"] == "Yil"

    def test_no_auto_fill_for_pie_chart(self):
        """Pie chart'ta series_field mantıksız — doldurma."""
        spec = {
            "needs_graph": True,
            "chart_type": "pie_chart",
            "x_field": "ProductName",
            "y_field": "ToplamSatis",
            "series_field": None,
        }
        results = [
            {"ProductName": "LATTE", "ToplamSatis": 100},
        ]
        profile = {
            "dimension_columns": ["ProductName"],
            "metric_columns": ["ToplamSatis"],
            "time_column": None,
            "columns": [
                {"name": "ProductName", "role": "dimension", "type": "text"},
                {"name": "ToplamSatis", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)

        assert validated["series_field"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestValidatorSeriesField -v`
Expected: `test_auto_fill_series_field_for_multi_dim` FAIL

- [ ] **Step 3: Add Rule 6 to validator**

`validator.py` — Rule 5'ten sonra (satır ~123), Rule 6 ekle:

```python
    # Rule 6: Series field completion
    # line_chart, bar_chart, comparison → kalan dimension'ı series_field yap
    _SERIES_COMPATIBLE = {"line_chart", "bar_chart", "comparison", "scatter_chart"}
    if (
        spec.get("needs_graph")
        and spec.get("chart_type") in _SERIES_COMPATIBLE
        and not spec.get("series_field")
        and spec.get("x_field")
        and spec.get("y_field")
    ):
        x = spec["x_field"]
        y = spec["y_field"]
        # x ve y dışında kalan dimension kolonlarını bul
        remaining_dims = [
            d for d in dimension_cols
            if d != x and d != y
        ]
        if remaining_dims:
            # En düşük unique count'a sahip olanı seç (daha iyi renk ayrımı)
            best = remaining_dims[0]
            best_unique = len(set(row.get(best) for row in results)) if best in actual_columns else 999
            for dim in remaining_dims[1:]:
                if dim in actual_columns:
                    unique = len(set(row.get(dim) for row in results))
                    if unique < best_unique:
                        best = dim
                        best_unique = unique
            # MAX_TRACES check: çok fazla kategori varsa series olarak kullanma
            if best_unique <= 50:
                spec["series_field"] = best
                logger.info(f"[VALIDATOR] Rule 6: series_field filled -> '{best}' ({best_unique} unique)")

    return spec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestValidatorSeriesField -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/validator.py \
  tests/test_viz_v2_field_mapping.py
git commit -m "fix(viz-v2): validator auto-fills series_field from remaining dimensions"
```

---

## Chunk 3: Conversation Context + LLM Prompt Enhancement

### Task 4: State — messages field + Node — conversation context forwarding

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/state.py`
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py:200-275`
- Modify: `src/graphs/report_agent/subagents/visualization_v2/prompts.py`

**Problem:** `VisualizationState`'te `messages` yok. Kullanıcı "haftalık olarak grafiğini ver" dediğinde LLM önceki context'i görmüyor — hangi ürünlerin karşılaştırıldığını, tablo yapısını bilmiyor.

- [ ] **Step 1: Add messages to VisualizationState**

`state.py`:

```python
class VisualizationState(TypedDict, total=False):
    # --- ReportState overlapping (auto-sync) ---
    messages: Optional[list]               # conversation context (LLM prompt'a eklenir)
    results: Optional[List[Dict[str, Any]]]
    user_query: str
    viz_request: Optional[str]
    query_type: Optional[str]
    wants_visualization: Optional[bool]
    visualization_output: Optional[Dict[str, Any]]
    error: Optional[str]

    # --- Internal ---
    data_profile: Optional[Dict[str, Any]]
    viz_decision: Optional[Dict[str, Any]]
    plotly_html_snippet: Optional[str]
```

Not: `messages` LangGraph'ın parent-child state sync'i ile otomatik ReportState'ten gelecek. ReportState'te `messages` zaten `Annotated[List[BaseMessage], add_messages]` olarak tanımlı.

- [ ] **Step 2: Build conversation summary helper**

`nodes.py` — helper fonksiyonu ekle (dosya başına yakın, `_build_column_info`'nun üstüne):

```python
def _build_conversation_context(state: dict, max_turns: int = 3) -> str:
    """Extract last N conversation turns as context for the LLM prompt."""
    messages = state.get("messages") or []
    if not messages:
        return "Onceki konusma yok."

    # Son max_turns human+ai çiftini al
    relevant = []
    for msg in messages[-(max_turns * 2):]:
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")

        if not content or len(str(content)) > 500:
            content = str(content)[:500] + "..."

        if msg_type == "human":
            relevant.append(f"Kullanici: {content}")
        elif msg_type == "ai":
            # Sadece text kısmını al, chart_html vs. dahil etme
            relevant.append(f"Sistem: {content}")

    return "\n".join(relevant) if relevant else "Onceki konusma yok."
```

- [ ] **Step 3: Update viz_decider_node to pass conversation context**

`nodes.py` — `create_viz_decider_node` içindeki LLM fallback bölümü (satır ~244-254) değişir:

```python
        effective_query = state.get("viz_request") or state.get("user_query", "")
        column_info = _build_column_info(profile, column_metadata)
        conversation_context = _build_conversation_context(state)

        prompt = VIZ_DECIDER_PROMPT.format(
            user_query=effective_query,
            query_type=state.get("query_type", "SINGLE"),
            wants_visualization=wants_viz,
            column_info=column_info,
            sample_rows=json.dumps(results[:3], ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
        )
```

- [ ] **Step 4: Update LLM prompt**

`prompts.py` — tam prompt'u aşağıdakiyle değiştir:

```python
VIZ_DECIDER_PROMPT = """Sen bir veri gorselleştirme uzmanisin.
Kullanici sorusu, onceki konusma baglami ve veri profiline gore en uygun gorselleştirmeyi belirle.

## ONCEKI KONUSMA BAGLAMI
{conversation_context}

## KULLANICI SORUSU
{user_query}

## SORGU TIPI
{query_type}

## GRAFIK TALEBI
wants_visualization: {wants_visualization}
⚠️ wants_visualization=True → needs_graph MUTLAKA True olmali.

## KOLON BILGILERI
{column_info}

## ORNEK VERI (ilk 3 satir)
{sample_rows}

## FIELD MAPPING KURALLARI

### x_field ve y_field SECIMI (KRITIK)
- SADECE ornek verideki gercek kolon adlarini kullan
- x_field: Dimension kolonu (kategori, sube, tarih gibi GRUPLAMA kolonu)
- y_field: Metric kolonu (tutar, miktar gibi SAYISAL DEGER kolonu)
- ⚠️ ASLA x_field'e metric, y_field'e dimension koyma
- Birden fazla metric varsa y_fields listesi kullan

### series_field (ONEMLI — KARSILASTIRMA GRAFIKLERI ICIN)
- Birden fazla dimension varsa: bir tanesi x_field, diger(ler)i series_field
- series_field renk/grup ayirimi yapar (her urun farkli renk gibi)
- ⚠️ Veri birden fazla entity icerir ve karsilastirma isteniyorsa series_field MUTLAKA set et
- Ornek: ProductName + Hafta + ToplamSatis → x_field=Hafta, series_field=ProductName

### COMPOSITE TIME AXIS (YENI)
- Veri hem Yil hem Hafta/Ay iceriyorsa:
  - x_field = en granüler zaman kolonu (Hafta > Ay > Yil)
  - Yil bilgisi x_field'e dahildir (renderer otomatik birlestirir)
- ⚠️ x_field'e ASLA "Yil" koyma eger daha granüler bir zaman kolonu varsa

### chart_type SECIMI
Kullanici grafik turu belirtmisse onu kullan:
- "cubuk/bar grafik" → bar_chart
- "cizgi/line grafik" → line_chart
- "pasta/pie/daire grafik" → pie_chart
- "scatter/dagilim" → scatter_chart
- "sunburst/hiyerarsik" → sunburst
- "treemap/agac harita" → treemap

Belirtmemisse veri profiline gore:
- Tek sayi → single_value (needs_graph=False)
- Kisa liste → simple_list (needs_graph=False)
- Detayli tablo → table (needs_graph=False)
- Zaman serisi → line_chart
- Kategori karsilastirmasi → bar_chart
- Oran/pay dagilimi → pie_chart
- 2+ dimension hiyerarsi → sunburst veya treemap

### orientation
- Kategori sayisi fazlaysa (10+) → "h" (yatay bar daha okunur)
- Azsa veya zaman serisi → "v" veya null

### top_n
- Pie chart icin 10'dan fazla kategori varsa → top_n=10 oner
- Ranking sorgusu ise kullanicinin istedigi N'i kullan
"""
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/state.py \
  src/graphs/report_agent/subagents/visualization_v2/nodes.py \
  src/graphs/report_agent/subagents/visualization_v2/prompts.py
git commit -m "feat(viz-v2): add conversation context to LLM prompt + composite time guidance"
```

---

## Chunk 4: Composite Time Axis — Renderer Preprocessing

### Task 5: chart_renderer — Composite Time Preprocessing

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py:62-79`
- Test: `tests/test_viz_v2_field_mapping.py`

**Problem:** x_field=Hafta olduğunda yıl geçişleri (2025-W52 → 2026-W1) sıralama bozuluyor. "Hafta 1" 2025 mi 2026 mı belli değil. Yil+Hafta birleştirilmeli.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viz_v2_field_mapping.py'e ekle

class TestCompositeTimeAxis:
    """Renderer Yil+Hafta kolonlarını birleştirmeli."""

    def test_yil_hafta_composite(self):
        """Yil+Hafta → sortable composite string oluşturmalı."""
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        spec = {
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": "ProductName",
            "needs_graph": True,
        }
        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 52, "ToplamSatis": 100},
            {"ProductName": "LATTE", "Yil": 2026, "Hafta": 1, "ToplamSatis": 200},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 52, "ToplamSatis": 150},
            {"ProductName": "AMERICANO", "Yil": 2026, "Hafta": 1, "ToplamSatis": 250},
        ]
        html = render_chart(spec, results, {})

        assert html is not None
        # HTML'de composite format olmalı (yıl bilgisi kaybolmamalı)
        assert "2025" in html or "W52" in html

    def test_yil_ay_composite(self):
        """Yil+Ay → sortable composite string."""
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        spec = {
            "chart_type": "line_chart",
            "x_field": "Ay",
            "y_field": "Tutar",
            "series_field": None,
            "needs_graph": True,
        }
        results = [
            {"Yil": 2025, "Ay": 12, "Tutar": 100},
            {"Yil": 2026, "Ay": 1, "Tutar": 200},
        ]
        html = render_chart(spec, results, {})

        assert html is not None
        assert "2025" in html or "2026" in html

    def test_no_composite_without_yil(self):
        """Yil kolonu yoksa composite yapmaz — sadece Hafta kullan."""
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        spec = {
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": None,
            "needs_graph": True,
        }
        results = [
            {"Hafta": 40, "ToplamSatis": 100},
            {"Hafta": 41, "ToplamSatis": 200},
        ]
        html = render_chart(spec, results, {})

        assert html is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestCompositeTimeAxis -v`
Expected: `test_yil_hafta_composite` FAIL (2025 bilgisi grafikte yok — sadece hafta numarası)

- [ ] **Step 3: Add composite time preprocessing**

`chart_renderer.py` — `_apply_preprocessing` fonksiyonundan sonra yeni fonksiyon ekle:

```python
# ---------------------------------------------------------------------------
# Composite Time Axis
# ---------------------------------------------------------------------------

# Patterns to detect year/period columns for composite axis
_YEAR_PATTERNS = {"yil", "year"}
_PERIOD_COMPOSITE = {
    # x_field pattern → (format_template, sort_keys)
    "hafta": ("W{period:02d}", ["_year_col", "_period_col"]),
    "week": ("W{period:02d}", ["_year_col", "_period_col"]),
    "ay": ("{period:02d}", ["_year_col", "_period_col"]),
    "month": ("{period:02d}", ["_year_col", "_period_col"]),
}


def _apply_composite_time(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """
    Combine Yil + Hafta/Ay into a sortable composite x-axis label.

    Example: Yil=2025, Hafta=40 → "2025-W40"
    """
    x = spec.get("x_field")
    if not x:
        return df

    x_lower = x.lower()

    # Check if this x_field is a period column that needs a year companion
    period_info = None
    for pattern, info in _PERIOD_COMPOSITE.items():
        if pattern in x_lower:
            period_info = info
            break

    if period_info is None:
        return df

    # Find year column in the dataframe
    year_col = None
    for col in df.columns:
        if col.lower() in _YEAR_PATTERNS and col != x:
            year_col = col
            break

    if year_col is None or year_col not in df.columns:
        return df

    fmt_template, _ = period_info

    # Create composite column
    composite_col = f"_{x}_composite"
    try:
        df = df.copy()
        df[composite_col] = df.apply(
            lambda row: f"{int(row[year_col])}-{fmt_template.format(period=int(row[x]))}",
            axis=1,
        )
        # Sort by year then period (numeric sort, not string sort)
        df = df.sort_values([year_col, x])
        # Replace x_field with composite column
        spec["x_field"] = composite_col
        # Drop the original year column from display (optional, keeps data clean)
        # Don't drop — series_field might reference it
    except (ValueError, TypeError, KeyError):
        pass  # Fallback: keep original x_field

    return df
```

- [ ] **Step 4: Hook composite preprocessing into render_chart**

`chart_renderer.py` — `render_chart` fonksiyonunda `_apply_preprocessing` çağrısından sonra ekle:

```python
    try:
        df = pd.DataFrame(results)
        df = _apply_preprocessing(df, spec)
        df = _apply_composite_time(df, spec)  # ← YENİ
        fig = _BUILDERS[chart_type](df, spec)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestCompositeTimeAxis -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py \
  tests/test_viz_v2_field_mapping.py
git commit -m "feat(viz-v2): composite time axis (Yil+Hafta → 2025-W40)"
```

---

## Chunk 5: Integration Test — End-to-End Scenario

### Task 6: Integration Test — ProductName × Hafta × Yil senaryosu

**Files:**
- Test: `tests/test_viz_v2_field_mapping.py`

**Problem:** Tüm parçalar birlikte çalışmalı: data_analyzer → (rule→LLM fallback) → validator → renderer.

- [ ] **Step 1: Write integration test**

```python
# tests/test_viz_v2_field_mapping.py'e ekle
import json


class TestEndToEndFieldMapping:
    """Tam akış: multi-dim data → doğru multi-trace line chart."""

    def test_full_pipeline_multi_product_weekly(self):
        """ProductName × Hafta × Yil → her ürün ayrı renkte haftalık line chart."""
        from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 50, "ToplamSatis": 312095.1},
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 51, "ToplamSatis": 364080.046},
            {"ProductName": "LATTE", "Yil": 2026, "Hafta": 1, "ToplamSatis": 263765.32},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 50, "ToplamSatis": 132010.1},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 51, "ToplamSatis": 178270.131},
            {"ProductName": "AMERICANO", "Yil": 2026, "Hafta": 1, "ToplamSatis": 129130.28},
        ]

        # Step 1: Data Analyzer
        analyzer = DataAnalyzer()
        profile = analyzer.analyze({"raw_data": results})["data_profile"]

        # Assertions: granularity fix
        assert profile["time_column"] == "Hafta", f"Expected Hafta, got {profile['time_column']}"
        assert "ProductName" in profile["dimension_columns"]

        # Step 2: Simulate LLM decision (what LLM should produce)
        llm_spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": "ProductName",
        }

        # Step 3: Validator
        validated = validate_spec(llm_spec, results, profile)

        assert validated["x_field"] == "Hafta"
        assert validated["y_field"] == "ToplamSatis"
        assert validated["series_field"] == "ProductName"
        assert validated["chart_type"] == "line_chart"

        # Step 4: Renderer
        html = render_chart(validated, results, {})

        assert html is not None
        # Multi-trace: her ürün ayrı renk
        assert "LATTE" in html
        assert "AMERICANO" in html
        # Composite axis: yıl bilgisi korunmalı
        assert "2025" in html

    def test_validator_safety_net_when_llm_misses_series(self):
        """LLM series_field'ı koymasa bile validator doldurmalı."""
        from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 50, "ToplamSatis": 100},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 50, "ToplamSatis": 200},
        ]

        analyzer = DataAnalyzer()
        profile = analyzer.analyze({"raw_data": results})["data_profile"]

        # LLM series_field'ı set etmemiş
        llm_spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": None,
        }

        validated = validate_spec(llm_spec, results, profile)

        # Validator safety net: ProductName otomatik series_field olmalı
        assert validated["series_field"] == "ProductName"
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_viz_v2_field_mapping.py::TestEndToEndFieldMapping -v`
Expected: ALL PASS

- [ ] **Step 3: Run all tests together**

Run: `pytest tests/test_viz_v2_field_mapping.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_viz_v2_field_mapping.py
git commit -m "test(viz-v2): add integration tests for multi-dim field mapping pipeline"
```

---

## Summary of Changes

| Dosya | Değişiklik | Etki |
|-------|-----------|------|
| `data_analyzer.py` | Time granularity ranking + `time_columns` | Hafta > Yil seçilir |
| `visualization/state.py` | `DataProfile.time_columns` eklendi | Composite axis için |
| `nodes.py` | Rule-based path: TIME_SERIES_COMPARISON → LLM fallback | LLM field mapping yapar |
| `nodes.py` | `_build_conversation_context` helper | LLM önceki turları görür |
| `prompts.py` | Conversation context + composite time guidance | LLM doğru karar verir |
| `state.py` (viz_v2) | `messages` field eklendi | Konuşma bağlamı sync |
| `validator.py` | Rule 6: series_field completion | Safety net: LLM unutsa bile |
| `chart_renderer.py` | `_apply_composite_time` | Yil+Hafta → "2025-W40" |

**Expected Result:** Aynı senaryo artık 20 renkli çizgi, her ürün ayrı, x-axis'te "2025-W40" formatında haftalık trend grafiği üretecek.
