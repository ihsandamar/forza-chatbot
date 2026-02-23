# Report Agent Yeniden Tasarımı

**Tarih:** 2026-02-23
**Klasör:** `src/graphs/report_agent/`
**Durum:** Onaylandı — Implementation bekliyor

---

## Motivasyon

Mevcut `src/graphs/report/` implementasyonu aşırı kompleks hale geldi:
- 900+ satır `graph.py`
- 15+ dosya, çoğu kullanılmıyor
- LangGraph'tan bağımsız gereksiz chat istekleri (5-7 LLM çağrısı/tur)
- `ConversationalSemanticCache`, `BusinessContextTracker`, `AmbiguityFramework`, `EntityValidator` gibi over-engineered bileşenler
- `AskUser` için 3 ekstra node + 2 ekstra edge (native HITL kullanılmıyor)

**Hedef:** Daha az kod, daha hızlı sonuç, LangGraph native patterns.

---

## Mimari: Shared-State Subgraph Pattern

### Yaklaşım

- Ana graph + subgraphlar **aynı `ReportState`** paylaşır
- Subgraph sınırlarında transformer fonksiyon yok
- `interrupt()` + `Command(resume=...)` ile native HITL
- Her subgraph sıfırdan yazılır, mevcut koddan bağımsız

### Klasör Yapısı

```
src/graphs/report_agent/
├── __init__.py
├── graph.py              # Ana graph (~200 satır)
├── state.py              # ReportState (15 field)
├── nodes.py              # classify_intent, modify_sql, extract_entity, build_response
├── prompts.py            # 3 prompt
└── subagents/
    ├── __init__.py
    ├── text2sql/
    │   ├── __init__.py
    │   ├── graph.py
    │   ├── nodes.py
    │   └── prompts.py
    └── visualization/
        ├── __init__.py
        ├── graph.py
        ├── nodes.py
        └── prompts.py
```

---

## Intent Types

| Type | Açıklama |
|------|----------|
| `NEW_QUERY` | Kullanıcı tamamen yeni bir sorgu istiyor |
| `MODIFY_QUERY` | Mevcut sorguyu değiştir (filtre ekle/çıkar, sıralama değiştir) |
| `USE_RESULT` | Önceki sonuçları kullan: (A) yeni SQL üret, (B) farklı viz ile göster |

## Query Types

| Type | Açıklama |
|------|----------|
| `SINGLE` | Tek metrik veya liste |
| `RANKING` | Sıralama / top-N |
| `COMPARISON` | İki grup/dönem karşılaştırması |
| `TIME_SERIES_COMPARISON` | Zaman bazlı karşılaştırma |

## AskUser Types

| Type | Kullanım |
|------|----------|
| `confirmation` | Evet/hayır onayı (düşük confidence durumu) |
| `options` | Kullanıcıdan seçenek seçmesini isteme (belirsizlik, boş result) |

---

## State Tasarımı

```python
class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]        # NEW_QUERY | MODIFY_QUERY | USE_RESULT
    query_type: Optional[str]         # SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    use_result_type: Optional[str]    # "new_query" | "revisualize" (USE_RESULT için)

    # Conversation Context
    active_sql: Optional[str]              # Son çalışan SQL
    active_results: Optional[List[Dict]]   # Son sonuçlar
    active_filters: Optional[List[Dict]]   # Aktif filtreler

    # Text2SQL I/O (subgraph shared)
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict]]
    error: Optional[str]

    # Visualization
    visualization_output: Optional[Dict]

    # Response
    final_response: Optional[str]
```

**~15 field** — mevcut 50+ field'ın 1/3'ü.

---

## Node Flow

```
START
  ↓
classify_intent          ← Tek LLM çağrısı: intent_type + query_type + confidence
  ↓
[intent_router]
  ├── NEW_QUERY      ──────────────────────────────────┐
  ├── MODIFY_QUERY   → modify_sql ─────────────────────┤
  ├── USE_RESULT(A)  → extract_entity ─────────────────┤→ text2sql_subgraph
  └── USE_RESULT(B)  ──────────────────────────────────┼──→ visualization_subgraph
                                                       ↓
                                              text2sql_subgraph
                                                       ↓
                                         [interrupt() if needed]
                                                       ↓
                                              visualization_subgraph
                                                       ↓
                                              build_response
                                                       ↓
                                                      END
```

**Toplam node sayısı: 6-7** (mevcut: 20+)

| Node | Açıklama |
|------|----------|
| `classify_intent` | intent + query type, tek LLM çağrısı, interrupt() ile AskUser |
| `modify_sql` | MODIFY için mevcut SQL'e delta uygular |
| `extract_entity` | USE_RESULT(A) için result'tan entity çeker |
| `text2sql` | Text2Sql subgraph (sıfırdan yazılıyor) |
| `visualization` | DataVisualization subgraph (sıfırdan yazılıyor) |
| `build_response` | Final response assembly |

---

## Prompt Tasarımı

### 1. `INTENT_CLASSIFIER_PROMPT`
Tek LLM çağrısı, structured output (Pydantic):
```
Output:
  intent_type:      NEW_QUERY | MODIFY_QUERY | USE_RESULT
  query_type:       SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
  confidence:       0.0 - 1.0
  use_result_type:  "new_query" | "revisualize"  (USE_RESULT için)
  modification:     {action, target, value}       (MODIFY_QUERY için)
```
Mevcut sistemde 2-3 ayrı LLM çağrısıydı → tek çağrıya indirildi.

### 2. `SQL_MODIFIER_PROMPT`
Sadece `MODIFY_QUERY` için. Mevcut SQL + modification intent → yeni SQL.
Text2SQL subgraph bypass edilir, doğrudan executor'a gider.

### 3. `ENTITY_EXTRACTOR_PROMPT`
Sadece `USE_RESULT(A)` için. Önceki result'tan entity çekip yeni sorgu seed'i oluşturur.

**Text2SQL subgraph içindeki prompts** (sql_architect, sql_query_builder vb.) sıfırdan yazılır ama mantığı korunur.

---

## AskUser — Native `interrupt()` Pattern

```python
# classify_intent içinde — confidence düşükse
answer = interrupt({
    "type": "confirmation",
    "question": "Önceki sorguyu mu değiştirmek istiyorsunuz?",
    "options": ["Evet", "Hayır, yeni sorgu"]
})

# text2sql içinde — boş result durumunda
answer = interrupt({
    "type": "options",
    "question": "Sonuç bulunamadı. Ne yapalım?",
    "options": ["Filtreyi genişlet", "Farklı tablo dene", "İptal"]
})
```

Resume: `Command(resume=answer, config=thread_config)` — mevcut frontend integration değişmez.

**Eski:** `ask_user (node) → process_clarification (node) → extract_query (node)` = 3 node, 2 edge
**Yeni:** `interrupt()` içinde, 0 ekstra node

---

## Subgraph Entegrasyonu

```python
graph = StateGraph(ReportState)

graph.add_node("classify_intent", classify_intent_node)
graph.add_node("modify_sql", modify_sql_node)
graph.add_node("extract_entity", extract_entity_node)
graph.add_node("text2sql", compiled_text2sql_subgraph)      # shared state
graph.add_node("visualization", compiled_visualization_subgraph)  # shared state
graph.add_node("build_response", build_response_node)

graph.add_edge(START, "classify_intent")
graph.add_conditional_edges("classify_intent", intent_router, {
    "text2sql": "text2sql",
    "modify_sql": "modify_sql",
    "extract_entity": "extract_entity",
    "visualization": "visualization",     # USE_RESULT(B)
})
graph.add_edge("modify_sql", "text2sql")
graph.add_edge("extract_entity", "text2sql")
graph.add_edge("text2sql", "visualization")
graph.add_edge("visualization", "build_response")
graph.add_edge("build_response", END)

compiled = graph.compile(checkpointer=MemorySaver())
```

### MODIFY_QUERY path
SQL hazır olduğu için Text2SQL subgraph içinde `sql_queries` varsa architect adımları skip edilir, doğrudan executor'a gider.

### USE_RESULT(B) path
`active_results` mevcut, yeni SQL yok — doğrudan visualization subgraph'a gider.

---

## Mevcut Sistemle Karşılaştırma

| | Mevcut | Yeni |
|--|--------|------|
| Dosya sayısı | 15+ | ~10 |
| graph.py satırı | 900+ | ~200 |
| State field sayısı | 50+ | ~15 |
| LLM çağrısı/tur | 5-7 | max 2 |
| Node sayısı | 20+ | 6-7 |
| AskUser implementasyonu | 3 node, 2 edge | interrupt() içinde |
| Subgraph bağımlılığı | Mevcut graph'lar reuse | Sıfırdan yazılıyor |
