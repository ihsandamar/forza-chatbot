# Feature 1.2 — Rapor Oluşturma Aşaması: Adım Adım Progress Bildirimi

**Tarih:** 2026-05-12  
**Kapsam:** Report agent pipeline çalışırken kullanıcıya her node için Türkçe durum mesajı göstermek.  
**Transport:** Server-Sent Events (SSE)  
**Granülerite:** Node bazlı (12–13 adım)  
**API değişikliği:** Yeni endpoint eklenir, mevcut `/api/chat/message` korunur.

---

## 1. Mimari Genel Bakış

```
src/
├── api/
│   ├── routes/
│   │   └── chat.py              ← POST /api/chat/stream route eklenir
│   ├── services/
│   │   └── chat_service.py      ← stream_message() + _prepare_graph_state() eklenir
│   └── models/
│       └── responses/
│           └── chat.py          ← StreamEvent Pydantic modeli eklenir
├── core/
│   └── chatbot.py               ← astream_events_async() metodu eklenir
└── graphs/
    └── report_agent/
        └── progress_mapper.py   ← YENİ DOSYA: node → Türkçe mesaj mapping
```

**Node dosyalarında hiçbir değişiklik yapılmaz.**

---

## 2. Yeni Endpoint

```
POST /api/chat/stream
Content-Type: application/json
Body: {"session_id": "...", "message": "..."}

Response: text/event-stream
```

Mevcut `POST /api/chat/message` (JSON) değiştirilmez, ikisi paralel çalışır.

---

## 3. SSE Event Protokolü

Üç event tipi:

### progress
```
event: progress
data: {"step": "sql_executor", "message": "Veriler çekiliyor...", "index": 9, "total": 13}
```

### result
```
event: result
data: {"text": "...", "type": "report", "action": {"type": "chart", "target": "<iframe...>"}}
```
Payload şekli mevcut `ResponseData` ile birebir aynıdır.

### error
```
event: error
data: {"message": "Bir hata oluştu"}
```

---

## 4. Node → Mesaj Mapping (`progress_mapper.py`)

```python
NODE_PROGRESS_MESSAGES: dict[str, tuple[str, int]] = {
    # Report Agent
    "classify_intent":    ("Sorgu analiz ediliyor...",          0),
    "modify_sql":         ("Sorgu güncelleniyor...",            0),  # MODIFY_QUERY alternatifi
    "report_chat":        ("Sorgu netleştiriliyor...",          0),  # VAGUE_QUERY alternatifi
    # Text2SQL subgraph
    "create_table":       ("Çalışma tablosu oluşturuluyor...", 1),
    "business_rules":     ("İş kuralları yükleniyor...",        2),
    "semantic_extractor": ("Sorgu anlamı çıkarılıyor...",       3),
    "term_resolver":      ("Terimler çözümleniyor...",          4),
    "term_validator":     ("Terimler doğrulanıyor...",          5),
    "schema_builder":     ("Sorgu şeması oluşturuluyor...",     6),
    "value_resolver":     ("Değerler çözümleniyor...",          7),
    "sql_generator":      ("SQL oluşturuluyor...",              8),
    "sql_executor":       ("Veriler çekiliyor...",              9),
    # Visualization subgraph
    "data_analyzer":      ("Veri analiz ediliyor...",          10),
    "template_renderer":  ("Grafik oluşturuluyor...",          11),
    # Final
    "build_response":     ("Yanıt hazırlanıyor...",            12),
}

TOTAL_STEPS = 13
```

Subgraph prefix normalizasyonu: `"text2sql:sql_executor"` → `"sql_executor"` (`:` sonrası alınır).

---

## 5. Veri Akışı

```
Client
  POST /api/chat/stream {session_id, message}
       │
       ▼
  chat.py route
  └─ ChatService.stream_message(request)
       ├─ _prepare_graph_state(request) → (state, config)
       └─ chatbot.astream_events_async(state, config)
                │
                │  AsyncGenerator[StreamEvent]
                ▼
       graph.astream_events(state, config, version="v2")
                │
          ┌─────┴──────────────────────────────────────┐
          │  on_chain_start: "classify_intent"              │
          │  → StreamEvent(event_type="progress", index=0) │
          │  on_chain_start: "create_table"                │
          │  → StreamEvent(event_type="progress", index=1) │
          │           ...                              │
          │  on_chain_end: root graph                  │
          │  → final state extracted                   │
          │  → StreamEvent(type="result", ...)         │
          └────────────────────────────────────────────┘
                │
       EventSourceResponse (sse-starlette)
                │
                ▼
          Client alır: progress (en fazla x13) → result (x1)
```

---

## 6. Yeni Sınıf ve Metod İmzaları

### `StreamEvent` (Pydantic model)

```python
class StreamEvent(BaseModel):
    event_type: Literal["progress", "result", "error"]
    # progress
    step: Optional[str] = None
    message: Optional[str] = None
    index: Optional[int] = None
    total: Optional[int] = None
    # result (ResponseData ile aynı şekil)
    text: Optional[str] = None
    type: Optional[str] = None
    confidence: Optional[float] = None
    action: Optional[dict] = None
```

### `chatbot.astream_events_async()`

```python
async def astream_events_async(
    self,
    state: dict,
    config: RunnableConfig,
) -> AsyncGenerator[StreamEvent, None]:
    """
    LangGraph astream_events() üzerinden StreamEvent generator döner.
    Son event her zaman type='result' veya type='error' olur.
    """
```

### `chat_service.stream_message()`

```python
async def stream_message(
    self,
    request: ChatMessageRequest,
) -> AsyncGenerator[StreamEvent, None]:
    """
    stream_message, send_message ile aynı session/HITL state yönetimini kullanır.
    _prepare_graph_state() shared private metodundan yararlanır.
    """
```

### `_prepare_graph_state()` (refactor — shared)

```python
async def _prepare_graph_state(
    self,
    request: ChatMessageRequest,
) -> tuple[dict, RunnableConfig]:
    """
    Session yönetimi, HITL state hazırlama, config oluşturma.
    send_message() ve stream_message() tarafından paylaşılır.
    """
```

---

## 7. Hata Yönetimi

| Senaryo | Davranış |
|---|---|
| Node exception | `event: error` emit edilir, stream kapanır |
| Graph çöküşü | Generator try/except ile yakalar, `error` event gönderir |
| Bilinmeyen node adı | Event sessizce atlanır, stream kesilmez |
| Client bağlantıyı keser | `asyncio.CancelledError` yakalanır, generator temizlenir |
| SQL retry (sql_executor → semantic_extractor) | İkinci emit için mesaj değişir: `"Sorgu yeniden deneniyor... (2/2)"` |
| HITL interrupt (value_resolver) | result event `type="question"` ile emit edilir, stream kapanır |

Duplicate event koruması: `emitted_steps: set[str]` per-request tutulur. Retry sayısı state field'ından değil, generator içinde aynı step'in kaçıncı kez görüldüğü sayılarak belirlenir (`step_counts: dict[str, int]`).

---

## 8. Bağımlılık

`sse-starlette>=1.6.1` — requirements.txt'te yoksa eklenir.

---

## 9. Test Stratejisi

**`tests/api/test_stream_endpoint.py`** (yeni dosya):

| Test | Assertion |
|---|---|
| Normal akış (NEW_QUERY) | progress event sırası doğru, total tutarlı, son event type="result" |
| HITL interrupt | Son event type="question", stream kapanıyor |
| Graph exception | `error` event alınıyor, stream kapanıyor |
| Bilinmeyen node | Atlanıyor, diğer event'ler normal |
| Subgraph prefix | `"text2sql:sql_executor"` → `"sql_executor"` normalize ediliyor |

Graph mock'lanır (unit test) — gerçek LangGraph çalıştırılmaz.

---

## 10. Kapsam Dışı

- Feature 1.1 (Sorgu Optimizasyonu / Yönlendirme)
- Feature 1.3 (Rapor Sonrası Bağlam Bildirimi)
- Frontend implementasyonu (bu repo'da değil)
- WebSocket desteği
- Progress event'lerinin veritabanına loglanması
