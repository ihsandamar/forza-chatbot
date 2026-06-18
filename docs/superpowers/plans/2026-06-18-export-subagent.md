# Export Subagent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kullanıcıların rapor sonuçlarını PDF / XLSX / DOCX / HTML / MD / CSV formatlarında indirmesini sağlayan bir export subagent.

**Architecture:** Plugin pattern — `BaseExporter` ABC + `ExporterRegistry` ile her format kendi sınıfında. LangGraph StateGraph subgraph (3 node, 0 LLM çağrısı) olarak `export_v1/` altında. Parent report agent graph'a `build_export_graph()` ile eklenir, `wants_export` + `export_format` flag'leri ile tetiklenir.

**Tech Stack:** Python 3.11, LangGraph, openpyxl, reportlab, python-docx, matplotlib (yeni), FastAPI StreamingResponse (mevcut), pytest-asyncio (mevcut).

## Global Constraints

- Python ≥ 3.11, LangGraph 1.0.6, FastAPI 0.121.2
- Tüm dosya yolları `src/graphs/report_agent/subagents/export_v1/` altında — visualization_v2 pattern'ına uy
- `openpyxl >= 3.1`, `reportlab >= 4.0`, `python-docx >= 1.1`, `matplotlib >= 3.8`
- Matplotlib backend `"Agg"` (non-interactive, server-side rendering)
- Export store: in-memory dict, session başına tek dosya, yeni export eskiyi overwrite eder
- `ExportSpec.title` format: `f"Rapor — {date.today().isoformat()}"` (çizgi, dash değil)
- Test dosyaları `tests/test_export_v1/` altında, visualization_v2 test pattern'ına uy
- `@ExporterRegistry.register` decorator her exporter'ı otomatik kayıt eder
- Matplotlib `Figure` import her zaman `matplotlib.pyplot` üzerinden

---

## File Map

**Yeni dosyalar:**
```
src/graphs/report_agent/subagents/export_v1/
├── __init__.py
├── state.py
├── models.py
├── graph.py
├── nodes.py
├── chart_bridge.py
└── exporters/
    ├── __init__.py
    ├── base.py
    ├── registry.py
    ├── csv.py
    ├── markdown.py
    ├── xlsx.py
    ├── pdf.py
    ├── html.py
    └── docx.py

src/api/services/export_store.py
src/api/routes/export.py

tests/test_export_v1/
├── __init__.py
├── test_registry.py
├── test_csv_exporter.py
├── test_markdown_exporter.py
├── test_chart_bridge.py
├── test_xlsx_exporter.py
├── test_pdf_exporter.py
├── test_html_exporter.py
├── test_docx_exporter.py
├── test_nodes.py
└── test_export_store.py
```

**Değişen dosyalar:**
```
src/graphs/report_agent/state.py           — wants_export, export_format, export_output field'ları
src/graphs/report_agent/prompts.py         — IntentClassificationResult'a wants_export + export_format + EXPORT_REQUEST
src/graphs/report_agent/nodes.py           — classify_intent return_dict güncellemesi
src/graphs/report_agent/graph.py           — export node + yeni routing
src/api/main.py                            — export router kaydı
requirements.txt (veya pyproject)          — openpyxl, reportlab, python-docx, matplotlib
```

---

### Task 1: Dependencies + Scaffolding

**Files:**
- Modify: `requirements.txt`
- Create: `src/graphs/report_agent/subagents/export_v1/__init__.py`
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/__init__.py`
- Create: `tests/test_export_v1/__init__.py`

**Interfaces:**
- Produces: Paketler import edilebilir hale gelir; boş `__init__.py` dosyaları oluşturulur

- [ ] **Step 1: Bağımlılıkları kur**

```bash
pip install "openpyxl>=3.1" "reportlab>=4.0" "python-docx>=1.1" "matplotlib>=3.8"
```

Expected: Her paket başarıyla yüklenir.

- [ ] **Step 2: requirements.txt'e ekle**

`requirements.txt` dosyasının sonuna şunları ekle (dosya varsa; pyproject.toml kullanılıyorsa oraya ekle):

```
openpyxl>=3.1
reportlab>=4.0
python-docx>=1.1
matplotlib>=3.8
```

- [ ] **Step 3: Dizin ve __init__ dosyalarını oluştur**

```bash
mkdir -p src/graphs/report_agent/subagents/export_v1/exporters
mkdir -p tests/test_export_v1
touch src/graphs/report_agent/subagents/export_v1/__init__.py
touch src/graphs/report_agent/subagents/export_v1/exporters/__init__.py
touch tests/test_export_v1/__init__.py
```

- [ ] **Step 4: Import testi**

```bash
python -c "import openpyxl; import reportlab; import docx; import matplotlib; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/graphs/report_agent/subagents/export_v1/ tests/test_export_v1/
git commit -m "chore(export): scaffold export_v1 directories + dependencies"
```

---

### Task 2: Models

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/models.py`
- Create: `tests/test_export_v1/test_models.py`

**Interfaces:**
- Produces:
  - `ExportSpec(format, include_chart, include_insight, title, sheet_name)` — Pydantic BaseModel
  - Tüm exporter'lar ve node'lar bu modeli kullanır

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_models.py
import pytest
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


def test_export_spec_defaults():
    spec = ExportSpec(format="xlsx", title="Rapor — 2026-06-18")
    assert spec.include_chart is False
    assert spec.include_insight is False
    assert spec.sheet_name == "Veri"


def test_export_spec_full():
    spec = ExportSpec(
        format="pdf",
        include_chart=True,
        include_insight=True,
        title="Rapor — 2026-06-18",
        sheet_name="Satışlar",
    )
    assert spec.format == "pdf"
    assert spec.include_chart is True
    assert spec.sheet_name == "Satışlar"


def test_export_spec_invalid_missing_format():
    with pytest.raises(Exception):
        ExportSpec(title="Rapor")
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_models.py -v
```

Expected: `ImportError` veya `ModuleNotFoundError`

- [ ] **Step 3: Modeli implement et**

```python
# src/graphs/report_agent/subagents/export_v1/models.py
from pydantic import BaseModel
from typing import Optional


class ExportSpec(BaseModel):
    format: str
    include_chart: bool = False
    include_insight: bool = False
    title: str
    sheet_name: str = "Veri"
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_models.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/models.py tests/test_export_v1/test_models.py
git commit -m "feat(export): ExportSpec model"
```

---

### Task 3: BaseExporter ABC + ExporterRegistry

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/base.py`
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/registry.py`
- Create: `tests/test_export_v1/test_registry.py`

**Interfaces:**
- Produces:
  - `BaseExporter` — ABC: `FORMAT: str`, `export(results, spec, chart_figure, insight_text) -> BytesIO`, `content_type: str`
  - `ExporterRegistry.register(cls)` — decorator, `cls._registry[FORMAT] = cls` yazar
  - `ExporterRegistry.get(format: str) -> BaseExporter` — kayıtlı instance döner, yoksa `ValueError`
  - `ExporterRegistry.supported_formats() -> list[str]`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_registry.py
import pytest
from io import BytesIO
from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


def test_register_and_get():
    @ExporterRegistry.register
    class FakeExporter(BaseExporter):
        FORMAT = "fake"

        @property
        def content_type(self):
            return "application/fake"

        def export(self, results, spec, chart_figure=None, insight_text="") -> BytesIO:
            return BytesIO(b"fake")

    exporter = ExporterRegistry.get("fake")
    assert isinstance(exporter, FakeExporter)
    spec = ExportSpec(format="fake", title="Test")
    result = exporter.export([], spec)
    assert result.getvalue() == b"fake"


def test_get_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported export format"):
        ExporterRegistry.get("nonexistent_xyz")


def test_supported_formats_includes_registered():
    @ExporterRegistry.register
    class AnotherFake(BaseExporter):
        FORMAT = "anotherfake"

        @property
        def content_type(self):
            return "application/anotherfake"

        def export(self, results, spec, chart_figure=None, insight_text="") -> BytesIO:
            return BytesIO()

    assert "anotherfake" in ExporterRegistry.supported_formats()
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_registry.py -v
```

Expected: `ImportError`

- [ ] **Step 3: BaseExporter ABC implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/base.py
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Dict, List, Optional


class BaseExporter(ABC):
    FORMAT: str

    @abstractmethod
    def export(
        self,
        results: List[Dict[str, Any]],
        spec: "ExportSpec",  # noqa: F821 — forward ref
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO: ...

    @property
    @abstractmethod
    def content_type(self) -> str: ...
```

- [ ] **Step 4: ExporterRegistry implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/registry.py
from typing import Dict, List, Type
from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter


class ExporterRegistry:
    _registry: Dict[str, Type[BaseExporter]] = {}

    @classmethod
    def register(cls, exporter_class: Type[BaseExporter]) -> Type[BaseExporter]:
        cls._registry[exporter_class.FORMAT] = exporter_class
        return exporter_class

    @classmethod
    def get(cls, format: str) -> BaseExporter:
        exporter_cls = cls._registry.get(format)
        if exporter_cls is None:
            raise ValueError(
                f"Unsupported export format: '{format}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return exporter_cls()

    @classmethod
    def supported_formats(cls) -> List[str]:
        return list(cls._registry.keys())
```

- [ ] **Step 5: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_registry.py -v
```

Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/exporters/base.py \
        src/graphs/report_agent/subagents/export_v1/exporters/registry.py \
        tests/test_export_v1/test_registry.py
git commit -m "feat(export): BaseExporter ABC + ExporterRegistry"
```

---

### Task 4: CSV + Markdown Exporters

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/csv.py`
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/markdown.py`
- Create: `tests/test_export_v1/test_csv_exporter.py`
- Create: `tests/test_export_v1/test_markdown_exporter.py`

**Interfaces:**
- Consumes: `BaseExporter`, `ExporterRegistry.register`, `ExportSpec`
- Produces:
  - `CsvExporter` — `FORMAT = "csv"`, `content_type = "text/csv; charset=utf-8"`, UTF-8 BOM ile çıktı (Excel uyumluluğu için)
  - `MarkdownExporter` — `FORMAT = "md"`, `content_type = "text/markdown; charset=utf-8"`, `# {title}` + tablo

- [ ] **Step 1: CSV failing test yaz**

```python
# tests/test_export_v1/test_csv_exporter.py
import csv
import io
import pytest

# Trigger registration
import src.graphs.report_agent.subagents.export_v1.exporters.csv  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_csv_export_produces_valid_csv():
    exporter = ExporterRegistry.get("csv")
    spec = ExportSpec(format="csv", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    content = buf.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["BranchName"] == "Istanbul"
    assert rows[0]["RowAmount"] == "50000"


def test_csv_export_empty_results():
    exporter = ExporterRegistry.get("csv")
    spec = ExportSpec(format="csv", title="Rapor")
    buf = exporter.export([], spec)
    assert buf.getvalue() != b""


def test_csv_content_type():
    exporter = ExporterRegistry.get("csv")
    assert "text/csv" in exporter.content_type
```

- [ ] **Step 2: CSV testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_csv_exporter.py -v
```

Expected: `ImportError` veya registry lookup hatası

- [ ] **Step 3: CsvExporter implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/csv.py
import csv
from io import BytesIO, StringIO
from typing import Any, Dict, List

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


@ExporterRegistry.register
class CsvExporter(BaseExporter):
    FORMAT = "csv"

    @property
    def content_type(self) -> str:
        return "text/csv; charset=utf-8"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        if not results:
            buf = BytesIO()
            buf.write("Veri bulunamadı\n".encode("utf-8-sig"))
            return buf
        si = StringIO()
        writer = csv.DictWriter(si, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
        buf = BytesIO()
        buf.write(si.getvalue().encode("utf-8-sig"))
        return buf
```

- [ ] **Step 4: CSV testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_csv_exporter.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Markdown failing test yaz**

```python
# tests/test_export_v1/test_markdown_exporter.py
import pytest

import src.graphs.report_agent.subagents.export_v1.exporters.markdown  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_markdown_export_has_title():
    exporter = ExporterRegistry.get("md")
    spec = ExportSpec(format="md", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "# Rapor — 2026-06-18" in content


def test_markdown_export_has_table():
    exporter = ExporterRegistry.get("md")
    spec = ExportSpec(format="md", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "| BranchName |" in content
    assert "| Istanbul |" in content
    assert "---" in content


def test_markdown_export_empty():
    exporter = ExporterRegistry.get("md")
    spec = ExportSpec(format="md", title="Rapor")
    buf = exporter.export([], spec)
    content = buf.read().decode("utf-8")
    assert "Veri bulunamadı" in content
```

- [ ] **Step 6: Markdown testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_markdown_exporter.py -v
```

Expected: `ImportError`

- [ ] **Step 7: MarkdownExporter implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/markdown.py
from io import BytesIO
from typing import Any, Dict, List

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


@ExporterRegistry.register
class MarkdownExporter(BaseExporter):
    FORMAT = "md"

    @property
    def content_type(self) -> str:
        return "text/markdown; charset=utf-8"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        lines = [f"# {spec.title}", ""]
        if not results:
            lines.append("Veri bulunamadı.")
            buf = BytesIO()
            buf.write("\n".join(lines).encode("utf-8"))
            return buf

        headers = list(results[0].keys())
        lines.append("| " + " | ".join(str(h) for h in headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in results:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

        buf = BytesIO()
        buf.write("\n".join(lines).encode("utf-8"))
        return buf
```

- [ ] **Step 8: Markdown testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_markdown_exporter.py -v
```

Expected: 3 PASSED

- [ ] **Step 9: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/exporters/csv.py \
        src/graphs/report_agent/subagents/export_v1/exporters/markdown.py \
        tests/test_export_v1/test_csv_exporter.py \
        tests/test_export_v1/test_markdown_exporter.py
git commit -m "feat(export): CsvExporter + MarkdownExporter"
```

---

### Task 5: chart_bridge.py

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/chart_bridge.py`
- Create: `tests/test_export_v1/test_chart_bridge.py`

**Interfaces:**
- Produces:
  - `build_chart_figure(viz_decision: dict, results: list) -> Optional[Figure]`
    - `viz_decision["chart_type"]`: `"bar_chart"` | `"line_chart"` | `"pie_chart"` | diğerleri → bar fallback
    - `viz_decision["x_field"]`, `viz_decision["y_field"]`, `viz_decision["series_field"]`
    - `results` boşsa veya `viz_decision` None ise `None` döner
    - Exception'da `None` döner (kapatıp), log yazar

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_chart_bridge.py
import pytest
from matplotlib.figure import Figure

from src.graphs.report_agent.subagents.export_v1.chart_bridge import build_chart_figure

SAMPLE_BAR = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
    {"BranchName": "Izmir", "RowAmount": 28000},
]

SAMPLE_TIME = [
    {"DocumentDate": "2024-01-01", "RowAmount": 10000},
    {"DocumentDate": "2024-01-02", "RowAmount": 12000},
    {"DocumentDate": "2024-01-03", "RowAmount": 9000},
]


def test_build_bar_chart_returns_figure():
    viz = {"chart_type": "bar_chart", "x_field": "BranchName", "y_field": "RowAmount", "series_field": None, "title": "Şube Satışları"}
    fig = build_chart_figure(viz, SAMPLE_BAR)
    assert isinstance(fig, Figure)


def test_build_line_chart_returns_figure():
    viz = {"chart_type": "line_chart", "x_field": "DocumentDate", "y_field": "RowAmount", "series_field": None, "title": "Trend"}
    fig = build_chart_figure(viz, SAMPLE_TIME)
    assert isinstance(fig, Figure)


def test_empty_results_returns_none():
    viz = {"chart_type": "bar_chart", "x_field": "BranchName", "y_field": "RowAmount", "series_field": None}
    assert build_chart_figure(viz, []) is None


def test_none_viz_decision_returns_none():
    assert build_chart_figure(None, SAMPLE_BAR) is None


def test_fallback_chart_type_still_produces_figure():
    viz = {"chart_type": "sunburst", "x_field": "BranchName", "y_field": "RowAmount", "series_field": None}
    fig = build_chart_figure(viz, SAMPLE_BAR)
    assert isinstance(fig, Figure)
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_chart_bridge.py -v
```

Expected: `ImportError`

- [ ] **Step 3: chart_bridge.py implement et**

```python
# src/graphs/report_agent/subagents/export_v1/chart_bridge.py
import logging
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


def build_chart_figure(
    viz_decision: Optional[Dict[str, Any]],
    results: List[Dict[str, Any]],
) -> Optional[Figure]:
    if not results or not viz_decision:
        return None

    chart_type = viz_decision.get("chart_type", "bar_chart")
    x_field = viz_decision.get("x_field")
    y_field = viz_decision.get("y_field")
    series_field = viz_decision.get("series_field")
    title = viz_decision.get("title", "")

    if not x_field or not y_field:
        keys = list(results[0].keys())
        x_field = x_field or (keys[0] if keys else None)
        y_field = y_field or (keys[1] if len(keys) > 1 else (keys[0] if keys else None))

    if not x_field or not y_field:
        return None

    try:
        if chart_type == "pie_chart":
            fig, ax = plt.subplots(figsize=(8, 8))
            _draw_pie(ax, results, x_field, y_field)
        elif chart_type == "line_chart":
            fig, ax = plt.subplots(figsize=(10, 6))
            _draw_line(ax, results, x_field, y_field, series_field)
        else:
            fig, ax = plt.subplots(figsize=(10, 6))
            _draw_bar(ax, results, x_field, y_field, series_field)

        if title:
            ax.set_title(title, fontsize=13, pad=10)
        fig.tight_layout()
        return fig
    except Exception as exc:
        logger.warning(f"[CHART_BRIDGE] Figure build failed: {exc}")
        plt.close("all")
        return None


def _draw_bar(ax, results, x_field, y_field, series_field):
    if series_field and series_field in results[0]:
        series_vals = list(dict.fromkeys(r.get(series_field) for r in results))
        x_vals = list(dict.fromkeys(r.get(x_field) for r in results))
        width = 0.8 / max(len(series_vals), 1)
        for i, sv in enumerate(series_vals):
            subset = [r for r in results if r.get(series_field) == sv]
            sub_x = [r.get(x_field) for r in subset]
            sub_y = [float(r.get(y_field) or 0) for r in subset]
            positions = [x_vals.index(x) + i * width for x in sub_x]
            ax.bar(positions, sub_y, width=width, label=str(sv))
        ax.set_xticks([i + (len(series_vals) - 1) * width / 2 for i in range(len(x_vals))])
        ax.set_xticklabels([str(x) for x in x_vals], rotation=45, ha="right")
        ax.legend(fontsize=9)
    else:
        x_vals = [str(r.get(x_field, "")) for r in results]
        y_vals = [float(r.get(y_field) or 0) for r in results]
        ax.bar(range(len(x_vals)), y_vals, color="#1F4E79")
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels(x_vals, rotation=45, ha="right")
    ax.set_xlabel(str(x_field), fontsize=10)
    ax.set_ylabel(str(y_field), fontsize=10)


def _draw_line(ax, results, x_field, y_field, series_field):
    if series_field and series_field in results[0]:
        series_vals = list(dict.fromkeys(r.get(series_field) for r in results))
        for sv in series_vals:
            subset = [r for r in results if r.get(series_field) == sv]
            x_vals = [str(r.get(x_field, "")) for r in subset]
            y_vals = [float(r.get(y_field) or 0) for r in subset]
            ax.plot(range(len(x_vals)), y_vals, marker="o", label=str(sv))
        ax.legend(fontsize=9)
        sample = [r for r in results if r.get(series_field) == series_vals[0]]
        all_x = [str(r.get(x_field, "")) for r in sample]
    else:
        all_x = [str(r.get(x_field, "")) for r in results]
        y_vals = [float(r.get(y_field) or 0) for r in results]
        ax.plot(range(len(all_x)), y_vals, marker="o", color="#1F4E79")

    step = max(1, len(all_x) // 10)
    ax.set_xticks(range(0, len(all_x), step))
    ax.set_xticklabels(all_x[::step], rotation=45, ha="right")
    ax.set_xlabel(str(x_field), fontsize=10)
    ax.set_ylabel(str(y_field), fontsize=10)


def _draw_pie(ax, results, x_field, y_field):
    labels = [str(r.get(x_field, "")) for r in results]
    values = [float(r.get(y_field) or 0) for r in results]
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_chart_bridge.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/chart_bridge.py \
        tests/test_export_v1/test_chart_bridge.py
git commit -m "feat(export): chart_bridge — viz_decision → Matplotlib Figure"
```

---

### Task 6: XLSX Exporter

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/xlsx.py`
- Create: `tests/test_export_v1/test_xlsx_exporter.py`

**Interfaces:**
- Consumes: `BaseExporter`, `ExporterRegistry.register`, `ExportSpec`, Matplotlib `Figure`
- Produces:
  - `XlsxExporter` — `FORMAT = "xlsx"`, `content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`
  - Sheet 1 ("Veri"): başlık satırı (row 1) + header row (row 3, lacivert arka plan) + veri satırları (row 4+)
  - Sheet 2 ("Grafik"): `chart_figure` verilmişse oluşturulur, PNG olarak eklenir

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_xlsx_exporter.py
import openpyxl
import pytest
from io import BytesIO

import src.graphs.report_agent.subagents.export_v1.exporters.xlsx  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_xlsx_produces_valid_workbook():
    exporter = ExporterRegistry.get("xlsx")
    spec = ExportSpec(format="xlsx", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    wb = openpyxl.load_workbook(buf)
    assert "Veri" in wb.sheetnames


def test_xlsx_data_rows_correct():
    exporter = ExporterRegistry.get("xlsx")
    spec = ExportSpec(format="xlsx", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    wb = openpyxl.load_workbook(buf)
    ws = wb["Veri"]
    # row 3 = header, row 4 = first data row
    assert ws.cell(row=3, column=1).value == "BranchName"
    assert ws.cell(row=4, column=1).value == "Istanbul"
    assert ws.cell(row=5, column=1).value == "Ankara"


def test_xlsx_chart_sheet_created_when_figure_given():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.bar(["A", "B"], [1, 2])
    exporter = ExporterRegistry.get("xlsx")
    spec = ExportSpec(format="xlsx", title="Rapor", include_chart=True)
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=fig)
    buf.seek(0)
    wb = openpyxl.load_workbook(buf)
    assert "Grafik" in wb.sheetnames
    plt.close("all")


def test_xlsx_no_chart_sheet_when_no_figure():
    exporter = ExporterRegistry.get("xlsx")
    spec = ExportSpec(format="xlsx", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=None)
    buf.seek(0)
    wb = openpyxl.load_workbook(buf)
    assert "Grafik" not in wb.sheetnames
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_xlsx_exporter.py -v
```

Expected: `ImportError`

- [ ] **Step 3: XlsxExporter implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/xlsx.py
import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict, List

import openpyxl
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Font, PatternFill

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

logger = logging.getLogger(__name__)

_HEADER_COLOR = "1F4E79"
_ALT_ROW_COLOR = "EBF5FB"


@ExporterRegistry.register
class XlsxExporter(BaseExporter):
    FORMAT = "xlsx"

    @property
    def content_type(self) -> str:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = spec.sheet_name

        ws.cell(row=1, column=1, value=spec.title).font = Font(bold=True, size=14)
        ws.row_dimensions[1].height = 24

        if not results:
            ws.cell(row=3, column=1, value="Veri bulunamadı.")
            buf = BytesIO()
            wb.save(buf)
            return buf

        headers = list(results[0].keys())
        header_fill = PatternFill("solid", fgColor=_HEADER_COLOR)
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col_idx, value=header)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        alt_fill = PatternFill("solid", fgColor=_ALT_ROW_COLOR)
        for row_idx, row in enumerate(results, 4):
            for col_idx, key in enumerate(headers, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=row.get(key))
                if (row_idx - 4) % 2 == 1:
                    cell.fill = alt_fill

        for col_idx, header in enumerate(headers, 1):
            col_letter = openpyxl.utils.get_column_letter(col_idx)
            max_len = max(
                len(str(header)),
                *[len(str(row.get(header, ""))) for row in results],
            )
            ws.column_dimensions[col_letter].width = min(max_len + 4, 40)

        if chart_figure is not None:
            ws_chart = wb.create_sheet("Grafik")
            ws_chart.cell(row=1, column=1, value=spec.title).font = Font(bold=True, size=14)
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                chart_figure.savefig(tmp_path, dpi=150, bbox_inches="tight")
                img = XlImage(tmp_path)
                img.anchor = "B3"
                ws_chart.add_image(img)
            except Exception as exc:
                logger.warning(f"[XLSX] Chart embedding failed: {exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        buf = BytesIO()
        wb.save(buf)
        return buf
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_xlsx_exporter.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/exporters/xlsx.py \
        tests/test_export_v1/test_xlsx_exporter.py
git commit -m "feat(export): XlsxExporter with chart sheet"
```

---

### Task 7: PDF Exporter

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/pdf.py`
- Create: `tests/test_export_v1/test_pdf_exporter.py`

**Interfaces:**
- Consumes: `BaseExporter`, `ExporterRegistry.register`, `ExportSpec`, Matplotlib `Figure`
- Produces:
  - `PdfExporter` — `FORMAT = "pdf"`, `content_type = "application/pdf"`
  - A4 sayfa: başlık → opsiyonel insight metni → opsiyonel grafik PNG → veri tablosu

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_pdf_exporter.py
import pytest
from io import BytesIO

import src.graphs.report_agent.subagents.export_v1.exporters.pdf  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_pdf_produces_pdf_bytes():
    exporter = ExporterRegistry.get("pdf")
    spec = ExportSpec(format="pdf", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    header = buf.read(4)
    assert header == b"%PDF", f"Expected PDF header, got {header!r}"


def test_pdf_empty_results_still_produces_pdf():
    exporter = ExporterRegistry.get("pdf")
    spec = ExportSpec(format="pdf", title="Rapor")
    buf = exporter.export([], spec)
    buf.seek(0)
    assert buf.read(4) == b"%PDF"


def test_pdf_with_chart_figure():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.bar(["A", "B"], [1, 2])
    exporter = ExporterRegistry.get("pdf")
    spec = ExportSpec(format="pdf", title="Rapor", include_chart=True)
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=fig)
    buf.seek(0)
    assert buf.read(4) == b"%PDF"
    plt.close("all")


def test_pdf_content_type():
    exporter = ExporterRegistry.get("pdf")
    assert exporter.content_type == "application/pdf"
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_pdf_exporter.py -v
```

Expected: `ImportError`

- [ ] **Step 3: PdfExporter implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/pdf.py
import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

logger = logging.getLogger(__name__)

_HEADER_HEX = colors.HexColor("#1F4E79")
_ALT_ROW_HEX = colors.HexColor("#EBF5FB")


@ExporterRegistry.register
class PdfExporter(BaseExporter):
    FORMAT = "pdf"

    @property
    def content_type(self) -> str:
        return "application/pdf"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ExportTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=12
        )

        story = [Paragraph(spec.title, title_style), Spacer(1, 0.4 * cm)]

        if spec.include_insight and insight_text:
            story.append(Paragraph(insight_text, styles["Normal"]))
            story.append(Spacer(1, 0.4 * cm))

        if chart_figure is not None:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                chart_figure.savefig(tmp_path, dpi=150, bbox_inches="tight")
                story.append(RLImage(tmp_path, width=15 * cm, height=9 * cm))
                story.append(Spacer(1, 0.4 * cm))
            except Exception as exc:
                logger.warning(f"[PDF] Chart embedding failed: {exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        if results:
            headers = list(results[0].keys())
            table_data = [headers] + [
                [str(row.get(h, "")) for h in headers] for row in results
            ]
            col_width = 15 * cm / max(len(headers), 1)
            tbl = Table(table_data, colWidths=[col_width] * len(headers), repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_HEX),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ALT_ROW_HEX]),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("PADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(tbl)
        else:
            story.append(Paragraph("Veri bulunamadı.", styles["Normal"]))

        doc.build(story)
        return buf
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_pdf_exporter.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/exporters/pdf.py \
        tests/test_export_v1/test_pdf_exporter.py
git commit -m "feat(export): PdfExporter with reportlab"
```

---

### Task 8: HTML Exporter

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/html.py`
- Create: `tests/test_export_v1/test_html_exporter.py`

**Interfaces:**
- Consumes: `BaseExporter`, `ExporterRegistry.register`, `ExportSpec`
- Produces:
  - `HtmlExporter` — `FORMAT = "html"`, `content_type = "text/html; charset=utf-8"`
  - Self-contained HTML dosyası: inline CSS + opsiyonel ECharts snippet (chart_figure string ise) + veri tablosu
  - `chart_figure` parametresi bu exporter'da `str` (ECharts HTML snippet) veya `None` — Matplotlib Figure değil

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_html_exporter.py
import pytest

import src.graphs.report_agent.subagents.export_v1.exporters.html  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_html_produces_valid_html():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "<!DOCTYPE html>" in content
    assert "<title>Rapor" in content


def test_html_contains_table_data():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "Istanbul" in content
    assert "BranchName" in content
    assert "<table" in content


def test_html_embeds_echarts_snippet_when_provided():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor", include_chart=True)
    echarts_snippet = '<div id="chart">ECharts HTML</div>'
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=echarts_snippet)
    content = buf.read().decode("utf-8")
    assert "ECharts HTML" in content


def test_html_no_chart_when_figure_is_none():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=None)
    content = buf.read().decode("utf-8")
    assert "chart-container" not in content


def test_html_empty_results():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor")
    buf = exporter.export([], spec)
    content = buf.read().decode("utf-8")
    assert "Veri bulunamadı" in content
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_html_exporter.py -v
```

Expected: `ImportError`

- [ ] **Step 3: HtmlExporter implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/html.py
from html import escape
from io import BytesIO
from typing import Any, Dict, List

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:2rem;color:#1a1a2e}
h1{color:#1F4E79;border-bottom:2px solid #1F4E79;padding-bottom:.5rem}
.insight{background:#EBF5FB;border-left:4px solid #1F4E79;padding:.75rem 1rem;margin:1rem 0;border-radius:4px}
.chart-container{margin:1.5rem 0}
table{border-collapse:collapse;width:100%;margin-top:1.5rem;font-size:.9rem}
th{background:#1F4E79;color:#fff;padding:10px 14px;text-align:left}
td{padding:8px 14px;border-bottom:1px solid #e0e0e0}
tr:nth-child(even){background:#F2F8FF}
tr:hover{background:#D6EAF8}
"""


@ExporterRegistry.register
class HtmlExporter(BaseExporter):
    FORMAT = "html"

    @property
    def content_type(self) -> str:
        return "text/html; charset=utf-8"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        chart_html = chart_figure if isinstance(chart_figure, str) else ""
        insight_html = (
            f"<p class='insight'>{escape(insight_text)}</p>"
            if spec.include_insight and insight_text
            else ""
        )
        chart_block = (
            f"<div class='chart-container'>{chart_html}</div>" if chart_html else ""
        )
        table_html = _build_table(results)

        html = (
            "<!DOCTYPE html>\n"
            "<html lang='tr'>\n"
            "<head>\n"
            "<meta charset='UTF-8'>\n"
            "<meta name='viewport' content='width=device-width,initial-scale=1.0'>\n"
            f"<title>{escape(spec.title)}</title>\n"
            f"<style>{_CSS}</style>\n"
            "</head>\n"
            "<body>\n"
            f"<h1>{escape(spec.title)}</h1>\n"
            f"{insight_html}\n"
            f"{chart_block}\n"
            f"{table_html}\n"
            "</body>\n"
            "</html>"
        )
        buf = BytesIO()
        buf.write(html.encode("utf-8"))
        return buf


def _build_table(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "<p>Veri bulunamadı.</p>"
    headers = list(results[0].keys())
    header_row = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = ""
    for row in results:
        cells = "".join(f"<td>{escape(str(row.get(h, '')))}</td>" for h in headers)
        body += f"<tr>{cells}</tr>\n"
    return f"<table><thead><tr>{header_row}</tr></thead><tbody>{body}</tbody></table>"
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_html_exporter.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/exporters/html.py \
        tests/test_export_v1/test_html_exporter.py
git commit -m "feat(export): HtmlExporter with ECharts embedding"
```

---

### Task 9: DOCX Exporter

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/exporters/docx.py`
- Create: `tests/test_export_v1/test_docx_exporter.py`

**Interfaces:**
- Consumes: `BaseExporter`, `ExporterRegistry.register`, `ExportSpec`, Matplotlib `Figure`
- Produces:
  - `DocxExporter` — `FORMAT = "docx"`, `content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"`
  - Word belgesi: başlık (Heading 1, lacivert) → opsiyonel insight → opsiyonel grafik → veri tablosu

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_docx_exporter.py
import pytest
from io import BytesIO

import src.graphs.report_agent.subagents.export_v1.exporters.docx  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec
from docx import Document

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_docx_produces_valid_document():
    exporter = ExporterRegistry.get("docx")
    spec = ExportSpec(format="docx", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    doc = Document(buf)
    assert len(doc.paragraphs) > 0


def test_docx_title_in_document():
    exporter = ExporterRegistry.get("docx")
    spec = ExportSpec(format="docx", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    doc = Document(buf)
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert any("Rapor" in h for h in headings)


def test_docx_table_has_correct_data():
    exporter = ExporterRegistry.get("docx")
    spec = ExportSpec(format="docx", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    doc = Document(buf)
    assert len(doc.tables) == 1
    table = doc.tables[0]
    # header row
    assert table.rows[0].cells[0].text == "BranchName"
    assert table.rows[1].cells[0].text == "Istanbul"


def test_docx_empty_results():
    exporter = ExporterRegistry.get("docx")
    spec = ExportSpec(format="docx", title="Rapor")
    buf = exporter.export([], spec)
    buf.seek(0)
    doc = Document(buf)
    texts = [p.text for p in doc.paragraphs]
    assert any("bulunamadı" in t for t in texts)
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_docx_exporter.py -v
```

Expected: `ImportError`

- [ ] **Step 3: DocxExporter implement et**

```python
# src/graphs/report_agent/subagents/export_v1/exporters/docx.py
import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict, List

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, RGBColor

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

logger = logging.getLogger(__name__)

_HEADER_RGB = RGBColor(0x1F, 0x4E, 0x79)


@ExporterRegistry.register
class DocxExporter(BaseExporter):
    FORMAT = "docx"

    @property
    def content_type(self) -> str:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        doc = Document()

        heading = doc.add_heading(spec.title, level=1)
        if heading.runs:
            heading.runs[0].font.color.rgb = _HEADER_RGB

        if spec.include_insight and insight_text:
            doc.add_paragraph(insight_text)

        if chart_figure is not None:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                chart_figure.savefig(tmp_path, dpi=150, bbox_inches="tight")
                doc.add_picture(tmp_path, width=Cm(15))
            except Exception as exc:
                logger.warning(f"[DOCX] Chart embedding failed: {exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        if results:
            headers = list(results[0].keys())
            table = doc.add_table(rows=1, cols=len(headers))
            table.style = "Table Grid"

            hdr_cells = table.rows[0].cells
            for i, h in enumerate(headers):
                cell = hdr_cells[i]
                cell.text = str(h)
                run = cell.paragraphs[0].runs[0]
                run.font.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
                _set_cell_bg(cell, "1F4E79")

            for row in results:
                cells = table.add_row().cells
                for i, h in enumerate(headers):
                    cells[i].text = str(row.get(h, ""))
        else:
            doc.add_paragraph("Veri bulunamadı.")

        buf = BytesIO()
        doc.save(buf)
        return buf


def _set_cell_bg(cell, hex_color: str) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_docx_exporter.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/exporters/docx.py \
        tests/test_export_v1/test_docx_exporter.py
git commit -m "feat(export): DocxExporter with python-docx"
```

---

### Task 10: ExportState + Graph Nodes + build_export_graph

**Files:**
- Create: `src/graphs/report_agent/subagents/export_v1/state.py`
- Create: `src/graphs/report_agent/subagents/export_v1/nodes.py`
- Create: `src/graphs/report_agent/subagents/export_v1/graph.py`
- Create: `tests/test_export_v1/test_nodes.py`

**Interfaces:**
- Consumes: Tüm Task 1–9 üretimleri
- Produces:
  - `ExportState` TypedDict — `results`, `wants_export`, `export_format`, `export_output`, `visualization_output`, `insight_output`, `session_id`, `active_results`, `error`, `export_spec`
  - `export_decider_node(state) -> dict` — `export_spec` üretir; `results` yoksa `active_results` kullanır; her ikisi de yoksa `error` set eder
  - `format_renderer_node(state) -> dict` — Registry'den exporter alır, `export_store.put()` çağırır, `export_output` döner
  - `export_response_builder_node(state) -> dict` — `export_output`'a `summary` ekler
  - `build_export_graph(export_store) -> CompiledGraph` — 3 node StateGraph

- [ ] **Step 1: ExportState yaz**

```python
# src/graphs/report_agent/subagents/export_v1/state.py
from typing import Any, Dict, List, Optional, TypedDict


class ExportState(TypedDict, total=False):
    # ReportState overlap (auto-sync)
    results: Optional[List[Dict[str, Any]]]
    active_results: Optional[List[Dict[str, Any]]]
    wants_export: Optional[bool]
    export_format: Optional[str]
    export_output: Optional[Dict[str, Any]]
    visualization_output: Optional[Dict[str, Any]]
    insight_output: Optional[str]
    session_id: Optional[str]
    error: Optional[str]
    user_query: str

    # Internal
    export_spec: Optional[Dict[str, Any]]
```

- [ ] **Step 2: Failing node testleri yaz**

```python
# tests/test_export_v1/test_nodes.py
import pytest

# trigger all exporter registrations
import src.graphs.report_agent.subagents.export_v1.exporters.csv   # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.markdown  # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.xlsx  # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.pdf   # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.html  # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.docx  # noqa

from src.graphs.report_agent.subagents.export_v1.nodes import (
    export_decider_node,
    format_renderer_node,
    export_response_builder_node,
)

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


@pytest.mark.asyncio
async def test_export_decider_produces_spec():
    state = {
        "results": SAMPLE_RESULTS,
        "export_format": "xlsx",
        "wants_export": True,
        "visualization_output": None,
        "insight_output": None,
    }
    result = await export_decider_node(state)
    assert "export_spec" in result
    assert result["export_spec"]["format"] == "xlsx"


@pytest.mark.asyncio
async def test_export_decider_falls_back_to_active_results():
    state = {
        "results": [],
        "active_results": SAMPLE_RESULTS,
        "export_format": "csv",
        "wants_export": True,
        "visualization_output": None,
    }
    result = await export_decider_node(state)
    assert "export_spec" in result
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_export_decider_sets_error_when_no_data():
    state = {"results": [], "active_results": [], "export_format": "xlsx", "wants_export": True}
    result = await export_decider_node(state)
    assert "error" in result


@pytest.mark.asyncio
async def test_format_renderer_produces_export_output(tmp_path, monkeypatch):
    from src.api.services import export_store

    captured = {}

    def fake_put(session_id, buffer, filename, content_type):
        captured["session_id"] = session_id
        captured["buffer"] = buffer

    monkeypatch.setattr(export_store, "put", fake_put)

    from src.graphs.report_agent.subagents.export_v1.models import ExportSpec
    spec = ExportSpec(format="csv", title="Rapor — 2026-06-18")
    state = {
        "results": SAMPLE_RESULTS,
        "export_spec": spec.model_dump(),
        "visualization_output": None,
        "session_id": "test-session",
    }
    result = await format_renderer_node(state)
    assert "export_output" in result
    assert result["export_output"]["format"] == "csv"
    assert "/api/export/test-session" in result["export_output"]["download_url"]
    assert "test-session" in captured


@pytest.mark.asyncio
async def test_export_passthrough_when_wants_export_false():
    state = {"wants_export": False, "results": SAMPLE_RESULTS}
    result = await export_decider_node(state)
    assert result == {}
```

- [ ] **Step 3: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_nodes.py -v
```

Expected: `ImportError`

- [ ] **Step 4: nodes.py implement et**

```python
# src/graphs/report_agent/subagents/export_v1/nodes.py
import logging
from datetime import date
from typing import Any, Dict

from src.graphs.report_agent.subagents.export_v1.chart_bridge import build_chart_figure
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

logger = logging.getLogger(__name__)

_HTML_FORMATS = {"html"}
_NO_CHART_FORMATS = {"csv", "md"}


async def export_decider_node(state: Dict[str, Any]) -> dict:
    if not state.get("wants_export"):
        return {}

    results = state.get("results") or state.get("active_results") or []
    if not results:
        logger.warning("[EXPORT] No results available for export")
        return {"error": "Export için veri bulunamadı. Önce bir sorgu çalıştırın."}

    export_format = state.get("export_format") or "xlsx"
    viz_out = state.get("visualization_output") or {}
    has_chart = bool(viz_out.get("needs_graph") and export_format not in _NO_CHART_FORMATS)
    has_insight = bool(state.get("insight_output") and export_format in ("pdf", "docx", "html"))

    spec = ExportSpec(
        format=export_format,
        include_chart=has_chart,
        include_insight=has_insight,
        title=f"Rapor — {date.today().isoformat()}",
    )
    logger.info(f"[EXPORT] spec: format={export_format}, chart={has_chart}, insight={has_insight}")
    return {"export_spec": spec.model_dump(), "results": results}


async def format_renderer_node(state: Dict[str, Any]) -> dict:
    from src.api.services import export_store

    raw_spec = state.get("export_spec")
    if not raw_spec:
        return {}

    spec = ExportSpec(**raw_spec)
    results = state.get("results") or []
    viz_out = state.get("visualization_output") or {}
    session_id = state.get("session_id") or "unknown"

    chart_figure = None
    if spec.include_chart:
        if spec.format in _HTML_FORMATS:
            chart_figure = viz_out.get("plotly_html_snippet") or ""
        else:
            chart_figure = build_chart_figure(viz_out, results)

    insight_text = state.get("insight_output") or ""

    try:
        exporter = ExporterRegistry.get(spec.format)
        buffer = exporter.export(results, spec, chart_figure=chart_figure, insight_text=insight_text)
        filename = f"rapor_{date.today().isoformat()}.{spec.format}"
        export_store.put(session_id, buffer, filename, exporter.content_type)
    except Exception as exc:
        logger.error(f"[EXPORT] Renderer failed: {exc}")
        return {"error": f"Export oluşturulamadı: {exc}"}

    logger.info(f"[EXPORT] format={spec.format}, session={session_id}")
    return {
        "export_output": {
            "format": spec.format,
            "download_url": f"/api/export/{session_id}",
            "filename": filename,
            "has_chart": chart_figure is not None and chart_figure != "",
        }
    }


async def export_response_builder_node(state: Dict[str, Any]) -> dict:
    out = state.get("export_output")
    if not out:
        return {}
    fmt = out.get("format", "").upper()
    url = out.get("download_url", "")
    summary = f"{fmt} raporu hazır. [İndir]({url})"
    return {"export_output": {**out, "summary": summary}}
```

- [ ] **Step 5: graph.py implement et**

```python
# src/graphs/report_agent/subagents/export_v1/graph.py
import logging

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.export_v1.nodes import (
    export_decider_node,
    export_response_builder_node,
    format_renderer_node,
)
from src.graphs.report_agent.subagents.export_v1.state import ExportState

logger = logging.getLogger(__name__)


def build_export_graph():
    graph = StateGraph(ExportState)
    graph.add_node("export_decider", export_decider_node)
    graph.add_node("format_renderer", format_renderer_node)
    graph.add_node("response_builder", export_response_builder_node)

    graph.add_edge(START, "export_decider")
    graph.add_edge("export_decider", "format_renderer")
    graph.add_edge("format_renderer", "response_builder")
    graph.add_edge("response_builder", END)

    compiled = graph.compile()
    logger.info("[EXPORT_V1] Built: 3 nodes, 0 LLM calls")
    return compiled
```

- [ ] **Step 6: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_nodes.py -v
```

Expected: 5 PASSED

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/export_v1/state.py \
        src/graphs/report_agent/subagents/export_v1/nodes.py \
        src/graphs/report_agent/subagents/export_v1/graph.py \
        tests/test_export_v1/test_nodes.py
git commit -m "feat(export): ExportState + nodes + build_export_graph"
```

---

### Task 11: Export Store + API Download Endpoint

**Files:**
- Create: `src/api/services/export_store.py`
- Create: `src/api/routes/export.py`
- Modify: `src/api/main.py`
- Create: `tests/test_export_v1/test_export_store.py`

**Interfaces:**
- Consumes: `build_export_graph` ürettiği `export_output["download_url"]` format'ı: `/api/export/{session_id}`
- Produces:
  - `export_store.put(session_id, buffer, filename, content_type)` — store'a yazar
  - `export_store.get(session_id) -> Optional[Tuple[BytesIO, str, str]]` — `(buffer, filename, content_type)` döner
  - `export_store.delete(session_id)` — entry siler
  - `GET /api/export/{session_id}` → `StreamingResponse` veya HTTP 404

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_export_v1/test_export_store.py
import pytest
from io import BytesIO
from src.api.services import export_store


def test_put_and_get():
    buf = BytesIO(b"hello")
    export_store.put("sess-1", buf, "rapor.csv", "text/csv")
    result = export_store.get("sess-1")
    assert result is not None
    buffer, filename, content_type = result
    buffer.seek(0)
    assert buffer.read() == b"hello"
    assert filename == "rapor.csv"
    assert content_type == "text/csv"


def test_overwrite_on_second_put():
    export_store.put("sess-2", BytesIO(b"first"), "r1.csv", "text/csv")
    export_store.put("sess-2", BytesIO(b"second"), "r2.csv", "text/csv")
    result = export_store.get("sess-2")
    assert result is not None
    buf, fname, _ = result
    buf.seek(0)
    assert buf.read() == b"second"
    assert fname == "r2.csv"


def test_get_missing_returns_none():
    assert export_store.get("nonexistent-session-xyz") is None


def test_delete_removes_entry():
    export_store.put("sess-3", BytesIO(b"x"), "r.csv", "text/csv")
    export_store.delete("sess-3")
    assert export_store.get("sess-3") is None
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
pytest tests/test_export_v1/test_export_store.py -v
```

Expected: `ImportError` veya `ModuleNotFoundError`

- [ ] **Step 3: export_store.py implement et**

```python
# src/api/services/export_store.py
from io import BytesIO
from typing import Dict, Optional, Tuple

_store: Dict[str, Tuple[BytesIO, str, str]] = {}


def put(session_id: str, buffer: BytesIO, filename: str, content_type: str) -> None:
    _store[session_id] = (buffer, filename, content_type)


def get(session_id: str) -> Optional[Tuple[BytesIO, str, str]]:
    return _store.get(session_id)


def delete(session_id: str) -> None:
    _store.pop(session_id, None)
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
pytest tests/test_export_v1/test_export_store.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: routes/export.py implement et**

```python
# src/api/routes/export.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.api.services import export_store

router = APIRouter()


@router.get("/export/{session_id}")
async def download_export(session_id: str) -> StreamingResponse:
    entry = export_store.get(session_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Export bulunamadı. Dosya oluşturulmamış veya oturum sona ermiş olabilir.",
        )
    buffer, filename, content_type = entry
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 6: main.py'e router ekle**

`src/api/main.py` dosyasında mevcut router kayıtlarının yanına şunu ekle:

```python
from src.api.routes.export import router as export_router
app.include_router(export_router, prefix="/api")
```

- [ ] **Step 7: Endpoint testi**

```bash
pytest tests/test_export_v1/test_export_store.py -v
# Ek: main.py'in syntax hatası olmadığını doğrula
python -c "from src.api.main import app; print('main OK')"
```

Expected: 4 PASSED + `main OK`

- [ ] **Step 8: Commit**

```bash
git add src/api/services/export_store.py \
        src/api/routes/export.py \
        src/api/main.py \
        tests/test_export_v1/test_export_store.py
git commit -m "feat(export): export_store + GET /api/export/{session_id} endpoint"
```

---

### Task 12: ReportState + IntentClassificationResult + classify_intent Changes

**Files:**
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/prompts.py`
- Modify: `src/graphs/report_agent/nodes.py`

**Interfaces:**
- Consumes: Task 10 ürettiği field adları: `wants_export`, `export_format`, `export_output`
- Produces:
  - `ReportState` — 3 yeni field: `wants_export`, `export_format`, `export_output`
  - `IntentClassificationResult` — 2 yeni field + `EXPORT_REQUEST` intent type
  - `classify_intent_node` — return dict'e `wants_export`, `export_format`, `export_output: None` eklenir

- [ ] **Step 1: state.py'e 3 field ekle**

`src/graphs/report_agent/state.py` dosyasında `ReportState` TypedDict'e şunları ekle (diğer Optional field'larla aynı bölüme):

```python
    # Export
    wants_export: Optional[bool]
    export_format: Optional[str]            # "xlsx"|"pdf"|"html"|"docx"|"md"|"csv"
    export_output: Optional[Dict[str, Any]]
```

`create_initial_state()` fonksiyonuna şunları ekle:

```python
        wants_export=None,
        export_format=None,
        export_output=None,
```

- [ ] **Step 2: prompts.py'de IntentClassificationResult'ı güncelle**

`src/graphs/report_agent/prompts.py` dosyasında `IntentClassificationResult` sınıfını güncelle:

**`intent_type` Literal'ine `"EXPORT_REQUEST"` ekle:**

```python
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY", "INSIGHT_REQUEST", "EXPORT_REQUEST"]
```

**İki yeni field ekle (mevcut field'ların sonuna):**

```python
    wants_export: bool = False
    export_format: Optional[str] = None    # "xlsx"|"pdf"|"html"|"docx"|"md"|"csv"
```

- [ ] **Step 3: Mevcut classifier promptunu güncelle**

`src/graphs/report_agent/prompts.py` dosyasında `INTENT_CLASSIFIER_PROMPT` string'ini bul. Prompt'a şu açıklamayı ekle (intent tipler listesinin yanına):

```
- EXPORT_REQUEST: Kullanıcı mevcut sonuçları bir dosya formatında indirmek istiyor 
  ("Excel'e aktar", "PDF rapor", "bunu indir", "Word belgesi olarak ver")
```

Ve format tespiti için:

```
wants_export: Kullanıcı "Excel", "PDF", "Word", "indir", "aktar", "dosya" gibi ifadeler 
  kullandıysa True. İlk sorguda da olabilir ("Satışları Excel'de göster").
export_format: Tespit edilen format — "xlsx" (Excel/varsayılan), "pdf", "html", "docx", 
  "md" (markdown), "csv". Belirtilmemişse "xlsx".
```

- [ ] **Step 4: nodes.py'de classify_intent_node return_dict'ini güncelle**

`src/graphs/report_agent/nodes.py` dosyasında `classify_intent_node` fonksiyonunun `return_dict` sözlüğüne şunları ekle:

```python
            "wants_export": result.wants_export,
            "export_format": result.export_format if result.wants_export else None,
            "export_output": None,
```

- [ ] **Step 5: Mevcut testlerin hâlâ geçtiğini doğrula**

```bash
pytest tests/graphs/report/ tests/unit/ -v --tb=short -q
```

Expected: Tüm mevcut testler PASS (yeni field'lar Optional olduğu için eski testler kırılmaz)

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/state.py \
        src/graphs/report_agent/prompts.py \
        src/graphs/report_agent/nodes.py
git commit -m "feat(export): ReportState + IntentClassificationResult — wants_export, export_format, EXPORT_REQUEST"
```

---

### Task 13: Parent Graph Integration (Final Wiring)

**Files:**
- Modify: `src/graphs/report_agent/graph.py`

**Interfaces:**
- Consumes: `build_export_graph()` (Task 10), `wants_export` state field (Task 12)
- Produces: Tam çalışan export pipeline — yeni routing ile tüm 3 senaryo aktif

- [ ] **Step 1: graph.py'i güncelle**

`src/graphs/report_agent/graph.py` dosyasını şu şekilde güncelle:

**Import satırı ekle:**
```python
from src.graphs.report_agent.subagents.export_v1.graph import build_export_graph
```

**`_intent_router` fonksiyonuna `EXPORT_REQUEST` ekle** (`INSIGHT_REQUEST` satırından sonra):
```python
    if intent == "EXPORT_REQUEST":
        return "export"
```

**`_after_hitl_check_router` fonksiyonunu güncelle** (mevcut `_visualization_router` çağrısını kaldır):
```python
def _after_hitl_check_router(state: dict) -> str:
    if state.get("_hitl_answered"):
        return "text2sql"
    if state.get("wants_visualization", False):
        return "visualization"
    if state.get("wants_export", False):
        return "export"
    return "build_response"
```

**Yeni `_after_visualization_router` fonksiyonu ekle:**
```python
def _after_visualization_router(state: dict) -> str:
    if state.get("wants_export", False):
        return "export"
    return "build_response"
```

**`_visualization_router` fonksiyonunu sil** (artık kullanılmıyor, `_after_hitl_check_router` içinde inlined edildi).

- [ ] **Step 2: build_report_agent_graph içinde export subgraph ekle**

`build_report_agent_graph` fonksiyonunda `visualization = build_visualization_graph(llm)` satırından sonra ekle:

```python
    export = build_export_graph()
```

`graph.add_node` satırlarına ekle:
```python
    graph.add_node("export", export)
```

- [ ] **Step 3: Kenarları güncelle**

**Kaldır:**
```python
graph.add_edge("visualization", "build_response")
```

**Değiştir** (`hitl_check` conditional edges map'ine `"export"` ekle):
```python
    graph.add_conditional_edges(
        "hitl_check",
        _after_hitl_check_router,
        {
            "text2sql":       "text2sql",
            "visualization":  "visualization",
            "export":         "export",
            "build_response": "build_response",
        },
    )
```

**Ekle** (visualization'dan sonra conditional):
```python
    graph.add_conditional_edges(
        "visualization",
        _after_visualization_router,
        {
            "export":         "export",
            "build_response": "build_response",
        },
    )
    graph.add_edge("export", "build_response")
```

**`intent_router` map'ine `"EXPORT_REQUEST"` ekle:**
```python
    graph.add_conditional_edges(
        "classify_intent",
        _intent_router,
        {
            "text2sql":        "text2sql",
            "modify_sql":      "modify_sql",
            "extract_entity":  "extract_entity",
            "visualization":   "visualization",
            "compute_results": "compute_results",
            "report_chat":     "report_chat",
            "insight_engine":  "insight_engine",
            "export":          "export",           # YENİ
        },
    )
```

- [ ] **Step 4: Graph build testi çalıştır**

```bash
python -c "
from unittest.mock import MagicMock
from src.graphs.report_agent.graph import build_report_agent_graph
llm = MagicMock()
llm.with_structured_output.return_value = MagicMock()
g = build_report_agent_graph(
    llm=llm,
    table_name='TestTable',
    column_metadata={},
    connection_string='mssql+pyodbc://dummy',
    business_rules_path='dummy.json',
    checkpointer=False,
)
print('Graph nodes:', list(g.nodes))
assert 'export' in g.nodes, 'export node missing!'
print('OK — export node found')
"
```

Expected:
```
Graph nodes: [..., 'export', ...]
OK — export node found
```

- [ ] **Step 5: Tüm mevcut testleri çalıştır**

```bash
pytest tests/ -v --tb=short -q --ignore=tests/integration
```

Expected: Tüm testler PASS (önceden geçen testler kırılmamış olmalı)

- [ ] **Step 6: Son commit**

```bash
git add src/graphs/report_agent/graph.py
git commit -m "feat(export): parent graph wiring — EXPORT_REQUEST intent, visualization→export routing"
```

---

## Self-Review

### Spec Coverage Check

| Spec Bölümü | Karşılayan Task |
|-------------|----------------|
| BaseExporter + Registry | Task 3 |
| CSV exporter | Task 4 |
| Markdown exporter | Task 4 |
| chart_bridge (Matplotlib) | Task 5 |
| XLSX exporter | Task 6 |
| PDF exporter | Task 7 |
| HTML exporter (ECharts native) | Task 8 |
| DOCX exporter | Task 9 |
| ExportState | Task 10 |
| export_decider node (active_results fallback) | Task 10 |
| format_renderer node | Task 10 |
| export_response_builder node | Task 10 |
| build_export_graph | Task 10 |
| export_store (in-memory, one-per-session) | Task 11 |
| GET /api/export/{session_id} endpoint | Task 11 |
| main.py router kaydı | Task 11 |
| ReportState yeni field'lar | Task 12 |
| IntentClassificationResult — wants_export, export_format, EXPORT_REQUEST | Task 12 |
| classify_intent return_dict güncelleme | Task 12 |
| Parent graph routing (EXPORT_REQUEST, viz→export) | Task 13 |
| Senaryo 1 (yeni sorgu + export) | Task 13 wiring |
| Senaryo 2 (grafik + export) | Task 13 wiring |
| Senaryo 3 (mevcut sonuçtan export) | Task 10 active_results fallback |

### Tip Tutarlılığı

- `ExportSpec` Task 2'de tanımlandı, Task 3–10 aynı import path'i kullanıyor: `from src.graphs.report_agent.subagents.export_v1.models import ExportSpec` ✅
- `ExporterRegistry.get(format)` Task 3'te tanımlandı, Task 10 nodes.py aynı signature'ı kullanıyor ✅
- `export_store.put(session_id, buffer, filename, content_type)` Task 11'de tanımlandı, Task 10 nodes.py aynı signature'ı çağırıyor ✅
- `build_chart_figure(viz_decision, results)` Task 5'te tanımlandı, Task 10 nodes.py aynı signature'ı kullanıyor ✅

### Placeholder Taraması

Tüm adımlarda gerçek kod blokları mevcut. "TBD", "TODO", "implement later" ifadesi yok. ✅
