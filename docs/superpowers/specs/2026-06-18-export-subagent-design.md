# Export Subagent Design
**Date:** 2026-06-18  
**Status:** Approved  
**Scope:** `src/graphs/report_agent/subagents/export_v1/` + API katmanı

---

## 1. Amaç

Report agent altında, kullanıcıların sorgu sonuçlarını PDF / XLSX / DOCX / HTML / MD / CSV formatlarında indirmesini sağlayan bir export subagent. Visualization subagent ile aynı pattern'da çalışır; kullanıcı ilk sorguda veya sonraki turda export talep edebilir.

---

## 2. Genel Mimari

```
src/graphs/report_agent/
├── subagents/
│   └── export_v1/
│       ├── __init__.py
│       ├── state.py          # ExportState
│       ├── graph.py          # build_export_graph()
│       ├── nodes.py          # export_decider, format_renderer, response_builder
│       ├── models.py         # ExportSpec, ExportOutput
│       ├── chart_bridge.py   # viz_decision → Matplotlib figure
│       └── exporters/
│           ├── base.py       # BaseExporter ABC
│           ├── registry.py   # ExporterRegistry
│           ├── xlsx.py       # XlsxExporter
│           ├── pdf.py        # PdfExporter
│           ├── html.py       # HtmlExporter
│           ├── docx.py       # DocxExporter
│           ├── markdown.py   # MarkdownExporter
│           └── csv.py        # CsvExporter
└── ...

src/api/
├── routes/export.py          # GET /api/export/{session_id}
└── services/export_store.py  # In-memory BytesIO store
```

**Subgraph akışı:**
```
START → export_decider → format_renderer → response_builder → END
```
3 node, 0 LLM çağrısı (pure Python pipeline).

---

## 3. State

```python
class ExportState(TypedDict, total=False):
    # ReportState overlap (auto-sync)
    results: Optional[List[Dict[str, Any]]]
    user_query: str
    wants_export: Optional[bool]
    export_format: Optional[str]          # "xlsx"|"pdf"|"html"|"docx"|"md"|"csv"
    export_output: Optional[Dict[str, Any]]
    visualization_output: Optional[Dict[str, Any]]
    insight_output: Optional[str]
    session_id: Optional[str]
    error: Optional[str]

    # Internal
    export_spec: Optional[Dict]           # ExportSpec.model_dump()
```

**ReportState'e eklenen field'lar:**
- `wants_export: Optional[bool]`
- `export_format: Optional[str]`
- `export_output: Optional[Dict[str, Any]]`

---

## 4. Models

```python
class ExportSpec(BaseModel):
    format: str                           # hedef format
    include_chart: bool                   # grafik embed edilsin mi
    include_insight: bool                 # insight metni eklensin mi
    title: str                            # "Rapor — 2026-06-18"
    sheet_name: Optional[str] = "Veri"   # XLSX için

# export_output dict alanları:
# {
#   "format": "xlsx",
#   "download_url": "/api/export/{session_id}",
#   "filename": "rapor_2026-06-18.xlsx",
#   "has_chart": True,
#   "summary": "XLSX raporu hazır. [İndir](/api/export/...)"
# }
```

---

## 5. Plugin Mimarisi

### BaseExporter ABC

```python
class BaseExporter(ABC):
    FORMAT: str

    @abstractmethod
    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,       # Matplotlib Figure | None
        insight_text: str = "",
    ) -> BytesIO: ...

    @property
    @abstractmethod
    def content_type(self) -> str: ...
```

### ExporterRegistry

```python
class ExporterRegistry:
    _registry: Dict[str, Type[BaseExporter]] = {}

    @classmethod
    def register(cls, exporter_class):
        cls._registry[exporter_class.FORMAT] = exporter_class
        return exporter_class  # decorator olarak kullanılır

    @classmethod
    def get(cls, format: str) -> BaseExporter:
        cls_ = cls._registry.get(format)
        if not cls_:
            raise ValueError(f"Unsupported format: {format}")
        return cls_()
```

Yeni format eklemek = `BaseExporter` extend eden bir sınıf + `@ExporterRegistry.register` decorator.

### chart_bridge.py

```python
def build_chart_figure(
    viz_decision: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> Optional[Figure]:
    """viz_decision.chart_type → Matplotlib Figure.
    HTML, CSV, MD formatları için None döner (bu formatlar chart_bridge kullanmaz).
    """
```

### Chart embedding stratejisi

| Format | Yöntem |
|--------|--------|
| HTML   | ECharts HTML native olarak gömülür |
| XLSX   | Matplotlib PNG olarak sheet'e eklenir |
| PDF    | Matplotlib PNG olarak sayfaya eklenir |
| DOCX   | Matplotlib PNG olarak belgeye eklenir |
| MD     | Grafik yok |
| CSV    | Grafik yok |

---

## 6. Graph Nodes

### export_decider
- Pure Python, LLM çağrısı yok
- `export_format` + `results` kontrol eder
- `ExportSpec` üretir
- `results` boşsa `error` set eder, pipeline durur

### format_renderer
- `ExporterRegistry.get(format)` ile exporter alır
- Gerekirse `build_chart_figure()` çağırır
- `exporter.export()` ile `BytesIO` üretir
- `export_store.put(session_id, buffer, filename, content_type)` ile store'a yazar
- `export_output` dict döner

### response_builder
- `export_output`'a `summary` field ekler
- Chat mesajına eklenecek özet metin üretir

---

## 7. Parent Graph Değişiklikleri

### graph.py — routing

Mevcut `_visualization_router` genişletilir, yeni `_after_hitl_router` şöyle çalışır:

```python
def _after_hitl_check_router(state):
    if state.get("_hitl_answered"):          return "text2sql"
    if state.get("wants_visualization"):     return "visualization"
    if state.get("wants_export"):            return "export"
    return "build_response"

# visualization bittikten sonra:
def _after_visualization_router(state):
    if state.get("wants_export"):            return "export"
    return "build_response"

# EXPORT_REQUEST intent — intent_router'a eklenir:
# "EXPORT_REQUEST" → "export"  (text2sql çalışmaz)
```

Kenarlar:
```python
graph.add_conditional_edges("visualization", _after_visualization_router,
    {"export": "export", "build_response": "build_response"})
graph.add_edge("export", "build_response")
```

### export_decider — active_results fallback

`EXPORT_REQUEST` geldiğinde `results` boş olur (text2sql çalışmadı).
`export_decider` node şunu yapar:

```python
results = state.get("results") or state.get("active_results") or []
```

`active_results` varsa `results` olarak kullanılır. Boşsa `error` set edilir.

### nodes.py — classify_intent

`IntentClassificationResult`'a eklenir:
```python
wants_export: bool = False
export_format: Optional[str] = None
```

Prompt'a eklenir: "Excel'e aktar", "PDF rapor al", "indir", "dosya olarak ver" gibi ifadeleri `wants_export=True` + ilgili `export_format` olarak tanı. Format belirtilmemişse `export_format="xlsx"` default.

---

## 8. API Katmanı

### export_store.py

```python
# src/api/services/export_store.py
_store: Dict[str, Tuple[BytesIO, str, str]] = {}
# key: session_id → (buffer, filename, content_type)

def put(session_id, buffer, filename, content_type): ...
def get(session_id) -> Optional[Tuple]: ...
def delete(session_id): ...
```

Bir session için her zaman tek export tutulur — yeni export eskinin üstüne yazar.

### routes/export.py

```python
GET /api/export/{session_id}
→ StreamingResponse(buffer, media_type=content_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
→ 404 if not found
```

### ChatMessageResponse action alanı

```json
{
  "type": "export",
  "target": "/api/export/{session_id}",
  "params": {
    "format": "xlsx",
    "filename": "rapor_2026-06-18.xlsx",
    "has_chart": true
  }
}
```

---

## 9. Uçtan Uca Senaryolar

**Senaryo 1 — Yeni sorgu + export:**
```
"Geçen ay satışlarını Excel'e aktar"
classify_intent → wants_export=True, export_format="xlsx", intent=NEW_QUERY
→ text2sql → hitl_check → visualization(skip) → export → build_response
```

**Senaryo 2 — Grafik + export:**
```
"Pasta grafik olarak göster ve PDF'e aktar"
classify_intent → wants_visualization=True, wants_export=True, export_format="pdf"
→ text2sql → hitl_check → visualization → export → build_response
```

**Senaryo 3 — Mevcut sonuçtan export:**
```
"Bunu Word belgesine aktar"
classify_intent → intent=EXPORT_REQUEST, export_format="docx"
→ export (active_results kullanır) → build_response
```

---

## 10. Hata Yönetimi

| Durum | Davranış |
|-------|---------|
| `results` boş | `error` field dolar, `export_output` set edilmez, normal response döner |
| Desteklenmeyen format | Registry `ValueError` → node yakalar → hata mesajı |
| Renderer exception | try/except → "export oluşturulamadı" mesajı |
| Store'da session yok | HTTP 404 |
| `wants_export=False` | export node pass-through, state değişmez |

---

## 11. Bağımlılıklar

```toml
openpyxl = ">=3.1"      # XLSX
reportlab = ">=4.0"     # PDF
python-docx = ">=1.1"   # DOCX
matplotlib = ">=3.8"    # chart bridge (PDF/DOCX/XLSX)
# HTML: mevcut PyECharts kullanılır, ek bağımlılık yok
# MD/CSV: stdlib yeterli
```

---

## 12. Kapsam Dışı (v1)

- Şirket logosu / marka rengi (v2)
- Çoklu sayfa / bölümlü PDF (v2)
- Scheduled export / email gönderimi (v2)
- Export geçmişi / çoklu dosya (v2)
