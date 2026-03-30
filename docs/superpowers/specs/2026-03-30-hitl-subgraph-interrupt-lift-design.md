# HITL Subgraph Interrupt Lift — Design Spec

**Date**: 2026-03-30
**Status**: Approved
**Scope**: report_agent + text2sql subgraph

---

## Problem

LangGraph `interrupt()` çağrıları yalnızca checkpointer'a sahip bir graph seviyesinde düzgün çalışır.
`text2sql` subgraph'ı `graph.compile()` (checkpointer yok) ile derlendiği için, içindeki `interrupt()` çağrıları supervisor → FastAPI'ye propagate etmiyor; graph sessizce END'e akıyor, kullanıcıya yalnızca ToolMessage görünüyor.

**Etkilenen interrupt noktaları (text2sql/nodes.py)**:
- `term_resolver_node` — 1 nokta (term ambiguity)
- `value_resolver_node` — 5-6 nokta (metric, date, category, free-text vb.)

**Çalışan interrupt'lar (dokunulmaz)**:
- `classify_intent_node` (report_agent direct node)
- `modify_sql_node` (report_agent direct node)
- `report_agent/nodes.py` içindeki diğer `interrupt()` çağrıları

---

## Çözüm

text2sql içindeki `interrupt()` çağrıları **kaldırılır**. Bunun yerine:
1. text2sql node'ları ambiguity'yi state sinyaliyle bildirir ve subgraph'tan erken çıkar.
2. report_agent seviyesindeki yeni `hitl_check_node` bu sinyali alır ve `interrupt()` çağırır.
3. Bu seviyede checkpointer (parent MemorySaver üzerinden) çalıştığından interrupt doğru propagate eder.
4. Cevap gelince text2sql, `text2sql_answers` state field'ı üzerinden önceki cevabı alarak tekrar çalışır.

---

## Akış

### Clarification gereken durum:
```
user msg → classify_intent → text2sql
  └─ value_resolver: cevap yok → {"text2sql_clarification": payload} → subgraph END
report_agent: hitl_check_node → interrupt(payload)           ← checkpointer burada ✓
FastAPI: GraphInterrupt yakalar → kullanıcıya soru
user cevabı → Command(resume=answer)
hitl_check resume: answers += [{source, answer}], _hitl_answered=True
routing: _hitl_answered=True → text2sql tekrar
  └─ value_resolver: answers'da cevap var → kullan → devam
  └─ sql_generator → sql_executor → cleanup → END
hitl_check: clarification yok → _hitl_answered=False → visualization_router → normal akış
```

### Çoklu clarification (örn. term + metric):
text2sql her erken çıkışında farklı bir `source` key taşır. `text2sql_answers` listesine birikimli eklenir. Her re-run'da node kendi source'una ait cevabı listeden arar.

---

## State Değişiklikleri

### `ReportState` (`report_agent/state.py`)

3 yeni field eklenir:

```python
# text2sql subgraph clarification pipeline
text2sql_clarification: Optional[dict]
# Payload: {"type", "question", "options", "source"}
# text2sql node set eder → hitl_check okur → None'a resetler

text2sql_answers: Optional[list]
# Birikimli cevaplar: [{"source": str, "answer": str}, ...]
# hitl_check append eder → text2sql node'ları okur
# classify_intent her turda None'a resetler

_hitl_answered: bool
# hitl_check → _after_hitl_check_router için sinyal
# True = text2sql'i tekrar çalıştır
# False = normal visualization/build_response akışı
# hitl_check her çağrıda set eder (True veya False)
```

`create_initial_state()` güncellemesi:
```python
text2sql_clarification=None,
text2sql_answers=None,
_hitl_answered=False,
```

### `Text2SQLState` (`subagents/text2sql/state.py`)

2 overlapping field eklenir (LangGraph parent-child state sync otomatik çalışır):

```python
text2sql_clarification: Optional[dict]   # node → parent (sinyal)
text2sql_answers: Optional[list]         # parent → node (cevaplar)
```

---

## text2sql Node Değişiklikleri (`subagents/text2sql/nodes.py`)

### Genel pattern

Her `interrupt()` çağrısı aşağıdaki pattern'e dönüşür:

```python
# ÖNCE:
answer = interrupt({"type": "choice", "question": "...", "options": [...]})
# answer ile devam...

# SONRA:
SOURCE = "value_resolver__metric"  # her nokta için benzersiz sabit
answers = state.get("text2sql_answers") or []
cached = next((a["answer"] for a in answers if a["source"] == SOURCE), None)
if cached is not None:
    answer = cached
else:
    return {
        "text2sql_clarification": {
            "type": "choice",
            "question": "...",
            "options": [...],
            "source": SOURCE,
        }
    }
# answer ile devam...
```

### Source key'leri (benzersiz, sabit string'ler)

| Node | SOURCE key |
|------|-----------|
| term_resolver — term ambiguity | `"term_resolver__ambiguous_term"` |
| value_resolver — RowAmount/Quantity | `"value_resolver__metric"` |
| value_resolver — date ambiguity | `"value_resolver__date"` |
| value_resolver — low confidence match | `"value_resolver__low_confidence"` |
| value_resolver — free text (manual) | `"value_resolver__manual"` |
| value_resolver — diğer | `"value_resolver__other"` |

> **Not**: Source key'ler `subagents/text2sql/nodes.py` dosyasının başında module-level sabit string'ler olarak tanımlanır (örn. `_SOURCE_TERM_AMBIGUOUS = "term_resolver__ambiguous_term"`).

---

## text2sql Graph Değişiklikleri (`subagents/text2sql/graph.py`)

Mevcut düz edge'ler conditional hale gelir:

```python
def _route_after_term_resolver(state: dict):
    if state.get("text2sql_clarification"):
        return END
    # fan-out — mevcut 3 paralel node (mevcut davranış korunur)
    return ["sql_architect", "schema_validator", "term_validator"]

def _route_after_value_resolver(state: dict):
    if state.get("text2sql_clarification"):
        return END
    return "sql_generator"

# graph.add_edge("term_resolver", "sql_architect/schema_validator/term_validator") kaldırılır
# graph.add_edge("value_resolver", "sql_generator") kaldırılır
# Yerine:
graph.add_conditional_edges(
    "term_resolver",
    _route_after_term_resolver,
    {END: END, "sql_architect": "sql_architect",
     "schema_validator": "schema_validator", "term_validator": "term_validator"},
)
graph.add_conditional_edges(
    "value_resolver",
    _route_after_value_resolver,
    {END: END, "sql_generator": "sql_generator"},
)
```

---

## report_agent Değişiklikleri

### Yeni node (`report_agent/nodes.py`)

```python
async def hitl_check_node(state: dict) -> dict:
    """
    text2sql subgraph'tan gelen clarification sinyalini yakalar.
    Varsa report_agent seviyesinde interrupt() çağırır (checkpointer burada çalışır).
    """
    clarification = state.get("text2sql_clarification")

    if not clarification:
        return {"_hitl_answered": False}

    answer = interrupt(clarification)

    answers = list(state.get("text2sql_answers") or [])
    answers.append({"source": clarification["source"], "answer": answer})

    return {
        "text2sql_clarification": None,
        "text2sql_answers": answers,
        "_hitl_answered": True,
    }
```

### Graph topology (`report_agent/graph.py`)

```python
# Import
from src.graphs.report_agent.nodes import hitl_check_node

# Node ekle
graph.add_node("hitl_check", hitl_check_node)

# Router
def _after_hitl_check_router(state: dict) -> str:
    if state.get("_hitl_answered"):
        return "text2sql"
    return _visualization_router(state)

# Edge değişikliği:
# KALDIR: graph.add_conditional_edges("text2sql", _visualization_router, {...})
# EKLE:
graph.add_edge("text2sql", "hitl_check")
graph.add_conditional_edges(
    "hitl_check",
    _after_hitl_check_router,
    {
        "text2sql":       "text2sql",
        "visualization":  "visualization",
        "build_response": "build_response",
    },
)
```

### classify_intent cleanup

`classify_intent_node` return_dict'e eklenir:

```python
"text2sql_clarification": None,
"text2sql_answers": None,
"_hitl_answered": False,
```

---

## FastAPI Tarafı (Değişmez)

`chat_service.py` mevcut implementasyonu yeterlidir:
- `except GraphInterrupt` bloğu interrupt'ı yakalar, HITL state'i session'da saklar, kullanıcıya `type="question"` response döner.
- HITL cevabı gelince `Command(resume=request.message)` ile graph resume edilir.
- `hitl_check_node` `interrupt()` çağırdığında bu mekanizma doğru çalışır çünkü `interrupt()` artık report_agent seviyesindedir.

---

## Sınırlar

- **Max clarification round**: Açık bir limit yoktur; her round text2sql'i baştan çalıştırır. Çok sayıda ambiguity varsa kullanıcı deneyimi kötüleşebilir. İleride `_clarification_count` benzeri bir counter eklenebilir.
- **text2sql cache**: Her re-run `create_table`, `business_rules`, `term_resolver` gibi pahalı node'ları da tekrar çalıştırır. İleride optimize edilebilir (ör. sadece value_resolver'dan devam et).
- **Visualization subgraph**: Bu spec kapsamında değil; visualization içindeki interrupt varsa ayrıca ele alınmalıdır.

---

## Etkilenen Dosyalar

| Dosya | Değişiklik |
|-------|-----------|
| `report_agent/state.py` | 3 field ekle |
| `report_agent/nodes.py` | `hitl_check_node` ekle, `classify_intent_node` cleanup |
| `report_agent/graph.py` | `hitl_check` node + routing |
| `subagents/text2sql/state.py` | 2 overlapping field ekle |
| `subagents/text2sql/nodes.py` | `interrupt()` → state signal pattern |
| `subagents/text2sql/graph.py` | conditional early-exit edges |
| `src/api/services/chat_service.py` | **Değişmez** |
| `src/core/chatbot.py` | **Değişmez** |
