# Codebase Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ölü kod ve tamamlanmamış migrasyonları temizleyerek projenin bakım yükünü ve kognitif karmaşıklığını azalt.

**Architecture:** Dört bağımsız temizlik alanı — her biri kendi commit'i ile tamamlanır. Hiçbir fonksiyonel değişiklik yapılmaz; sadece silinmesi gereken dosyalar kaldırılır, bağımlılıklar doğru yere taşınır.

**Tech Stack:** Python, git

---

## Temizlik Kapsamı ve Risk Seviyeleri

| Görev | Alan | Risk | Neden |
|-------|------|------|-------|
| 1 | `graph_repository.py` tekrarlı importlar | Düşük | Sadece log mesajı değişir |
| 2 | `visualization v1` → silinme hazırlığı | Orta | v2 state tipleri v1'den import ediyor |
| 3 | `visualization v1` dizini silme | Düşük (Task 2 sonrası) | Task 2 bağımlılığı çözerse sıfır risk |
| 4 | `data_visualization` stub silme | Düşük | Hiçbir route çağırmıyor |
| 5 | `ChatService` envanteri | Sıfır | Kod değişimi yok, belge üretimi |

**Kapsam dışı (bu PR'de dokunulmaz):**
- `routing/nodes.py` (2059 satır) bölme → ayrı refactor
- `generic_text2sql/nodekit.py` (2225 satır) bölme → ayrı refactor  
- `ReportState` alan birleştirme → insight pipeline öncesi ayrı görev
- `ChatService` birleştirme → Task 5 envanteri tamamlandıktan sonra karar

---

## Task 1: graph_repository.py Tekrarlı Import Düzeltmesi

**Files:**
- Modify: `src/graphs/graph_repository.py`

**Sorun:** `register_all()` içinde `src.graphs.routing.graph` üç kez import ediliyor ve her biri farklı bir isim altında log'lanıyor. Ayrıca silinen 15 eski graph'ın listesi bir TODO comment olarak duruyor.

- [ ] **Step 1: Mevcut durumu doğrula**

```bash
grep -n "import src.graphs.routing" src/graphs/graph_repository.py
```

Beklenen çıktı: 3 ayrı satırda `import src.graphs.routing.graph`

- [ ] **Step 2: graph_repository.py'yi düzenle**

`src/graphs/graph_repository.py` dosyasını aşağıdaki içerikle değiştir:

```python
from src.graphs.registry import GRAPH_REGISTRY
from src.models.llm import LLM

class GraphRepository:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.register_all()

    def get(self, graph_type: str):
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        return GRAPH_REGISTRY[graph_type](self.llm).build_graph()

    def get_raw(self, graph_type: str):
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        return GRAPH_REGISTRY[graph_type](self.llm)

    def list_graphs(self):
        return list(GRAPH_REGISTRY.keys())

    def register_all(self):
        """
        Registers all graph modules.
        Uses explicit imports to ensure PyInstaller compatibility.
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            import src.graphs.chat.graph
            import src.graphs.supervisor.graph
            import src.graphs.routing.graph
            logger.info("All graphs registered: chat, supervisor, routing")
        except ImportError as e:
            logger.warning(f"Could not import graphs: {e}")
```

- [ ] **Step 3: Import çözünürlüğü bozulmadığını doğrula**

```bash
python -c "from src.graphs.graph_repository import GraphRepository; print('OK')"
```

Beklenen çıktı: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/graphs/graph_repository.py
git commit -m "refactor: deduplicate graph_repository register_all imports and remove stale TODO list"
```

---

## Task 2: visualization v1 Bağımlılık Migrasyonu

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/state.py`
- Modify: `src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py`

**Sorun:** `visualization_v2/data_analyzer.py` şu an `ColumnType`, `ColumnRole`, `ColumnInfo`, `DataProfile` tiplerini `visualization/state.py`'den import ediyor. Bu, v1 dizini silinmeden önce çözülmeli.

```
# Şu anki bağımlılık (YANLIŞ):
visualization_v2/data_analyzer.py
    └── from src.graphs.report_agent.subagents.visualization.state import (
            DataProfile, ColumnInfo, ColumnType, ColumnRole
        )

# Hedef:
visualization_v2/data_analyzer.py
    └── from src.graphs.report_agent.subagents.visualization_v2.state import (
            DataProfile, ColumnInfo, ColumnType, ColumnRole
        )
```

- [ ] **Step 1: Mevcut import'u doğrula**

```bash
grep -n "from.*visualization.state import" src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py
```

Beklenen: `from src.graphs.report_agent.subagents.visualization.state import (` satırı görünmeli

- [ ] **Step 2: Tipleri visualization_v2/state.py'e ekle**

`src/graphs/report_agent/subagents/visualization_v2/state.py` dosyasının başına şu enum ve TypedDict tanımlarını ekle (mevcut `VisualizationState` sınıfından ÖNCE):

```python
"""
Visualization V2 — State Definition

VisualizationState: LangGraph shared-state pattern ile parent ReportState'e baglanir.
Mevcut v1 state ile ayni key'ler — parent uyumlu.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# =============================================================================
# COLUMN TYPES & ROLES  (DataAnalyzer tarafından kullanılır)
# =============================================================================

class ColumnType(str, Enum):
    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    UNKNOWN = "unknown"


class ColumnRole(str, Enum):
    DIMENSION = "dimension"
    METRIC = "metric"
    TIME = "time"
    IDENTIFIER = "identifier"


class ColumnInfo(TypedDict, total=False):
    name: str
    type: ColumnType
    role: ColumnRole
    sample_values: List[Any]
    unique_count: int
    null_count: int
    min_value: Optional[float]
    max_value: Optional[float]
    avg_value: Optional[float]


class DataProfile(TypedDict, total=False):
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    dimension_columns: List[str]
    metric_columns: List[str]
    time_column: Optional[str]
    time_columns: Optional[List[str]]
    has_time_series: bool
    has_multiple_dimensions: bool
    is_aggregated: bool
    sample_rows: List[Dict[str, Any]]


# =============================================================================
# VISUALIZATION STATE
# =============================================================================

class VisualizationState(TypedDict, total=False):
    # --- ReportState overlapping (auto-sync) ---
    messages: Optional[list]
    results: Optional[List[Dict[str, Any]]]
    user_query: str
    viz_request: Optional[str]
    query_type: Optional[str]
    wants_visualization: Optional[bool]
    visualization_output: Optional[Dict[str, Any]]
    error: Optional[str]
    time_granularity: Optional[str]
    comparison_dimension: Optional[str]
    requested_chart_type: Optional[str]

    # --- Internal ---
    data_profile: Optional[Dict[str, Any]]
    viz_decision: Optional[Dict[str, Any]]
    plotly_html_snippet: Optional[str]
```

- [ ] **Step 3: visualization_v2/data_analyzer.py import'unu güncelle**

`visualization_v2/data_analyzer.py` dosyasında:

```python
# ESKI (silinecek):
from src.graphs.report_agent.subagents.visualization.state import (
    DataProfile,
    ColumnInfo,
    ColumnType,
    ColumnRole,
)

# YENİ (yazılacak):
from src.graphs.report_agent.subagents.visualization_v2.state import (
    DataProfile,
    ColumnInfo,
    ColumnType,
    ColumnRole,
)
```

- [ ] **Step 4: visualization_v2'nin ayakta kalıp kalmadığını doğrula**

```bash
python -c "
from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph
print('visualization_v2 import OK')
"
```

Beklenen çıktı: `visualization_v2 import OK`

- [ ] **Step 5: v1'e başka bir import var mı kontrol et**

```bash
grep -rn "subagents.visualization.state\|subagents/visualization/state\|subagents\.visualization\b" src/ --include="*.py" | grep -v "__pycache__" | grep -v "visualization_v2"
```

Beklenen: Hiçbir satır çıkmamalı. Eğer çıkarsa, o dosyayı da güncelle.

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/state.py \
        src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py
git commit -m "refactor: migrate DataProfile/ColumnInfo types into visualization_v2, remove v1 dependency"
```

---

## Task 3: visualization v1 Dizini Silme

**Files:**
- Delete: `src/graphs/report_agent/subagents/visualization/` (tüm dizin)

**Ön koşul:** Task 2 tamamlanmış olmalı ve v2 import testi geçmiş olmalı.

- [ ] **Step 1: v1'e son bir kez import kontrolü yap**

```bash
grep -rn "subagents.visualization" src/ --include="*.py" | grep -v "__pycache__" | grep -v "visualization_v2"
```

Beklenen: Hiçbir satır çıkmamalı. Çıkarsa Task 2'ye dön.

- [ ] **Step 2: report_agent/graph.py'nin v2'yi kullandığını doğrula**

```bash
grep -n "visualization" src/graphs/report_agent/graph.py | head -5
```

Beklenen: `visualization_v2` içeren import satırı görünmeli, `visualization` değil.

- [ ] **Step 3: v1 dizinini sil**

```bash
rm -rf src/graphs/report_agent/subagents/visualization/
```

- [ ] **Step 4: Hiçbir şey kırılmadığını doğrula**

```bash
python -c "
from src.graphs.report_agent.graph import build_report_agent_graph
print('report_agent graph import OK')
"
```

Beklenen çıktı: `report_agent graph import OK`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete visualization v1 subagent — v2 is the active implementation"
```

---

## Task 4: data_visualization Stub Silme

**Files:**
- Modify: `src/graphs/graph_entrypoints.py`
- Delete: `src/graphs/data_visualization/` (tüm dizin)

**Sorun:** `data_visualization/` hiçbir route tarafından çağrılmıyor, graph_repository'e kayıtlı değil, graph.py stub durumda. Sadece `graph_entrypoints.py`'de bir `data_visualization_graph()` fonksiyonu tanımı var — onu da kaldıracağız.

- [ ] **Step 1: data_visualization'ın gerçekten kullanılmadığını doğrula**

```bash
grep -rn "data_visualization_graph\|data_visualization" src/api/ --include="*.py" | grep -v "__pycache__"
```

Beklenen: Hiçbir satır çıkmamalı. (Varsa, önce o çağrıları kaldır veya plan kapsamını genişlet.)

- [ ] **Step 2: graph_entrypoints.py'den data_visualization import ve fonksiyonunu kaldır**

`src/graphs/graph_entrypoints.py` dosyasından şu satırı sil:

```python
# SİLİNECEK import:
from src.graphs.data_visualization.graph import build_visualization_graph
```

Ve şu fonksiyonu tamamen sil:

```python
# SİLİNECEK fonksiyon:
def data_visualization_graph() -> BaseGraph:
    """
    Create and return the data visualization graph.
    ...
    """
    config = _get_config()
    llm = LLM(...)
    return build_visualization_graph(llm=llm)
```

- [ ] **Step 3: graph_entrypoints.py'nin hâlâ çalıştığını doğrula**

```bash
python -c "from src.graphs.graph_entrypoints import report_agent_graph; print('entrypoints OK')"
```

Beklenen çıktı: `entrypoints OK`

- [ ] **Step 4: data_visualization dizinini sil**

```bash
rm -rf src/graphs/data_visualization/
```

- [ ] **Step 5: Herhangi bir import kırılmadığını doğrula**

```bash
python -c "
import src.graphs.graph_entrypoints
print('graph_entrypoints OK')
"
```

Beklenen çıktı: `graph_entrypoints OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete data_visualization stub graph and remove unused entrypoint"
```

---

## Task 5: ChatService Envanteri (Kod Değişimi Yok)

**Files:**
- Create: `docs/superpowers/specs/2026-04-16-chatservice-inventory.md`

**Sorun:** İki ayrı `ChatService` implementasyonu var. Bu görev hangi sınıfın nerede kullanıldığını belgeleyecek; birleştirme kararını ileriye taşıyacak.

- [ ] **Step 1: Her iki sınıfın constructor imzasını kaydet**

```bash
grep -n "def __init__" src/api/chat_service.py src/api/services/chat_service.py
```

- [ ] **Step 2: Hangi modülün hangisini kullandığını listele**

```bash
grep -rn "from src.api.chat_service import\|from src.api.services.chat_service import" src/ --include="*.py" | grep -v "__pycache__"
```

- [ ] **Step 3: Envanter dokümanını yaz**

`docs/superpowers/specs/2026-04-16-chatservice-inventory.md` dosyasını oluştur ve şu bilgileri doldur:

```markdown
# ChatService Envanteri

## api/chat_service.py
- Constructor: `__init__(self, chatbot, session_manager, conversation_manager, assistant_manager)`
- Kullananlar: `di_container.py`, `interfaces/cli_interface.py`, `api/__init__.py`
- Özellikler: [step 1 ve 2 çıktısına göre doldur]

## api/services/chat_service.py  
- Constructor: `__init__(self, chatbot: Chatbot)`
- Kullananlar: `api/dependencies.py`, `api/routes/chat.py`, `api/routes/configuration.py`, `interfaces/gradio_interface.py`
- Özellikler: [step 1 ve 2 çıktısına göre doldur]

## Karar
[ ] Birleştir — canonical olarak [hangisi?] seç
[ ] İkisini de koru — CLI ve API ayrı ihtiyaçlara hizmet ediyor
[ ] Ayrı refactor görevi aç
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-16-chatservice-inventory.md
git commit -m "docs: add ChatService inventory to track dual-implementation decision"
```

---

## Doğrulama — Tüm Görevler Tamamlandıktan Sonra

```bash
# 1. Silinen dizinler gerçekten yok mu?
ls src/graphs/report_agent/subagents/ | grep -v visualization_v2
ls src/graphs/ | grep data_visualization

# 2. Hiçbir import kırılmadı mı?
python -c "
from src.graphs.report_agent.graph import build_report_agent_graph
from src.graphs.graph_entrypoints import report_agent_graph, generic_text2sql_graph
from src.graphs.graph_repository import GraphRepository
from src.api.services.chat_service import ChatService
from src.api.chat_service import ChatService as ChatServiceCLI
print('Tüm importlar OK')
"

# 3. git log — temiz commit geçmişi
git log --oneline -5
```

---

## Bu Temizlik Sonrası Beklentiler

| Metrik | Önce | Sonra |
|--------|------|-------|
| Aktif graph dizin sayısı | 8 | 6 |
| `visualization` dizin sayısı | 2 (v1 + v2) | 1 (v2) |
| `graph_repository.py` satır sayısı | 80 | ~45 |
| `register_all()` tekrarlı import | 3x routing.graph | 1x |
| Dead code dosyaları | ~15 | 0 |
