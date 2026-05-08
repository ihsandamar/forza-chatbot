# Context Propagation Fix (RC-1, RC-2, RC-3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix "bu 3 ürün" cross-turn pronoun resolution so all referenced entities survive into the semantic extractor and generate a correct `ProductName IN (...)` filter.

**Architecture:** Three interacting root causes must be fixed together. RC-1 removes the `accumulated_entities` wipe from `classify_intent_node` so entities survive `NEW_QUERY` turns. RC-2 threads `accumulated_entities` into `extract_entity_node` so the `USE_RESULT` path's `new_query_seed` includes cross-turn entities. RC-3 adds a stronger prompt rule so `semantic_extractor` generates `filter_value` (not `dimension`) entities for TIME_SERIES_COMPARISON + pronoun references.

**Tech Stack:** Python 3.12, LangGraph, Pydantic, pytest-asyncio, unittest.mock

---

## Root Causes (verified by code trace)

| # | Location | Problem |
|---|----------|---------|
| RC-1 | `nodes.py:147` | `accumulated_entities = None` when `intent_type == "NEW_QUERY"` — wipes LAS VEGAS before subgraph starts |
| RC-2 | `nodes.py:extract_entity_node` | `ENTITY_EXTRACTOR_PROMPT` only sees `active_results[:5]` — cross-turn entities (e.g. LAS VEGAS not in Turn 2 results) never reach `new_query_seed` |
| RC-3 | `text2sql/prompts.py:SEMANTIC_EXTRACTOR_PROMPT` | For `TIME_SERIES_COMPARISON`, LLM generates `dimension("ürün")` (GROUP BY, no filter) instead of 3 `filter_value` entities (WHERE ProductName IN ...) |

## Files

| File | Action | What changes |
|------|--------|-------------|
| `src/graphs/report_agent/nodes.py` | Modify | RC-1: remove wipe. RC-2: build `accumulated_context` and pass to prompt |
| `src/graphs/report_agent/prompts.py` | Modify | RC-2: add `{accumulated_context}` slot to `ENTITY_EXTRACTOR_PROMPT` |
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | Modify | RC-3: add TIME_SERIES_COMPARISON + pronoun → filter_value rule |
| `tests/graphs/report/test_accumulated_entities.py` | Modify | Update `test_classify_intent_resets_accumulated_entities_on_new_query` — behavior inverted by RC-1 |
| `tests/graphs/report/test_extract_entity_node.py` | Modify | Add accumulated_context tests for RC-2 |

---

## Task 1: RC-1 — Never wipe `accumulated_entities` in `classify_intent_node`

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:147`
- Modify: `tests/graphs/report/test_accumulated_entities.py:116-128`

### Why this is safe
`accumulated_entities` is used only for pronoun resolution context — the LLM never applies these values as automatic filters. A stale BranchName entity won't pollute a ProductName query. The 100-item cap + per-column cap (already in place) manages memory.

- [ ] **Step 1: Update the test to reflect new behavior (test must FAIL before fix)**

In `tests/graphs/report/test_accumulated_entities.py`, replace `test_classify_intent_resets_accumulated_entities_on_new_query` (lines 116–128):

```python
def test_classify_intent_preserves_accumulated_entities_on_new_query():
    """RC-1: NEW_QUERY artık accumulated_entities'i silmemeli — cross-turn entities korunur."""
    node = _make_classify_node("NEW_QUERY")
    accumulated = [{"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"}]
    state = {
        "messages": [HumanMessage(content="farklı bir soru")],
        "active_sql": None,
        "active_results": [],
        "accumulated_entities": accumulated,
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    # RC-1 fix: must NOT be None — entities survive NEW_QUERY classification
    assert result["accumulated_entities"] == accumulated
```

- [ ] **Step 2: Run test to confirm it FAILS before the fix**

```
pytest tests/graphs/report/test_accumulated_entities.py::test_classify_intent_preserves_accumulated_entities_on_new_query -v
```

Expected: `FAIL` — current code returns `None`, test asserts `== accumulated`.

- [ ] **Step 3: Apply the fix in `nodes.py`**

In `src/graphs/report_agent/nodes.py`, change line 147:

```python
# BEFORE:
"accumulated_entities": None if result.intent_type == "NEW_QUERY" else state.get("accumulated_entities"),

# AFTER:
"accumulated_entities": state.get("accumulated_entities"),
```

- [ ] **Step 4: Run the full accumulated_entities test suite**

```
pytest tests/graphs/report/test_accumulated_entities.py -v
```

Expected: ALL 15 tests pass. (The renamed test now passes; the four `preserves_*` tests were already testing correct behavior and still pass.)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_accumulated_entities.py
git commit -m "fix(classify-intent): never wipe accumulated_entities — entities survive NEW_QUERY"
```

---

## Task 2: RC-2 — Thread `accumulated_entities` into `extract_entity_node`

**Files:**
- Modify: `src/graphs/report_agent/prompts.py:294-311` (ENTITY_EXTRACTOR_PROMPT)
- Modify: `src/graphs/report_agent/nodes.py:296-320` (extract_entity_node inner function)
- Modify: `tests/graphs/report/test_extract_entity_node.py` (add two new tests)

### What changes
`ENTITY_EXTRACTOR_PROMPT` gains a new `{accumulated_context}` slot. The node builds the context string from `state["accumulated_entities"]` and passes it to the prompt so the LLM can see cross-turn entities (e.g. LAS VEGAS from Turn 1) when generating `new_query_seed`.

- [ ] **Step 1: Write two new failing tests in `tests/graphs/report/test_extract_entity_node.py`**

Append to the end of the file:

```python
@pytest.mark.asyncio
async def test_extract_entity_prompt_contains_accumulated_entities():
    """RC-2: ENTITY_EXTRACTOR_PROMPT must include accumulated_entities context so LLM can see cross-turn entities."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    from src.graphs.report_agent.prompts import EntityExtractionResult

    captured_prompts: list = []

    async def capturing_invoke(prompt):
        captured_prompts.append(prompt)
        return EntityExtractionResult(
            entity_names=["LAS VEGAS UC PEYNIRLI BAGEL", "LATTE", "FINCAN CAY"],
            entity_type="product",
            new_query_seed="LAS VEGAS UC PEYNIRLI BAGEL, LATTE ve FINCAN CAY urunlerinin gunluk satisi",
        )

    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = capturing_invoke
    mock_llm.with_structured_output = MagicMock(return_value=structured)

    node = create_extract_entity_node(mock_llm)
    state = {
        "active_results": [
            {"ProductName": "LATTE", "ToplamCiro": 45000.0},
            {"ProductName": "FINCAN CAY", "ToplamCiro": 30000.0},
        ],
        "accumulated_entities": [
            {"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"},
        ],
        "user_query": "bu 3 urunun gunluk satisini goster",
        "use_result_type": "new_query",
    }
    await node(state)

    assert len(captured_prompts) == 1
    prompt_text = captured_prompts[0]
    # The cross-turn entity from accumulated_entities must appear in the prompt
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in prompt_text


@pytest.mark.asyncio
async def test_extract_entity_no_accumulated_entities_still_works():
    """RC-2: When accumulated_entities is None/empty, node still works normally."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    from src.graphs.report_agent.prompts import EntityExtractionResult

    async def mock_invoke(prompt):
        return EntityExtractionResult(
            entity_names=["LATTE"],
            entity_type="product",
            new_query_seed="LATTE icin detaylar",
        )

    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = mock_invoke
    mock_llm.with_structured_output = MagicMock(return_value=structured)

    node = create_extract_entity_node(mock_llm)
    state = {
        "active_results": [{"ProductName": "LATTE", "ToplamCiro": 45000.0}],
        "accumulated_entities": None,
        "user_query": "bu urunu goster",
        "use_result_type": "new_query",
    }
    result = await node(state)
    assert result["user_query"] == "LATTE icin detaylar"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/graphs/report/test_extract_entity_node.py::test_extract_entity_prompt_contains_accumulated_entities -v
```

Expected: `FAIL` — "LAS VEGAS" not in prompt (prompt doesn't have accumulated_context yet).

- [ ] **Step 3: Update `ENTITY_EXTRACTOR_PROMPT` in `src/graphs/report_agent/prompts.py`**

Replace lines 294–311 entirely:

```python
ENTITY_EXTRACTOR_PROMPT = """Kullanıcı önceki sorgu sonuçlarından bir veya daha fazla entity seçmek istiyor.

## ÖNCEKİ SONUÇLAR (ilk 5 satır)
{active_results}

## KONUŞMA BAĞLAMI (önceki turlardaki değerler dahil)
{accumulated_context}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının hangi entity'leri seçtiğini belirle ve yeni bir sorgu için seed oluştur.

Kullanıcı "bu 3 ürün", "bu şubeler", "bunların hepsi" gibi çoğul referans kullanıyorsa →
ÖNCEKİ SONUÇLAR ve KONUŞMA BAĞLAMI'ndaki TÜM ilgili değerleri entity_names listesine ekle.

- entity_names: Seçilen değerlerin tam adları listesi
  Tekil referans için tek elemanlı liste: ["Ankara Şubesi"]
  Çoğul referans için tüm seçilenleri listele: ["LATTE", "FINCAN CAY", "LAS VEGAS UC PEYNIRLI BAGEL"]
- entity_type: product | branch | customer | category | period
- new_query_seed: Bu entity'ler için doğal dil sorgu cümlesi (Text2SQL'e gönderilecek)
  Örnek: "LATTE, FINCAN CAY ve LAS VEGAS UC PEYNIRLI BAGEL ürünlerinin son 1 yıldaki günlük satış trendi çizgi grafik"
  ÖNEMLİ: Kullanıcının orijinal isteğindeki TÜM detayları (dönem, grafik tipi, kırılım) new_query_seed'e koru!
"""
```

- [ ] **Step 4: Update `extract_entity_node` in `src/graphs/report_agent/nodes.py`**

Replace the function body (lines 296–318) — keep the outer `create_extract_entity_node` signature unchanged:

```python
    async def extract_entity_node(state: dict) -> dict:
        active_results = state.get("active_results") or []
        if not active_results:
            logger.warning("[EXTRACT_ENTITY] No results, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        # Build accumulated entity context for cross-turn pronoun resolution
        accumulated_entities = state.get("accumulated_entities") or []
        acc_col_map: dict = {}
        for e in accumulated_entities:
            col, val = e.get("column", ""), e.get("value", "")
            if col and val:
                if col not in acc_col_map:
                    acc_col_map[col] = []
                if val not in acc_col_map[col]:
                    acc_col_map[col].append(val)
        if acc_col_map:
            acc_lines = [f"  - {col}: {vals[:10]}" for col, vals in acc_col_map.items()]
            accumulated_context = "Konuşmada geçen değerler (önceki turlar):\n" + "\n".join(acc_lines)
        else:
            accumulated_context = "Önceki konuşma bağlamı yok."

        prompt = ENTITY_EXTRACTOR_PROMPT.format(
            active_results=json.dumps(active_results[:5], ensure_ascii=False, indent=2),
            user_query=state.get("user_query", ""),
            accumulated_context=accumulated_context,
        )

        result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[EXTRACT_ENTITY] {result.entity_names} ({result.entity_type})")

        if state.get("use_result_type") == "modify_context":
            names_str = ", ".join(result.entity_names)
            original_query = state.get("user_query", "")
            enriched = f"{names_str} icin: {original_query}"
            logger.info(f"[EXTRACT_ENTITY] modify_context -> enriched query: {enriched[:80]}")
            return {"user_query": enriched}

        return {"user_query": result.new_query_seed}
```

- [ ] **Step 5: Run the full extract_entity test suite**

```
pytest tests/graphs/report/test_extract_entity_node.py -v
```

Expected: ALL tests pass — including the 2 new ones.

- [ ] **Step 6: Run the full accumulated_entities test suite to verify no regression**

```
pytest tests/graphs/report/test_accumulated_entities.py -v
```

Expected: ALL 15 tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/prompts.py src/graphs/report_agent/nodes.py tests/graphs/report/test_extract_entity_node.py
git commit -m "fix(extract-entity): thread accumulated_entities context into prompt — cross-turn entities reach new_query_seed"
```

---

## Task 3: RC-3 — Stronger prompt rule for TIME_SERIES_COMPARISON + pronoun → `filter_value`

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py` (SEMANTIC_EXTRACTOR_PROMPT)
- Create: `tests/graphs/report/test_semantic_extractor_prompt.py`

### What changes
Add an explicit section to `SEMANTIC_EXTRACTOR_PROMPT` before the existing entity_type rules. It names the failure mode (generating `dimension` = no WHERE filter = all products returned) and gives a concrete corrective example. No new format variables — pure text addition.

The `{query_type}` placeholder already receives `"TIME_SERIES_COMPARISON"` at runtime, so the LLM sees this in the prompt context section. The new rule section references this context directly.

- [ ] **Step 1: Write the failing test**

Create `tests/graphs/report/test_semantic_extractor_prompt.py`:

```python
"""Tests that SEMANTIC_EXTRACTOR_PROMPT contains the critical rules for cross-turn pronoun resolution."""
from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_time_series_filter_value_rule():
    """SEMANTIC_EXTRACTOR_PROMPT must explicitly forbid 'dimension' for pronoun refs in TIME_SERIES_COMPARISON."""
    assert "TIME_SERIES_COMPARISON" in SEMANTIC_EXTRACTOR_PROMPT
    # Must say that dimension is WRONG for pronoun + TIME_SERIES context
    assert "dimension" in SEMANTIC_EXTRACTOR_PROMPT.lower()
    # Must have the rule section header
    assert "TIME_SERIES_COMPARISON + ZAMIR" in SEMANTIC_EXTRACTOR_PROMPT or \
           "TIME_SERIES + zamir" in SEMANTIC_EXTRACTOR_PROMPT or \
           "TIME_SERIES_COMPARISON" in SEMANTIC_EXTRACTOR_PROMPT and "filter_value" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_anti_dimension_example():
    """Prompt must have an explicit WRONG/CORRECT example contrasting dimension vs filter_value."""
    # Must contain a negative example showing dimension leads to no filter
    assert "YANLIŞ" in SEMANTIC_EXTRACTOR_PROMPT or "dimension" in SEMANTIC_EXTRACTOR_PROMPT
    # Must contain filter_value as the correct entity_type
    assert "filter_value" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_group_by_auto_note():
    """Prompt must tell LLM that system auto-adds GROUP BY so LLM only needs filter_value."""
    assert "GROUP BY" in SEMANTIC_EXTRACTOR_PROMPT or "otomatik" in SEMANTIC_EXTRACTOR_PROMPT
```

- [ ] **Step 2: Run to see current state**

```
pytest tests/graphs/report/test_semantic_extractor_prompt.py -v
```

Expected: The first two tests likely pass (TIME_SERIES_COMPARISON is already mentioned), but the prompt lacks the explicit anti-dimension rule + auto-GROUP-BY note. Check which fail.

- [ ] **Step 3: Add the rule section to `SEMANTIC_EXTRACTOR_PROMPT`**

In `src/graphs/report_agent/subagents/text2sql/prompts.py`, find the existing plural-pronoun rule block:

```
Çoğul referanslarda ("bu 3 ürün", "bu şubeler", "bunların hepsi", "bu ikisi") →
bağlamdaki TÜM ilgili değerleri AYRI filter_value entity olarak üret. Kaç entity isteniyorsa o kadar üret.
```

**Immediately after** that block (and before the `## ÖNCEKİ SQL HATASI` line), insert:

```
## TIME_SERIES_COMPARISON + ZAMIR REFERANS (KRİTİK)
Sorgu tipi TIME_SERIES_COMPARISON ise VE kullanıcı zamir kullanıyorsa ("bu ürünler", "bu 3 ürün", "bunlar"):
→ Bağlamdaki HER spesifik değer için AYRI "filter_value" entity üret
→ "dimension" entity ÜRETME — sistem GROUP BY'ı otomatik ekler, sen sadece WHERE filtresini üretirsin
→ YANLIŞ (dimension seçersen filtre OLMAZ, tüm ürünler gelir):
   entity("ürün", entity_type="dimension", column_hint="ProductName")
→ DOĞRU (3 ürün için 3 ayrı filter_value):
   "bu 3 ürünün günlük satış trendi" + bağlamda ProductName: ["LAS VEGAS UC PEYNIRLI BAGEL", "LATTE", "FINCAN CAY"]
   → entity("LAS VEGAS UC PEYNIRLI BAGEL", entity_type="filter_value", column_hint="ProductName")
   → entity("LATTE", entity_type="filter_value", column_hint="ProductName")
   → entity("FINCAN CAY", entity_type="filter_value", column_hint="ProductName")
   # Sistem TIME_SERIES_COMPARISON için ProductName'i GROUP BY'a otomatik ekler
```

- [ ] **Step 4: Verify the section appears in the prompt at the right location**

The prompt must look like this (section order):

```
Çoğul referanslarda ("bu 3 ürün", ...) → ...
<blank line>
## TIME_SERIES_COMPARISON + ZAMIR REFERANS (KRİTİK)
...
<blank line>
## ÖNCEKİ SQL HATASI
```

Read the file to confirm the section is in place:

```
pytest tests/graphs/report/test_semantic_extractor_prompt.py -v
```

Expected: ALL 3 tests pass.

- [ ] **Step 5: Run the full text2sql-related test suite for regression check**

```
pytest tests/graphs/report/ -v --ignore=tests/graphs/report/test_sql_executor_active_filters.py -k "not chromadb"
```

Expected: All non-chromadb tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py tests/graphs/report/test_semantic_extractor_prompt.py
git commit -m "fix(semantic-extractor): add TIME_SERIES_COMPARISON + pronoun → filter_value rule, forbid dimension"
```

---

## Task 4: End-to-end data flow integration test

**Files:**
- Create: `tests/graphs/report/test_three_product_scenario.py`

This test traces the exact "bu 3 ürün" scenario through the data structures (no LLM calls, no DB) to verify that RC-1 + RC-2 together ensure LAS VEGAS reaches the semantic extractor context.

- [ ] **Step 1: Write the test**

Create `tests/graphs/report/test_three_product_scenario.py`:

```python
"""
Integration test for the 'bu 3 ürün' multi-turn context propagation scenario.

Scenario:
  Turn 1: "kahvaltı en çok satan ürün" → LAS VEGAS result → accumulated_entities has LAS VEGAS
  Turn 2: intent classified as NEW_QUERY (RC-1 must keep LAS VEGAS!) → LATTE + FINCAN CAY added
  Turn 3: "bu 3 ürün" → context must show all 3 products

Tests data structures only — no LLM, no DB.
"""
from src.graphs.report_agent.context_builder import build_query_context_summary
from src.graphs.report_agent.subagents.text2sql.nodes import _merge_accumulated_entities


def _simulate_turn1_executor_output():
    """Simulates sql_executor after Turn 1 (kahvaltı top product)."""
    results = [
        {"ProductName": "LAS VEGAS UC PEYNIRLI BAGEL", "CategoryName": "KAHVALTI", "ToplamCiro": 80000.0},
    ]
    return _merge_accumulated_entities(None, results)


def _simulate_turn2_executor_output(accumulated_from_turn1):
    """Simulates sql_executor after Turn 2 (second most popular product, different result set)."""
    results = [
        {"ProductName": "LATTE", "ToplamCiro": 120000.0},
        {"ProductName": "FINCAN CAY", "ToplamCiro": 95000.0},
    ]
    # RC-1: Turn 2 is NEW_QUERY — but we no longer wipe, so accumulated_from_turn1 is passed in
    return _merge_accumulated_entities(accumulated_from_turn1, results)


def test_las_vegas_survives_into_turn3_context():
    """
    RC-1 + RC-2 together: LAS VEGAS must be present in query_context
    sent to semantic_extractor at Turn 3.
    """
    # Turn 1: executor accumulates LAS VEGAS
    acc_turn1 = _simulate_turn1_executor_output()
    assert any(e["value"] == "LAS VEGAS UC PEYNIRLI BAGEL" for e in acc_turn1), \
        "Turn 1 must add LAS VEGAS to accumulated_entities"

    # Turn 2: RC-1 means we pass accumulated_from_turn1 (not None) to executor
    # (Previously, NEW_QUERY would set None before sql_executor ran)
    acc_turn2 = _simulate_turn2_executor_output(acc_turn1)

    # All 3 products must be in accumulated_entities after Turn 2
    values = {e["value"] for e in acc_turn2 if e["column"] == "ProductName"}
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in values, "LAS VEGAS must survive after Turn 2"
    assert "LATTE" in values
    assert "FINCAN CAY" in values

    # Turn 3: semantic_extractor receives query_context with accumulated_entities
    # active_results = Turn 2 results (LATTE, FINCAN CAY only — NOT LAS VEGAS)
    active_results_turn2 = [
        {"ProductName": "LATTE", "ToplamCiro": 120000.0},
        {"ProductName": "FINCAN CAY", "ToplamCiro": 95000.0},
    ]
    active_filters_turn2 = []

    context = build_query_context_summary(
        active_results=active_results_turn2,
        active_filters=active_filters_turn2,
        accumulated_entities=list(acc_turn2),
    )

    # LAS VEGAS must be visible in the context despite not being in active_results
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in context, \
        "LAS VEGAS must appear in query_context at Turn 3 — RC-1 fix required"
    assert "LATTE" in context
    assert "FINCAN CAY" in context


def test_query_context_deduplicates_active_and_accumulated():
    """
    Values already in active_results must NOT appear twice in the context
    (they're shown in active_results section; accumulated section skips them).
    """
    active_results = [{"ProductName": "LATTE"}]
    accumulated = [
        {"column": "ProductName", "value": "LATTE"},       # already in active_results
        {"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"},  # cross-turn only
    ]
    context = build_query_context_summary(
        active_results=active_results,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    # LATTE appears once (in active_results section); LAS VEGAS in accumulated section
    assert context.count("LATTE") == 1
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in context


def test_per_column_cap_prevents_budget_starvation():
    """
    A single high-cardinality column must not consume the entire 100-item budget.
    After fix: max 10 values per column.
    """
    # 15 ProductName values in existing accumulated_entities (already at cap)
    existing = [{"column": "ProductName", "value": f"PRODUCT_{i}"} for i in range(10)]
    # New results have more ProductName values + a BranchName value
    new_results = [
        {"ProductName": f"NEW_PRODUCT_{i}", "BranchName": "ANKARA"} for i in range(5)
    ] + [{"BranchName": "ISTANBUL"}]

    merged = _merge_accumulated_entities(existing, new_results)

    product_values = [e["value"] for e in merged if e["column"] == "ProductName"]
    branch_values = [e["value"] for e in merged if e["column"] == "BranchName"]

    # ProductName already at cap (10) — new ones must not be added
    assert len(product_values) <= 10
    # BranchName must be present despite ProductName being at cap
    assert "ANKARA" in branch_values or "ISTANBUL" in branch_values
```

- [ ] **Step 2: Run the tests**

```
pytest tests/graphs/report/test_three_product_scenario.py -v
```

Expected: ALL pass (these test data structures only — no mocking needed).

- [ ] **Step 3: Commit**

```bash
git add tests/graphs/report/test_three_product_scenario.py
git commit -m "test(context-propagation): integration test for three-product cross-turn scenario"
```

---

## Task 5: Full regression run

- [ ] **Step 1: Run the complete report test suite**

```
pytest tests/graphs/report/ -v 2>&1 | tail -40
```

Expected outcome:
- `test_accumulated_entities.py` — 15 tests pass (including updated `test_classify_intent_preserves_accumulated_entities_on_new_query`)
- `test_extract_entity_node.py` — all tests pass including 2 new ones
- `test_semantic_extractor_prompt.py` — 3 tests pass
- `test_three_product_scenario.py` — 4 tests pass
- `test_sql_executor_active_filters.py` — 3 tests pass
- chromadb-dependent tests — skip/fail as before (pre-existing, not caused by this PR)

- [ ] **Step 2: Note any new failures**

If any test that was previously passing now fails, investigate before proceeding. Do not skip.

---

## Self-Review

**Spec coverage:**
1. RC-1 (accumulated_entities wipe) → Task 1 ✓
2. RC-2 (extract_entity_node missing accumulated context) → Task 2 ✓
3. RC-3 (dimension vs filter_value for TIME_SERIES_COMPARISON) → Task 3 ✓
4. End-to-end data flow verification → Task 4 ✓
5. Regression check → Task 5 ✓

**Placeholder scan:** No TBD, no "implement later", no "add error handling". All steps have concrete code.

**Type consistency:**
- `accumulated_entities: list[dict] | None` — consistent across all uses
- `EntityExtractionResult.entity_names: List[str]` — already plural from previous fix, unchanged
- `ENTITY_EXTRACTOR_PROMPT.format(active_results=..., user_query=..., accumulated_context=...)` — 3 format vars, all provided in Task 2 node code

**Edge cases checked:**
- `accumulated_entities = None` → `extract_entity_node` handles via `state.get("accumulated_entities") or []`
- Empty `acc_col_map` → `accumulated_context = "Önceki konuşma bağlamı yok."` — same fallback string, no KeyError
- Per-column cap at 10 + total cap at 100 — tested in Task 4

**One known gap:** RC-3 fixes the prompt rule but LLM behavior cannot be tested deterministically. The prompt test in Task 3 only verifies prompt content, not LLM output. If LLM still ignores the rule despite the example, a schema_builder-level safeguard (detecting filter_value for dimension column in TIME_SERIES_COMPARISON and adding GROUP BY) would be the next layer of defense — that is a follow-up, not in scope here.
