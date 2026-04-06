# Parallel Chart Type Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `classify_intent_node` içinde chart type tespitini ayrı, odaklı bir LLM çağrısına taşı; `asyncio.gather` ile intent LLM çağrısı ile paralel çalıştır.

**Architecture:** `prompts.py`'a `ChartTypeResult` modeli ve `CHART_TYPE_PROMPT` eklenir. `IntentClassificationResult`'tan `requested_chart_type` kaldırılır. `classify_intent_node` içinde `asyncio.gather(return_exceptions=True)` ile iki LLM çağrısı paralel yapılır; chart_type local variable olarak hesaplanır.

**Tech Stack:** Python asyncio, LangChain `with_structured_output`, Pydantic v2, pytest-asyncio

---

## Dosya Haritası

| Dosya | İşlem | Ne değişiyor |
|---|---|---|
| `src/graphs/report_agent/prompts.py` | Modify | `ChartTypeResult` + `CHART_TYPE_PROMPT` ekle; `IntentClassificationResult`'tan `requested_chart_type` kaldır; `INTENT_CLASSIFIER_PROMPT`'tan `requested_chart_type` bölümünü kaldır |
| `src/graphs/report_agent/nodes.py` | Modify | `asyncio` import; `chart_llm` instance; `asyncio.gather`; model_copy satırını kaldır |
| `tests/graphs/report/test_chart_type_detection.py` | Modify | Mock'u iki chain için güncelle; yeni test ekle (exception degrade + parallel path) |

---

## Task 1: `ChartTypeResult` ve `CHART_TYPE_PROMPT` ekle

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`

- [ ] **Step 1: `IntentClassificationResult`'tan `requested_chart_type` kaldır**

  `prompts.py`'da `IntentClassificationResult` sınıfından şu satırları kaldır:

  ```python
  # KALDIR:
  requested_chart_type: Optional[Literal[
      "bar_chart", "line_chart", "pie_chart", "scatter_chart",
      "heatmap", "sunburst", "treemap",
  ]] = None  # Kullanıcı açıkça istediği grafik tipi (typo toleranslı)
  ```

- [ ] **Step 2: `ChartTypeResult` modelini ekle**

  `IntentClassificationResult` tanımından hemen sonra ekle:

  ```python
  class ChartTypeResult(BaseModel):
      """Dedicated chart type detection — classify_intent ile paralel çalışır."""
      chart_type: Optional[Literal[
          "bar_chart", "line_chart", "pie_chart", "scatter_chart",
          "heatmap", "sunburst", "treemap",
      ]] = None
  ```

- [ ] **Step 3: `CHART_TYPE_PROMPT` ekle**

  `INTENT_CLASSIFIER_PROMPT` sabitinden önce ekle:

  ```python
  CHART_TYPE_PROMPT = """Kullanıcı sorgusuna göre en uygun grafik tipini belirle.

  Sorgu: {user_query}

  ## KURALLAR

  Aşağıdaki öncelik sırasıyla karar ver:

  1. Kullanıcı açıkça bir grafik tipi belirttiyse → o tipi döndür (typo toleranslı: "sunbrust"→sunburst, "hetmap"→heatmap)

  2. Grafik tipi belirtilmemişse, sorgu yapısına göre:
     - Zaman + kategori/boyut karşılaştırması (hiyerarşik, çok boyutlu: "aylık kategoriler", "dönemsel kırılım") → sunburst
     - Hiyerarşik part-of-whole, zaman boyutu yok ("kategorilerin alt kırılımı", "grup içi dağılım") → treemap
     - Saf zaman serisi / trend (tek metrik: "aylık ciro", "günlük satış trendi") → line_chart
     - Kategoriler arası flat karşılaştırma ("en çok satan", "şubeleri karşılaştır") → bar_chart
     - Oran / pay / yüzdesel dağılım ("payı nedir", "yüzde dağılım") → pie_chart
     - İki boyutlu dağılım matrisi (entity × periyot: "saatlere göre günler") → heatmap
     - İki sayısal değişken korelasyonu ("X arttıkça Y") → scatter_chart

  3. Grafik talebi belirsizse veya sadece veri/tablo isteniyorsa → null

  Yalnızca chart_type alanını doldur. Açıklama yapma.
  """
  ```

- [ ] **Step 4: `INTENT_CLASSIFIER_PROMPT`'tan `requested_chart_type` bölümünü kaldır**

  `INTENT_CLASSIFIER_PROMPT` içindeki şu bölümü tamamen kaldır:

  ```
  **requested_chart_type:**
  İki durumda doldur:
  1. Kullanıcı açıkça bir grafik tipi belirttiyse (typo toleranslı):
     ...
  2. Kullanıcı grafik istiyor (wants_visualization=True) ...
  ```

  Yerine tek satır bırak:
  ```
  requested_chart_type alanı bu modelde yoktur — ayrı bir LLM çağrısı ile belirlenir.
  ```

  **NOT:** Bu satır aslında prompt'ta gereksiz — modelde alan olmadığı için LLM zaten dolduramaz. Ama karışıklık olmaması için ufak bir not bırakmak iyi pratik.

- [ ] **Step 5: `__all__` veya import listesi varsa güncelle**

  Dosyada `__all__` tanımı varsa `ChartTypeResult` ve `CHART_TYPE_PROMPT`'u ekle. Yoksa bu adımı atla.

- [ ] **Step 6: Commit**

  ```bash
  git add src/graphs/report_agent/prompts.py
  git commit -m "feat: add ChartTypeResult + CHART_TYPE_PROMPT, remove requested_chart_type from IntentClassificationResult"
  ```

---

## Task 2: `classify_intent_node` güncelle

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`

- [ ] **Step 1: Import ekle**

  `nodes.py` en üstüne `import asyncio` ekle (zaten yoksa).

  `prompts.py`'dan import listesine `ChartTypeResult` ve `CHART_TYPE_PROMPT` ekle:

  ```python
  from src.graphs.report_agent.prompts import (
      ChartTypeResult,           # YENİ
      EntityExtractionResult,
      IntentClassificationResult,
      QueryClarificationResult,
      SqlModificationResult,
      CHART_TYPE_PROMPT,         # YENİ
      ENTITY_EXTRACTOR_PROMPT,
      INTENT_CLASSIFIER_PROMPT,
      QUERY_CLARIFICATION_PROMPT,
      SQL_MODIFIER_PROMPT,
  )
  ```

- [ ] **Step 2: `create_classify_intent_node` içinde ikinci LLM chain ekle**

  Mevcut:
  ```python
  def create_classify_intent_node(llm) -> Callable:
      structured_llm = llm.with_structured_output(IntentClassificationResult)
  ```

  Yeni:
  ```python
  def create_classify_intent_node(llm) -> Callable:
      structured_llm = llm.with_structured_output(IntentClassificationResult)
      chart_llm = llm.with_structured_output(ChartTypeResult)
  ```

- [ ] **Step 3: Tek LLM çağrısını `asyncio.gather` ile değiştir**

  Mevcut (nodes.py ~line 149):
  ```python
  result: IntentClassificationResult = await structured_llm.ainvoke(prompt)
  ```

  Yeni:
  ```python
  results = await asyncio.gather(
      structured_llm.ainvoke(prompt),
      chart_llm.ainvoke(CHART_TYPE_PROMPT.format(user_query=user_query)),
      return_exceptions=True,
  )
  intent_raw, chart_raw = results[0], results[1]

  # intent_llm hatası: normal exception mekanizmasına bırak
  if isinstance(intent_raw, Exception):
      raise intent_raw

  result: IntentClassificationResult = intent_raw

  # chart_llm hatası → graceful degrade, deterministic fallback'e düşer
  chart_type_from_llm: Optional[str] = None
  if not isinstance(chart_raw, Exception) and chart_raw is not None:
      chart_type_from_llm = chart_raw.chart_type
  ```

- [ ] **Step 4: model_copy satırını kaldır, local variable kullan**

  Mevcut kod bloğu (kaldır):
  ```python
  _wants_viz_effective = result.wants_visualization or (result.use_result_type == "revisualize")
  if _wants_viz_effective and result.requested_chart_type is None:
      _detected = _detect_chart_type_from_query(user_query)
      if _detected:
          result = result.model_copy(update={"requested_chart_type": _detected})
          logger.info(
              f"[CLASSIFY] Fallback chart type detected: '{_detected}' from query"
          )
  ```

  Yerine koy (gather bloğundan hemen sonra):
  ```python
  # Merge: chart_type sadece visualization isteklerinde kullanılır
  _wants_viz_effective = result.wants_visualization or (result.use_result_type == "revisualize")
  chart_type: Optional[str] = None
  if _wants_viz_effective:
      chart_type = chart_type_from_llm
      if chart_type is None:
          chart_type = _detect_chart_type_from_query(user_query)
          if chart_type:
              logger.info(f"[CLASSIFY] Fallback chart type: '{chart_type}' from query keywords")
  ```

- [ ] **Step 5: return dict'te `requested_chart_type` kaynağını güncelle**

  Mevcut (~line 217):
  ```python
  "requested_chart_type": result.requested_chart_type,
  ```

  Yeni:
  ```python
  "requested_chart_type": chart_type,
  ```

  Aynı satırda `wants_visualization` için (`wants_viz` zaten mevcut kod ile doğru hesaplanıyor):
  ```python
  "wants_visualization": wants_viz,   # Bu satır zaten var, değişmez
  ```

- [ ] **Step 6: Log satırı ekle (opsiyonel ama izlenebilirlik için)**

  `chart_type` hesaplandıktan sonra:
  ```python
  if _wants_viz_effective:
      logger.info(f"[CLASSIFY] chart_type={chart_type} (llm={chart_type_from_llm})")
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add src/graphs/report_agent/nodes.py
  git commit -m "feat: parallel chart type LLM call with asyncio.gather in classify_intent_node"
  ```

---

## Task 3: Testleri güncelle

**Files:**
- Modify: `tests/graphs/report/test_chart_type_detection.py`

Mevcut `_make_mock_llm` helper tek bir `with_structured_output` mock döndürüyor. Yeni kod iki kez çağırıyor — `IntentClassificationResult` için ve `ChartTypeResult` için. Mock'u güncellememiz gerekiyor.

- [ ] **Step 1: `_make_mock_llm` helper'ı iki chain için güncelle**

  Mevcut:
  ```python
  def _make_mock_llm(intent_type=..., ..., requested_chart_type=None):
      mock_result = IntentClassificationResult(
          ..., requested_chart_type=requested_chart_type
      )
      mock_llm = MagicMock()
      structured = MagicMock()
      structured.ainvoke = AsyncMock(return_value=mock_result)
      mock_llm.with_structured_output = MagicMock(return_value=structured)
      return mock_llm
  ```

  Yeni (`requested_chart_type` artık `ChartTypeResult`'tan geliyor):
  ```python
  def _make_mock_llm(
      intent_type="NEW_QUERY",
      query_type="COMPARISON",
      confidence=0.9,
      wants_visualization=True,
      use_result_type=None,
      chart_type=None,               # YENİ: ChartTypeResult'tan gelecek
      chart_llm_raises=None,         # YENİ: chart LLM exception testi için
  ):
      from src.graphs.report_agent.prompts import IntentClassificationResult, ChartTypeResult

      mock_intent = IntentClassificationResult(
          intent_type=intent_type,
          query_type=query_type,
          confidence=confidence,
          wants_visualization=wants_visualization,
          use_result_type=use_result_type,
          # requested_chart_type artık yok
      )
      mock_chart = ChartTypeResult(chart_type=chart_type)

      intent_chain = MagicMock()
      intent_chain.ainvoke = AsyncMock(return_value=mock_intent)

      chart_chain = MagicMock()
      if chart_llm_raises:
          chart_chain.ainvoke = AsyncMock(side_effect=chart_llm_raises)
      else:
          chart_chain.ainvoke = AsyncMock(return_value=mock_chart)

      mock_llm = MagicMock()
      # with_structured_output çağrı sırasına göre farklı chain döndürür
      mock_llm.with_structured_output = MagicMock(
          side_effect=[intent_chain, chart_chain]
      )
      return mock_llm
  ```

- [ ] **Step 2: Mevcut testleri yeni `_make_mock_llm` signature'ına güncelle**

  `requested_chart_type=` parametresini `chart_type=` olarak değiştir.
  `test_fallback_does_not_override_when_llm_returns_value` testinde:
  ```python
  # ESKİ:
  llm = _make_mock_llm(wants_visualization=True, requested_chart_type="bar_chart")
  # YENİ:
  llm = _make_mock_llm(wants_visualization=True, chart_type="bar_chart")
  ```

  Diğer testler için `requested_chart_type=None` → `chart_type=None` güncelle.

- [ ] **Step 3: Yeni test — chart LLM exception → graceful degrade**

  ```python
  @pytest.mark.asyncio
  async def test_chart_llm_exception_falls_back_to_keyword_detection():
      """chart_llm Exception fırlatırsa keyword fallback devreye girmeli, node çökmemeli."""
      from langchain_core.messages import HumanMessage
      from src.graphs.report_agent.nodes import create_classify_intent_node

      llm = _make_mock_llm(
          wants_visualization=True,
          chart_llm_raises=RuntimeError("OpenAI rate limit"),
      )
      node = create_classify_intent_node(llm)
      state = {"messages": [HumanMessage(content="sunburst grafik ver")]}
      result = await node(state)
      # keyword fallback: "sunburst" → sunburst
      assert result["requested_chart_type"] == "sunburst"
  ```

- [ ] **Step 4: Yeni test — chart LLM değer döndürüyor, wants_viz=True**

  ```python
  @pytest.mark.asyncio
  async def test_parallel_chart_llm_value_used_when_wants_viz():
      """chart LLM sonucu doğrudan kullanılmalı (keyword override olmamalı)."""
      from langchain_core.messages import HumanMessage
      from src.graphs.report_agent.nodes import create_classify_intent_node

      llm = _make_mock_llm(wants_visualization=True, chart_type="treemap")
      node = create_classify_intent_node(llm)
      state = {"messages": [HumanMessage(content="kategorilerin alt kırılımını göster")]}
      result = await node(state)
      assert result["requested_chart_type"] == "treemap"
  ```

- [ ] **Step 5: Yeni test — chart LLM None, wants_viz=False → chart_type None kalmalı**

  ```python
  @pytest.mark.asyncio
  async def test_chart_type_none_when_no_viz_requested():
      """wants_visualization=False olduğunda chart LLM sonucu kullanılmamalı."""
      from langchain_core.messages import HumanMessage
      from src.graphs.report_agent.nodes import create_classify_intent_node

      llm = _make_mock_llm(wants_visualization=False, chart_type="sunburst")
      node = create_classify_intent_node(llm)
      state = {"messages": [HumanMessage(content="son 3 aydaki satışlar")]}
      result = await node(state)
      assert result["requested_chart_type"] is None
  ```

- [ ] **Step 6: Tüm testleri çalıştır**

  ```bash
  pytest tests/graphs/report/test_chart_type_detection.py -v
  ```

  Beklenen: tüm testler PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add tests/graphs/report/test_chart_type_detection.py
  git commit -m "test: update chart type detection tests for parallel LLM approach"
  ```

---

## Task 4: Mevcut test suite ile bütünlük kontrolü

- [ ] **Step 1: Tüm report agent testlerini çalıştır**

  ```bash
  pytest tests/graphs/report/ -v
  ```

  Eğer `requested_chart_type` alanını `IntentClassificationResult` üzerinden doğrudan oluşturan başka test varsa, `ValidationError` alınır → o testlerde `requested_chart_type=...` parametresini kaldır.

- [ ] **Step 2: Interrupt flow testini çalıştır**

  ```bash
  pytest tests/test_interrupt_flow.py -v
  ```

  `interrupt()` path'i değişmedi — testler geçmeli.

- [ ] **Step 3: Tüm test suite**

  ```bash
  pytest tests/ -v --ignore=tests/integration -x
  ```

  Beklenen: hiçbir regression yok.

- [ ] **Step 4: Final commit (gerekirse)**

  Eğer Step 1-3'te ek düzeltme yaptıysan:
  ```bash
  git add -p
  git commit -m "fix: update remaining tests after IntentClassificationResult field removal"
  ```
