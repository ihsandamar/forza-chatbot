# Chart Type Deterministic Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `classify_intent_node` LLM çağrısı "sunbrust" gibi yazım hatalarını `requested_chart_type=None` döndürdüğünde, deterministic keyword fallback devreye girerek doğru chart type'ı set etsin; böylece FastAPI ve LangGraph Dev arasındaki non-deterministik davranış ortadan kalksın.

**Architecture:** LLM çağrısı (`structured_llm.ainvoke`) değişmiyor. LLM sonucu `None` dönerse, module-level pure function `_detect_chart_type_from_query` user query üzerinde normalized keyword lookup yapar ve `result.model_copy(update=...)` ile override eder. Sıfır yeni node, sıfır yeni edge, sıfır mimari değişiklik.

**Tech Stack:** Python, pytest, pytest-asyncio, `re` (stdlib — dış bağımlılık yok)

---

## Değişecek Dosyalar

| Dosya | İşlem | Değişiklik |
|---|---|---|
| `src/graphs/report_agent/nodes.py` | Modify | Module-level `_detect_chart_type_from_query` + node içinde post-LLM fallback |
| `tests/graphs/report/test_chart_type_detection.py` | Create | Pure function + entegrasyon testleri |

---

## Task 1: `_detect_chart_type_from_query` Pure Function

**Dosyalar:**
- Modify: `src/graphs/report_agent/nodes.py` (`MODIFY_AMBIGUITY_THRESHOLD` sabitinden hemen sonra)
- Create: `tests/graphs/report/test_chart_type_detection.py`

**Bağlam:** `nodes.py` zaten `re` import ediyor (satır 3) ve `Optional` import ediyor (satır 4). Yeni import gerekmez. Function module-level olacak — node closure'ın dışında, test edilebilir.

**Keyword map tasarım kararı:** Bare English single-word aliases (`"bar"`, `"line"`, `"pie"`, `"scatter"`) eklenmez — bunlar Türkçe kelimelerin içinde geçen substring'ler olarak yanlış match yapabilir (örn. "kabartma" içinde "bar"). Sadece compound forms ve açıkça chart-specific Türkçe kelimeler kullanılır.

- [ ] **Step 1: Failing test yaz**

`tests/graphs/report/test_chart_type_detection.py` dosyasını oluştur:

```python
"""Unit tests for _detect_chart_type_from_query deterministic fallback.

Pure function tests — no LLM, no I/O, no async.
"""


def _fn(text):
    from src.graphs.report_agent.nodes import _detect_chart_type_from_query
    return _detect_chart_type_from_query(text)


# --- Exact keyword match ---
def test_sunburst_exact():
    assert _fn("sunburst grafik ver") == "sunburst"

def test_heatmap_exact():
    assert _fn("heatmap göster") == "heatmap"

def test_treemap_exact():
    assert _fn("treemap istiyorum") == "treemap"

def test_bar_chart_turkish():
    assert _fn("çubuk grafik") == "bar_chart"

def test_line_chart_turkish():
    assert _fn("çizgi grafik") == "line_chart"

def test_pie_chart_turkish():
    assert _fn("pasta grafik") == "pie_chart"

def test_scatter_chart_compound():
    assert _fn("scatter chart ver") == "scatter_chart"

def test_bar_chart_compound_english():
    assert _fn("bar chart istiyorum") == "bar_chart"

def test_line_chart_compound_english():
    assert _fn("line chart göster") == "line_chart"

def test_pie_chart_compound_english():
    assert _fn("pie chart ver") == "pie_chart"


# --- Typo tolerance (root cause case) ---
def test_sunbrust_typo():
    """Root cause: 'sunbrust' LLM tarafından resolve edilemiyor — bu test bunu yakalar."""
    assert _fn("sunbrust grafik ver") == "sunburst"

def test_sunbrust_uppercase():
    assert _fn("SUNBRUST GRAFİK") == "sunburst"

def test_sunbrust_in_full_query():
    """Actual failing query from the bug report."""
    q = ("Son 3 aydaki satışları karşılaştır ve bunlar içinde hangi kategoriler "
         "ne kadar satmış onu da gösteren sunbrust grafik ver")
    assert _fn(q) == "sunburst"


# --- Turkish heatmap ---
def test_isı_haritası():
    assert _fn("ısı haritası göster") == "heatmap"


# --- No false positives for bare English words in Turkish text ---
def test_no_false_positive_kabartma():
    """'kabartma' contains 'bar' as substring — must NOT trigger bar_chart."""
    assert _fn("kabartma tekniği") is None

def test_no_false_positive_line_in_turkish():
    """'oline' (as in online) must NOT trigger line_chart."""
    assert _fn("online rapor ver") is None


# --- No match cases ---
def test_no_chart_keyword_returns_none():
    assert _fn("son 3 aydaki satışları göster") is None

def test_empty_string_returns_none():
    assert _fn("") is None

def test_only_whitespace_returns_none():
    assert _fn("   ") is None
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report/test_chart_type_detection.py -v
```

Beklenen çıktı: `ImportError: cannot import name '_detect_chart_type_from_query'`

- [ ] **Step 3: Fonksiyonu implement et**

`src/graphs/report_agent/nodes.py` dosyasında `MODIFY_AMBIGUITY_THRESHOLD = 0.85` sabitinden hemen sonra, `create_classify_intent_node` fonksiyon tanımından önce şunu ekle:

```python
# ---------------------------------------------------------------------------
# Chart type keyword detection — deterministic fallback for LLM structured output.
#
# LLM with structured Literal fields can return None for typos like "sunbrust".
# This pure function covers that gap without touching the LLM call.
#
# Design: bare English single-words ("bar", "line", "pie") intentionally excluded
# — they are collision-prone substrings in Turkish text (e.g. "kabartma" contains
# "bar"). Only compound English forms and clearly chart-specific Turkish keywords
# are included.
# ---------------------------------------------------------------------------
_CHART_KEYWORD_MAP: dict[str, str] = {
    # sunburst — includes the common typo that triggered this fix
    "sunburst": "sunburst",
    "sunbrust": "sunburst",
    # heatmap
    "heatmap": "heatmap",
    "isıharitası": "heatmap",   # Turkish: "ısı haritası" → stripped spaces
    # treemap
    "treemap": "treemap",
    # bar chart — compound only (bare "bar" is a collision risk in Turkish)
    "barchart": "bar_chart",
    "çubuk": "bar_chart",
    "cubuk": "bar_chart",
    # line chart — compound only
    "linechart": "line_chart",
    "çizgi": "line_chart",
    "cizgi": "line_chart",
    # pie chart — compound only
    "piechart": "pie_chart",
    "pasta": "pie_chart",
    # scatter chart — compound only
    "scatterchart": "scatter_chart",
}


def _detect_chart_type_from_query(text: str) -> Optional[str]:
    """Deterministic chart type extraction from user query text.

    Normalizes input (lowercase, collapse whitespace/hyphens/underscores) then
    checks for substrings against _CHART_KEYWORD_MAP.

    Returns canonical chart type string (e.g. "sunburst") or None if no keyword found.
    Pure function — no LLM, no I/O, safe to call from any context.
    """
    if not text or not text.strip():
        return None
    # Normalize: lowercase, strip whitespace/separators (keep Turkish chars like ı, ş, ç)
    normalized = re.sub(r"[\s_\-]", "", text.lower())
    for keyword, chart_type in _CHART_KEYWORD_MAP.items():
        if keyword in normalized:
            return chart_type
    return None
```

- [ ] **Step 4: Testleri çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report/test_chart_type_detection.py -v
```

Beklenen çıktı: Tüm testler `PASSED`

- [ ] **Step 5: Commit**

```bash
git add tests/graphs/report/test_chart_type_detection.py src/graphs/report_agent/nodes.py
git commit -m "feat: add _detect_chart_type_from_query deterministic fallback"
```

---

## Task 2: `classify_intent_node` İçine Fallback Entegrasyonu

**Dosyalar:**
- Modify: `src/graphs/report_agent/nodes.py` (`result = await structured_llm.ainvoke(prompt)` satırından hemen sonra)
- Modify: `tests/graphs/report/test_chart_type_detection.py` (entegrasyon testleri ekle)

**Bağlam:** `result = await structured_llm.ainvoke(prompt)` satırı (`create_classify_intent_node` içinde) mevcut — koda göre bul, satır numarasına göre değil (Task 1 sonrası numara kayar). Test pattern: proje `@pytest.mark.asyncio` kullanıyor (bkz. `tests/graphs/report/test_extract_entity_node.py:21`).

**Fallback koşulu:** `result.wants_visualization or result.use_result_type == "revisualize"` — nodes.py satır 136'daki `wants_viz` hesabını yansıtır. `revisualize` path'inde kullanıcı "sunbrust grafik olarak göster" derse fallback da devreye girmeli.

- [ ] **Step 1: Entegrasyon testlerini ekle**

`tests/graphs/report/test_chart_type_detection.py` dosyasının sonuna şunu ekle:

```python
# ---------------------------------------------------------------------------
# Integration: classify_intent_node fallback path (LLM mock ile)
# Projedeki pattern: @pytest.mark.asyncio + async def (test_extract_entity_node.py)
# ---------------------------------------------------------------------------
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_llm(
    intent_type="NEW_QUERY",
    query_type="COMPARISON",
    confidence=0.9,
    wants_visualization=True,
    use_result_type=None,
    requested_chart_type=None,
):
    """Structured LLM mock: ainvoke → IntentClassificationResult döner."""
    from src.graphs.report_agent.prompts import IntentClassificationResult

    mock_result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=confidence,
        wants_visualization=wants_visualization,
        use_result_type=use_result_type,
        requested_chart_type=requested_chart_type,
    )
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm.with_structured_output = MagicMock(return_value=structured)
    return mock_llm


@pytest.mark.asyncio
async def test_fallback_sets_sunburst_when_llm_returns_none():
    """Root cause: LLM None döndüğünde 'sunbrust' fallback ile sunburst olmalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, requested_chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları sunbrust grafik ile göster")]}
    result = await node(state)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_fallback_does_not_override_when_llm_returns_value():
    """LLM zaten bir değer döndürdüyse fallback override etmemeli."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, requested_chart_type="bar_chart")
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="sunburst grafik ver")]}
    result = await node(state)
    assert result["requested_chart_type"] == "bar_chart"


@pytest.mark.asyncio
async def test_fallback_inactive_when_no_visualization():
    """wants_visualization=False ve use_result_type=None ise fallback çalışmamalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=False, use_result_type=None, requested_chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="sunbrust grafik ver")]}
    result = await node(state)
    assert result["requested_chart_type"] is None


@pytest.mark.asyncio
async def test_fallback_active_on_revisualize_path():
    """use_result_type=revisualize + LLM None → fallback devreye girmeli."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(
        intent_type="USE_RESULT",
        wants_visualization=False,   # revisualize path'inde LLM bunu False bırakabilir
        use_result_type="revisualize",
        requested_chart_type=None,
    )
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="bunu sunbrust olarak göster")]}
    result = await node(state)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_fallback_returns_none_when_no_keyword():
    """Keyword yoksa fallback None bırakmalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, requested_chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları karşılaştır")]}
    result = await node(state)
    assert result["requested_chart_type"] is None
```

- [ ] **Step 2: Testleri çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report/test_chart_type_detection.py::test_fallback_sets_sunburst_when_llm_returns_none -v
```

Beklenen çıktı: `FAILED` — fallback henüz yok, `requested_chart_type=None` döner

- [ ] **Step 3: `classify_intent_node` içine fallback ekle**

`src/graphs/report_agent/nodes.py` içinde `create_classify_intent_node` fonksiyonunda, `result = await structured_llm.ainvoke(prompt)` satırından hemen sonra şu bloğu ekle:

```python
        result: IntentClassificationResult = await structured_llm.ainvoke(prompt)

        # Post-LLM fallback: LLM structured output typo/edge-case'lerde
        # requested_chart_type=None döndürebilir (non-deterministic, OpenAI backend-dependent).
        # Kullanıcı vizualizasyon istiyorsa ve LLM chart type'ı çözemediyse,
        # deterministic keyword lookup ile override et.
        # revisualize path'ini de kapsar (nodes.py:136 mantığını yansıtır).
        _wants_viz_effective = result.wants_visualization or (result.use_result_type == "revisualize")
        if _wants_viz_effective and result.requested_chart_type is None:
            _detected = _detect_chart_type_from_query(user_query)
            if _detected:
                result = result.model_copy(update={"requested_chart_type": _detected})
                logger.info(
                    f"[CLASSIFY] Fallback chart type detected: '{_detected}' from query"
                )
```

- [ ] **Step 4: Tüm testleri çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report/test_chart_type_detection.py -v
```

Beklenen çıktı: Tüm testler `PASSED`

- [ ] **Step 5: Mevcut report testlerini kır mı kontrol et**

```bash
pytest tests/graphs/report/ -v --tb=short
```

Beklenen çıktı: Tüm mevcut testler `PASSED` — hiçbir regresyon yok

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_chart_type_detection.py
git commit -m "fix: apply deterministic chart type fallback after LLM in classify_intent_node

When gpt-4.1 structured output returns requested_chart_type=None for
edge-case inputs like the 'sunbrust' typo, keyword lookup now overrides
it deterministically. Covers both wants_visualization=True and
use_result_type=revisualize paths. Fixes FastAPI vs LangGraph Dev divergence."
```

---

## Task 3: Smoke Verification

- [ ] **Step 1: Tüm test suite'i çalıştır**

```bash
pytest tests/ -v --tb=short -q
```

Beklenen çıktı: Yeni testler dahil tüm testler `PASSED`, `0 errors`

- [ ] **Step 2: Root cause senaryosunu doğrula**

```bash
python -c "
from src.graphs.report_agent.nodes import _detect_chart_type_from_query

q = 'Son 3 aydaki satışları karşılaştır ve bunlar içinde hangi kategoriler ne kadar satmış onu da gösteren sunbrust grafik ver'
result = _detect_chart_type_from_query(q)
assert result == 'sunburst', f'Expected sunburst, got {result!r}'

assert _detect_chart_type_from_query('heatmap göster') == 'heatmap'
assert _detect_chart_type_from_query('pasta grafik') == 'pie_chart'
assert _detect_chart_type_from_query('kabartma tekniği') is None
assert _detect_chart_type_from_query('herhangi bir grafik yok') is None
print('All smoke checks passed')
"
```

Beklenen çıktı: `All smoke checks passed`

- [ ] **Step 3: Final commit log kontrol**

```bash
git log --oneline -3
```

Son 2 commit görünmeli:
```
<hash> fix: apply deterministic chart type fallback after LLM in classify_intent_node
<hash> feat: add _detect_chart_type_from_query deterministic fallback
```

---

## Özet

| Task | Değişiklik | Satır sayısı |
|---|---|---|
| Task 1 | `_detect_chart_type_from_query` + keyword map | ~45 satır (nodes.py) |
| Task 2 | Fallback bloğu in `classify_intent_node` | ~8 satır (nodes.py) |
| Testler | `test_chart_type_detection.py` | ~100 satır |

**Toplam prod kod değişikliği: ~53 satır. Sıfır yeni dosya, sıfır yeni node, sıfır mimari değişiklik.**
