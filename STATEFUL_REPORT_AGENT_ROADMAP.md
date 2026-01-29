# 🚀 Stateful Memory Report Agent - Mimarı Değerlendirmesi & Roadmap

**Tarih:** 29 Ocak 2026
**Branch:** `feat/report-hitl`
**Hedef:** Report Agent → Sohbet-Odaklı, Stateful Memory ile Analiz Partneri Sistemi

---

## 📊 BÖLÜM 1: YAPININ UYGUNLUĞU (Feasibility Assessment)

### ✅ Zaten Mevcut - Temel Altyapı Hazır

| Özellik | Mevcut Durum | Konum |
|---------|-------------|-------|
| **LangGraph Mimarisi** | ✅ Full implementation | `/src/graphs/` |
| **Multi-Agent Orchestration** | ✅ Supervisor pattern | `/src/graphs/supervisor/graph.py` |
| **State Management (TypedDict)** | ✅ Hierarchical states | `/src/core/states/` |
| **Session Management** | ✅ In-memory (scalable) | `/src/core/session_manager.py` |
| **Configuration Injection** | ✅ 3-level cascading | `/src/core/runtime_config.py` |
| **Database Integration** | ✅ MSSQL + pyodbc | `/src/graphs/generic_text2sql/` |
| **Text2SQL Agent** | ✅ Full pipeline | `/src/graphs/generic_text2sql/` |
| **Value Resolver** | ✅ Fuzzy matching, schema discovery | `value_resolver_service.py` |
| **Checkpointing** | ⚠️ Partial (SqliteSaver) | `BaseGraph.get_memory()` |
| **API Layer** | ✅ FastAPI ready | `/src/api/` |

### ⚠️ Kısmen Mevcut - Geliştirme Gerekir

| Özellik | Mevcut Durum | Eksik Kısım |
|---------|-------------|------------|
| **Stateful Conversation** | 🟡 Messages var | **Active query context YOK** |
| **HITL (Soru Sorma)** | 🟡 Supervisor tools var | **Ask-user interrupt flow YOK** |
| **Incremental SQL** | ❌ Sıfırdan SQL üretilir | **Delta-update logic YOK** |
| **Context Rollback** | ❌ Yok | **Query checkpoint history YOK** |
| **Intent Analysis** | 🟡 Parser var | **Son N mesaj özeti YOK** |
| **Conversation Summarization** | ❌ Yok | **Context bloat prevention YOK** |

### ❌ Tamamen Eksik - Yeni Geliştirme

| Özellik | Gerekçe | Çözüm |
|---------|---------|--------|
| **active_query_context** | SQL state saklamak için | State'e yeni field ekleme |
| **Delta-SQL Generator** | "Bunu da ekle" mantığı | New SQL node variant |
| **Confidence Score System** | HITL karar mantığı | Supervisor enhancement |
| **ask_user Tool** | Interrupt mechanism | New tool + waiting_room state |
| **Query History Manager** | Undo/Redo capability | State reducer functions |
| **Semantic Intent Detector** | "Ekle mi, değiştir mi?" analizi | New intent classifier |
| **Context Bloat Prevention** | Uzun konuşmalarda hata | Summarization middleware |

---

## 🎯 BÖLÜM 2: MİMARİ DEĞERLENDİRME

### **Sonuç: %95 UYGUN ✅**

**Neden?**
1. **LangGraph zaten minimal setup'ta**: State reducer patterns kullanmaya hazır
2. **Supervisor orchestration hazır**: Routing logic'i active_query_context yönetimi için adapt edilebilir
3. **TypedDict hierarchy**: Yeni state fields kolayca eklenir
4. **Config injection ready**: Runtime'da table names, filters vs. inject edilebilir
5. **SessionManager ready**: thread_id-based session history backup

**Riskler:**
- ⚠️ **Performance**: Uzun SQL history (list) state'de saklanırsa memory bloat olabilir → **Çözüm**: History → separate cache
- ⚠️ **Checkpointer overhead**: Her delta-update saklanırsa DB yazılımı artar → **Çözüm**: Async checkpoint, batch writes
- ⚠️ **HITL latency**: Interrupt ve bekleme logic'i real-time olmalı → **Çözüm**: Streaming + interrupt_before

---

## 🗺️ BÖLÜM 3: ROADMAP - 7 AŞAMA

### **PHASE 1: State Architecture Enhancement (3-4 gün)**

**Amaç:** Report agentinin state'ine "memory" ekleme

#### 1.1 - Enhanced ReportState Tanımı
**Dosya:** `/src/graphs/report/state.py`

```python
# YENİ STATE YAPISI
class ActiveQueryContext(TypedDict):
    """Mevcut SQL sorgusu ve bağlamı saklar"""
    current_table: str                  # "SatışVerileri", "MüşteriVerileri"
    current_sql: str                    # Aktif SQL string
    applied_filters: List[Dict]         # [{"column": "şehir", "value": "İstanbul", "operator": "="}]
    grouping_columns: List[str]         # Grup kolonları
    order_by_columns: List[str]         # Sıralama
    result_sample: Optional[Dict]       # İlk 5 satırın özeti (full data değil)
    result_row_count: int               # Kaç satır döndü
    last_execution_time: str            # Timestamp
    confidence_score: float             # 0.0-1.0 güven skoru

class QueryCheckpoint(TypedDict):
    """Undo/redo için sorgu versiyonları"""
    version: int
    timestamp: str
    active_context: ActiveQueryContext
    user_message: str

class ReportStateEnhanced(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

    # YENI ALANLAR
    active_query_context: Optional[ActiveQueryContext]
    query_history: Annotated[List[QueryCheckpoint], "append"]  # Reducer
    pending_questions: List[Dict]  # {"question": "...", "options": [...]}
    waiting_for_user_input: bool
    context_summary: Optional[str]  # Son N mesaj özeti

    # Existing
    text2sql_output: Optional[dict]
    visualization_output: Optional[dict]
    error: Optional[str]
```

**Aksiyon:**
1. `state.py` güncelle: `ActiveQueryContext`, `QueryCheckpoint`, `ReportStateEnhanced` ekle
2. Reducer functions ekle:
   ```python
   def append_query_checkpoint(existing, new):
       # Keep only last 10 versions (memory limit)
       return (existing + [new])[-10:]
   ```

---

#### 1.2 - Supervisor State Enhancement
**Dosya:** `/src/graphs/supervisor/state.py` (veya supervisor graph'ında)

**Eklenecek Logic:**
```python
class SupervisorState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

    # YENI - HITL support
    pending_clarification: Optional[Dict]  # {"question": "Hangi tablo?", "options": [...]}
    user_confidence_threshold: float = 0.75  # Supervisor soru sormak için
    current_context_snapshot: Optional[Dict]  # Önceki aktif context
```

**Aksiyon:**
1. Supervisor state'e clarification fields ekle
2. confidence_score calculation logic oluştur

---

### **PHASE 2: Supervisor Intelligence & HITL Integration (4-5 gün)**

**Amaç:** "Soru soran", "anlamlandıran" supervisor

#### 2.1 - Intent Classification + Confidence Scoring
**Yeni Dosya:** `/src/graphs/supervisor/intent_classifier.py`

```python
class IntentType(str, Enum):
    NEW_QUERY = "new_query"              # "İK raporu getir"
    APPEND_MODIFICATION = "append"       # "Bunu da ekle", "Sadece İstanbul"
    CLARIFY_EXISTING = "clarify"         # "Biraz daha detaylı"
    ROLLBACK = "rollback"                # "Bir önceki hali göster"
    VISUALIZE_DIFFERENT = "viz_change"   # "Bunu bar chart yap"

class ClassificationResult(TypedDict):
    intent_type: IntentType
    confidence: float  # 0.0-1.0
    requires_clarification: bool
    clarification_options: Optional[List[str]]  # Kullanıcıya sunulacak seçenekler

async def classify_user_intent(
    user_message: str,
    conversation_history: List[BaseMessage],
    active_context: Optional[ActiveQueryContext],
    llm: BaseLanguageModel
) -> ClassificationResult:
    """
    Prompt logic:
    1. Son 3 mesajı özetle
    2. Aktif context varsa göster
    3. İstenilen niyet nedir? (enum)
    4. Bu niyet ne kadar net? (%75+ ise devam, altı ise sor)
    5. Eksik bilgi varsa ne soracağız?
    """
    pass
```

**Aksiyon:**
1. LLM-based intent classifier oluştur (chain pattern)
2. Confidence threshold logic ekle

---

#### 2.2 - Supervisor Decision Matrix
**Dosya:** `/src/graphs/supervisor/graph.py` - `supervisor_agent_node` enhance

**Yeni Logic Örneği:**

```python
async def supervisor_decision_node(state: SupervisorState):
    """
    Karar Matrix:

    IF intent == NEW_QUERY:
        → Archive eski context
        → Route to text2sql (fresh start)

    IF intent == APPEND_MODIFICATION and confidence >= 0.75:
        → Get active_query_context
        → Route to delta_sql_generator

    IF intent == APPEND_MODIFICATION and confidence < 0.75:
        → Confidence score ile soru oluştur
        → Route to ask_user_node (interrupt)
        → Wait for clarification

    IF intent == CLARIFY_EXISTING and has active_context:
        → Supervisor soru sorar: "Şehir bazlı mı, ilçe bazlı mı detay istiyorsunuz?"
        → Clarification options ekle

    IF intent == ROLLBACK:
        → query_history'den önceki version al
        → active_query_context restore et
        → Visualization yenile
    """
    pass
```

**Aksiyon:**
1. Supervisor node'u refactor: `supervisor_agent_node` → conditional logic
2. Clarification prompt templates oluştur

---

#### 2.3 - Ask-User Tool & Waiting Room
**Yeni Dosya:** `/src/graphs/supervisor/tools.py` (enhanced)

```python
# Existing tools + NEW

async def ask_user_for_clarification(
    question: str,
    options: List[str],
    context: str
) -> Dict:
    """
    Tool logic:
    1. Kullanıcıya JSON message gönder: {"type": "user_question", "question": ..., "options": ...}
    2. State'e pending_clarification ekle
    3. waiting_for_user_input = True set et
    4. LangGraph'ı "interrupt" state'ine al (beslenmiş veri bekleme modu)
    5. Kullanıcı cevap verince waiting_for_user_input = False yap

    Message format:
    {
        "type": "user_question",
        "question": "Hangi tablo? Bireysel_Müşteriler mi yoksa Kurumsal_Müşteriler mi?",
        "options": ["Bireysel", "Kurumsal", "İkisini Birleştir"],
        "context": "Müşteri listesi istendi..."
    }
    """
    pass
```

**Aksiyon:**
1. `ask_user_for_clarification` tool implement et
2. Supervisor edge logic: `ask_user_tool` return → waiting_room state → message handler → resume

---

### **PHASE 3: Delta-SQL Update Engine (5-6 gün)**

**Amaç:** "Bunu da ekle" → SQL modify (rebuild değil)

#### 3.1 - Delta-SQL Node (Yeni Node Type)
**Yeni Dosya:** `/src/graphs/generic_text2sql/delta_sql_node.py`

```python
class DeltaSQLRequest(TypedDict):
    """Mevcut SQL'i update etmek için"""
    current_sql: str
    current_filters: List[Dict]         # WHERE clause'daki filtreler
    user_modification: str              # "Sadece İstanbul olsun"
    modification_type: str              # "add_filter", "remove_filter", "change_aggregation"
    active_context: ActiveQueryContext

class DeltaSQLResult(TypedDict):
    updated_sql: str
    modified_clauses: Dict              # Ne değişti? {"where": [...], "group_by": [...]}
    change_summary: str                 # "WHERE clause'a İstanbul filtresi eklendi"

async def delta_sql_generator_node(
    state: GenericText2SQLState,
    llm: BaseLanguageModel
) -> Dict[str, DeltaSQLResult]:
    """
    Prompt Design:

    System Prompt:
    "Veritabanı SQL uzmanısın. Senden şu görev: Mevcut bir SQL sorgusunu kullanıcı isteğine göre MODIFIY etmek.
     - Sorgunun WHERE, GROUP BY, ORDER BY clause'larını değiştirebilirsin
     - SELECT, FROM hiç değiştirme (aksi talep edilmedikçe)
     - Mantıksal sonuç döndür (boş veri vs. check et)
     - Değişikliklerin özetini ver"

    Input:
    Current SQL: "SELECT şehir, SUM(satış) FROM Satışlar WHERE yıl=2024 GROUP BY şehir"
    User modification: "Sadece İstanbul olsun"

    Expected Output:
    Modified SQL: "SELECT şehir, SUM(satış) FROM Satışlar WHERE yıl=2024 AND şehir='İstanbul' GROUP BY şehir"
    Changed: {"where": ["şehir='İstanbul' condition added"]}
    Summary: "WHERE clause'a İstanbul filtresi eklendi"

    Modification Types:
    - add_filter: "Sadece İstanbul", "Son 30 gün"
    - remove_filter: "Şehir filtresini kaldır"
    - change_aggregation: "Günlük değil aylık göster" (GROUP BY değişikliği)
    - add_column: "Buna da mağaza ekle" (SELECT'e kolon ekleme)
    - order_change: "Ters sırada göster"
    """

    # Implementation approach:
    # 1. Parse user_modification with LLM → determine change type
    # 2. Extract current WHERE/GROUP BY/ORDER BY clauses
    # 3. Apply delta logic (SQL template + variable injection)
    # 4. Validate: execute test query with LIMIT 1
    # 5. If no results after delta → suggest rollback

    pass
```

**Aksiyon:**
1. Delta SQL node logic oluştur
2. Modification type classifier oluştur
3. SQL clause parser utility oluştur (WHERE/GROUP BY/ORDER BY extraction)
4. Validation query (LIMIT 1 check) implement et

---

#### 3.2 - Text2SQL Graph Enhancement
**Dosya:** `/src/graphs/generic_text2sql/graph.py`

**Yeni Edge Logic:**

```python
# Mevcut flow:
extract_query → intent_parser → text2sql_node → execute → result

# YENİ FLOW (conditional):
extract_query →  intent_analyzer (report agent'ın supervisor'undan)
    ↓
IF is_delta_request (mevcut context + "ekle" semantiği):
    → delta_sql_generator_node (MODIFY existing SQL)
    → validate_delta_result
    ↓
ELSE:
    → sql_architect (fresh start)
    → sql_query_builder
    ↓
execute → result
```

**Aksiyon:**
1. Graph'a conditional edge ekle: `intent_analyzer` → delta vs. fresh
2. `delta_sql_generator_node` integrate et

---

### **PHASE 4: Context Summarization & Memory Management (3-4 gün)**

**Amaç:** Uzun konuşmalarda bağlam karışması önleme

#### 4.1 - Conversation Summarizer
**Yeni Dosya:** `/src/graphs/supervisor/conversation_summarizer.py`

```python
class ConversationSummary(TypedDict):
    summary_text: str                   # "Son 6 mesajda: Satış verileri, Aralık 2024, İstanbul şehri"
    key_entities: List[str]             # ["Satış", "Aralık 2024", "İstanbul"]
    extracted_tables: List[str]         # ["Satışlar"]
    extracted_filters: Dict             # {"tarih": "2024-12", "şehir": "İstanbul"}

async def summarize_conversation_history(
    messages: List[BaseMessage],
    max_messages: int = 3
) -> ConversationSummary:
    """
    Her 5-6 mesajda bir, son N mesajı özetle.
    Çıkartılanlar:
    - Tablolar / raporlar
    - Filtreler (tarih, şehir vs.)
    - Aggregation types (aylık, günlük vs.)
    - Problem domains (Satış, Müşteri, İnsan Kaynakları)

    Amaç: Context bloat prevention + Supervisor'a hint verme
    """
    pass
```

**Aksiyon:**
1. LLM-based conversation summarizer oluştur
2. Token-efficient prompt design (GPT-4o mini ile)
3. Supervisor node'a summary injection ekle

---

#### 4.2 - Context Bloat Prevention
**Dosya:** `/src/graphs/supervisor/graph.py` - enhancement

**Logic:**

```python
async def supervisor_maintenance_node(state: SupervisorState):
    """
    Her N mesajda bir çalışan "cleanup" node:

    1. Message count > 15 ise:
        → Son 4 mesajı tut
        → Öncekiler + active context → summary'ye çevir
        → State'den eski mesajları sil (archive yapma, sil)

    2. Query checkpoint count > 10 ise:
        → Last 5 checkpoint'i tut
        → Diğerleri silinir

    3. Active context > 30 dakika eskiyse:
        → Archive et, uyarı ver
    """
    pass
```

**Aksiyon:**
1. Maintenance node ekle
2. Cleanup trigger logic oluştur (message count, time-based)

---

### **PHASE 5: Checkpoint & Rollback System (3-4 gün)**

**Amaç:** Undo/Redo capability + Error recovery

#### 5.1 - Query Checkpoint Manager
**Yeni Dosya:** `/src/graphs/report/checkpoint_manager.py`

```python
class QueryCheckpointManager:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.checkpoints: List[QueryCheckpoint] = []

    async def create_checkpoint(self, context: ActiveQueryContext, user_message: str):
        """Her başarılı SQL execute'dan sonra checkpoint oluştur"""
        checkpoint = QueryCheckpoint(
            version=len(self.checkpoints) + 1,
            timestamp=datetime.now().isoformat(),
            active_context=context,
            user_message=user_message
        )
        self.checkpoints.append(checkpoint)
        # Persist to session manager / DB
        return checkpoint

    async def validate_checkpoint(self, checkpoint: QueryCheckpoint) -> bool:
        """Checkpoint'i re-execute et, hala geçerli mi?"""
        # Re-execute last SQL with LIMIT 1
        # If no results → invalid, return False
        pass

    async def rollback_to_checkpoint(self, version: int) -> ActiveQueryContext:
        """Eski state'e geri dön"""
        checkpoint = self.checkpoints[version - 1]
        # Restore active_context
        # Re-execute SQL
        # Update visualization
        return checkpoint.active_context

    async def suggest_checkpoint_on_empty_result(self):
        """Boş sonuç gelince: "Geçen hali geri yükleyelim mi?" sor"""
        pass
```

**Aksiyon:**
1. CheckpointManager class oluştur
2. Report state'e integrate et

---

#### 5.2 - Rollback Node & Interrupt
**Dosya:** `/src/graphs/report/nodes.py` - new node

```python
async def handle_empty_result_node(state: ReportStateEnhanced):
    """
    Eğer text2sql_output.row_count == 0:
        1. Bildir: "Bu filtreyle veri bulunamadı"
        2. Soru sor: "Son başarılı sorguya geri dönelim mi?"
        3. pending_questions'a ekle
        4. waiting_for_user_input = True
    Else:
        → next node (visualization)
    """
    pass
```

**Aksiyon:**
1. Empty result handler node implement et
2. Supervisor'da "rollback accepted" edge logic ekle

---

### **PHASE 6: Context Injection & Delta-Update Integration (3-4 gün)**

**Amaç:** State → LLM prompts'a context inject etme

#### 6.1 - Context Injection Middleware
**Yeni Dosya:** `/src/graphs/supervisor/context_injector.py`

```python
class ContextInjectionMiddleware:
    """Her LLM call'a aktif context'i inject et"""

    @staticmethod
    def inject_into_system_prompt(
        base_prompt: str,
        active_context: Optional[ActiveQueryContext]
    ) -> str:
        """
        Original: "Bana SQL uzmanısın, yapabileceğin sorguları ver"

        Injected:
        "Bana SQL uzmanısın...

        CURRENT CONTEXT:
        - Table: Satışlar
        - Current SQL: SELECT şehir, SUM(satış) FROM Satışlar WHERE yıl=2024 GROUP BY şehir
        - Active Filters: yıl=2024
        - Result: 15 şehir, 25M TL toplam
        - Last execution: 2 dakika önce

        Kullanıcının sonraki isteği bu bağlamda yapılacak. Mevcut SQL'i modifiye et veya yenisini yaz."
        """
        pass

    @staticmethod
    def inject_clarification_hints(
        options: List[str],
        active_context: Optional[ActiveQueryContext]
    ) -> List[Dict]:
        """
        Seçenekleri context'e göre enrich et

        Example:
        Options: ["Şehir bazlı", "İlçe bazlı", "Mağaza bazlı"]
        Context: "Şu an şehir bazlı görüyorsünüz (15 satır)"

        Result:
        [
            {"label": "Şehir bazlı", "description": "(Şu an seçili - 15 satır)"},
            {"label": "İlçe bazlı", "description": "(Daha detaylı - tahmini 150 satır)"},
            {"label": "Mağaza bazlı", "description": "(En detaylı - tahmini 1500 satır)"}
        ]
        """
        pass
```

**Aksiyon:**
1. Middleware implement et
2. System prompt injection'ını test et

---

#### 6.2 - Supervisor-to-Text2SQL Handoff Enhancement
**Dosya:** `/src/graphs/supervisor/graph.py` ve `/src/graphs/generic_text2sql/graph.py`

**Handoff Data Structure:**

```python
class SupervisorHandoff(TypedDict):
    """Supervisor → Text2SQL ajanı handoff'u"""
    user_query: str
    is_delta_request: bool
    active_query_context: Optional[ActiveQueryContext]
    suggested_modification_type: Optional[str]  # "add_filter", "change_aggregation"
    confidence_level: float
    clarification_provided: Optional[str]  # Supervisor'ın aldığı user answer
```

**Aksiyon:**
1. Handoff data structure define et
2. Supervisor'da handoff structure'ı create et
3. Text2SQL'de handoff'u parse et

---

### **PHASE 7: Integration, Testing & Optimization (5-6 gün)**

**Amaç:** Tüm pieces'leri bir araya getir, test et

#### 7.1 - Full Report Agent Graph Refactor
**Dosya:** `/src/graphs/report/graph.py`

**Yeni Flow (End-to-End):**

```
START
    ↓
supervisor_classifies_intent
    ├─ intent.confidence >= 0.75 → proceed
    └─ confidence < 0.75 → ask_user_for_clarification
    ↓
user_responds [waiting_room] (interrupt)
    ↓
supervisor_decision_matrix
    ├─ NEW_QUERY → archive_old_context
    ├─ APPEND_MODIFICATION → invoke_delta_sql_node
    ├─ ROLLBACK → restore_checkpoint
    └─ VISUALIZE → keep_same_sql_new_viz
    ↓
text2sql_or_delta_sql_invoke
    ↓
check_result_validity
    ├─ empty_result → suggest_rollback (interrupt)
    ├─ error → suggest_known_alternatives
    └─ success → continue
    ↓
user_responds [waiting_room]
    ↓
create_checkpoint (successful state)
    ↓
visualization_node
    ↓
context_refresh_check (every 5 messages)
    ├─ yes → supervisor_summary_node → explicit_context_update_message
    └─ no → build_response
    ↓
build_response (include context preview)
    ↓
END
```

**Aksiyon:**
1. Full graph refactor et
2. Conditional edges + waiting_room integrate et
3. Checkpoint creation integrate et

---

#### 7.2 - State Adapter Update
**Dosya:** `/src/adapters/` (varsa report adapter, veya new)

**Örnek:**

```python
class ReportStateAdapter(BaseStateAdapter):
    """Report-specific state adaptations"""

    async def adapt(self, state: ChatbotState) -> ReportStateEnhanced:
        """Çevir: ChatbotState → ReportStateEnhanced"""
        return ReportStateEnhanced(
            messages=state.messages,
            active_query_context=None,  # Initialize
            query_history=[],
            pending_questions=[],
            waiting_for_user_input=False,
            context_summary=None,
            text2sql_output=None,
            visualization_output=None,
            error=None
        )
```

**Aksiyon:**
1. Report-specific adapter create/enhance et
2. Supervisor'ın adapter'ı invoke etmesini ensure et

---

#### 7.3 - End-to-End Test Scenarios
**Yeni Dosya:** `/tests/test_stateful_report_e2e.py`

**Test Cases:**

```python
# Scenario 1: New Query (baseline)
def test_new_query_fresh_context():
    # User: "Geçen ayın satışlarını göster"
    # Assert: active_query_context created
    # Assert: current_sql generated from scratch
    pass

# Scenario 2: Append Modification
def test_append_filter_delta_update():
    # Setup: existing context with SQL
    # User: "Sadece İstanbul olsun"
    # Assert: current_sql MODIFIED (not rebuilt)
    # Assert: WHERE clause updated
    pass

# Scenario 3: HITL - Ambiguity
def test_hitl_clarification_ambiguity():
    # Setup: Müşteri tablosu ambiguous
    # User: "Müşterileri listele"
    # Assert: ask_user_for_clarification called
    # Assert: pending_questions populated
    # Assert: waiting_for_user_input = True
    # User input: "Bireysel"
    # Assert: resume with selected option
    pass

# Scenario 4: Empty Result Recovery
def test_empty_result_rollback():
    # Setup: existing context with data
    # User: "Sadece Urfa olsun"
    # Result: 0 rows
    # Assert: suggest_rollback offered
    # User: "Evet, geri al"
    # Assert: previous checkpoint restored
    pass

# Scenario 5: Context Bloat Prevention
def test_context_summarization_on_long_chat():
    # Setup: 20+ messages
    # Assert: old messages archived
    # Assert: summary created
    # Assert: query_history limited to last 5
    pass

# Scenario 6: Full Conversation Flow
def test_full_conversation_flow():
    # User: "Geçen ayın satışlarını göster"
    #   → SQL generated, visualization created
    # User: "Sadece İstanbul olsun"
    #   → Delta SQL applied
    # User: "Bunu bar chart yap"
    #   → Same SQL, new visualization
    # User: "Tüm il\çeleri göster"
    #   → Rollback or new SQL?
    # Assert: all transitions work seamlessly
    pass
```

**Aksiyon:**
1. E2E test suite create et
2. Mock LLM + database fixture'ları oluştur
3. Tüm scenarios pass et

---

#### 7.4 - Performance Optimization
**Tasks:**

1. **Query History Caching**: Query checkpoint'leri Redis'e cache et (optional)
2. **LLM Prompt Caching**: Mevcut SQL prompt'larını cache et (OpenAI API feature)
3. **Async Checkpointing**: Checkpoint yazılımını async background task yap
4. **State Size Monitoring**: state size metrics log et (Prometheus)

**Aksiyon:**
1. Performance profiling et
2. Bottleneck identify et
3. Optimization implement et

---

## 📋 BÖLÜM 4: DETAILED TASK BREAKDOWN

### Quick Reference - 7 Fase Özeti

| Fase | Dosyalar | Estimated Lines | Dependencies |
|-----|----------|------------------|--------------|
| 1 | `/src/graphs/report/state.py` | +150 | None |
| 2 | Supervisor graph + intent_classifier | +400 | Phase 1 |
| 3 | Delta SQL node | +300 | Phase 1, 2 |
| 4 | Conversation summarizer | +200 | Phase 1, 2 |
| 5 | Checkpoint manager | +250 | Phase 1 |
| 6 | Context injector | +150 | All phases |
| 7 | Tests + integration | +500 | Phase 1-6 |
| **TOPLAM** | | **~1950 lines** | Sequential |

---

## 🛠️ BÖLÜM 5: TEKNIK KILAVUZLAR

### 5.1 - State Reducer Functions (TypedDict Patterns)

```python
# Pattern 1: Append with History Limit
from typing import Annotated

def keep_last_n_checkpoints(existing: List, new: List, n=10):
    """Keep only last N items"""
    return (existing + new)[-n:]

# Usage:
query_history: Annotated[
    List[QueryCheckpoint],
    lambda existing, new: keep_last_n_checkpoints(existing, new, n=10)
]
```

### 5.2 - Interrupt-Resume Pattern

```python
# In supervisor_node:
if requires_clarification:
    return {
        "pending_questions": [{"question": "...", "options": [...]}],
        "waiting_for_user_input": True,
        # Continue with normal message processing
        # LangGraph will pause and wait for user input
    }

# After user responds (in message handler):
# The message handler adds user's choice to messages
# LangGraph resumes from where it left off
# Supervisor reads pending_questions and user response
# Proceed with new info
```

### 5.3 - Context Injection Example

```python
# In text2sql agent system prompt:
system_prompt = f"""
You are a SQL expert...

CURRENT CONTEXT:
Table: {active_context.current_table}
SQL: {active_context.current_sql}
Filters: {json.dumps(active_context.applied_filters)}
Result: {active_context.result_row_count} rows

User's request: Modify this SQL based on the user's new request.
"""
```

### 5.4 - Handoff Tool Usage

```python
# In supervisor:
tools = [
    assign_to_report_agent,  # Existing
    ask_user_for_clarification,  # New
]

# In node:
response = llm_with_tools.invoke(
    {"messages": [system_prompt, ...]}
    tools=tools
)

# If LLM calls ask_user tool:
if response.tool_calls[0].name == "ask_user_for_clarification":
    return {
        "pending_questions": [...],
        "waiting_for_user_input": True
    }
    # LangGraph interrupts here
```

---

## 🎯 BÖLÜM 6: SUCCESS CRITERIA

### Aşama 1 Başarısı
- [ ] ReportStateEnhanced tüm yeni fields ile tanımlanmış
- [ ] Reducer functions test passed
- [ ] State serialize/deserialize works

### Aşama 2 Başarısı
- [ ] Intent classifier %80+ accuracy
- [ ] Clarification flow e2e work
- [ ] ask_user tool interrupt'ı proper çalışıyor

### Aşama 3 Başarısı
- [ ] Delta SQL node "Ekle/Çıkar" mantığı işliyor
- [ ] Mevcut SQL vs. new SQL comparison'u doğru
- [ ] Empty result detection works

### Aşama 4 Başarısı
- [ ] Context summarization 30% token reduction sağlıyor
- [ ] Bloat prevention active_context clean tutuyor

### Aşama 5 Başarısı
- [ ] Rollback to previous checkpoint works
- [ ] All 10 previous versions accessible
- [ ] Checkpoint validation logic (re-execute) works

### Aşama 6 Başarısı
- [ ] Context injection prompts better responses
- [ ] LLM "mevcut SQL'i modifiye et" anladığında evet yapıyor
- [ ] Handoff data all fields properly passed

### Aşama 7 Başarısı
- [ ] All 6 e2e scenarios pass
- [ ] Performance: <100ms state update latency
- [ ] No memory leaks (query_history cleanup verified)

---

## 📊 BÖLÜM 7: MIMARÎ DIYAGRAM (Sonuç)

```
SOHBETÇI / USER
      ↓

[SUPERVISOR AGENT] ← HITL + Confidence Score
      ↓
      ├─ Intent: NEW_QUERY → Archive old context
      ├─ Intent: APPEND → Check confidence
      │   ├─ High (≥0.75) → Delta SQL generator
      │   └─ Low (<0.75) → ask_user (interrupt)
      ├─ Intent: ROLLBACK → Checkpoint manager
      └─ Intent: VISUALIZE → Same SQL, new viz
      ↓
[TEXT2SQL AGENT] ← Context Injection (current SQL, filters, etc.)
      ├─ Fresh SQL generation (NEW_QUERY)
      └─ Delta SQL modification (APPEND)
      ↓
[ACTIVE QUERY CONTEXT] ← State management
      ├─ current_table
      ├─ current_sql
      ├─ applied_filters
      ├─ result_sample
      └─ query_history (last 10 versions)
      ↓
[DATABASE] (MSSQL)
      ↓
[DATA VISUALIZATION] (Plotly)
      ↓
USER RESPONSE (Chat + Chart)
      ↓
[CHECKPOINT MANAGER] ← Save successful state
      ├─ version tracking
      ├─ rollback capability
      └─ context archive
```

---

## ✅ BÖLÜM 8: ÖZET & BAŞLAMA ADIMI

### **Mimarinin Uygunluğu: %95 ✅**

**Neden?**
1. LangGraph infrastructure full ready
2. State management (TypedDict) ekleme için optimal
3. Supervisor pattern already in place
4. Config injection pattern kullanıma hazır
5. Database integration solid

**Risk Mitigation:**
- Memory bloat → Query history limit (10 versions)
- Checkpoint overhead → Async writes, batch commits
- HITL latency → Streaming, pre-computed suggestions

### **Başlamadan Önce Checklist**

- [ ] `feat/report-hitl` branch active ve clean
- [ ] Existing test suite pass
- [ ] `.env` configured (LLM API key, DB connection)
- [ ] Dependencies updated (langgraph, langchain latest)

### **İlk Adım (PHASE 1 Başı)**

```bash
# 1. Branch hazırlama
git checkout feat/report-hitl
git pull origin feat/report-hitl

# 2. PHASE 1 başlama
# Düzenle: /src/graphs/report/state.py
# Ekle: ActiveQueryContext, QueryCheckpoint, ReportStateEnhanced

# 3. Reducer functions
# Ekle: query_history reducer

# 4. Test
pytest tests/test_report_state.py -v
```

---

## 📚 BÖLÜM 9: LangGraph Kaynakları

**Useful Docs:**
- [LangGraph State Management](https://langchain-ai.github.io/langgraph/concepts/agentic_concepts/)
- [TypedDict with Reducers](https://langchain-ai.github.io/langgraph/concepts/low_level_conceptual_guide/#reducers)
- [Interrupts & Human-in-the-Loop](https://langchain-ai.github.io/langgraph/how-tos/human-in-the-loop/)
- [Checkpointing](https://langchain-ai.github.io/langgraph/how-tos/persistence/)

**Code References (This Project):**
- `/src/graphs/supervisor/graph.py` - Routing pattern example
- `/src/graphs/generic_text2sql/nodekit.py` - NodeKit pattern + config injection
- `/src/core/session_manager.py` - Session persistence baseline

---

**Son Güncelleme:** 29 Ocak 2026
**Hazırlayan:** Claude Code Analysis
**Branch:** `feat/report-hitl`
