# Conversation Context Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tüm node'larda konuşma geçmişi çıkarımını tek bir shared utility üzerinden standartlaştır; duplicate query injection, tutarsız rol etiketleri, eksik VAGUE_QUERY context ve kullanılmayan model alanlarını düzelt.

**Architecture:** Yeni `context_utils.py` modülü `extract_conversation_history()` fonksiyonunu barındırır; 4 farklı yerdeki kopyalanmış mantığın hepsi bu fonksiyona yönlendirilir. Prompt şablonları ve Pydantic modeli minimal değişiklikle güncellenir.

**Tech Stack:** Python 3.11, LangChain `BaseMessage` (HumanMessage / AIMessage), pytest, no new dependencies.

---

## Değişecek Dosyalar

| Dosya | İşlem | Neden |
|---|---|---|
| `src/graphs/report_agent/context_utils.py` | **Oluştur** | Shared utility — tek doğruluk kaynağı |
| `tests/unit/test_context_utils.py` | **Oluştur** | TDD testleri |
| `src/graphs/report_agent/prompts.py` | Güncelle | Unused alanlar kaldır + QUERY_CLARIFICATION_PROMPT güncelle |
| `src/graphs/report_agent/nodes.py` | Güncelle | classify_intent + modify_sql + report_chat node'ları |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | Güncelle | semantic_extractor_node |
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Güncelle | `_build_conversation_context` kaldır, shared util kullan |

---

## Task 1: `context_utils.py` — Shared History Utility (TDD)

**Files:**
- Create: `src/graphs/report_agent/context_utils.py`
- Create: `tests/unit/test_context_utils.py`

### 1.1 — Failing test yaz

```python
# tests/unit/test_context_utils.py
from langchain_core.messages import HumanMessage, AIMessage


def test_empty_returns_placeholder():
    from src.graphs.report_agent.context_utils import extract_conversation_history
    result = extract_conversation_history([])
    assert result == "Önceki konuşma yok."


def test_basic_human_ai_pair():
    from src.graphs.report_agent.context_utils import extract_conversation_history
    messages = [HumanMessage(content="merhaba"), AIMessage(content="hoş geldin")]
    result = extract_conversation_history(messages)
    assert "Kullanıcı: merhaba" in result
    assert "Asistan: hoş geldin" in result


def test_exclude_last_removes_current_query():
    """classify_intent: current query already in {user_query}, don't repeat in history."""
    from src.graphs.report_agent.context_utils import extract_conversation_history
    messages = [
        HumanMessage(content="soru1"),
        AIMessage(content="cevap1"),
        HumanMessage(content="soru2"),  # current query
    ]
    result = extract_conversation_history(messages, exclude_last=True)
    assert "soru2" not in result
    assert "soru1" in result
    assert "cevap1" in result


def test_max_turns_limits_window():
    from src.graphs.report_agent.context_utils import extract_conversation_history
    messages = [
        HumanMessage(content="a"), AIMessage(content="b"),
        HumanMessage(content="c"), AIMessage(content="d"),
        HumanMessage(content="e"), AIMessage(content="f"),
        HumanMessage(content="current"),
    ]
    result = extract_conversation_history(messages, max_turns=1, exclude_last=True)
    # Only last 1 turn = 2 messages before "current"
    assert "e" in result
    assert "f" in result
    assert "c" not in result


def test_char_limit_truncates():
    from src.graphs.report_agent.context_utils import extract_conversation_history
    long_text = "x" * 500
    messages = [HumanMessage(content=long_text)]
    result = extract_conversation_history(messages, char_limit=50)
    # Truncated at 50 chars
    assert len(result.split("Kullanıcı: ")[1]) <= 53  # 50 chars + possible "..."


def test_role_labels_standardized():
    """msg.type raw values ("human", "ai") must map to Turkish labels."""
    from src.graphs.report_agent.context_utils import extract_conversation_history
    messages = [HumanMessage(content="q"), AIMessage(content="a")]
    result = extract_conversation_history(messages)
    assert result.startswith("Kullanıcı:")
    assert "Asistan:" in result
    # Must NOT contain raw type names
    assert "human:" not in result
    assert "ai:" not in result


def test_dict_messages_supported():
    """text2sql subgraph passes messages as dicts in some paths."""
    from src.graphs.report_agent.context_utils import extract_conversation_history
    messages = [
        {"type": "human", "content": "dict soru"},
        {"type": "ai", "content": "dict cevap"},
    ]
    result = extract_conversation_history(messages)
    assert "dict soru" in result
    assert "dict cevap" in result


def test_non_human_ai_messages_skipped():
    """Tool messages and system messages should not appear in history."""
    from langchain_core.messages import SystemMessage, ToolMessage
    from src.graphs.report_agent.context_utils import extract_conversation_history
    messages = [
        SystemMessage(content="sistem"),
        HumanMessage(content="kullanici"),
        ToolMessage(content="tool_output", tool_call_id="x"),
    ]
    result = extract_conversation_history(messages)
    assert "sistem" not in result
    assert "tool_output" not in result
    assert "kullanici" in result


def test_none_messages_defaults_to_placeholder():
    from src.graphs.report_agent.context_utils import extract_conversation_history
    assert extract_conversation_history(None) == "Önceki konuşma yok."
```

- [ ] **Step 1: Testleri çalıştır, hepsinin FAIL ettiğini doğrula**

```
pytest tests/unit/test_context_utils.py -v
```

Beklenen: `ImportError: cannot import name 'extract_conversation_history'`

### 1.2 — Implementasyonu yaz

- [ ] **Step 2: `context_utils.py` oluştur**

```python
# src/graphs/report_agent/context_utils.py
from __future__ import annotations

from typing import Optional


def extract_conversation_history(
    messages,
    max_turns: int = 3,
    char_limit: int = 200,
    exclude_last: bool = False,
) -> str:
    """
    Extract last N conversation turns from a LangChain message list.

    Args:
        messages:     List of BaseMessage objects or dicts with 'type'/'content' keys.
        max_turns:    Maximum number of human+ai pairs to include.
        char_limit:   Truncate each message content to this many characters.
        exclude_last: When True, skip the last message in the list (used by
                      classify_intent to avoid repeating the current query).

    Returns:
        Formatted string like "Kullanıcı: ...\nAsistan: ..." or "Önceki konuşma yok."
    """
    if not messages:
        return "Önceki konuşma yok."

    pool = list(messages[:-1]) if exclude_last else list(messages)
    window = pool[-(max_turns * 2):]

    parts: list[str] = []
    for msg in window:
        msg_type = _get_type(msg)
        content = _get_content(msg)
        if not content:
            continue

        if msg_type == "human":
            parts.append(f"Kullanıcı: {str(content)[:char_limit]}")
        elif msg_type == "ai":
            parts.append(f"Asistan: {str(content)[:char_limit]}")
        # system, tool, function → skip

    return "\n".join(parts) if parts else "Önceki konuşma yok."


def _get_type(msg) -> Optional[str]:
    if isinstance(msg, dict):
        return msg.get("type")
    return getattr(msg, "type", None)


def _get_content(msg) -> Optional[str]:
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", None)
```

- [ ] **Step 3: Testleri çalıştır, hepsinin PASS ettiğini doğrula**

```
pytest tests/unit/test_context_utils.py -v
```

Beklenen: 9 test PASS

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/context_utils.py tests/unit/test_context_utils.py
git commit -m "feat(context): add shared extract_conversation_history utility with tests"
```

---

## Task 2: `IntentClassificationResult` — Unused Alanları Sil

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`

Bu üç alan hiçbir downstream node tarafından okunmuyor; LLM token'ı boşa harcıyor.

- [ ] **Step 1: Alanları sil**

`src/graphs/report_agent/prompts.py`'de `IntentClassificationResult` sınıfından şu 3 satırı kaldır:

```python
# SİL — bu 3 satır:
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None
```

Kalan sınıf şöyle görünmeli:

```python
class IntentClassificationResult(BaseModel):
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap", "comparison", "turkey_map",
    ]] = None
    chart_x_hint: Optional[str] = None
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    time_breakdown: bool = False

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def clear_chart_hints_when_no_chart_type(self) -> "IntentClassificationResult":
        if self.chart_type is None:
            self.chart_x_hint = None
        return self
```

- [ ] **Step 2: Mevcut testlerin kırmadığını doğrula**

```
pytest tests/ -v -k "not integration" --tb=short
```

Beklenen: Tüm testler PASS (bu alanlar hiçbir testte kullanılmıyor)

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/prompts.py
git commit -m "refactor(prompts): remove unused modification_action/target/value fields from IntentClassificationResult"
```

---

## Task 3: `classify_intent_node` — Duplicate Query Fix + Window Genişletme

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`

**Sorunlar:**
1. `messages[-4:]` current query'yi de alıyor → `{user_query}` ile tekrar oluyor
2. 4 mesaj (2 tur) → 6 mesaj (3 tur) olmalı (diğer node'larla tutarlı)
3. Inline loop → shared util ile değiştir

- [ ] **Step 1: Import ekle**

`nodes.py`'nin import bloğuna şunu ekle (diğer local import'ların yanına):

```python
from src.graphs.report_agent.context_utils import extract_conversation_history
```

- [ ] **Step 2: `classify_intent_node` içindeki history bloğunu değiştir**

Şu bloğu (`nodes.py` satır 59-68):

```python
        history_parts = []
        for msg in messages[-4:]:
            if isinstance(msg, HumanMessage):
                history_parts.append(f"Kullanıcı: {msg.content[:100]}")
            elif isinstance(msg, AIMessage):
                history_parts.append(f"Asistan: {msg.content[:100]}")

        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_query=user_query,
            conversation_history="\n".join(history_parts) or "İlk mesaj",
```

Şununla değiştir:

```python
        conversation_history = extract_conversation_history(
            messages,
            max_turns=3,
            char_limit=100,
            exclude_last=True,  # current query zaten {user_query}'de var
        )

        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_query=user_query,
            conversation_history=conversation_history,
```

- [ ] **Step 3: Testleri çalıştır**

```
pytest tests/ -v -k "not integration" --tb=short
```

Beklenen: Tüm testler PASS

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/nodes.py
git commit -m "fix(classify-intent): exclude current query from history, expand window to 3 turns"
```

---

## Task 4: `modify_sql_node` — Inline Loop → Shared Utility

**Files:**
- Modify: `src/graphs/report_agent/nodes.py` (Task 3'te zaten import eklendi)

`modify_sql_node` içindeki inline loop'u shared utility ile değiştir.

- [ ] **Step 1: `modify_sql_node` içindeki context bloğunu değiştir**

Şu bloğu (`nodes.py` satır 192-205):

```python
        # Konuşma geçmişi: zamir referanslarını ("bu ürün", "o şube") çözmek için
        # Son 6 mesajı al (modification_request ile çakışma zararsız)
        messages = state.get("messages") or []
        context_lines: list[str] = []
        for msg in messages[-6:]:
            if isinstance(msg, HumanMessage):
                role = "Kullanıcı"
            elif isinstance(msg, AIMessage):
                role = "Asistan"
            else:
                continue
            content = msg.content[:200] if msg.content else ""
            context_lines.append(f"{role}: {content}")
        conversation_context = "\n".join(context_lines) if context_lines else "Yok"
```

Şununla değiştir:

```python
        messages = state.get("messages") or []
        conversation_context = extract_conversation_history(
            messages,
            max_turns=3,
            char_limit=200,
        )
```

- [ ] **Step 2: Testleri çalıştır**

```
pytest tests/ -v -k "not integration" --tb=short
```

Beklenen: Tüm testler PASS

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/nodes.py
git commit -m "refactor(modify-sql): replace inline history loop with shared extract_conversation_history"
```

---

## Task 5: `semantic_extractor_node` — Rol Etiketi Düzeltme

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

Şu anda `msg.type` raw değeri kullanılıyor ("human:", "ai:") — Türkçe prompt'larla uyumsuz.

- [ ] **Step 1: Import ekle**

`text2sql/nodes.py`'nin import bloğuna ekle (diğer src imports'ların yanına):

```python
from src.graphs.report_agent.context_utils import extract_conversation_history
```

- [ ] **Step 2: `semantic_extractor_node` içindeki context bloğunu değiştir**

Şu bloğu (`text2sql/nodes.py` satır 1365-1375):

```python
        # Build conversation context from message history (last 3 pairs at most)
        if messages:
            last_msgs = messages[-6:]  # up to 3 human+ai pairs
            conv_lines = []
            for m in last_msgs:
                role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else "?")
                content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else str(m))
                conv_lines.append(f"{role}: {content[:200]}")
            conversation_context = "\n".join(conv_lines)
        else:
            conversation_context = "Yeni konuşma, önceki bağlam yok."
```

Şununla değiştir:

```python
        conversation_context = extract_conversation_history(
            messages,
            max_turns=3,
            char_limit=200,
        )
```

- [ ] **Step 3: Testleri çalıştır**

```
pytest tests/ -v -k "not integration" --tb=short
```

Beklenen: Tüm testler PASS (özellikle `tests/unit/text2sql/test_semantic_extractor_node.py`)

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "fix(semantic-extractor): replace raw msg.type labels with standardized Kullanıcı/Asistan via shared util"
```

---

## Task 6: Viz `_build_conversation_context` → Shared Utility

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`

`_build_conversation_context()` private fonksiyonu artık gereksiz — shared util ile aynı işi yapıyor.

- [ ] **Step 1: Import ekle**

`visualization_v2/nodes.py`'nin import bloğuna ekle:

```python
from src.graphs.report_agent.context_utils import extract_conversation_history
```

- [ ] **Step 2: Private fonksiyonu sil**

`visualization_v2/nodes.py` satır 255-276 arasındaki tüm `_build_conversation_context` fonksiyonunu sil:

```python
# SİL — bu fonksiyon tamamen kaldırılacak:
def _build_conversation_context(state: dict, max_turns: int = 3) -> str:
    """Extract last N conversation turns as context for the LLM prompt."""
    messages = state.get("messages") or []
    if not messages:
        return "Onceki konusma yok."

    relevant = []
    for msg in messages[-(max_turns * 2):]:
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")

        if not content:
            continue
        if len(str(content)) > 500:
            content = str(content)[:500] + "..."

        if msg_type == "human":
            relevant.append(f"Kullanici: {content}")
        elif msg_type == "ai":
            relevant.append(f"Sistem: {content}")

    return "\n".join(relevant) if relevant else "Onceki konusma yok."
```

- [ ] **Step 3: Çağrıyı değiştir**

Viz decider içindeki çağrı (~satır 363):

```python
        conversation_context = _build_conversation_context(state)
```

Şununla değiştir:

```python
        conversation_context = extract_conversation_history(
            state.get("messages") or [],
            max_turns=3,
            char_limit=500,
        )
```

Not: `char_limit=500` — viz decider için önceki değer korundu (daha uzun AI yanıtları chart seçimi için anlamlı olabilir).

- [ ] **Step 4: Testleri çalıştır**

```
pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py -v --tb=short
```

Beklenen: Tüm testler PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py
git commit -m "refactor(viz-decider): remove _build_conversation_context, use shared utility (fixes Kullanici/Sistem labels)"
```

---

## Task 7: VAGUE_QUERY Clarifier — Konuşma Geçmişi Ekle

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`
- Modify: `src/graphs/report_agent/nodes.py`

Şu an `report_chat_node` sadece `user_query` + `column_metadata` görüyor. Kullanıcı ikinci turda "evet onu seç" gibi bir cevap verirse clarifier bağlamı bilemiyor.

### 7.1 — Önce test yaz

- [ ] **Step 1: Test ekle**

`tests/unit/test_context_utils.py`'ye şu testi ekle (mevcut dosyanın sonuna):

```python
def test_query_clarification_prompt_accepts_conversation_history():
    """QUERY_CLARIFICATION_PROMPT must have {conversation_history} placeholder."""
    from src.graphs.report_agent.prompts import QUERY_CLARIFICATION_PROMPT
    assert "{conversation_history}" in QUERY_CLARIFICATION_PROMPT
```

- [ ] **Step 2: Testi çalıştır, FAIL ettiğini doğrula**

```
pytest tests/unit/test_context_utils.py::test_query_clarification_prompt_accepts_conversation_history -v
```

Beklenen: FAIL — placeholder henüz yok

### 7.2 — Prompt'u güncelle

- [ ] **Step 3: `QUERY_CLARIFICATION_PROMPT`'a history bloğu ekle**

`src/graphs/report_agent/prompts.py`'deki mevcut prompt başlığını değiştir:

```python
# ÖNCE:
QUERY_CLARIFICATION_PROMPT = """Kullanıcının sorgusu çok genel/belirsiz. Sorguyu netleştirmek için öneriler üret.

## KULLANICI SORGUSU
{user_query}

## MEVCUT VERİ KOLONLARI
{column_metadata}
```

```python
# SONRA:
QUERY_CLARIFICATION_PROMPT = """Kullanıcının sorgusu çok genel/belirsiz. Sorguyu netleştirmek için öneriler üret.

## KONUŞMA GEÇMİŞİ
{conversation_history}

## KULLANICI SORGUSU
{user_query}

## MEVCUT VERİ KOLONLARI
{column_metadata}
```

### 7.3 — Node'u güncelle

- [ ] **Step 4: `report_chat_node` içine history ekle**

`nodes.py`'deki `report_chat_node` fonksiyonunda prompt çağrısını değiştir.

Şu kod (~satır 286-289):

```python
        prompt = QUERY_CLARIFICATION_PROMPT.format(
            user_query=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )
```

Şununla değiştir:

```python
        messages = state.get("messages") or []
        conversation_history = extract_conversation_history(
            messages,
            max_turns=2,
            char_limit=150,
            exclude_last=True,
        )
        prompt = QUERY_CLARIFICATION_PROMPT.format(
            user_query=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
            conversation_history=conversation_history,
        )
```

- [ ] **Step 5: Tüm testleri çalıştır**

```
pytest tests/ -v -k "not integration" --tb=short
```

Beklenen: Tüm testler PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/prompts.py src/graphs/report_agent/nodes.py
git commit -m "fix(report-chat): add conversation history to VAGUE_QUERY clarification prompt"
```

---

## Son Doğrulama

- [ ] **Full test suite çalıştır**

```
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Beklenen: Tüm testler PASS, hiç regression yok.

- [ ] **4 dosyada inline history loop kalmadığını doğrula**

```bash
grep -rn "msg.content\[:100\]\|msg.content\[:200\]\|for msg in messages\[-" \
  src/graphs/report_agent/nodes.py \
  src/graphs/report_agent/subagents/text2sql/nodes.py \
  src/graphs/report_agent/subagents/visualization_v2/nodes.py
```

Beklenen: Çıktı yok (sıfır eşleşme)

- [ ] **context_utils import'larını doğrula**

```bash
grep -rn "extract_conversation_history" src/
```

Beklenen: `context_utils.py` (tanım) + 3 node dosyası (import + kullanım)

---

## Özet: Ne Değişti, Neden

| Sorun | Dosya | Çözüm |
|---|---|---|
| Current query hem `{user_query}` hem history'de | `nodes.py` classify_intent | `exclude_last=True` |
| History window 4 → 6 msg | `nodes.py` classify_intent | `max_turns=3` |
| 4 yerde copy-paste history loop | 4 dosya | `context_utils.py` shared util |
| "human:" / "ai:" / "Kullanici:" / "Sistem:" karmaşası | `text2sql/nodes.py`, `viz/nodes.py` | Tek standart: "Kullanıcı:" / "Asistan:" |
| VAGUE_QUERY clarifier bağlamı göremez | `nodes.py`, `prompts.py` | `conversation_history` parametresi eklendi |
| 3 kullanılmayan Pydantic alanı | `prompts.py` | Silindi |
