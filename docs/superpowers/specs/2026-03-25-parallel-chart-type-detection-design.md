# Parallel Chart Type Detection — Design Spec

**Date:** 2026-03-25
**Status:** Approved (v2 — post spec-review)
**Scope:** `src/graphs/report_agent/`

---

## Problem

`classify_intent_node` tek bir büyük LLM çağrısında hem intent sınıflandırması hem de chart type tespiti yapıyor. Bu yaklaşımın iki sorunu var:

1. **Ortam tutarsızlığı:** LangGraph dev ortamında supervisor'ın boş `AIMessage`'ı (tool_calls içeren) `conversation_history`'ye giriyor ve LLM'in `requested_chart_type` çıktısını etkiliyor. FastAPI'de bu noise yok → farklı sonuçlar.
2. **Düşük doğruluk:** Çok sayıda alan (8+) içeren karmaşık structured output'ta `requested_chart_type` güvenilir şekilde doldurulamıyor.

Örnek: `"Son 3 aydaki satışları karşılaştır ve kategoriler ne kadar satmış"` → LangGraph dev: `sunburst`, FastAPI: `null` → viz_decider rule-based → `line_chart` (hatalı).

---

## Çözüm: asyncio.gather İçinde Paralel LLM Çağrıları

Graf yapısı **değişmez.** `classify_intent_node` içinde iki LLM çağrısı eş zamanlı başlatılır.

### Mimari

```
classify_intent_node (async):
  ┌──────────────────────────────────────┐  asyncio.gather(return_exceptions=True)
  │ intent_llm.ainvoke(intent_prompt)    │ ──► IntentClassificationResult | Exception
  │ chart_llm.ainvoke(chart_type_prompt) │ ──► ChartTypeResult | Exception
  └──────────────────────────────────────┘
       ↓ merge (hata toleranslı)
  wants_visualization=True  → requested_chart_type = chart_result.chart_type
  wants_visualization=False → requested_chart_type = None
  chart_type=None + wants_viz=True → _detect_chart_type_from_query() fallback
  chart_llm Exception → chart_type = _detect_chart_type_from_query() fallback
```

**Süre karşılaştırması:**
- Mevcut: 1 büyük LLM çağrısı ≈ 1.2s
- Yeni: `max(intent_llm_time, chart_llm_time)` ≈ 1.0–1.1s (paralel)

---

## Değişecek Dosyalar

| Dosya | Değişiklik |
|---|---|
| `prompts.py` | `IntentClassificationResult`'tan `requested_chart_type` kaldır; `ChartTypeResult` + `CHART_TYPE_PROMPT` ekle |
| `nodes.py` | `create_classify_intent_node` içinde `asyncio.gather`; merge logic; fallback güncelle |
| `graph.py` | **Değişmez** |
| `state.py` | **Değişmez** |

---

## Yeni Pydantic Modeli

```python
class ChartTypeResult(BaseModel):
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap"
    ]] = None
    # confidence alanı yok — kullanılmıyor, implementer'ı yanıltır
```

---

## `IntentClassificationResult` Değişikliği

`requested_chart_type` alanı kaldırılır:

```python
class IntentClassificationResult(BaseModel):
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None
    # requested_chart_type KALDIRILDI — artık ChartTypeResult'tan geliyor
```

---

## CHART_TYPE_PROMPT Kuralları

Prompt yalnızca `{user_query}` alır — conversation_history, context, query_type yok.

| Sorgu yapısı | Chart tipi |
|---|---|
| Kullanıcı açıkça bir tip belirtmiş (typo toleranslı: "sunbrust", "hetmap") | Belirtilen tip |
| Zaman + kategori/boyut karşılaştırması (hiyerarşik, çok boyutlu, "hangi X hangi dönem") | `sunburst` |
| Hiyerarşik part-of-whole, zaman boyutu yok ("kategorilerin alt kırılımı") | `treemap` |
| Saf zaman serisi (tek metrik, trend, "ay ay", "günlük") | `line_chart` |
| Kategoriler arası flat karşılaştırma ("en çok satan X", "en yüksek Y") | `bar_chart` |
| Oran / pay / dağılım ("yüzde", "pay", "dağılım") | `pie_chart` |
| Entity × periyot matrisi ("saatlere göre günler", "günlere göre şubeler") | `heatmap` |
| İki sayısal değişken arasındaki korelasyon ("X arttıkça Y") | `scatter_chart` |
| Belirsiz / sadece tablo/veri / grafik talep yok | `null` |

---

## `classify_intent_node` Değişikliği (nodes.py)

### Paralel çağrı + hata toleransı

```python
intent_llm = llm.with_structured_output(IntentClassificationResult)
chart_llm  = llm.with_structured_output(ChartTypeResult)

async def classify_intent_node(state: dict) -> dict:
    ...
    chart_prompt_str = CHART_TYPE_PROMPT.format(user_query=user_query)

    # return_exceptions=True: chart_llm hatası intent çağrısını öldürmez
    results = await asyncio.gather(
        intent_llm.ainvoke(intent_prompt),
        chart_llm.ainvoke(chart_prompt_str),
        return_exceptions=True,
    )
    intent_result, chart_raw = results[0], results[1]

    # intent_llm hatası: node'un normal exception mekanizmasına bırak
    if isinstance(intent_result, Exception):
        raise intent_result

    # chart_llm hatası: graceful degrade — deterministic fallback'e düş
    chart_type_from_llm = None
    if not isinstance(chart_raw, Exception):
        chart_type_from_llm = chart_raw.chart_type
```

### Merge logic + model_copy kaldırma

Mevcut kodda `result.model_copy(update={"requested_chart_type": ...})` satırı **kaldırılır** — `requested_chart_type` artık `IntentClassificationResult` alanı değil. Bunun yerine bağımsız `chart_type` local variable kullanılır:

```python
    # Merge: sadece visualization isteklerinde chart_type kullanılır
    _wants_viz = intent_result.wants_visualization or (intent_result.use_result_type == "revisualize")
    chart_type = None
    if _wants_viz:
        chart_type = chart_type_from_llm
        if chart_type is None:
            chart_type = _detect_chart_type_from_query(user_query)

    # ... interrupt() / _resolve_intent_from_answer() mevcut akışı değişmez ...

    # return dict'te:
    return {
        ...
        "wants_visualization": _wants_viz,  # revisualize dahil
        "requested_chart_type": chart_type,
        ...
    }
```

### interrupt() re-entry davranışı

`interrupt()` çağrıldığında LangGraph node'u baştan çalıştırır (resume). Bu durumda `asyncio.gather` **ikinci kez** çalışır. Bu mevcut kodda da var (tek LLM çağrısı da ikinci kez çalışır) — önceden var olan davranış, bu değişiklikle kötüleşmez. İleride optimize edilebilir (intent result'ı state'e geçici olarak kaydetmek), ancak bu spec kapsamı dışında.

### is_refresh_request early-return

Lines 118–133 arası erken dönüş kodu değişmez — `asyncio.gather`'a ulaşmadan döner, `requested_chart_type: None` hard-coded olarak kalır.

---

## Beklenen Sonuç

- Her iki ortamda (LangGraph dev, FastAPI) aynı chart type sonucu
- `"Son 3 aydaki satışları karşılaştır + kategoriler"` → tutarlı olarak `sunburst`
- chart_llm hata verirse: deterministic fallback → sistem çalışmaya devam eder
- Intent routing (NEW_QUERY / MODIFY_QUERY vb.) etkilenmez
- Hız: eşit veya hafif iyileşme (paralel çağrılar)
