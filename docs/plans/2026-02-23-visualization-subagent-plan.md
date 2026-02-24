# Visualization Subagent Plan

**Klasör:** `src/graphs/report_agent/subagents/visualization/`
**Amaç:** `results` + `user_query` → `visualization_output` (Plotly HTML + summary)

---

## Mevcut Sistemden Ne Öğrendik

| Mevcut Node | Karar | Gerekçe |
|-------------|-------|---------|
| `state_transformer` | **Kaldır** | Shared state → dönüşüm gerekmez |
| `data_analyzer` | **DataAnalyzer class'ını koru** | Türkçe pattern'ler + tip/rol tespiti mükemmel, sıfırdan yazma |
| `visualization_decider` | **Yeniden yaz** | Raw JSON parse → Pydantic structured output |
| `chart_config_builder` | **`chart_generator`'a merge et** | Ayrı LLM değil pure Python'du; config mantığı LLM prompt'a taşınır |
| `plotly_code_generator` | **Koru, async yap** | LLM kodu çalışıyor; sadece async wrapper ve Pydantic output ekle |
| `response_builder` | **Koru, basitleştir** | Pure Python, mantık sağlam |

---

## Node Yapısı (4 Node)

```
START
  ↓
data_analyzer    ← Pure Python: results → DataProfile (tip, rol, istatistik)
  ↓
viz_decider      ← LLM (Pydantic): DataProfile + user_query → VizDecision (chart_type, axes)
  ↓
chart_generator  ← LLM: VizDecision + data → Plotly Python kodu → execute → HTML snippet
  ↓
response_builder ← Pure Python: Plotly output → visualization_output dict
  ↓
END
```

**Önceki sistemden:** 7 node → **4 node**
**LLM çağrısı:** 2 (viz_decider + chart_generator) — aynı

---

## Node Detayları

### Node 1: `data_analyzer` — Pure Python
**Tek Sorumluluk:** Veriyi analiz et, kolon tipleri ve rollerini tespit et.

Mevcut `DataAnalyzer` class'ı **doğrudan alınır**, sadece:
- `DataVisualizationState` → `dict` (shared state uyumu)
- Async wrapper eklenir (`async def data_analyzer_node`)
- Input: `state["results"]` → `raw_data` olarak kullanılır

Reads: `results`
Writes: `data_profile` (DataProfile TypedDict)

---

### Node 2: `viz_decider` — LLM (Pydantic structured output)
**Tek Sorumluluk:** Veri profiline ve kullanıcı sorusuna göre chart tipi karar ver.

Mevcut sistemdeki sorun: `json.loads(response.content)` — kırılgan.
Yeni: `llm.with_structured_output(VizDecision)` — güvenilir.

Reads: `data_profile`, `user_query`, `query_type`
Writes: `viz_decision` (VizDecision dict)

**Hızlı karar kuralları (LLM'e gitmeden önce, pure Python):**
- `results` boş → `needs_graph=False, chart_type="table"`
- 1 satır + 1 kolon → `needs_graph=False, chart_type="single_value"`
- Gerisi → LLM

---

### Node 3: `chart_generator` — LLM
**Tek Sorumluluk:** Plotly Python kodu üret ve çalıştır, HTML snippet oluştur.

`needs_graph=False` ise bu node'u **atla** (conditional edge).

Mevcut sistemdeki `PlotlyCodeGenerator` mantığını korur:
- `go`, `px`, `pd`, `data` değişkenleri pre-inject edilmiş ortamda kod çalıştırılır
- `fig.to_html(include_plotlyjs="cdn", full_html=False)` → HTML snippet

Reads: `viz_decision`, `results`, `user_query`
Writes: `plotly_html_snippet` (str)

---

### Node 4: `response_builder` — Pure Python
**Tek Sorumluluk:** Tüm çıktıları `visualization_output` dict'e paketle.

Mevcut `ResponseBuilder` mantığını korur:
- `single_value` → değeri string olarak döndür
- `simple_list` → markdown liste format
- `table` → satır/kolon sayısı özeti
- Graf olan tipler → chart açıklaması

Reads: `viz_decision`, `results`, `data_profile`, `plotly_html_snippet`
Writes: `visualization_output` (ReportState'deki shared field)

---

## State Tasarımı

```python
class VisualizationState(TypedDict, total=False):
    # ReportState overlapping keys
    results: Optional[List[Dict[str, Any]]]
    user_query: str
    query_type: Optional[str]
    visualization_output: Optional[Dict[str, Any]]
    error: Optional[str]

    # Internal
    data_profile: Optional[Dict[str, Any]]    # DataProfile TypedDict
    viz_decision: Optional[Dict[str, Any]]    # VizDecision dict
    plotly_html_snippet: Optional[str]        # Üretilen HTML
```

---

## Pydantic Modeli

```python
class VizDecision(BaseModel):
    needs_graph: bool
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart",
        "scatter_chart", "single_value", "simple_list",
        "table", "comparison", "sunburst", "treemap"
    ]
    x_field: Optional[str] = None      # x ekseninde hangi kolon
    y_field: Optional[str] = None      # y ekseninde hangi kolon
    series_field: Optional[str] = None # Renk/seri için kolon (karşılaştırma)
    title: Optional[str] = None
    reason: str
```

---

## Routing

```python
def _route_after_decider(state: VisualizationState) -> str:
    viz = state.get("viz_decision", {})
    if viz.get("needs_graph", False):
        return "chart_generator"
    return "response_builder"   # Grafik gereksiz → doğrudan response
```

`data_analyzer → viz_decider → [conditional] → chart_generator → response_builder → END`
veya
`data_analyzer → viz_decider → [conditional] → response_builder → END`

---

## DataAnalyzer Entegrasyonu

`DataAnalyzer` class'ı **kopyalanır** (tüm pattern'ler, tip/rol tespiti):

```python
# nodes.py içinde
from src.graphs.report_agent.subagents.visualization.data_analyzer import DataAnalyzer

async def data_analyzer_node(state: dict) -> dict:
    results = state.get("results") or []
    if not results:
        return {"data_profile": None}

    # Mevcut DataAnalyzer class'ı — DataVisualizationState formatında çağır
    analyzer = DataAnalyzer()
    fake_state = {"raw_data": results}
    profile_state = analyzer.analyze(fake_state)
    return {"data_profile": profile_state.get("data_profile")}
```

---

## Dosya Yapısı

```
subagents/visualization/
├── __init__.py           # zaten var
├── state.py              # VisualizationState
├── prompts.py            # VizDecision Pydantic + 2 prompt
├── data_analyzer.py      # DataAnalyzer class kopyalandı (değişiklik yok)
├── nodes.py              # 4 node fonksiyonu
└── graph.py              # build_visualization_graph — 4 node, 1 conditional edge
```

---

## Eski vs Yeni Karşılaştırma

| | Eski | Yeni |
|--|------|------|
| Node sayısı | 7 | 4 |
| State transformer | Ayrı node | Yok (shared state) |
| Chart config builder | Ayrı node (pure Python) | viz_decider LLM prompt'a merge |
| LLM JSON parsing | `json.loads()` kırılgan | Pydantic structured output |
| DataAnalyzer | `DataVisualizationState` bağımlı | Standalone, shared state uyumlu |
| LLM çağrısı/tur | 2 | 2 (aynı) |
