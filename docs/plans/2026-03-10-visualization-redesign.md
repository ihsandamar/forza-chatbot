# Visualization Subagent Redesign

**Tarih:** 2026-03-10
**Durum:** Onaylandı
**Yaklaşım:** LLM → JSON Config + Validation Layer → Template Engine (Approach C)

## Problem

Mevcut visualization subagent yanlış grafikler üretiyor:
- **Yanlış field mapping**: LLM yanlış kolon seçiyor veya x/y'yi ters koyuyor
- **exec() güvenlik riski**: LLM'in ürettiği Python kodu exec() ile çalıştırılıyor
- **Kırılgan yapı**: LLM code generation hatalı kod üretebiliyor

## Tasarım Kararları

1. **Yeni subagent ayrı dizine yazılacak** (`visualization_v2/`), eski korunacak
2. **LLM karar katmanı** ve **grafik çizim katmanı** tamamen ayrı olacak
3. **exec() tamamen kaldırılacak** — LLM asla kod üretmeyecek, sadece JSON
4. **Validation layer** LLM hatalarını yakalar ve düzeltir

## Mimari: İki Katmanlı Ayrım

```
┌─────────────────────────────────────────────┐
│          KARAR KATMANI (LLM + Rules)        │
│                                             │
│  data_analyzer → viz_decider → spec_validator│
│                                             │
│  Çıktı: Validated ChartSpec (JSON)          │
│  ⚠️ Hiçbir Plotly/grafik kodu yok           │
└──────────────────┬──────────────────────────┘
                   │ ChartSpec JSON
                   ▼
┌─────────────────────────────────────────────┐
│        ÇİZİM KATMANI (Deterministic)       │
│                                             │
│  template_renderer → response_builder       │
│                                             │
│  Girdi: ChartSpec JSON + DataFrame          │
│  ⚠️ LLM yok, sadece Plotly API çağrıları   │
└─────────────────────────────────────────────┘
```

## Graph Akışı

```
START → data_analyzer → viz_decider → spec_validator → [conditional]
  ├── needs_graph=True  → template_renderer → response_builder → END
  └── needs_graph=False → response_builder → END
```

## Bileşenler

### 1. ChartSpec Model (`models.py`)

```python
class ChartSpec(BaseModel):
    needs_graph: bool
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "single_value", "simple_list", "table",
        "comparison", "sunburst", "treemap"
    ]
    x_field: Optional[str] = None
    y_field: Optional[str] = None
    y_fields: Optional[List[str]] = None
    series_field: Optional[str] = None
    hierarchy_fields: Optional[List[str]] = None
    title: Optional[str] = None
    orientation: Optional[Literal["v", "h"]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = None
    top_n: Optional[int] = None
    reason: str
```

### 2. LLM Prompt (Geliştirilmiş)

Mevcut prompt'un eksikleri:
- Kolon açıklamaları yok → LLM ne olduğunu bilmiyor
- Rol bilgisi yok → dimension/metric ayrımı yapamıyor

Yeni prompt'a eklenen `column_info`:
```
- BranchName (DIMENSION, TEXT): Şube adı
- RowAmount (METRIC, NUMERIC): Satış tutarı (TL)
- DocumentDate (TIME, DATE): Satış tarihi
```

### 3. Spec Validator (`validator.py`)

5 kural sırayla çalışır (Pure Python, LLM yok):

1. **Kolon varlık kontrolü** — field results'ın gerçek kolonlarında var mı? Yoksa fuzzy match
2. **Rol uyumu** — x dimension mi, y metric mi? Ters ise swap
3. **Chart-data uyumu** — pie+30 kategori→top_n, line+zaman yok→bar
4. **Eksik field tamamlama** — needs_graph=True ama x/y None → profile'dan doldur
5. **Multi-metric doğrulama** — y_fields geçerli mi?

⚠️ Fuzzy match `results` kolonlarına karşı yapılır, DB kolonlarına değil.
SQL alias'lar (`SUM(RowAmount) as ToplamSatis`) results'ta farklı isimle gelir.

### 4. Template Renderer (`chart_renderer.py`)

- Mevcut `chart_templates.py` refactored
- Builder'lar `spec` dict alır (tüm field'lara erişim)
- Multi-metric desteği (y_fields → multi-bar/multi-line)
- Orientation LLM'den gelir (hardcoded 15-row threshold yerine)
- top_n ve sort_by spec'ten uygulanır
- Template başarısız → table fallback (exec yok)

### 5. Rule-Based Fast Path (Sadeleştirilmiş)

- `chart_type` ve `needs_graph` seçer
- **Field mapping yapmaz** (x_field, y_field = None)
- Validator Rule 4 ile field'ları data_profile'dan doldurur

## Dosya Yapısı

```
src/graphs/report_agent/subagents/visualization_v2/
├── __init__.py
├── graph.py              # 5-node graph tanımı
├── state.py              # VisualizationState (mevcut + uyumlu)
├── models.py             # ChartSpec Pydantic model
├── prompts.py            # VIZ_DECIDER_PROMPT (geliştirilmiş)
├── nodes.py              # data_analyzer, viz_decider, spec_validator, response_builder
├── validator.py          # ChartSpec validation (5 kural)
├── chart_renderer.py     # Template engine (deterministic, exec yok)
└── data_analyzer.py      # DataAnalyzer class (mevcut kopyası)
```

## Korunan Arayüzler

- `VisualizationState` key'leri aynı kalır
- `visualization_output` dict formatı değişmez (parent uyumlu)
- `RunnableConfig.configurable.column_metadata` erişimi korunur
- `build_visualization_graph(llm)` aynı signature

## Silinen Kodlar (v2'de olmayacak)

- `_execute_plotly_code()` — exec()
- `_clean_plotly_code()` — markdown temizleme
- `CHART_GENERATOR_PROMPT` — LLM code generation prompt'u
- chart_generator_node içindeki LLM fallback bloğu

## Entegrasyon

`graph.py` (parent report agent) sadece import path'i değişecek:
```python
# Eski
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph
# Yeni
from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph
```
