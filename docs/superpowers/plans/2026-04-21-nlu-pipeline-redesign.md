# NLU Pipeline Redesign — SemanticIntent Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor report_agent's NLU pipeline to cleanly separate LLM (semantic) and Python (operational) layers using a SemanticIntent contract, eliminating the 407-line sql_architect prompt and non-deterministic SQL structural rules.

**Architecture:** LLM calls extract semantic meaning only (SemanticIntent ~70-line prompt); Python converts SemanticIntent → QuerySchema deterministically (schema_builder). ChromaDB term_store removes Turkish suffix regex — embedding handles morphology. schema_validator + merge_schemas nodes eliminated.

**Tech Stack:** LangGraph, LangChain (structured output), Pydantic v2, ChromaDB (sentence-transformers), pyodbc / T-SQL

---

## File Structure

### New files
| Path | Responsibility |
|------|---------------|
| `src/graphs/report_agent/subagents/text2sql/exceptions.py` | NLUError hierarchy |
| `src/graphs/report_agent/subagents/text2sql/semantic_models.py` | SemanticIntent, SemanticEntity, SemanticMetric, SemanticTime, TermMatch |
| `src/graphs/report_agent/subagents/text2sql/date_parser.py` | SemanticTime → DateDescriptor (Python, no LLM) |
| `src/graphs/report_agent/subagents/text2sql/schema_builder.py` | SemanticIntent + TermMatch map → QuerySchema (Python, no LLM) |
| `tests/unit/text2sql/__init__.py` | Test package |
| `tests/unit/text2sql/test_nlu_exceptions.py` | NLUError tests |
| `tests/unit/text2sql/test_date_parser.py` | date_parser unit tests |
| `tests/unit/text2sql/test_schema_builder.py` | schema_builder unit tests |

### Modified files
| Path | Change |
|------|--------|
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | Add `SEMANTIC_EXTRACTOR_PROMPT` |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | Add `create_semantic_extractor_node`, `schema_builder_node`; update `term_resolver_node`; remove `create_sql_architect_node`, `create_schema_validator_node`, `schema_merge_node` |
| `src/graphs/report_agent/subagents/text2sql/graph.py` | New serial flow; remove sql_architect/schema_validator/schema_merge; retry → semantic_extractor |
| `src/graphs/report_agent/subagents/text2sql/state.py` | Add `semantic_intent`, `term_resolution`; remove `schema_validation`, `term_hints` |
| `src/graphs/report_agent/subagents/text2sql/stores/term_store.py` | Remove `_keyword_patterns` + `_keyword_pre_resolve()`; add `resolve_terms(raw_texts)` + per-entry threshold |
| `src/graphs/report_agent/prompts.py` | Add `time_breakdown: bool` to `IntentClassificationResult` |
| `src/graphs/report_agent/nodes.py` | Remove `chart_llm` parallel call + `_CHART_KEYWORD_MAP` + `_detect_chart_type_from_query`; add `time_breakdown` + `semantic_intent/term_resolution` reset to return dict |
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Move `_CHART_KEYWORD_MAP` + `_detect_chart_type_from_query` here; add keyword fallback in viz_decider_node |

---

## Task 1: NLUError hierarchy

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/exceptions.py`
- Create: `tests/unit/text2sql/__init__.py`
- Create: `tests/unit/text2sql/test_nlu_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_nlu_exceptions.py
import pytest

def test_nlu_error_is_app_base_exception():
    from src.core.exceptions.exceptions import AppBaseException
    from src.graphs.report_agent.subagents.text2sql.exceptions import NLUError
    err = NLUError("test", error_code="NLU_ERROR")
    assert isinstance(err, AppBaseException)
    assert err.error_code == "NLU_ERROR"

def test_subclasses_are_nlu_error():
    from src.graphs.report_agent.subagents.text2sql.exceptions import (
        SemanticExtractionError, TermResolutionError,
        SchemaBuilderError, ValueGroundingError, SQLGenerationError, NLUError,
    )
    for cls in [SemanticExtractionError, TermResolutionError, SchemaBuilderError,
                ValueGroundingError, SQLGenerationError]:
        err = cls("test")
        assert isinstance(err, NLUError), f"{cls.__name__} must be NLUError subclass"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_nlu_exceptions.py -v
```
Expected: `ModuleNotFoundError: No module named '...exceptions'`

- [ ] **Step 3: Create `tests/unit/text2sql/__init__.py` (empty)**

- [ ] **Step 4: Write minimal implementation**

```python
# src/graphs/report_agent/subagents/text2sql/exceptions.py
from src.core.exceptions.exceptions import AppBaseException


class NLUError(AppBaseException):
    pass


class SemanticExtractionError(NLUError):
    pass


class TermResolutionError(NLUError):
    pass


class SchemaBuilderError(NLUError):
    pass


class ValueGroundingError(NLUError):
    pass


class SQLGenerationError(NLUError):
    pass
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_nlu_exceptions.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/exceptions.py tests/unit/text2sql/__init__.py tests/unit/text2sql/test_nlu_exceptions.py
git commit -m "feat(nlu): add NLUError hierarchy for pipeline error classification"
```

---

## Task 2: SemanticIntent + TermMatch models

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/semantic_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_date_parser.py — add at top (shared import verification)
import pytest

def test_semantic_intent_defaults():
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent
    intent = SemanticIntent(raw_query="test sorgusu")
    assert intent.entities == []
    assert intent.metrics == []
    assert intent.time is None
    assert intent.order_direction == "DESC"
    assert intent.limit is None

def test_semantic_entity_validation():
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity
    e = SemanticEntity(raw_text="dürümler", entity_type="filter_value")
    assert e.column_hint is None

def test_term_match_dataclass():
    from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch
    m = TermMatch(column_name="CategoryName", filter_structured=None,
                  specificity=1.0, similarity=0.92)
    assert m.column_name == "CategoryName"
    assert m.filter_structured is None
```

Save these tests to `tests/unit/text2sql/test_semantic_models.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_semantic_models.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/graphs/report_agent/subagents/text2sql/semantic_models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class SemanticEntity(BaseModel):
    raw_text: str
    entity_type: Literal["filter_value", "dimension", "comparison_value"]
    column_hint: Optional[str] = None


class SemanticMetric(BaseModel):
    raw_text: str
    aggregation_hint: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]


class SemanticTime(BaseModel):
    raw_text: str
    breakdown: bool  # True = GROUP BY kırılımı, False = WHERE filtresi


class SemanticIntent(BaseModel):
    entities: List[SemanticEntity] = []
    metrics: List[SemanticMetric] = []
    time: Optional[SemanticTime] = None
    limit: Optional[int] = None
    order_direction: Literal["ASC", "DESC"] = "DESC"
    raw_query: str = ""


@dataclass
class TermMatch:
    column_name: str
    filter_structured: Optional[Dict]
    specificity: float
    similarity: float
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_semantic_models.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/semantic_models.py tests/unit/text2sql/test_semantic_models.py
git commit -m "feat(nlu): add SemanticIntent + TermMatch data models (LLM/Python contract)"
```

---

## Task 3: SemanticTime date parser

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/date_parser.py`
- Create: `tests/unit/text2sql/test_date_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/text2sql/test_date_parser.py
import pytest
from datetime import date


def test_son_3_ay_no_breakdown():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 3 ay", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "relative"
    assert dd.unit == "month"
    assert dd.amount == -3
    assert gran is None


def test_son_1_ay_breakdown_returns_monthly():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 1 ay", breakdown=True)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "relative"
    assert gran == "monthly"


def test_bu_yil():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="bu yıl", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "current_period"
    assert dd.period == "year"
    assert gran is None


def test_bu_ay_breakdown_returns_monthly():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="bu ay", breakdown=True)
    _, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert gran == "monthly"


def test_gecen_yil():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="geçen yıl", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "relative"
    assert dd.unit == "year"
    assert dd.amount == -1
    assert gran is None


def test_exact_year():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="2024", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "exact"
    assert dd.value == "2024-01-01"
    assert gran is None


def test_month_name_year():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="ocak 2024", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "exact"
    assert dd.value == "2024-01-01"


def test_day_month():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="15 mart", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "exact"
    assert dd.value == "2026-03-15"


def test_unknown_format_raises_semantic_extraction_error():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    from src.graphs.report_agent.subagents.text2sql.exceptions import SemanticExtractionError
    st = SemanticTime(raw_text="gelecek çeyrek", breakdown=False)
    with pytest.raises(SemanticExtractionError):
        parse_semantic_time(st, date(2026, 4, 21))


def test_son_hafta():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 2 hafta", breakdown=True)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.unit == "week"
    assert dd.amount == -2
    assert gran == "weekly"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_date_parser.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/graphs/report_agent/subagents/text2sql/date_parser.py
"""
SemanticTime → DateDescriptor converter.
Pure Python, no LLM, deterministic.
Raises SemanticExtractionError for unrecognized patterns.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

from src.graphs.report_agent.subagents.text2sql.exceptions import SemanticExtractionError
from src.graphs.report_agent.subagents.text2sql.prompts import DateDescriptor
from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime

_UNIT_MAP = {
    "ay": "month", "gün": "day", "yıl": "year", "sene": "year", "hafta": "week",
}
_PERIOD_MAP = {
    "yıl": "year", "ay": "month", "gün": "day", "çeyrek": "quarter",
}
_GRAN_MAP = {
    "ay": "monthly", "yıl": "yearly", "sene": "yearly",
    "gün": "daily", "hafta": "weekly",
}
_TR_MONTH_MAP = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}


def parse_semantic_time(st: SemanticTime, today: date) -> Tuple[Optional[DateDescriptor], Optional[str]]:
    """
    Parse SemanticTime.raw_text → (DateDescriptor, time_granularity).

    time_granularity is non-None only when st.breakdown=True and pattern supports it.
    Raises SemanticExtractionError if raw_text is not a recognized date pattern.
    """
    text = st.raw_text.lower().strip()
    gran: Optional[str] = None

    # "son N ay/gün/yıl/sene/hafta"
    m = re.match(r"son\s+(\d+)\s*(ay|gün|yıl|sene|hafta)", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        dd = DateDescriptor(type="relative", unit=_UNIT_MAP[unit], amount=-n)
        if st.breakdown:
            gran = _GRAN_MAP.get(unit)
        return dd, gran

    # "geçen yıl/ay"
    m = re.match(r"geçen\s*(yıl|ay)", text)
    if m:
        unit = m.group(1)
        dd = DateDescriptor(type="relative", unit=_UNIT_MAP[unit], amount=-1)
        if st.breakdown:
            gran = _GRAN_MAP.get(unit)
        return dd, gran

    # "bu yıl/ay/gün/çeyrek"
    m = re.match(r"bu\s*(yıl|ay|gün|çeyrek)", text)
    if m:
        period_key = m.group(1)
        dd = DateDescriptor(type="current_period", period=_PERIOD_MAP[period_key])
        if st.breakdown:
            gran = _GRAN_MAP.get(period_key)
        return dd, gran

    # "YYYY" exact year
    m = re.fullmatch(r"(\d{4})", text)
    if m:
        year = m.group(1)
        dd = DateDescriptor(type="exact", value=f"{year}-01-01")
        return dd, None  # schema_builder adds end-of-year filter separately

    # "[ay adı] YYYY"
    for month_name, month_num in _TR_MONTH_MAP.items():
        m = re.match(rf"{re.escape(month_name)}\s+(\d{{4}})", text)
        if m:
            year = m.group(1)
            dd = DateDescriptor(type="exact", value=f"{year}-{month_num:02d}-01")
            gran = "monthly" if st.breakdown else None
            return dd, gran

    # "DD [ay adı]"
    for month_name, month_num in _TR_MONTH_MAP.items():
        m = re.match(rf"(\d{{1,2}})\s+{re.escape(month_name)}", text)
        if m:
            day = int(m.group(1))
            dd = DateDescriptor(type="exact", value=f"{today.year}-{month_num:02d}-{day:02d}")
            return dd, None

    raise SemanticExtractionError(
        f"Tanımlanamayan tarih formatı: {st.raw_text!r}",
        error_code="UNKNOWN_DATE_FORMAT",
        context={"raw_text": st.raw_text},
    )
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_date_parser.py -v
```
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/date_parser.py tests/unit/text2sql/test_date_parser.py
git commit -m "feat(nlu): add SemanticTime date parser — Python replaces LLM DateDescriptor logic"
```

---

## Task 4: schema_builder

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/schema_builder.py`
- Create: `tests/unit/text2sql/test_schema_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/text2sql/test_schema_builder.py
import pytest
from datetime import date


def _make_tm(col, filter_structured=None, specificity=1.0, similarity=0.9):
    from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch
    return TermMatch(column_name=col, filter_structured=filter_structured,
                     specificity=specificity, similarity=similarity)


def test_value_hint_always_set():
    """Every SchemaFilter produced by schema_builder must have value_hint set (not None)."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent, SemanticEntity, SemanticMetric
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="Ankara", entity_type="filter_value", column_hint="BranchName")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="Ankara şubesi ciro",
    )
    term_resolution = {
        "Ankara": _make_tm("BranchName"),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "SINGLE", False, date(2026, 4, 21))
    for f in schema.filters:
        assert f.value_hint is not None, f"SchemaFilter for column={f.column} has None value_hint"


def test_comparison_query_generates_IN_not_AND():
    """comparison_value entities with same column → SchemaFilter operator=IN, not two AND= filters."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="dürümler", entity_type="comparison_value", column_hint="CategoryName"),
            SemanticEntity(raw_text="içecek", entity_type="comparison_value", column_hint="CategoryName"),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="dürümler ve içecek karşılaştır",
    )
    term_resolution = {
        "dürümler": _make_tm("CategoryName"),
        "içecek": _make_tm("CategoryName"),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "COMPARISON", False, date(2026, 4, 21))
    cat_filters = [f for f in schema.filters if f.column == "CategoryName"]
    assert len(cat_filters) == 1, "Expected single IN filter, not two AND= filters"
    assert cat_filters[0].operator == "IN"
    assert set(cat_filters[0].values) == {"dürümler", "içecek"}


def test_monthly_time_series_sets_granularity():
    """SemanticTime(breakdown=True, 'son 1 ay') → time_granularity='monthly'."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric, SemanticTime,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        time=SemanticTime(raw_text="son 1 ay", breakdown=True),
        raw_query="aylık ciro son 1 ay",
    )
    schema = build_query_schema(intent, {"ciro": _make_tm("RowAmount")},
                                "TIME_SERIES_COMPARISON", True, date(2026, 4, 21))
    assert schema.time_granularity == "monthly"


def test_intent_time_breakdown_false_overridden_by_query_type_flag():
    """time_breakdown=True at schema_builder level overrides SemanticTime.breakdown=False."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric, SemanticTime,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        time=SemanticTime(raw_text="son 3 ay", breakdown=False),  # LLM said False
        raw_query="aylık ciro",
    )
    # time_breakdown=True from intent_resolver overrides
    schema = build_query_schema(intent, {"ciro": _make_tm("RowAmount")},
                                "TIME_SERIES_COMPARISON", True, date(2026, 4, 21))
    assert schema.time_granularity == "monthly"


def test_dimension_entity_goes_to_group_by():
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="ürün", entity_type="dimension")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="ürünlere göre ciro",
    )
    term_resolution = {
        "ürün": _make_tm("ProductName"),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "LISTING", False, date(2026, 4, 21))
    assert "ProductName" in schema.group_by


def test_filter_term_with_pre_built_filter_structured():
    """TermMatch with filter_structured → SchemaFilter uses filter values, value_hint still set."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    filter_structured = {"column": "DocumentTypeIsReturn", "operator": "=", "value": "1"}
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="iade", entity_type="filter_value")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="iade ciro",
    )
    term_resolution = {
        "iade": _make_tm("DocumentTypeIsReturn", filter_structured=filter_structured),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "SINGLE", False, date(2026, 4, 21))
    return_filters = [f for f in schema.filters if f.column == "DocumentTypeIsReturn"]
    assert len(return_filters) == 1
    assert return_filters[0].value == "1"
    assert return_filters[0].value_hint == "iade"  # always set
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_schema_builder.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/graphs/report_agent/subagents/text2sql/schema_builder.py
"""
schema_builder: SemanticIntent + TermMatch map → QuerySchema.
Pure Python, deterministic. Raises SchemaBuilderError on rule violation.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
from src.graphs.report_agent.subagents.text2sql.exceptions import SchemaBuilderError
from src.graphs.report_agent.subagents.text2sql.prompts import (
    QuerySchema, SchemaAggregation, SchemaFilter,
)
from src.graphs.report_agent.subagents.text2sql.semantic_models import (
    SemanticIntent, SemanticTime, TermMatch,
)


def build_query_schema(
    intent: SemanticIntent,
    term_resolution: Dict[str, TermMatch],
    query_type: str,
    time_breakdown: bool,
    today: Optional[date] = None,
) -> QuerySchema:
    """
    SemanticIntent + TermMatch map → QuerySchema.

    term_resolution keys are entity/metric raw_text strings.
    time_breakdown=True from intent_resolver overrides SemanticTime.breakdown=False.
    """
    if today is None:
        today = date.today()

    filters: List[SchemaFilter] = []
    group_by: List[str] = []
    aggregations: List[SchemaAggregation] = []
    comparison_col_values: Dict[str, List[str]] = {}

    # --- entities ---
    for entity in intent.entities:
        tm = term_resolution.get(entity.raw_text)
        col = (tm.column_name if tm else entity.column_hint) or None

        if entity.entity_type == "dimension":
            if col and col not in group_by:
                group_by.append(col)

        elif entity.entity_type == "filter_value":
            if col is None:
                raise SchemaBuilderError(
                    f"filter_value '{entity.raw_text}' has no column resolution",
                    error_code="UNRESOLVED_ENTITY",
                    context={"raw_text": entity.raw_text},
                )
            if tm and tm.filter_structured:
                filters.append(SchemaFilter(
                    column=tm.filter_structured.get("column", col),
                    operator=tm.filter_structured.get("operator", "="),
                    value=tm.filter_structured.get("value"),
                    value_hint=entity.raw_text,
                    logical_operator="AND",
                ))
            else:
                filters.append(SchemaFilter(
                    column=col,
                    operator="=",
                    value_hint=entity.raw_text,
                    logical_operator="AND",
                ))

        elif entity.entity_type == "comparison_value":
            if col is None:
                raise SchemaBuilderError(
                    f"comparison_value '{entity.raw_text}' has no column resolution",
                    error_code="UNRESOLVED_ENTITY",
                    context={"raw_text": entity.raw_text},
                )
            comparison_col_values.setdefault(col, []).append(entity.raw_text)

    # comparison_value entities → IN filter (not multiple AND=)
    for col, values in comparison_col_values.items():
        if len(values) == 1:
            filters.append(SchemaFilter(
                column=col, operator="=", value_hint=values[0], logical_operator="AND",
            ))
        else:
            filters.append(SchemaFilter(
                column=col, operator="IN", values=values,
                value_hint=values[0], logical_operator="AND",
            ))

    # --- metrics ---
    for metric in intent.metrics:
        tm = term_resolution.get(metric.raw_text)
        col = (tm.column_name if tm else None) or "RowAmount"
        alias = f"Toplam{col}" if metric.aggregation_hint == "SUM" else f"{metric.aggregation_hint}{col}"
        aggregations.append(SchemaAggregation(
            function=metric.aggregation_hint, column=col, alias=alias,
        ))

    # --- time ---
    granularity: Optional[str] = None
    if intent.time:
        effective_breakdown = intent.time.breakdown or time_breakdown
        effective_st = SemanticTime(raw_text=intent.time.raw_text, breakdown=effective_breakdown)
        try:
            dd, granularity = parse_semantic_time(effective_st, today)
        except Exception as e:
            raise SchemaBuilderError(str(e), error_code="DATE_PARSE_ERROR") from e
        if dd is not None:
            filters.append(SchemaFilter(
                column="DocumentDate",
                operator=">=",
                date_descriptor=dd,
                value_hint=intent.time.raw_text,
                logical_operator="AND",
            ))

    return QuerySchema(
        description=intent.raw_query,
        select_columns=[],
        filters=filters,
        aggregations=aggregations,
        group_by=group_by,
        time_granularity=granularity,
        order_by_direction=intent.order_direction,
        limit=intent.limit,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_schema_builder.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/schema_builder.py tests/unit/text2sql/test_schema_builder.py
git commit -m "feat(nlu): add schema_builder — deterministic SemanticIntent→QuerySchema conversion"
```

---

## Task 5: SEMANTIC_EXTRACTOR_PROMPT

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_prompts_extractor.py
def test_semantic_extractor_prompt_importable():
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "{user_query}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "{query_type}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "{column_names}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "SQL" not in SEMANTIC_EXTRACTOR_PROMPT.upper() or "YAZMA" in SEMANTIC_EXTRACTOR_PROMPT
```

Save to `tests/unit/text2sql/test_prompts_extractor.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_prompts_extractor.py -v
```
Expected: `ImportError: cannot import name 'SEMANTIC_EXTRACTOR_PROMPT'`

- [ ] **Step 3: Add to `src/graphs/report_agent/subagents/text2sql/prompts.py`** (append after the last constant)

```python
# =============================================================================
# SEMANTIC EXTRACTOR PROMPT — SemanticIntent structured output (~70 lines)
# LLM KATMANI: SQL bilgisi YOK, DB verisi YOK. Sadece "ne istendi?" sorusu.
# =============================================================================

SEMANTIC_EXTRACTOR_PROMPT = """Sen bir semantik analiz uzmanısın. Kullanıcı sorgusunu analiz et ve yapılandırılmış semantik çıkarım üret.

SQL veya veritabanı bilgisi GEREKMİYOR. Sadece "kullanıcı ne istedi?" sorusunu yanıtla.

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ (intent_resolver tarafından belirlendi)
{query_type}

## MEVCUT KOLON ADLARI (column_hint için referans — değerler değil)
{column_names}

## KONUŞMA BAĞLAMI
{conversation_context}

## ÖNCEKİ SQL HATASI (varsa — farklı çıkarım dene)
{sql_error}

---

## entity_type KURALLARI

**"filter_value"**: Sorguda filtre değeri olan spesifik kavram.
  - "dürümler kategorisi" → entity("dürümler", filter_value)
  - "Ankara şubesi" → entity("Ankara", filter_value, column_hint="BranchName")
  - "son 1 yılda" — entity DEĞİL, time alanına yaz

**"dimension"**: Gruplama boyutu. "...e göre", "...lere göre", "bazında", "kırılımı" ile gelir.
  - "ürünlere göre" → entity("ürün", dimension)
  - "kategoriler bazında" → entity("kategori", dimension)

**"comparison_value"**: COMPARISON sorgusunda karşılaştırılan iki veya daha fazla spesifik değer.
  - "dürümler ve içecek karşılaştır" → entity("dürümler", comparison_value) + entity("içecek", comparison_value)
  - Her iki değer AYRI entity olarak yazılır

## aggregation_hint KURALLARI
- "ciro", "tutar", "gelir", "satış tutarı" → SUM
- "adet", "miktar", "kaç tane", "sayısı" → COUNT
- "ortalama", "ort." → AVG
- "en yüksek", "maksimum", "max" → MAX
- "en düşük", "minimum", "min" → MIN

## time.breakdown KURALI
- **True** — Zaman KIRILIMı isteniyor: "aylık", "haftalık", "günlük", "yıllık" kırılım
- **False** — Sadece zaman FİLTRESİ: "son 3 ay", "bu yıl", "2024", "ocak 2024"

## limit ve order_direction
- limit: Sayı varsa ("top 10", "en çok satan 5 ürün") → o sayı, yoksa null
- order_direction: "DESC" varsayılan; "en az", "en düşük", "artan" ifadeleri → "ASC"

## column_hint
Sadece güçlü ipucun varsa gerçek DB kolon adını yaz. Emin değilsen None bırak.

## ÖNEMLİ KISITLAMALAR
- SQL ifadeleri YAZMA (WHERE, GROUP BY, SELECT, HAVING vb.)
- raw_query: Orijinal sorguyu AYNEN kopyala
- Aynı kavramı hem filter_value hem dimension olarak ekleme
"""
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_prompts_extractor.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py tests/unit/text2sql/test_prompts_extractor.py
git commit -m "feat(nlu): add SEMANTIC_EXTRACTOR_PROMPT — 70-line LLM semantic extraction prompt"
```

---

## Task 6: semantic_extractor_node and schema_builder_node

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_semantic_extractor_node.py
import pytest
from unittest.mock import AsyncMock, MagicMock


def test_semantic_extractor_node_writes_semantic_intent():
    """semantic_extractor_node writes model_dump() to state['semantic_intent']."""
    import asyncio
    from src.graphs.report_agent.subagents.text2sql.nodes import create_semantic_extractor_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    expected_intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürümler", entity_type="filter_value")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="dürümler ciro",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=expected_intent)
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

    node = create_semantic_extractor_node(mock_llm, {"RowAmount": "Satış tutarı"})
    state = {"user_query": "dürümler ciro", "query_type": "SINGLE"}
    result = asyncio.get_event_loop().run_until_complete(node(state))

    assert "semantic_intent" in result
    assert result["semantic_intent"]["raw_query"] == "dürümler ciro"
    assert result["sql_error"] is None


def test_schema_builder_node_produces_query_schema():
    """schema_builder_node converts semantic_intent dict → query_schema dict."""
    import asyncio
    from src.graphs.report_agent.subagents.text2sql.nodes import schema_builder_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch

    tm_dict = TermMatch(column_name="RowAmount", filter_structured=None,
                        specificity=1.0, similarity=0.9)
    state = {
        "query_type": "SINGLE",
        "time_breakdown": False,
        "semantic_intent": {
            "entities": [],
            "metrics": [{"raw_text": "ciro", "aggregation_hint": "SUM"}],
            "time": None,
            "limit": None,
            "order_direction": "DESC",
            "raw_query": "ciro ne kadar",
        },
        "term_resolution": {
            "ciro": {"column_name": "RowAmount", "filter_structured": None,
                     "specificity": 1.0, "similarity": 0.9},
        },
    }
    result = asyncio.get_event_loop().run_until_complete(schema_builder_node(state))
    assert "query_schema" in result
    assert result["query_schema"]["aggregations"][0]["column"] == "RowAmount"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v
```
Expected: `ImportError: cannot import name 'create_semantic_extractor_node'`

- [ ] **Step 3: Add nodes to `src/graphs/report_agent/subagents/text2sql/nodes.py`**

Add after the existing imports (add SemanticIntent import):
```python
from src.graphs.report_agent.subagents.text2sql.prompts import (
    ...,  # existing imports
    SEMANTIC_EXTRACTOR_PROMPT,
)
from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent, TermMatch
from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
from src.graphs.report_agent.subagents.text2sql.exceptions import SchemaBuilderError
```

Add the two new node factory functions after the existing imports section (before `MAX_RETRY`):

```python
# =============================================================================
# NODE: SEMANTIC EXTRACTOR (replaces sql_architect for semantic understanding)
# =============================================================================

def create_semantic_extractor_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM (STRUCTURED OUTPUT): user_query → SemanticIntent.
    SQL bilgisi YOK. Sadece semantik entity/metric/time çıkarımı.
    """
    structured_llm = llm.with_structured_output(SemanticIntent)

    async def semantic_extractor_node(state: dict, *, config: RunnableConfig = None) -> dict:
        user_query = state.get("user_query", "")
        query_type = state.get("query_type", "SINGLE")
        sql_error = state.get("sql_error") or "Yok"
        effective_metadata = _get_configurable(config, "column_metadata", column_metadata)

        from langchain_core.messages import HumanMessage as _HumanMessage
        messages = state.get("messages", [])
        human_msgs = [m for m in messages if isinstance(m, _HumanMessage)]
        ctx_parts = [m.content[:100] for m in human_msgs[-3:]]
        active_sql = state.get("active_sql")
        if active_sql:
            ctx_parts.append(f"Aktif SQL: {active_sql[:300]}")
        conversation_context = "\n".join(ctx_parts) or "Yeni sorgu."

        column_names = ", ".join(list(effective_metadata.keys())) if effective_metadata else ""

        prompt = SEMANTIC_EXTRACTOR_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            column_names=column_names,
            conversation_context=conversation_context,
            sql_error=sql_error,
        )

        logger.info(f"[SEMANTIC_EXTRACTOR] INPUT: {user_query[:80]} (type={query_type})")
        intent: SemanticIntent = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SEMANTIC_EXTRACTOR] OUTPUT: entities={len(intent.entities)}, "
            f"metrics={len(intent.metrics)}, time={intent.time}, limit={intent.limit}"
        )
        return {
            "semantic_intent": intent.model_dump(),
            "sql_error": None,
        }

    return semantic_extractor_node


# =============================================================================
# NODE: SCHEMA BUILDER (pure Python — SemanticIntent + term_resolution → QuerySchema)
# =============================================================================

async def schema_builder_node(state: dict) -> dict:
    """
    Pure Python: semantic_intent + term_resolution → query_schema.
    Deterministic, no LLM.
    SchemaBuilderError → sql_error (retry → semantic_extractor).
    """
    semantic_intent_dict = state.get("semantic_intent")
    if not semantic_intent_dict:
        return {"error": "semantic_intent eksik", "results": []}

    term_resolution_dict = state.get("term_resolution") or {}
    query_type = state.get("query_type", "SINGLE")
    time_breakdown = state.get("time_breakdown", False)

    # Reconstruct TermMatch objects from state dict
    term_resolution: Dict[str, TermMatch] = {
        raw_text: TermMatch(
            column_name=tm_dict["column_name"],
            filter_structured=tm_dict.get("filter_structured"),
            specificity=float(tm_dict.get("specificity", 1.0)),
            similarity=float(tm_dict.get("similarity", 0.0)),
        )
        for raw_text, tm_dict in term_resolution_dict.items()
    }

    intent = SemanticIntent(**semantic_intent_dict)

    try:
        schema = build_query_schema(intent, term_resolution, query_type, time_breakdown)
        logger.info(
            f"[SCHEMA_BUILDER] OUTPUT: filters={len(schema.filters)}, "
            f"aggs={len(schema.aggregations)}, group_by={schema.group_by}, gran={schema.time_granularity}"
        )
        return {
            "query_schema": schema.model_dump(),
            "time_granularity": schema.time_granularity,
        }
    except SchemaBuilderError as e:
        logger.error(f"[SCHEMA_BUILDER] Error: {e} → retry")
        return {"sql_error": str(e)}
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/unit/text2sql/test_semantic_extractor_node.py
git commit -m "feat(nlu): add semantic_extractor_node and schema_builder_node to text2sql nodes"
```

---

## Task 7: term_store — remove regex, add resolve_terms + per-entry threshold

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/stores/term_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_term_store_resolve_terms.py
import pytest
from unittest.mock import MagicMock, patch


def test_resolve_terms_method_exists():
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    assert hasattr(TermStore, "resolve_terms")


def test_keyword_pre_resolve_removed():
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    assert not hasattr(TermStore, "_keyword_pre_resolve"), \
        "_keyword_pre_resolve must be removed (regex-based suffix matching)"


def test_term_store_has_no_keyword_patterns_attr():
    """TermStore.__init__ must not set _keyword_patterns."""
    import inspect
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    src = inspect.getsource(TermStore.__init__)
    assert "_keyword_patterns" not in src, \
        "_keyword_patterns dict must be removed from __init__"
```

Save to `tests/unit/text2sql/test_term_store_resolve_terms.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_term_store_resolve_terms.py -v
```
Expected: `FAIL` — `_keyword_pre_resolve` exists, `_keyword_patterns` in `__init__`

- [ ] **Step 3: Modify `src/graphs/report_agent/subagents/text2sql/stores/term_store.py`**

**3a. Remove from `__init__`:**
```python
# DELETE this line:
self._keyword_patterns: Dict[str, re.Pattern] = {}
```

**3b. Remove from `initialize()`:**
```python
# DELETE these lines (lines 157-164):
self._keyword_patterns = {
    alias.lower(): re.compile(
        rf"(?<![{_TR_CHARS}]){re.escape(alias.lower())}(?:ları|leri|lar|ler|su|sı|si|sü|nın|nin|nun|nün|dan|den|tan|ten|da|de|ta|te|ya|ye|yı|yi|yu|yü|ı|i|u|ü|a|e)?(?![{_TR_CHARS}])"
    )
    for entry in self._terms_data
    if not entry.get("filter_structured") and not entry.get("ambiguous_columns")
    for alias in [entry["term"]] + entry.get("aliases", [])
}
```

**3c. Remove `_TR_CHARS` module constant** (no longer needed):
```python
# DELETE this line:
_TR_CHARS = r"a-zA-ZçğıöşüÇĞİÖŞÜ"
```

**3d. Remove `_keyword_pre_resolve()` method entirely** (lines 225–294).

**3e. Update `resolve()` to remove `_keyword_pre_resolve` call:**
```python
def resolve(self, user_query: str) -> TermResolverOutput:
    """Legacy: single user_query → TermResolverOutput. Calls resolve_terms([user_query])."""
    return self.resolve_terms([user_query])
```

**3f. Add `_build_index()` per-entry threshold storage** — in the metadata dict in `_build_index()`:
```python
metadata = {
    ...,  # existing fields
    "similarity_threshold": str(entry.get("similarity_threshold", "")),
}
```

**3g. Update `_semantic_search()` per-entry threshold** — use lower base threshold (0.70) and check per-entry threshold per candidate:
```python
def _semantic_search(self, query_text: str) -> List[TermCandidate]:
    """ChromaDB semantic query → List[TermCandidate]. Applies per-entry threshold."""
    if self._collection is None:
        logger.warning("[TERM_STORE] Not initialized, returning empty")
        return []

    results = self._collection.query(
        query_texts=[query_text],
        n_results=min(_TOP_K, self._collection.count() or 1),
    )

    candidates: List[TermCandidate] = []
    for i, term_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        similarity = 1 - distance

        meta = results["metadatas"][0][i]
        # Per-entry threshold overrides global (filter terms need higher precision)
        entry_threshold_str = meta.get("similarity_threshold", "")
        entry_threshold = float(entry_threshold_str) if entry_threshold_str else self.similarity_threshold

        if similarity < entry_threshold:
            continue

        candidates.append(TermCandidate(
            term_id=term_id,
            category=meta.get("category", ""),
            term=meta.get("term", term_id),
            column=meta.get("column", ""),
            specificity=float(meta.get("specificity", "1.0")),
            hint=meta.get("hint", ""),
            filter_structured=json.loads(meta.get("filter_structured_json", "{}")) or None,
            ambiguous_columns=json.loads(meta.get("ambiguous_columns_json", "[]")),
            similarity=similarity,
        ))
    return candidates
```

**3h. Add `resolve_terms()` method** (before `_keyword_pre_resolve`'s old location, after `resolve()`):
```python
def resolve_terms(self, raw_texts: List[str]) -> TermResolverOutput:
    """
    Search ChromaDB for each raw_text individually and return conflict-resolved output.
    Used by term_resolver_node with SemanticIntent entity/metric raw_texts.
    """
    all_candidates: List[TermCandidate] = []
    seen_ids: set = set()

    for raw_text in raw_texts:
        if not raw_text or not raw_text.strip():
            continue
        candidates = self._semantic_search(raw_text)
        for c in candidates:
            if c.term_id not in seen_ids:
                seen_ids.add(c.term_id)
                all_candidates.append(c)

    # user_query for ambiguous prompts is joined raw_texts
    combined_query = " ".join(raw_texts)
    return self._apply_conflict_resolution(all_candidates, combined_query)
```

- [ ] **Step 4: Remove unused `re` import** from top of term_store.py (since regex removed — verify no other re usage first; the `_RULE_FILTER_EQ_RE` is in `nodes.py`, not `term_store.py`):

Check: `grep -n "^import re\|re\." src/graphs/report_agent/subagents/text2sql/stores/term_store.py`

If `re` is only used for `_keyword_patterns`, remove the import.

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_term_store_resolve_terms.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 6: Run existing tests to check for regressions**

```
pytest tests/unit/test_base_vector_store.py tests/unit/test_vectorstore_auto_init.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/stores/term_store.py tests/unit/text2sql/test_term_store_resolve_terms.py
git commit -m "feat(nlu): remove Turkish suffix regex from term_store; add resolve_terms() + per-entry threshold"
```

---

## Task 8: term_resolver_node — consume SemanticIntent

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_term_resolver_intent.py
import pytest
from unittest.mock import MagicMock
import asyncio


def test_term_resolver_reads_semantic_intent_entities():
    """term_resolver_node reads entity raw_texts from semantic_intent, not user_query."""
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    mock_store = MagicMock()
    mock_store.resolve_terms.return_value = TermResolverOutput(
        term_filters=[],
        candidate_filter_terms=[],
        hints_text="Özel terim yok.",
        ambiguous=[],
    )

    node = create_term_resolver_node(mock_store)
    state = {
        "semantic_intent": {
            "entities": [
                {"raw_text": "dürümler", "entity_type": "filter_value", "column_hint": None},
            ],
            "metrics": [
                {"raw_text": "ciro", "aggregation_hint": "SUM"},
            ],
            "time": None,
            "limit": None,
            "order_direction": "DESC",
            "raw_query": "dürümler ciro",
        },
        "text2sql_answers": [],
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))

    mock_store.resolve_terms.assert_called_once()
    call_args = mock_store.resolve_terms.call_args[0][0]
    assert "dürümler" in call_args
    assert "ciro" in call_args


def test_term_resolver_writes_term_resolution_map():
    """term_resolver_node writes {raw_text: TermMatch dict} to state['term_resolution']."""
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    mock_store = MagicMock()
    mock_store.resolve_terms.return_value = TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )

    node = create_term_resolver_node(mock_store)
    state = {
        "semantic_intent": {
            "entities": [{"raw_text": "Ankara", "entity_type": "filter_value", "column_hint": "BranchName"}],
            "metrics": [],
            "time": None,
            "limit": None,
            "order_direction": "DESC",
            "raw_query": "Ankara",
        },
        "text2sql_answers": [],
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))
    assert "term_resolution" in result
```

Save to `tests/unit/text2sql/test_term_resolver_intent.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_term_resolver_intent.py -v
```
Expected: FAIL — term_resolver_node currently calls `resolve(user_query)` and doesn't write `term_resolution`

- [ ] **Step 3: Update `create_term_resolver_node` in nodes.py**

Replace the body of `term_resolver_node` inside `create_term_resolver_node`:

```python
async def term_resolver_node(state: dict) -> dict:
    # Extract raw_texts from semantic_intent
    semantic_intent_dict = state.get("semantic_intent") or {}
    raw_texts = [
        e["raw_text"] for e in semantic_intent_dict.get("entities", [])
    ] + [
        m["raw_text"] for m in semantic_intent_dict.get("metrics", [])
    ]
    if not raw_texts:
        user_query = state.get("user_query", "")
        raw_texts = [user_query] if user_query else []

    logger.info(f"[TERM_RESOLVER] INPUT: {len(raw_texts)} terms: {raw_texts}")
    result = term_vector_store.resolve_terms(raw_texts)

    # Build term_resolution map: raw_text → TermMatch dict
    # Best candidate per raw_text (by similarity)
    term_resolution: dict = {}
    for raw_text in raw_texts:
        candidates = term_vector_store._semantic_search(raw_text)
        if candidates:
            best = max(candidates, key=lambda c: c.similarity * c.specificity)
            if not best.is_ambiguous:
                from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch
                term_resolution[raw_text] = {
                    "column_name": best.column,
                    "filter_structured": best.filter_structured,
                    "specificity": best.specificity,
                    "similarity": best.similarity,
                }

    term_filters = list(result.term_filters)
    metric_choice_hints: list[str] = []
    answers = state.get("text2sql_answers") or []

    for amb in result.ambiguous:
        source_key = _KEY_PREFIX_TERM + amb.term
        option_labels = [
            f"{opt['column']}: {opt.get('description', '')}"
            for opt in amb.options
        ]
        cached = _get_cached_answer(answers, source_key)

        if cached is None:
            return {
                "text2sql_clarification": {
                    "type": "choice",
                    "question": f'"{amb.term}" için hangi ölçütü kastettiniz?',
                    "options": option_labels,
                    "source": source_key,
                }
            }

        answer = cached
        for opt in amb.options:
            key = f"{opt['column']}: {opt.get('description', '')}"
            if key == answer:
                if opt.get("filter_structured"):
                    fs = dict(opt["filter_structured"])
                    fs.setdefault("logical_operator", "AND")
                    term_filters.append(fs)
                else:
                    chosen_col = opt["column"]
                    metric_choice_hints.append(
                        f'- Kullanıcı "{amb.term}" için [{chosen_col}] seçti'
                    )
                break

    logger.info(
        f"[TERM_RESOLVER] OUTPUT: {len(term_filters)} filter(s), "
        f"{len(term_resolution)} resolution(s), "
        f"{len(metric_choice_hints)} metric choice(s)"
    )
    return {
        "term_filters": term_filters,
        "term_resolution": term_resolution,
        "candidate_filter_terms": result.candidate_filter_terms,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_term_resolver_intent.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/unit/text2sql/test_term_resolver_intent.py
git commit -m "feat(nlu): term_resolver_node reads SemanticIntent entities/metrics instead of user_query"
```

---

## Task 9: State changes

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_state_fields.py
def test_semantic_intent_field_exists():
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
    hints = Text2SQLState.__annotations__
    assert "semantic_intent" in hints
    assert "term_resolution" in hints

def test_schema_validation_removed():
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
    assert "schema_validation" not in Text2SQLState.__annotations__

def test_term_hints_removed():
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
    assert "term_hints" not in Text2SQLState.__annotations__

def test_time_breakdown_field_exists():
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
    assert "time_breakdown" in Text2SQLState.__annotations__
```

Save to `tests/unit/text2sql/test_state_fields.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_state_fields.py -v
```
Expected: FAIL on all 4

- [ ] **Step 3: Update `src/graphs/report_agent/subagents/text2sql/state.py`**

```python
from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """
    Text2SQL subagent state.

    Overlapping keys (LangGraph auto-syncs with parent ReportState):
        user_query, query_type, active_sql, active_filters,
        sql_queries, results, error, active_results

    Internal keys:
        semantic_intent, term_resolution, query_schema,
        auto_rules, term_filters, candidate_filter_terms,
        validated_term_filters, retry_count, sql_error
    """

    # --- ReportState overlapping ---
    user_query: str
    query_type: Optional[str]
    time_breakdown: Optional[bool]         # intent_resolver → schema_builder
    active_sql: Optional[str]
    active_filters: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    pre_built_sql: Optional[str]
    time_granularity: Optional[str]
    comparison_dimension: Optional[str]
    modification_hints: Optional[List[Dict[str, Any]]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    text2sql_clarification: Optional[dict]
    text2sql_answers: Optional[list]

    # --- Internal ---
    semantic_intent:     Optional[Dict[str, Any]]       # SemanticIntent.model_dump()
    term_resolution:     Optional[Dict[str, Any]]       # {raw_text → TermMatch dict}
    query_schema:        Optional[Dict[str, Any]]       # QuerySchema.model_dump()
    auto_rules:          Optional[List[Dict[str, Any]]]
    term_filters:        Optional[List[Dict[str, Any]]]
    candidate_filter_terms: Optional[List[Dict[str, Any]]]
    validated_term_filters: Optional[List[Dict[str, Any]]]
    retry_count:         int
    sql_error:           Optional[str]
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_state_fields.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/state.py tests/unit/text2sql/test_state_fields.py
git commit -m "refactor(nlu): update Text2SQLState — add semantic_intent/term_resolution, remove schema_validation/term_hints"
```

---

## Task 10: intent_resolver — add time_breakdown, remove chart_type parallel call

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`
- Modify: `src/graphs/report_agent/nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_intent_resolver_changes.py
def test_intent_classification_result_has_time_breakdown():
    from src.graphs.report_agent.prompts import IntentClassificationResult
    result = IntentClassificationResult(
        intent_type="NEW_QUERY",
        query_type="TIME_SERIES_COMPARISON",
        confidence=0.95,
        time_breakdown=True,
    )
    assert result.time_breakdown is True

def test_intent_classification_result_time_breakdown_defaults_false():
    from src.graphs.report_agent.prompts import IntentClassificationResult
    result = IntentClassificationResult(
        intent_type="NEW_QUERY", query_type="SINGLE", confidence=0.9,
    )
    assert result.time_breakdown is False
```

Save to `tests/unit/text2sql/test_intent_resolver_changes.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_intent_resolver_changes.py -v
```
Expected: FAIL — `time_breakdown` field doesn't exist

- [ ] **Step 3: Add `time_breakdown` to `IntentClassificationResult` in `src/graphs/report_agent/prompts.py`**

```python
class IntentClassificationResult(BaseModel):
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False
    time_breakdown: bool = False           # YENİ: True → TIME_SERIES periyodik kırılım sinyali
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None
    ...
```

Also add `time_breakdown` description to `INTENT_CLASSIFIER_PROMPT` before the closing quotes:

```
**time_breakdown:**
- True: Kullanıcı dönemsel kırılım istiyor — "aylık", "haftalık", "günlük", "yıllık" ifadeleri var
- False: Dönemsel kırılım YOK (salt zaman filtresi veya zaman yok)
```

- [ ] **Step 4: Update `create_classify_intent_node` in `src/graphs/report_agent/nodes.py`**

**4a.** Remove `chart_llm` from `create_classify_intent_node`:
```python
# DELETE:
chart_llm = llm.with_structured_output(ChartTypeResult)
```

**4b.** Change `asyncio.gather` to single LLM call:
```python
# OLD:
gather_results = await asyncio.gather(
    structured_llm.ainvoke(prompt),
    chart_llm.ainvoke(chart_prompt_str),
    return_exceptions=True,
)
intent_raw, chart_raw = gather_results[0], gather_results[1]

# NEW:
result: IntentClassificationResult = await structured_llm.ainvoke(prompt)
```

**4c.** Remove `explicit_chart` keyword detection usage from chart_type assignment. Keep `wants_viz` from `result.wants_visualization` + `revisualize` check only:
```python
wants_viz = (
    result.wants_visualization
    or (result.use_result_type == "revisualize")
)
```

**4d.** Add `time_breakdown` and reset fields to `return_dict`:
```python
return_dict = {
    ...existing fields...,
    "time_breakdown": result.time_breakdown,    # NEW
    "semantic_intent": None,                    # NEW — reset each turn
    "term_resolution": None,                    # NEW — reset each turn
    "requested_chart_type": None,               # chart_type moves to viz_decider
}
```

**4e.** Remove `_CHART_KEYWORD_MAP`, `_detect_chart_type_from_query`, and `_DATE_EQ_RE` that are only used for chart detection (keep `_DATE_EQ_RE` if used elsewhere — grep first).

Check: `grep -n "_DATE_EQ_RE\|_CHART_KEYWORD_MAP\|_detect_chart_type" src/graphs/report_agent/nodes.py`

Remove only those that are purely chart-type related and no longer called.

**4f.** Remove unused import `ChartTypeResult`, `CHART_TYPE_PROMPT` from `nodes.py` imports.

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_intent_resolver_changes.py -v
```
Expected: PASS

- [ ] **Step 6: Run existing intent tests**

```
pytest tests/graphs/report/test_chart_type_detection.py tests/graphs/report/test_graph_routing.py -v
```
Expected: PASS (or update to match new behavior)

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/prompts.py src/graphs/report_agent/nodes.py tests/unit/text2sql/test_intent_resolver_changes.py
git commit -m "feat(nlu): add time_breakdown to IntentClassificationResult; remove chart_type parallel LLM call from intent_resolver"
```

---

## Task 11: viz_decider — chart_type detection moved here

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_viz_decider_chart_detection.py
def test_chart_keyword_map_in_viz_decider():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _CHART_KEYWORD_MAP
    assert "sunburst" in _CHART_KEYWORD_MAP
    assert "pasta" in _CHART_KEYWORD_MAP

def test_detect_chart_type_from_query_in_viz_decider():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _detect_chart_type_from_query
    assert _detect_chart_type_from_query("pasta grafik istiyorum") == "pie_chart"
    assert _detect_chart_type_from_query("sunbrust") == "sunburst"
    assert _detect_chart_type_from_query("normal tablo") is None
```

Save to `tests/unit/text2sql/test_viz_decider_chart_detection.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_viz_decider_chart_detection.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Add to `src/graphs/report_agent/subagents/visualization_v2/nodes.py`** (after existing imports):

```python
import re as _re

# ---------------------------------------------------------------------------
# Chart type keyword detection — moved from report_agent/nodes.py
# Fallback when LLM structured output returns None for chart_type.
# Bare English single-words excluded — collision-prone in Turkish text.
# ---------------------------------------------------------------------------
_CHART_KEYWORD_MAP: dict[str, str] = {
    "sunburst": "sunburst",
    "sunbrust": "sunburst",
    "heatmap": "heatmap",
    "ısıharitası": "heatmap",
    "treemap": "treemap",
    "barchart": "bar_chart",
    "çubuk": "bar_chart",
    "cubuk": "bar_chart",
    "linechart": "line_chart",
    "çizgi": "line_chart",
    "cizgi": "line_chart",
    "piechart": "pie_chart",
    "pasta": "pie_chart",
    "scatterchart": "scatter_chart",
}


def _detect_chart_type_from_query(text: str) -> Optional[str]:
    """Deterministic chart type extraction from user query text.
    Returns canonical chart type or None. No LLM, no I/O."""
    if not text or not text.strip():
        return None
    normalized = _re.sub(r"[\s_\-]", "", text.lower())
    for keyword, chart_type in _CHART_KEYWORD_MAP.items():
        if keyword in normalized:
            return chart_type
    return None
```

Also update the `viz_decider_node` (find it in this file) to apply keyword fallback:
Inside the viz_decider_node function, after the LLM produces `chart_spec` or similar result, add:
```python
# Keyword fallback: if LLM didn't determine chart_type, check query keywords
query_text = state.get("viz_request") or state.get("user_query") or ""
if not chart_spec.chart_type and query_text:
    keyword_chart = _detect_chart_type_from_query(query_text)
    if keyword_chart:
        chart_spec = chart_spec.model_copy(update={"chart_type": keyword_chart})
        logger.info(f"[VIZ_DECIDER] chart_type keyword fallback: '{keyword_chart}'")
```

(Exact insertion point depends on viz_decider_node structure — add after LLM result processing, before returning.)

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_viz_decider_chart_detection.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Run existing viz tests**

```
pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py tests/unit/text2sql/test_viz_decider_chart_detection.py
git commit -m "feat(nlu): move chart_type keyword detection to viz_decider (SRP — grafik kararı tek yerde)"
```

---

## Task 12: Graph integration

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_graph_new_flow.py
def test_graph_builds_without_schema_validator():
    """build_text2sql_graph succeeds and does not register schema_validator node."""
    from unittest.mock import MagicMock, patch
    from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = MagicMock()

    with patch("src.graphs.report_agent.subagents.text2sql.graph.TermStore") as MockTermStore, \
         patch("src.graphs.report_agent.subagents.text2sql.graph.BusinessRulesStore") as MockBRStore, \
         patch("src.graphs.report_agent.subagents.text2sql.graph.ValueResolverService") as MockVR, \
         patch("src.graphs.report_agent.subagents.text2sql.graph._table_init_started", True):
        MockTermStore.return_value.initialize.return_value = None
        MockBRStore.return_value.initialize.return_value = None
        compiled = build_text2sql_graph(
            llm=mock_llm,
            table_name="TestTable",
            column_metadata={"RowAmount": "Satış tutarı"},
            connection_string="mssql+pyodbc://...",
            business_rules_path="dummy.json",
        )
    assert compiled is not None
    node_names = list(compiled.get_graph().nodes.keys())
    assert "semantic_extractor" in node_names
    assert "schema_builder" in node_names
    assert "schema_validator" not in node_names
    assert "sql_architect" not in node_names
    assert "schema_merge" not in node_names


def test_retry_routes_to_semantic_extractor():
    """On sql_error, graph routes to semantic_extractor not sql_architect."""
    from src.graphs.report_agent.subagents.text2sql.graph import _route_after_executor
    state = {"sql_error": "Invalid column name 'X'", "retry_count": 1}
    assert _route_after_executor(state) == "semantic_extractor"
```

Save to `tests/unit/text2sql/test_graph_new_flow.py`.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/text2sql/test_graph_new_flow.py -v
```
Expected: FAIL — `semantic_extractor` not in graph, retry returns `sql_architect`

- [ ] **Step 3: Rewrite `src/graphs/report_agent/subagents/text2sql/graph.py`**

```python
"""
Text2SQL Subagent Graph (v3 — SemanticIntent Architecture)

START → create_table → business_rules → semantic_extractor
        → term_resolver → [HITL if ambiguous] → term_validator
        → schema_builder → value_resolver → [HITL if needed]
        → sql_generator → sql_executor
             ↑ (retry, max 2 → semantic_extractor)
        → cleanup_table → END
"""
import logging
import threading
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.text2sql.stores import BusinessRulesStore, TermStore
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_semantic_extractor_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,
    create_term_validator_node,
    create_value_resolver_node,
    schema_builder_node,
    init_master_table_background,
    _table_init_event,
    _table_init_started,
)
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService

logger = logging.getLogger(__name__)


def _route_after_executor(state: dict) -> str:
    if state.get("sql_error") and state.get("retry_count", 0) <= MAX_RETRY:
        logger.info(f"[TEXT2SQL] Retry {state['retry_count']}/{MAX_RETRY} → semantic_extractor")
        return "semantic_extractor"
    return "cleanup_table"


def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
):
    logger.info(f"[TEXT2SQL] Building subgraph v3 (SemanticIntent) for table: {table_name}")

    value_resolver = ValueResolverService(
        db_connection_string=connection_string,
        table_name=table_name,
    )

    _DATA_DIR = Path(__file__).parent.parent.parent / "data" / "vector"

    vector_store = BusinessRulesStore(rules_file_path=business_rules_path)
    vector_store.initialize()
    business_rules = create_business_rules_node(vector_store, llm=llm)

    term_store = TermStore(dict_path=_DATA_DIR / "term_dictionary.json")
    term_store.initialize()
    term_resolver = create_term_resolver_node(term_store)

    create_table        = create_create_table_node(connection_string, table_name)
    semantic_extractor  = create_semantic_extractor_node(llm, column_metadata)
    term_validator      = create_term_validator_node(llm)
    value_resolver_node = create_value_resolver_node(value_resolver)
    sql_generator       = create_sql_generator_node(table_name, column_metadata)
    sql_executor        = create_sql_executor_node(connection_string)
    cleanup_table       = create_cleanup_table_node(connection_string, table_name)

    graph = StateGraph(Text2SQLState)

    graph.add_node("create_table",       create_table)
    graph.add_node("business_rules",     business_rules)
    graph.add_node("semantic_extractor", semantic_extractor)
    graph.add_node("term_resolver",      term_resolver)
    graph.add_node("term_validator",     term_validator)
    graph.add_node("schema_builder",     schema_builder_node)
    graph.add_node("value_resolver",     value_resolver_node)
    graph.add_node("sql_generator",      sql_generator)
    graph.add_node("sql_executor",       sql_executor)
    graph.add_node("cleanup_table",      cleanup_table)

    graph.add_edge(START,                "create_table")
    graph.add_edge("create_table",       "business_rules")
    graph.add_edge("business_rules",     "semantic_extractor")
    graph.add_edge("semantic_extractor", "term_resolver")

    def _route_after_term_resolver(state: dict):
        if state.get("text2sql_clarification"):
            return END
        return "term_validator"

    graph.add_conditional_edges("term_resolver", _route_after_term_resolver)
    graph.add_edge("term_validator",     "schema_builder")

    def _route_after_schema_builder(state: dict):
        if state.get("sql_error"):
            return "semantic_extractor"
        return "value_resolver"

    graph.add_conditional_edges(
        "schema_builder",
        _route_after_schema_builder,
        {"semantic_extractor": "semantic_extractor", "value_resolver": "value_resolver"},
    )

    def _route_after_value_resolver(state: dict):
        if state.get("text2sql_clarification"):
            return END
        return "sql_generator"

    graph.add_conditional_edges(
        "value_resolver",
        _route_after_value_resolver,
        {END: END, "sql_generator": "sql_generator"},
    )

    graph.add_edge("sql_generator",      "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"semantic_extractor": "semantic_extractor", "cleanup_table": "cleanup_table"},
    )
    graph.add_edge("cleanup_table",      END)

    compiled = graph.compile()
    logger.info(
        "[TEXT2SQL] Subgraph v3 built: "
        "create_table → business_rules → semantic_extractor → term_resolver "
        "→ term_validator → schema_builder → value_resolver "
        "→ sql_generator → sql_executor → cleanup_table (max 2 retry)"
    )

    if not _table_init_started:
        sql_file = Path(__file__).parent / "master_table_creation.sql"
        if sql_file.exists():
            sql_script = sql_file.read_text(encoding="utf-8")
            init_thread = threading.Thread(
                target=init_master_table_background,
                args=(connection_string, table_name, sql_script),
                daemon=True,
            )
            init_thread.start()
        else:
            logger.warning(f"[TEXT2SQL] SQL file not found at {sql_file}")
            _table_init_event.set()
    else:
        logger.info("[TEXT2SQL] Background table init already started")

    return compiled
```

- [ ] **Step 4: Update imports in `nodes.py`** — ensure `create_schema_validator_node`, `create_sql_architect_node`, `schema_merge_node` are removed from the public interface (they can remain as dead code temporarily — remove in cleanup):

In `graph.py`, the import list is already updated above (doesn't import schema_validator/sql_architect).

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/unit/text2sql/test_graph_new_flow.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 6: Run graph routing tests**

```
pytest tests/graphs/report/test_graph_routing.py -v
```
Expected: PASS or update routing tests to reflect new nodes

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py tests/unit/text2sql/test_graph_new_flow.py
git commit -m "refactor(nlu): rebuild text2sql graph v3 — serial SemanticIntent flow, remove sql_architect/schema_validator/merge"
```

---

## Task 13: value_grounder value_hint guarantee + log standard

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/text2sql/test_value_hint_guarantee.py
import pytest


def test_schema_builder_never_produces_none_value_hint():
    """Integration: schema_builder always sets value_hint on filters — no None slips to value_resolver."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric, SemanticTime, TermMatch
    )
    from datetime import date

    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="Ankara", entity_type="filter_value", column_hint="BranchName"),
            SemanticEntity(raw_text="ürün", entity_type="dimension"),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        time=SemanticTime(raw_text="son 3 ay", breakdown=False),
        raw_query="Ankara ürünlere göre son 3 ay ciro",
    )
    term_resolution = {
        "Ankara": TermMatch("BranchName", None, 1.0, 0.95),
        "ürün": TermMatch("ProductName", None, 1.0, 0.88),
        "ciro": TermMatch("RowAmount", None, 1.0, 0.92),
    }
    schema = build_query_schema(intent, term_resolution, "LISTING", False, date(2026, 4, 21))

    for f in schema.filters:
        assert f.value_hint is not None, (
            f"SchemaFilter column={f.column!r} operator={f.operator!r} has value_hint=None. "
            "schema_builder must always set value_hint."
        )
```

Save to `tests/unit/text2sql/test_value_hint_guarantee.py`.

- [ ] **Step 2: Run test to verify it passes** (should already pass with schema_builder implementation):

```
pytest tests/unit/text2sql/test_value_hint_guarantee.py -v
```
Expected: PASS

- [ ] **Step 3: Add DECISION log line to schema_builder_node in nodes.py**

Find `schema_builder_node` in `nodes.py` and ensure it has INPUT/DECISION/OUTPUT log lines:

```python
logger.info(f"[SCHEMA_BUILDER] INPUT: semantic_intent={bool(semantic_intent_dict)}, "
            f"term_resolution={len(term_resolution_dict)} terms, "
            f"query_type={query_type}, time_breakdown={time_breakdown}")
# ... after build:
logger.info(f"[SCHEMA_BUILDER] DECISION: filters={len(schema.filters)}, "
            f"group_by={schema.group_by}, gran={schema.time_granularity}")
logger.info(f"[SCHEMA_BUILDER] OUTPUT: query_schema ready, aggs={len(schema.aggregations)}")
```

Verify `semantic_extractor_node` already has the 3-line log pattern (it does from Task 6).
Verify `term_resolver_node` log lines are consistent (INPUT/OUTPUT already added in Task 8).

- [ ] **Step 4: Run full unit test suite**

```
pytest tests/unit/ -v
```
Expected: All PASS

- [ ] **Step 5: Run integration smoke test**

```
pytest tests/graphs/report/ -v --tb=short
```
Expected: PASS (fix any test that relied on old sql_architect/schema_validator nodes)

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/unit/text2sql/test_value_hint_guarantee.py
git commit -m "fix(nlu): guarantee value_hint always set in schema_builder; add INPUT/DECISION/OUTPUT log standard"
```

---

## Task 14: Cleanup — remove dead code from nodes.py

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: Remove dead functions from nodes.py**

These functions are no longer used (graph.py no longer imports them):
- `create_sql_architect_node` (replaced by `create_semantic_extractor_node`)
- `create_schema_validator_node` (eliminated)
- `schema_merge_node` (eliminated)

Also remove from imports:
```python
# DELETE from prompts import:
SchemaValidationResult,
SCHEMA_VALIDATOR_PROMPT,
SQL_ARCHITECT_PROMPT,
```

- [ ] **Step 2: Run full test suite**

```
pytest tests/ -v --tb=short -x
```
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "refactor(nlu): remove dead code — sql_architect, schema_validator, schema_merge nodes eliminated"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by task |
|---|---|
| SemanticIntent LLM/Python contract | Task 2, 5, 6 |
| TermMatch ChromaDB/Python contract | Task 2, 7 |
| SemanticTime date parser (Python) | Task 3 |
| schema_builder (Python, deterministic) | Task 4, 6 |
| semantic_extractor ~70-line prompt | Task 5, 6 |
| term_store regex removal | Task 7 |
| term_store per-entry threshold | Task 7 |
| term_resolver → SemanticIntent input | Task 8 |
| term_resolver → term_validator serial | Task 12 |
| intent_resolver time_breakdown | Task 10 |
| intent_resolver remove chart_type LLM | Task 10 |
| viz_decider chart_type detection | Task 11 |
| State: semantic_intent, term_resolution | Task 9 |
| State: remove schema_validation, term_hints | Task 9 |
| Graph: schema_validator + merge removed | Task 12 |
| Graph: retry → semantic_extractor | Task 12 |
| NLUError hierarchy | Task 1 |
| Log standard (INPUT/DECISION/OUTPUT) | Task 13 |
| value_hint guarantee test | Task 13 |
| comparison_value → IN (not AND=) | Task 4 |
| time_breakdown override logic | Task 4 |

**Type consistency check:** `TermMatch` dataclass used in Task 2, 4, 8, 13 — all fields consistent (`column_name`, `filter_structured`, `specificity`, `similarity`). `SemanticIntent` used in Task 2, 4, 5, 6, 8 — all field names consistent. `build_query_schema` signature in Task 4 matches usage in Task 6 (`schema_builder_node`).

**Placeholder scan:** No TBD/TODO in any code block.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-21-nlu-pipeline-redesign.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
