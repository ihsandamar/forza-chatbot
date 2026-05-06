# Local Debug Tracer — Design Spec

**Date**: 2026-05-06  
**Status**: Approved

## Problem

LangSmith API üzerinden thread analizi yavaş (5 run ≈ 4s), recursive tree traverse + rate limit beklemeleri var. Geliştirme sırasında `classify_intent`'in ne gördüğünü, state'in node'dan node'a nasıl aktığını anında görmek gerekiyor.

## Çözüm

`@debug_node` decorator ile her node'un giriş/çıkış state'ini local JSONL dosyasına yaz. `DEBUG_TRACE=1` env var ile aktif, kapalıyken sıfır overhead.

---

## Mimari

### Yeni dosya

```
src/services/debug_tracer.py
```

Tek sorumluluk: node event'lerini serialize et, JSONL'e yaz, retention uygula.

### Log lokasyonu

```
logs/debug/<session_id>.jsonl
```

`DEBUG_TRACE_DIR` env var ile override edilebilir (default: `logs/debug`).

### JSONL event formatı

Her satır bir JSON objesi:

```json
{
  "ts": "2026-05-06T09:25:10.123456",
  "node": "classify_intent",
  "event": "enter",
  "turn": 2,
  "state": { ...full snapshot... }
}
```

- `event`: `"enter"` (tam gelen state) veya `"exit"` (node'un return ettiği dict)
- `turn`: `messages` listesindeki `HumanMessage` sayısından hesaplanır, ekstra state field gerekmez
- `state` → enter'da tam ReportState, exit'te node'un döndürdüğü dict

---

## Session ID Yayılımı

`Text2SQLState` ve `VisualizationState`'te `session_id` field'ı yok. Subgraph node'larında `state.get("session_id")` `None` döner.

**Çözüm**: Python `contextvars.ContextVar` kullanılır. Report agent'taki ilk node (`classify_intent`) `session_id`'yi context variable'a set eder; tüm subgraph node'ları aynı async context'te çalıştığı için decorator bu değeri okuyabilir. State schema'ya dokunulmaz.

```python
import contextvars
_current_session: contextvars.ContextVar[str] = contextvars.ContextVar("session_id", default="unknown")

# Decorator içinde:
session_id = state.get("session_id") or _current_session.get()
if state.get("session_id"):
    _current_session.set(state["session_id"])
```

---

## Decorator

```python
ENABLED = os.getenv("DEBUG_TRACE", "0") == "1"

def debug_node(node_name: str):
    def decorator(fn):
        if not ENABLED:
            return fn  # no-op

        @functools.wraps(fn)
        async def async_wrapper(state: dict) -> dict:
            session_id = state.get("session_id", "unknown")
            _write_event(session_id, node_name, "enter", state)
            result = await fn(state)
            _write_event(session_id, node_name, "exit", result)
            return result

        @functools.wraps(fn)
        def sync_wrapper(state: dict) -> dict:
            session_id = state.get("session_id", "unknown")
            _write_event(session_id, node_name, "enter", state)
            result = fn(state)
            _write_event(session_id, node_name, "exit", result)
            return result

        return async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper
    return decorator
```

---

## JSON Serialization

State içindeki serialize edilemeyen tipler için custom encoder:

| Tip | Davranış |
|-----|----------|
| `BaseMessage` | `{"type": classname, "content": content[:500]}` |
| `datetime` / `date` | `.isoformat()` |
| `Decimal` | `float(obj)` |
| Diğerleri | `str(obj)` |

`messages` field'ı kısaltılır (content[:500]) — büyük conversation geçmişlerinin dosyayı şişirmemesi için.

---

## Retention

- Maksimum 10 session saklanır
- Session başında (ilk `enter` event'i yazılırken) bir kez kontrol edilir
- `logs/debug/*.jsonl` dosyaları `mtime`'a göre sıralanır, 10'u aşanlar silinir

```python
def _enforce_retention(log_dir: Path, max_sessions: int = 10):
    files = sorted(log_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
    for old in files[:-max_sessions]:
        old.unlink()
```

---

## Node Entegrasyonu

Decorator şu dosyalardaki node'lara eklenir:

### `src/graphs/report_agent/nodes.py`
- `classify_intent_node`
- `modify_sql_node`
- `extract_entity_node`
- `compute_results_node`
- `report_chat_node`
- `build_response_node`
- `hitl_check_node` (sync)

### `src/graphs/report_agent/subagents/text2sql/nodes.py`
- `create_table_node`
- `business_rules_node`
- `semantic_extractor_node`
- `term_resolver_node`
- `term_validator_node`
- `schema_builder_node`
- `value_resolver_node`
- `sql_generator_node`
- `sql_executor_node`
- `cleanup_table_node`

### `src/graphs/report_agent/subagents/visualization_v2/nodes.py`
- `data_analyzer_node`
- `viz_decider_node`
- `spec_validator_node`
- `template_renderer_node`
- `response_builder_node`

---

## Geliştirici Aracı

`tools/read_trace.py` — LangSmith'e bağlanmadan JSONL'i okuyup turn/node bazında özet basar:

```bash
python tools/read_trace.py <session_id>
python tools/read_trace.py <session_id> --node classify_intent
python tools/read_trace.py <session_id> --turn 2
python tools/read_trace.py <session_id> --turn 2 --node classify_intent --full
```

`--full` flag'i olmadan state özeti (sadece key'ler + kısa değerler), `--full` ile raw JSON.

---

## Çevre Değişkenleri

```env
DEBUG_TRACE=1              # zorunlu — aktif etmek için
DEBUG_TRACE_DIR=logs/debug # opsiyonel, default bu
```

---

## Kapsam Dışı

- Supervisor graph node'ları (ayrı graph, ayrı state)
- Routing graph node'ları
- Test coverage (mevcut test suite'e dokunulmaz)
- LangSmith entegrasyonu (bu sistem tamamen bağımsız)
