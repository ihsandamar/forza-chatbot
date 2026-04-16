# Dead Code Cleanup — Design Spec

**Tarih:** 2026-04-16
**Branch:** refactor/cleanup-and-consolidation
**Durum:** Onaylandı — implementasyon bekliyor

---

## Motivasyon

Kapsamlı bir SOLID/KISS/YAGNI denetimiyle tespit edildi: projede ~25 dosya ve ~3.000+ satır canlı request path'e hiç bağlanmamış dead code bulunuyor. Bu dosyalar:

- Geliştirme sırasında bağlanmayan spekülativ tasarımlar
- Launch layer refactor sonrası devre dışı kalan builder/adapter katmanları
- `ChatService`'in kendi dict yapısını kullanmasından sonra orphan kalan manager sınıflar
- Paralel ama hiç kullanılmayan state/message altyapısı

**Hedef:** Projeyi gerçekte çalışan kod + test dosyaları ve gerekli altyapıya indirgemek. KISS ve YAGNI.

---

## Kapsam

| Dahil | Dışarıda |
|-------|---------|
| Dead file silme (Aşama 1) | `src/graphs/` graph mantığı |
| Bozuk endpoint kaldırma | `src/api/routes/` route içerikleri |
| Exception hiyerarşisi budama | Gradio UI mantığı |
| Async alias metod temizliği | `src/core/app_config.py`, `src/launch/` (yeni) |
| `_from_graph_state` public API | HITL / LangGraph node mantığı |

---

## Yaklaşım

**Aynı branch, iki aşama — 10 commit.**

Aşama 1 salt silmedir: başka hiçbir dosyaya dokunmadan `git rm`. Aşama 2 canlı dosyalarda cerrahi değişiklikler.

---

## Aşama 1: Salt Silmeler

### Commit 1 — Core managers

**Sil:**
```
src/core/session_manager.py
src/core/conversation.py
src/core/assistant_manager.py
```

**Neden:** `ChatService` session verilerini kendi `self.sessions: Dict[str, dict]`'inde tutuyor. Bu üç sınıfın dışarıdan tek callsite'ı yok. `AssistantManager._config_history` hiç okunmuyor; `ConversationManager` bir listeyi sarıyor, sarmaladığı liste de kullanılmıyor.

**Yan etki yok:** `src/core/__init__.py` bu sınıfları re-export ediyorsa ilgili satır da kaldırılır.

---

### Commit 2 — Dead models

**Sil:**
```
src/models/erp_langgraph_models.py
src/models/models.py
src/models/standard_types.py
```

**Neden:**
- `erp_langgraph_models.py`: 468 satır, hiç import edilmiyor. "ahmet.yilmaz@ankara_elvankent" hardcoded sample data içeriyor — farklı bir domain için yazılmış, projeye hiç bağlanmamış.
- `models.py`: `State` TypedDict; GIB Mevzuat ve restaurant ERP alanlarına ait field'lar içeriyor, aktif graph'lardan hiçbiri kullanmıyor.
- `standard_types.py`: `StandardResponse`, `StandardAction` vb. — live response path'i `ChatMessageResponse` (Pydantic) kullanıyor, bunlara hiç ulaşmıyor.

---

### Commit 3 — Core states/messages altyapısı

**Sil:**
```
src/core/states/base_state.py
src/core/states/state_adapter.py
src/core/states/state_registry.py
src/core/states/transformers.py
src/core/messages/extractors.py
src/core/messages/validators.py
```

**Neden:** `StateRegistry`, `StateAdapter`, `StateTransformer`, `MessageExtractor`, `MessageValidator` — dekoratör tabanlı kayıt sistemi, async transform, intent detection, regex tabanlı entity extraction. Tek external callsite yok. `detect_intent()` keyword-based mantığı aktif graph'lardakiyle çakışmıyor.

**Not:** `src/core/states/` ve `src/core/messages/` dizinleri tamamen boşalacak — dizinler de silinir.

---

### Commit 4 — Builders + Adapters

**Sil:**
```
src/builders/chatbot_builder.py
src/builders/dependency_factory.py
src/builders/adapter_factory.py
src/adapters/base_state_adapter.py
src/adapters/default_state_adapter.py
src/adapters/vegaforza_state_adapter.py
```

**Neden:** Launch layer refactor (`src/launch/`) sonrası bu katmanlar tamamen devre dışı. `ChatbotBuilder` hiçbir entry point'tan çağrılmıyor. `AdapterFactory`'nin `register_adapter()` metodu için sıfır callsite var. `DefaultStateAdapter.from_graph_state()` mantığı `chatbot.py`'de kopyalanmış, orijinal adapter layer'a ulaşılmıyor.

---

### Commit 5 — Graph base artıkları

**Sil:**
```
src/graphs/base_graph.py          ← 42-satır, enhanced versiyonla çakışıyor
src/graphs/base/graph_config.py   ← 306 satır, YAML dosyaları hiç oluşturulmamış
src/graphs/base/graph_types.py    ← GraphOutput/GraphState hiçbir aktif graph'ta yok
```

**Neden:**
- `base_graph.py` (kök): `src/graphs/base/base_graph.py` (460 satır enhanced) ile paralel. Aktif graph'lar enhanced versiyonu import ediyor; kök versiyon sadece type hint için import ediliyor.
- `graph_config.py`: `from_yaml`, `from_yaml_relative` metodları — repo'da ilgili YAML dosyası mevcut değil, hiç instantiate edilmiyor.
- `graph_types.py`: `GraphOutput`, `GraphState` base TypedDict'leri — aktif graph state'leri kendi `state.py`'lerini kullanıyor.

**Önemli:** `src/graphs/base/` dizinindeki `__init__.py` ve `base_graph.py` (enhanced) **korunur**. Sadece yukarıdaki üç dosya silinir.

---

### Commit 6 — Misc dead files

**Sil:**
```
src/interfaces/flask_interface.py
src/services/container.py
src/api/models.py               ← root-level duplicate (package ayrı kalır)
```

**Neden:**
- `flask_interface.py`: 14 satır Flask app, proje FastAPI kullanıyor, hiç import edilmiyor.
- `container.py`: 14 satır service locator, `ServiceContainer` sıfır callsite.
- `src/api/models.py` (root file): `src/api/models/` package'ının içeriğini kopyalıyor; routes sadece `src/api/models/requests/` ve `src/api/models/responses/` kullanıyor.

---

## Aşama 2: Canlı Dosya Temizlikleri

### Commit 7 — Bozuk metrics endpoint'lerini kaldır

**Dosya:** `src/api/routes/metrics.py`

**Kaldır:**
- `GET /metrics/cache/stats` (76-109. satırlar): `cache = None` hardcoded, her zaman `{"status": "not_initialized"}` döner.
- `POST /metrics/cache/reset` (111-146. satırlar): `cache = None` hardcoded, her zaman `HTTPException(404)` fırlatır.

Router kaydı da kaldırılır. Kalan endpoint'ler (`GET /metrics/sessions`, vb.) dokunulmaz.

---

### Commit 8 — Exception hiyerarşisi budama

**Dosya:** `src/core/exceptions/chatbot_exception.py`

**Koru** (canlı kodda raise edilen 5 sınıf):
```python
ConfigurationException
MessageProcessingException
GraphExecutionException
GraphInvocationException
InvalidGraphStateException
```

**Sil:** Geri kalan 17 exception sınıfı (hiç raise edilmiyor):
`InvalidConfigurationException`, `ConfigurationFileException`, `InvalidMessageException`, `MessageValidationException`, `MessageExtractionException`, `AdapterException`, `StateAdaptationException`, `InvalidAdapterException`, `BuilderException`, `BuilderValidationException`, `InvalidBuilderStateException`, `ModuleException`, `ModuleNotFoundException`, `ModuleInitializationException`, `ModuleProcessingException`, `LLMException`, `LLMInvocationException`, `InvalidLLMResponseException`, `DatabaseException`, `DatabaseConnectionException`, `QueryExecutionException`, `ResponseException`, `ResponseFormattingException`

**Sil:** `src/graphs/routing/exceptions.py` (10 sınıf, routing node'larında hiç catch edilmiyor).

---

### Commit 9 — ChatService async alias metodları

**Dosya:** `src/api/services/chat_service.py`

**Kaldır** (sadece `return await self.gerçek_metod()` yapan 4 metod):
```python
start_session_async(request)    → start_session(request) zaten async
send_message_async(request)     → send_message(request) zaten async
get_history_async(session_id)   → get_session_history(session_id) zaten async
clear_history_async(session_id) → clear_conversation(session_id) senkron
```

**Güncelle:**
- `src/interfaces/cli_interface.py`: `start_session_async` → `start_session`, `send_message_async` → `send_message`, `get_history_async` → `get_session_history`
- `src/interfaces/gradio_interface.py`: aynı şekilde, mevcut async çağrılar doğrudan metoda yönlendirilir

**Not:** `clear_history_async` alias'ı `clear_conversation` senkron metodunu çağırıyor. `cli_interface.py`'deki `await` çağrısı düz çağrıya çevrilir.

---

### Commit 10 — `_from_graph_state` public API

**Sorun:** `chat_service.py:446` doğrudan `self.chatbot._from_graph_state(graph_output)` — bir private metoda dışarıdan erişim (SRP ihlali).

**Çözüm:**
- `src/core/chatbot.py`: `_from_graph_state` → `extract_response(graph_output: dict) -> str` olarak yeniden adlandırılır (public, type-annotated)
- `src/api/services/chat_service.py:446`: `self.chatbot._from_graph_state(...)` → `self.chatbot.extract_response(...)` güncellenir

---

## Başarı Kriterleri

- [ ] Silinen dosyaların hiçbiri başka bir dosyadan import edilmiyor
- [ ] `pytest tests/` çalışıyor, yeni failure yok (pre-existing failure'lar hariç)
- [ ] `python -c "import main; import api_app; print('OK')"` çalışıyor
- [ ] `/api/metrics` route'u hâlâ var, sadece bozuk 2 endpoint gitti
- [ ] `chatbot.extract_response(...)` çağrısı `chat_service.py`'de çalışıyor
- [ ] Toplam satır sayısı: ~3.000 satır azalma
