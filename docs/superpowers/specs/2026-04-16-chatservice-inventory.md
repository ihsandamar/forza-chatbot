# ChatService Envanteri

**Tarih:** 2026-04-16
**Durum:** Analiz — kod değişikliği yok

---

## api/chat_service.py

**Constructor:** `__init__(self, chatbot: Chatbot, session_manager: SessionManager, conversation_manager: ConversationManager, assistant_manager: AssistantManager)`

**Key methods:**
- `start_session(request: SessionStartRequest) -> SessionStartResponse` — session ve conversation oluşturur, AssistantManager snapshot'ı saklar
- `end_session(request: SessionEndRequest) -> SessionEndResponse` — session ve conversation'ı siler
- `send_message(request: ChatMessageRequest) -> ChatMessageResponse` — mesajı chatbot'a gönderir, history'ye ekler, session interaction time günceller
- `get_history(request: HistoryRequest) -> HistoryResponse` — ConversationManager'dan mesajları çeker
- `clear_history(request: ClearHistoryRequest) -> ClearHistoryResponse` — ConversationManager'dan mesajları siler
- `reconfigure_assistant(request: ReconfigureAssistantRequest) -> ReconfigureAssistantResponse` — AssistantManager üzerinden runtime config değişikliği
- `get_session_stats() -> dict` — SessionManager.get_stats() proxy
- `get_conversation_stats() -> dict` — ConversationManager.get_stats() proxy
- `get_assistant_config() -> dict` — AssistantManager.get_config() proxy
- `cleanup_expired_sessions(timeout_seconds) -> int` — expired session temizliği
- Her senkron metod için `*_async` async wrapper'ı mevcut (run_in_executor ile)

**Kullananlar:**
- `src/di_container.py`
- `src/interfaces/cli_interface.py`
- `src/api/__init__.py`

**Sorumluluğu:** Klasik servis katmanı. Dört bağımlılığı (SessionManager, ConversationManager, Chatbot, AssistantManager) enjekte ederek orkestre eder. Session yaşam döngüsü, mesaj geçmişi ve asistan konfigürasyonunu ayrı manager sınıflarına delege eder. CLI ve DI container tarafından kullanılır; FastAPI route'larından bağımsızdır.

---

## api/services/chat_service.py

**Constructor:** `__init__(self, chatbot: Chatbot)`

**Key methods:**
- `start_session(request: SessionStartRequest) -> SessionStartResponse` — in-memory `self.sessions` dict'e kaydeder, SessionSettings uygular
- `start_session_async(...)` — start_session'ın alias wrapper'ı
- `get_session(session_id) -> Optional[dict]` — ham session dict'ini döner
- `session_exists(session_id) -> bool` — session varlık kontrolü
- `send_message(request: ChatMessageRequest) -> ChatMessageResponse` (async) — HITL akışını yönetir; GraphInterrupt yakalar, routing/report/text tepkilerini tespit eder
- `send_message_async(...)` — send_message'ın alias wrapper'ı
- `get_session_history(session_id) -> SessionHistoryResponse` (async) — ResponseFormat'a göre mesaj filtrelemesi (ALL_MESSAGES vs LAST_MESSAGE_ONLY)
- `get_history_async(...)` — get_session_history alias'ı
- `clear_conversation(session_id) -> int` — session içindeki mesajları temizler
- `clear_history_async(...)` — clear_conversation alias'ı
- `get_session_stats() -> dict` — toplam/aktif session sayısı
- `get_conversation_stats() -> dict` — toplam mesaj sayısı
- `get_assistant_config() -> dict` — sabit hardcoded değerler döner (`"Forza Chatbot"`, `"2.0"`)
- `list_sessions() -> list` — tüm session metadata listesi, creation time'a göre sıralı
- `create_new_session(user_id) -> SessionStartResponse` (async) — start_session kolaylık wrapper'ı
- `_detect_routing_response(messages)` — tool mesajlarında URL arar
- `_detect_report_response(messages)` — chart_html veya iframe içerikli AI mesajı arar
- `_detect_hitl_question(graph_output)` — state tabanlı HITL tespiti (fallback)
- `_store_hitl_state / _get_hitl_state / _clear_hitl_state` — HITL akışı için session state yönetimi
- `_filter_messages_by_format(messages)` — ardışık assistant mesajlarını filtreleyerek son'u tutar
- `_parse_message(msg)` — dict veya LangChain mesaj nesnesini `(role, content)` tuple'ına normalize eder
- `_get_current_turn_messages(messages)` — sadece son user mesajından sonraki mesajları döner
- `_extract_url_from_message(content)` — regex ile URL çıkarır

**Kullananlar:**
- `src/api/dependencies.py`
- `src/api/routes/chat.py`
- `src/api/routes/configuration.py`
- `src/interfaces/gradio_interface.py`

**Sorumluluğu:** FastAPI ve Gradio için tam-özellikli async servis. Tek bağımlılık Chatbot'tur; session state'i in-memory dict'te tutar. LangGraph entegrasyonu derindir: GraphInterrupt yakalar, HITL akışını yönetir (Command resume pattern), ve graph output'undan routing/report/text yanıt tiplerini tespit eder. Gerçek üretim akışına karşılık gelir.

---

## Fark Analizi

| Özellik | `api/chat_service.py` | `api/services/chat_service.py` |
|---|---|---|
| Constructor bağımlılıkları | 4 (Chatbot, SessionManager, ConversationManager, AssistantManager) | 1 (Chatbot) |
| Session depolama | SessionManager (dış bağımlılık) | In-memory `self.sessions` dict |
| Async pattern | `run_in_executor` wrapper'ları | Native `async/await` |
| HITL desteği | Yok | Var (GraphInterrupt, Command.resume) |
| Yanıt tipleri | Tek tip (text) | Routing / Report / Text / Question |
| LangGraph bağlantısı | `chatbot.send()` (sync) | `chatbot.get_graph_output_async()` (async) |
| Asistan konfigürasyonu | AssistantManager üzerinden dinamik | Hardcoded sabit değerler |
| Mesaj geçmişi yönetimi | ConversationManager (dış) | Session dict'i direkt günceller |
| Kullanıcı arayüzü | CLI | FastAPI REST API + Gradio |
| Satır sayısı | ~534 | ~753 |

**Temel fark:** `api/chat_service.py` bağımlılık enjeksiyonu ile çok bileşenli bir mimariyi orkestre eden eski/CLI servisidir. `api/services/chat_service.py` ise LangGraph'a doğrudan entegre olan, HITL ve yanıt-tipi tespitini barındıran, FastAPI/Gradio için yazılmış güncel async servistir.

---

## Karar

- [ ] Birleştir — `api/services/chat_service.py` canonical olarak seçilebilir
- [ ] İkisini de koru — CLI ve API ayrı ihtiyaçlara hizmet ediyor
- [X] Ayrı refactor görevi aç — şu an kapsam dışı

---

## Birleştirme İçin Risk Notları

Eğer ileride birleştirilecekse dikkat edilmesi gerekenler:

1. **CLI uyumluluğu:** `cli_interface.py` senkron `send_message` çağırır. `api/services/chat_service.py` tamamen async; CLI'yı async uyumlu hale getirmek gerekir (`asyncio.run(...)` veya event loop yönetimi).

2. **DI container yeniden yazımı:** `di_container.py` dört bağımlılıklı constructor'ı enjekte eder. Birleşme sonrası sadece `Chatbot` gerekecektir; DI yapılandırması değişmelidir.

3. **Session depolama farkı:** `api/chat_service.py` SessionManager'a (dışsal, kalıcı olabilir) güvenirken yeni sınıf in-memory dict kullanır. Uygulama yeniden başladığında session state kaybolur — üretim ortamında Redis/DB gerektirir.

4. **AssistantManager kaybı:** `reconfigure_assistant` yeteneği yeni sınıfta yoktur. Birleşme sırasında bu özelliğin ya eklenmesi ya da kaldırılması gerekir.

5. **`api/__init__.py` re-export:** `src/api/__init__.py` eski sınıfı re-export eder. Import yollarının tüm tüketicilerde güncellenmesi gerekir.

6. **Model uyumsuzluğu:** İki sınıf aynı isimli ancak farklı modüllerdeki `SessionStartRequest`, `ChatMessageRequest` vb. kullanır (`src/api/models` vs `src/api/models/requests/chat`). Birleşme öncesinde model namespace'leri hizalanmalıdır.
