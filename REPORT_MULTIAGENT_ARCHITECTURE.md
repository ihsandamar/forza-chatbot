# 🎯 Multi-Agent Raporlama Sistemi - Mimarisi & Kullanım Rehberi

**Versiyon:** 2.0 (Conversational Multi-Agent)
**Tarih:** 2026-01-09
**Durum:** 🟢 Production Ready Architecture

---

## 📋 İçindekiler

1. [İsteğin Doğruluğu & Validasyonu](#1-isteğin-doğruluğu--validasyonu)
2. [Mimari Tasarım](#2-mimari-tasarım)
3. [Aracılar & Sorumlulukları](#3-aracılar--sorumlulukları)
4. [Kullanıcı Perspektifi (UX Flow)](#4-kullanıcı-perspektifi-ux-flow)
5. [Desteklenen Özellikler](#5-desteklenen-özellikler)
6. [İmplementasyon Stratejisi](#6-implementasyon-stratejisi)

---

## 1. İsteğin Doğruluğu & Validasyonu

### ✅ Talebiniz TAMAMEN DOĞRU

**Sizin Tasarladığınız Flow:**
```
User Query
    ↓
Intent Agent (Parametreleri çıkar)
    ↓
SQL Executor (Sorgu çalıştır)
    ↓
Results Returned (Sonuçları göster)
    ↓
User Iteration (Filtre/Grupla/Edit)
    ↓
Visualizer (Görselleştir - OPTIONAL)
    ↓
Export (Dosya indir)
    ↓
[LOOP BACK TO USER ITERATION]
```

### ✅ Neden Bu Tasarım Doğru?

| Aspekt | Neden |
|--------|-------|
| **Hızlılık** | Her adım minimal işlem, paralel çalıştırılabilir |
| **Doğruluk** | Intent → SQL → Results doğrusal, hata takibi kolay |
| **Conversational** | Kullanıcı sonuçları görüp iterasyon yapabiliyor |
| **Efficiency** | Gereksiz viz yok, kullanıcı istersen yapıyor |
| **Ölçeklenebilirlik** | Sub-agents bağımsız, yeni agent eklemesi kolay |
| **Fault Tolerance** | Bir agent başarısız olsa, diğerleri çalışıyor |

### 📊 Benzer Başarılı Sistemler

| Sistem | Mimarı | Faydalı Aspect |
|--------|--------|-----------------|
| **Anthropic Agents** | Tool-use based | Intent → Tool → Result loop |
| **LangGraph Multi-Agent** | Supervisor pattern | Supervisor karar veriyor |
| **Crew AI** | Task-based | Her agent bir task sorumlusu |
| **SalesForce Einstein** | Decision tree | Intent → Action → Feedback |
| **Google Duet AI** | Iterative refinement | User iteration based |

**BENZER NOKTANIZ:** Intent → Action → Result → Iteration model

---

## 2. Mimari Tasarım

### 2.1 Sistem Blok Diyagramı

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERFACE (Chat)                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Query Input | Previous Results | Export Options        │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────▼────────────┐
        │ REPORT SUPERVISOR AGENT │ (Orchestrator)
        │ - Route management      │
        │ - State tracking        │
        │ - Error handling        │
        └────────────┬────────────┘
                     │
        ┌────────────▼──────────────┐
        │  1️⃣ INTENT ANALYZER AGENT │
        │  ├─ NLP Processing       │
        │  ├─ Parameter Extraction │
        │  └─ Query Understanding  │
        └────────────┬──────────────┘
                     │
        ┌────────────▼──────────────┐
        │ 2️⃣ SQL EXECUTOR AGENT     │
        │ ├─ Query Building        │
        │ ├─ DB Execution          │
        │ └─ Result Validation      │
        └────────────┬──────────────┘
                     │
    ┌────────────────▼────────────────┐
    │   RESULTS CACHE & SESSION      │
    │  (Kullanıcı iteration için)     │
    └────────────────┬────────────────┘
                     │
        ┌────────────▼──────────────┐
        │ 3️⃣ VISUALIZER AGENT       │
        │    (Optional)              │
        │ ├─ Chart Type Selection  │
        │ ├─ Plotly Generation     │
        │ └─ i18n Localization     │
        └────────────┬──────────────┘
                     │
        ┌────────────▼──────────────┐
        │ 4️⃣ EXPORT FORMATTER AGENT │
        │  ├─ JSON/CSV/Excel      │
        │  ├─ PDF Generation      │
        │  └─ Download Management  │
        └────────────┬──────────────┘
                     │
    ┌────────────────▼──────────────┐
    │  FILE STORAGE & RETRIEVAL    │
    │  (Cloud/Local Storage)        │
    └───────────────────────────────┘
```

### 2.2 Agent Koordinasyon (LangGraph)

```python
# Graph Flow
START
    ↓
[supervisor_agent]
    ├─ Route: "analyze_intent"
    │   ↓
    │   [intent_analyzer_agent] → intent_state
    │
    ├─ Route: "execute_sql"
    │   ↓
    │   [sql_executor_agent] → results_state
    │   ↓
    │   [DECISION] Visualize needed?
    │   ├─ YES → "visualize"
    │   │   ↓
    │   │   [visualizer_agent] → viz_state
    │   │
    │   └─ NO → skip
    │
    ├─ Route: "export"
    │   ↓
    │   [export_formatter_agent] → file_path
    │
    └─ Route: "iterate"
        ↓
        [modify_query_agent] → new_intent_state
        (Loop back to sql_executor)

END
```

---

## 3. Aracılar & Sorumlulukları

### 3.1 SUPERVISOR AGENT 🎯
**Rol:** Orkestrasyonu yönet, kararları ver

```python
class ReportSupervisor:
    """
    Sorumlulukları:
    1. Intent Analyzer'ı çağır
    2. Sonucu analiz et
    3. SQL Executor'u çağır
    4. Sonuç almıştır, sonraki adımı belirle
    5. Visualizer/Export'u çağır (Opsiyonel)
    6. Error handling ve retry
    """

    ROUTES = {
        "analyze_intent": IntentAnalyzerAgent,
        "execute_sql": SQLExecutorAgent,
        "visualize": VisualizerAgent,
        "export": ExportFormatterAgent,
        "iterate": IterationAgent
    }

    async def route_decision(state: ReportState) -> str:
        """Sonraki route'u belirle"""
        if state.get("needs_visualization"):
            return "visualize"
        elif state.get("export_format"):
            return "export"
        elif state.get("user_iteration"):
            return "iterate"
        else:
            return "end"
```

**Input:** `ReportState` (user_query)
**Output:** `ReportState` (final_result)
**Timeout:** 30s

---

### 3.2 INTENT ANALYZER AGENT 🧠
**Rol:** Natural language'dan parametreleri çıkar

```python
class IntentAnalyzer:
    """
    Sorumlulukları:
    1. User query'yi oku
    2. Intent'i belirle (SELECT, AGGREGATE, TIME_SERIES, etc.)
    3. Parametreleri çıkar:
       - Tablo adı
       - Filtreler
       - Gruplandırma
       - Sıralama
       - Limit
    4. Görselleştirme gerekli mi? (Opsiyonel)
    5. Export formatı?
    """

    OUTPUT SCHEMA:
    {
        "intent": "aggregate|timeseries|ranking",
        "table": "MasterReportDocumentTable",
        "filters": [
            {"field": "DocumentDate", "operator": ">=", "value": "DATEADD(DAY, -10, ...)"}
        ],
        "group_by": ["ProductName"],
        "aggregations": [
            {"function": "SUM", "field": "Quantity", "alias": "TotalQty"}
        ],
        "order_by": [{"field": "TotalQty", "direction": "DESC"}],
        "limit": 10,
        "needs_visualization": false,  # User'ı sor
        "export_format": null,
        "confidence": 0.95
    }
```

**Input:** `user_query: str`
**Output:** `IntentState` (structured parameters)
**LLM:** gpt-4o-mini
**Latency:** 1-2s

---

### 3.3 SQL EXECUTOR AGENT ⚙️
**Rol:** SQL oluştur, çalıştır, sonuçları döndür

```python
class SQLExecutor:
    """
    Sorumlulukları:
    1. Intent'ten SQL oluştur
    2. Business rules uygula
    3. NULL checks ekle
    4. Query'yi validat et
    5. Database'de çalıştır
    6. Sonuçları döndür
    7. Error ise → self-correct (retry) veya fallback
    """

    WORKFLOW:
    1. SQL_GENERATOR_LLM(intent) → sql_query
    2. VALIDATOR(sql_query) → valid?
       - YES: execute
       - NO: retry with error context
    3. DATABASE.execute(sql_query) → results[]
    4. FORMATTER(results) → user_friendly_data
    5. CACHE(query_hash, results) → for iteration

    RESULT SCHEMA:
    {
        "sql_query": "SELECT...",
        "results": [
            {"ProductName": "X", "TotalQty": 100},
            ...
        ],
        "row_count": 5,
        "execution_time": 1.23,
        "cache_key": "abc123",
        "can_visualize": true,
        "metadata": {
            "columns": ["ProductName", "TotalQty"],
            "types": ["string", "int"]
        }
    }
```

**Input:** `IntentState` (structured intent)
**Output:** `ExecutionState` (results + metadata)
**Latency:** 2-3s

---

### 3.4 VISUALIZER AGENT 📊
**Rol:** Sonuçları görselleştir (OPTIONAL)

```python
class Visualizer:
    """
    Sorumlulukları:
    1. Result type'ını analiz et
    2. En uygun chart'ı seç
    3. Data'yı transform et
    4. Plotly figure oluştur
    5. Turkish i18n uygula
    6. HTML snippet dönür
    """

    SUPPORTED_CHARTS:
    - bar_chart (kategorik vs numeric)
    - line_chart (time series)
    - pie_chart (distribution)
    - scatter_plot (correlation)
    - table (raw data)

    OUTPUT SCHEMA:
    {
        "chart_type": "bar_chart",
        "plotly_figure": Figure(...),
        "plotly_html": "<div>...</div>",
        "chart_title": "Ürün Kategorilerine Göre Ciro",
        "can_download": true
    }
```

**Input:** `ExecutionState` (results)
**Output:** `VisualizationState` (plotly chart)
**Latency:** 1-2s
**Note:** Tamamen OPTIONAL - User isterse çağrılır

---

### 3.5 EXPORT FORMATTER AGENT 💾
**Rol:** Sonuçları dosya olarak indir

```python
class ExportFormatter:
    """
    Sorumlulukları:
    1. Export format'ı belirle (JSON/CSV/Excel/PDF)
    2. Data'yı format'a uygun hale getir
    3. Dosya oluştur
    4. Metadata ekle (tarih, query, user)
    5. Upload to storage
    6. Download link döndür
    """

    SUPPORTED_FORMATS:
    - json
    - csv
    - excel
    - pdf
    - html_report

    OUTPUT SCHEMA:
    {
        "format": "excel",
        "filename": "Rapor_2026-01-09.xlsx",
        "download_url": "https://...",
        "file_size": "2.3MB",
        "created_at": "2026-01-09T12:30:00Z"
    }
```

**Input:** `ExecutionState` (results) + export_format
**Output:** `ExportState` (file_path + download_url)
**Latency:** 1-2s

---

## 4. Kullanıcı Perspektifi (UX Flow)

### 4.1 Kullanıcı Sorgusunun Yaşam Döngüsü

```
┌─────────────────────────────────────────────────────┐
│ ADIM 1: BAŞLANGIÇ                                   │
│ User: "En çok satan ürün nedir?"                   │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │ INTENT ANALYZER     │
        │ Extracts:           │
        │ - Intent: ranking   │
        │ - Aggregation: SUM  │
        │ - Group by: product │
        └──────────┬──────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│ ADIM 2: SQL GENERATION & EXECUTION                  │
│                                                     │
│ Generated SQL:                                      │
│ SELECT TOP 10 ProductName, SUM(Quantity) AS Total  │
│ FROM MasterReportDocumentTable                     │
│ GROUP BY ProductName                               │
│ ORDER BY Total DESC                                │
│                                                     │
│ Results:                                            │
│ ┌────────────────┬────────┐                         │
│ │ ProductName    │ Total  │                         │
│ ├────────────────┼────────┤                         │
│ │ Laptop         │ 5000   │                         │
│ │ Phone          │ 3200   │                         │
│ │ Tablet         │ 1800   │                         │
│ └────────────────┴────────┘                         │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│ ADIM 3: ITERASYON (Conversational)                  │
│                                                     │
│ User Choice 1: "Laptop'u 'Son 7 gün' için göster" │
│ → New Query (merged with previous context)        │
│ → SQL EXECUTOR runs new query                     │
│ → Results updated                                  │
│                                                     │
│ User Choice 2: "Günlere göre kıra"                │
│ → New aggregation: GROUP BY DayOfWeek             │
│ → SQL updated                                      │
│                                                     │
│ User Choice 3: "Bunu grafik olarak göster"        │
│ → VISUALIZER called (bar chart)                   │
│                                                     │
│ User Choice 4: "Excel'e indir"                    │
│ → EXPORT_FORMATTER creates Excel file             │
│ → Download link provided                          │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────▼─────────┐
       │ ADIM 4: İŞLEM BİTTİ │
       │ File downloaded     │
       └─────────────────────┘
```

### 4.2 Conversational Loop (Session Based)

```python
SESSION EXAMPLE:

User Message 1: "Son 30 gün satış"
→ Intent Analyzer extracts:
   {time_range: "30d", metric: "sales"}
→ SQL Executor runs query
→ Results: 150 rows
→ Show results table

User Message 2: "Bu ürünlere göre kıra"
→ CONTEXT: Previous query cached
→ Modifies GROUP BY: add ProductName
→ SQL Executor runs MERGED query
→ Results: aggregated by product
→ Show updated results

User Message 3: "Bunu grafiğe çevir"
→ CONTEXT: Previous results available
→ Visualizer generates bar chart
→ Show interactive Plotly chart

User Message 4: "Excel ile indir"
→ CONTEXT: Previous results cached
→ Export Formatter creates file
→ Provide download link

User Message 5: "Son 10 günü de ekle"
→ CONTEXT: Previous query modified
→ Merge time filters
→ New query executed
→ Results updated
→ Loop continues...
```

---

## 5. Desteklenen Özellikler

### ✅ CORE FEATURES (REQUIRED)

| Feature | Status | Detail |
|---------|--------|--------|
| **Natural Language Query** | ✅ | "En çok satan ürün" → SQL |
| **SQL Generation** | ✅ | Intent → T-SQL |
| **Query Execution** | ✅ | Database quyruğu |
| **Results Display** | ✅ | Table format (paginated) |
| **User Iteration** | ✅ | Filtre/Grupla/Sırala |
| **Error Tolerance** | ✅ | SQL retry + self-correction |
| **Session Management** | ✅ | Query caching for iteration |
| **Export (Excel/CSV)** | ✅ | Download results |

### 🟡 ENHANCED FEATURES (OPTIONAL)

| Feature | Priority | Timing |
|---------|----------|--------|
| **Visualization** | P1 | Week 1 |
| **Turkish i18n** | P1 | Week 1 |
| **PDF Export** | P2 | Week 2 |
| **Scheduled Reports** | P2 | Week 3 |
| **Report Sharing** | P3 | Week 4 |
| **Chart Templates** | P3 | Week 4 |

### 🚀 FUTURE FEATURES (ROADMAP)

- Real-time collaboration
- Advanced analytics (ML predictions)
- Custom business logic rules
- Report versioning
- Audit trail logging

---

## 6. Implementasyon Stratejisi

### 6.1 Folder Structure

```
src/graphs/report_supervisor/
├── __init__.py
├── graph.py                          # Main supervisor graph
├── state.py                          # Shared state definitions
│
├── agents/
│   ├── intent_analyzer/
│   │   ├── __init__.py
│   │   ├── node.py                   # Intent analyzer logic
│   │   ├── prompts.py                # LLM prompts
│   │   └── state.py                  # Intent state schema
│   │
│   ├── sql_executor/
│   │   ├── __init__.py
│   │   ├── node.py                   # SQL generation + execution
│   │   ├── generator.py              # SQL building logic
│   │   ├── validator.py              # SQL validation
│   │   ├── prompts.py
│   │   └── state.py
│   │
│   ├── visualizer/
│   │   ├── __init__.py
│   │   ├── node.py
│   │   ├── chart_selector.py         # Chart type selection
│   │   ├── i18n.py                   # Turkish localization
│   │   └── state.py
│   │
│   └── export_formatter/
│       ├── __init__.py
│       ├── node.py
│       ├── exporters/
│       │   ├── json_exporter.py
│       │   ├── csv_exporter.py
│       │   ├── excel_exporter.py
│       │   └── pdf_exporter.py
│       └── state.py
│
├── services/
│   ├── session_manager.py            # Query caching + iteration
│   ├── error_handler.py              # Error management
│   └── config.py                     # Runtime configuration
│
└── tests/
    ├── test_intent_analyzer.py
    ├── test_sql_executor.py
    ├── test_visualizer.py
    └── test_export.py
```

### 6.2 Implementation Phases

#### PHASE 1: Foundation (Week 1)
- [ ] ReportSupervisor graph'ını oluştur
- [ ] IntentAnalyzer agent'ını implement et
- [ ] SQLExecutor agent'ını iyileştir (mevcut code'dan refactor)
- [ ] Session management ekle
- [ ] Basic error handling

**Expected:** Intent → SQL → Results çalışıyor

#### PHASE 2: Iteration (Week 2)
- [ ] Query modification logic
- [ ] Caching mechanism
- [ ] Conversational follow-up
- [ ] Filter merging

**Expected:** User iterations çalışıyor

#### PHASE 3: Visualization (Week 3)
- [ ] VisualizerAgent implement et
- [ ] Chart type selection
- [ ] Turkish i18n
- [ ] Plotly integration

**Expected:** Optional visualization çalışıyor

#### PHASE 4: Export (Week 4)
- [ ] ExportFormatter agent'ını implement et
- [ ] Multiple format support (Excel/CSV/JSON/PDF)
- [ ] File management
- [ ] Download mechanism

**Expected:** Export çalışıyor

---

## 7. State Definitions

### 7.1 Main ReportState

```python
class ReportState(TypedDict):
    # Input
    user_query: str
    conversation_history: List[Dict]  # Previous queries

    # Intent
    intent_data: Optional[IntentData]

    # Execution
    sql_query: Optional[str]
    results: Optional[List[Dict]]
    row_count: int
    execution_time: float

    # Visualization
    needs_visualization: bool
    visualization_data: Optional[Dict]
    chart_type: Optional[str]

    # Export
    export_format: Optional[str]  # json|csv|excel|pdf
    export_path: Optional[str]

    # Session
    session_id: str
    query_cache: Dict  # {query_hash: results}
    context: Dict  # Previous query context

    # Error Handling
    error: Optional[str]
    retry_count: int
    last_error_context: Optional[str]
```

### 7.2 IntentData Schema

```python
class IntentData(TypedDict):
    intent_type: Literal["ranking", "timeseries", "distribution", "comparison"]
    table_name: str
    filters: List[Filter]
    group_by: List[str]
    aggregations: List[Aggregation]
    order_by: List[OrderBy]
    limit: Optional[int]
    confidence: float
    ambiguities: List[str]  # If any
```

---

## 8. API/Interface Examples

### 8.1 User Interaction Example

```python
# Initialize session
session = ReportSupervisor()

# Query 1: Basic
response1 = await session.chat("En çok satan 5 ürün")
# Output:
# {
#   "type": "results_table",
#   "data": [...],
#   "suggestions": [
#     "Tarih aralığı ekle",
#     "Kategoriye göre kıra",
#     "Grafikle göster"
#   ]
# }

# Query 2: Iteration
response2 = await session.chat("Son 10 gün için")
# Output: Updated results (merged with context)

# Query 3: Visualization
response3 = await session.chat("Bunu grafik olarak göster")
# Output:
# {
#   "type": "visualization",
#   "chart_html": "...",
#   "chart_type": "bar_chart"
# }

# Query 4: Export
response4 = await session.chat("Excel'e indir")
# Output:
# {
#   "type": "file_download",
#   "filename": "Rapor_2026-01-09.xlsx",
#   "download_url": "..."
# }
```

### 8.2 REST API Example

```bash
# POST /api/report/query
{
  "session_id": "abc123",
  "user_query": "Son 30 gün satış toplamı",
  "visualization": false,
  "export_format": null
}

# Response
{
  "status": "success",
  "data": {
    "type": "results_table",
    "columns": ["ProductName", "TotalSales"],
    "rows": [...],
    "row_count": 15,
    "execution_time": 2.34,
    "suggestions": [...]
  }
}

# POST /api/report/query (with iteration)
{
  "session_id": "abc123",
  "user_query": "Bunu kategorilere göre kıra",
  "use_context": true  # ← Use previous query context
}

# POST /api/report/export
{
  "session_id": "abc123",
  "format": "excel"
}

# Response
{
  "status": "success",
  "download_url": "https://storage.com/Rapor_2026-01-09.xlsx"
}
```

---

## 9. Güvenlik & Performans

### 9.1 Güvenlik Önlemleri

✅ SQL Injection Prevention
- Parameterized queries only
- Input validation
- SQL whitelist (SELECT, WHERE, GROUP BY, ORDER BY only)

✅ Access Control
- Session-based authentication
- User → Query → Results lineage
- Audit logging

✅ Data Privacy
- Export files encrypted
- Temporary file cleanup
- GDPR compliance

### 9.2 Performans Hedefleri

| Operation | Target | Notes |
|-----------|--------|-------|
| Intent Analysis | <2s | LLM call |
| SQL Execution | <2s | DB query |
| Visualization | <2s | Plotly rendering |
| Export | <3s | File generation |
| **Total** | **<10s** | Per user request |

---

## 10. Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Query Accuracy | >95% | - |
| Response Time | <10s | - |
| Conversation Continuity | >90% | - |
| Export Success Rate | >99% | - |
| User Satisfaction | >4.5/5 | - |

---

## 📝 Summary

### Sizin İsteğiniz:
✅ Intent Agent → SQL → Results → User Iteration → Visualize (optional) → Export

### Neden Bu Doğru:
✅ Hızlı (minimal processing)
✅ Doğru (focused agents)
✅ Conversational (user iteration)
✅ Scalable (modular agents)
✅ Fault-tolerant (independent agents)

### Implementasyon:
✅ 4 haftada ready
✅ Modular, testable
✅ Production-grade

---

**Ready to implement? Start with PHASE 1 (Intent + SQL Executor refactor)**
