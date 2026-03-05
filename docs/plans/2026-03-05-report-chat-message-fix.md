# Report Chat Message Loop Fix - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the report_chat → classify_intent loop so that the user's clarified query is picked up by classify_intent instead of the original vague query.

**Architecture:** `report_chat` must add the user's chosen query as a HumanMessage to `messages` — this is how `classify_intent` reads the current query (line 50: `human_msgs[-1].content`). Currently `report_chat` only sets `user_query` state field which classify_intent ignores in favor of messages.

**Tech Stack:** LangGraph, LangChain messages, Python

---

### Task 1: Fix report_chat_node to add HumanMessage to messages

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:305-308`

**Step 1: Update report_chat_node return dict**

The return dict currently only sets `user_query`. It must also add the chosen query as a HumanMessage to `messages` so classify_intent picks it up.

Change lines 305-308 from:

```python
        return {
            "user_query": chosen_query,
            "_clarification_count": count,
        }
```

To:

```python
        return {
            "user_query": chosen_query,
            "messages": [HumanMessage(content=chosen_query)],
            "_clarification_count": count,
        }
```

**Why this works:** `classify_intent_node` (line 45-50) always reads `messages[-1]` HumanMessage as the query. By adding the clarified query as a new HumanMessage, classify_intent naturally picks it up. The `messages` field uses `add_messages` reducer (state.py line 9), so this appends rather than overwrites.

**Why this doesn't break existing flow:** All other nodes that set messages use the same pattern — `HumanMessage(content=...)` appended to the list. classify_intent already handles multiple HumanMessages by taking the last one.

**Step 2: Add HumanMessage import check**

Verify that `HumanMessage` is already imported at the top of `nodes.py`. It is (line 6: `from langchain_core.messages import AIMessage, HumanMessage`). No change needed.

**Step 3: Verify max-turns fallback path**

The max-turns fallback (lines 273-281) returns `{"intent_type": "NEW_QUERY"}` without setting `user_query` or `messages`. This is correct — when max turns is reached, classify_intent won't run again because `intent_type` is directly set to `NEW_QUERY` and the router will send to `text2sql`.

Wait — actually this is wrong. `report_chat` always returns to `classify_intent` via the edge. The `intent_type: NEW_QUERY` set by report_chat will be overwritten by classify_intent's own LLM output. So the max-turns fallback also needs to add the original query as a HumanMessage so classify_intent processes it as NEW_QUERY.

But actually, the original query is already in messages. The issue is that the max-turns fallback should force classify_intent to treat it as NEW_QUERY. Since classify_intent will re-classify the same query and might return VAGUE_QUERY again, we need a different approach for the fallback.

**Solution:** Add a `_skip_vague_check` flag. When max turns is reached, set this flag. classify_intent reads it and forces NEW_QUERY if VAGUE_QUERY would be returned.

### Task 2: Add _skip_vague_check to state

**Files:**
- Modify: `src/graphs/report_agent/state.py`

**Step 1: Add field to ReportState**

Add after `_clarification_count`:

```python
    _skip_vague_check: Optional[bool]  # True = max clarification reached, force NEW_QUERY
```

**Step 2: Add to create_initial_state**

Add `_skip_vague_check=False` to the initial state dict.

### Task 3: Update report_chat max-turns fallback

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:273-281`

**Step 1: Update max-turns return**

Change from:

```python
            return {
                "intent_type": "NEW_QUERY",
                "_clarification_count": 0,
            }
```

To:

```python
            return {
                "_clarification_count": 0,
                "_skip_vague_check": True,
            }
```

Remove `intent_type` — classify_intent will set it. Add `_skip_vague_check` so classify_intent knows to override VAGUE_QUERY.

### Task 4: Update classify_intent to respect _skip_vague_check

**Files:**
- Modify: `src/graphs/report_agent/nodes.py` (classify_intent_node, after LLM call)

**Step 1: Add override logic after LLM classification**

After the LLM returns `result` (around line 91), add:

```python
        # Max clarification tur aşıldıysa VAGUE_QUERY'yi NEW_QUERY'ye zorla
        if result.intent_type == "VAGUE_QUERY" and state.get("_skip_vague_check"):
            logger.info("[CLASSIFY] _skip_vague_check active, overriding VAGUE_QUERY → NEW_QUERY")
            result.intent_type = "NEW_QUERY"
```

**Step 2: Reset _skip_vague_check in return dict**

Add `"_skip_vague_check": False` to the return_dict (around line 146).

### Task 5: Verify and test

**Step 1: Run diagnostics**

Check all modified files for errors.

**Step 2: Manual trace of the flow**

Trace the "satış durumu nedir" scenario:
1. User sends "satış durumu nedir" → messages has HumanMessage("satış durumu nedir")
2. classify_intent → VAGUE_QUERY → routes to report_chat
3. report_chat → LLM generates suggestions → interrupt → user selects "Son 1 ayın kategorilere göre satış cirosu"
4. report_chat returns `{user_query: "Son 1 ayın...", messages: [HumanMessage("Son 1 ayın...")], _clarification_count: 1}`
5. classify_intent reads messages[-1] = "Son 1 ayın kategorilere göre satış cirosu" → NEW_QUERY → text2sql
6. Normal flow continues

Max-turns scenario:
1. User sends vague query twice
2. On 3rd report_chat entry, count > 2 → returns `{_skip_vague_check: True, _clarification_count: 0}`
3. classify_intent reads same messages[-1] → LLM says VAGUE_QUERY → overridden to NEW_QUERY
4. Routes to text2sql with best-effort query
