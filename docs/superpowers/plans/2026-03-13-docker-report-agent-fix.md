# Docker Report Agent Fix — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 bugs preventing the report agent from working in Docker: ChromaDB singleton conflict, ODBC Driver version mismatch, and EphemeralClient tenant error.

**Architecture:** All 3 bugs are independent. ChromaDB fix shares a single client instance across vector stores via a factory function. ODBC fix changes the default driver from 17→18. EphemeralClient fix removes the broken `Settings()` constructor call.

**Tech Stack:** chromadb 1.3.4, pyodbc, Docker, ODBC Driver 18

---

## Root Cause Summary

| Bug | Log Message | Root Cause |
|-----|-------------|------------|
| 1 | `An instance of Chroma already exists for /app/data/vector_store with different settings` | `build_text2sql_graph` creates `BusinessRulesVectorStore` + `TermVectorStore` + generic copy — all call `PersistentClient(path=same_dir)` separately. ChromaDB enforces one client per path. |
| 2 | `Can't open lib 'ODBC Driver 17 for SQL Server'` | `_parse_connection_string()` defaults to Driver 17 when URL has no `driver=` param. Dockerfile installs Driver **18**. |
| 3 | `Could not connect to tenant default_tenant` | `EphemeralClient(settings=Settings(...))` in chromadb 1.3.4 doesn't accept `Settings` this way. Fallback is broken. |

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py` | Modify (lines 90-102) | Use shared ChromaDB client factory |
| `src/graphs/report_agent/subagents/text2sql/term_vector_store.py` | Modify (lines 118-130) | Use shared ChromaDB client factory |
| `src/graphs/generic_text2sql/business_rules_vector_store.py` | Modify (lines 86-96) | Use shared ChromaDB client factory |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | Modify (line 305) | Change ODBC default from Driver 17→18 |

---

## Task 1: Fix ODBC Driver Default (Driver 17 → 18)

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:305`

- [ ] **Step 1: Change default driver version**

In `_parse_connection_string()`, change line 305:

```python
# BEFORE:
driver = query_params.get("driver", ["ODBC Driver 17 for SQL Server"])[0]

# AFTER:
driver = query_params.get("driver", ["ODBC Driver 18 for SQL Server"])[0]
```

- [ ] **Step 2: Verify locally**

Run: `python -c "from src.graphs.report_agent.subagents.text2sql.nodes import _parse_connection_string; print(_parse_connection_string('mssql+pyodbc://sa:pw@host/db'))"`

Expected output should contain `Driver={ODBC Driver 18 for SQL Server}`

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "fix: change default ODBC driver from 17 to 18 for Docker compatibility"
```

---

## Task 2: Fix ChromaDB — Single Shared Client per Path

**Problem recap:** `BusinessRulesVectorStore` and `TermVectorStore` both call `PersistentClient(path="/app/data/vector_store")` separately. ChromaDB 1.3.4 enforces one `PersistentClient` per path per process. Second call fails.

**Fix:** Replace `try PersistentClient / except EphemeralClient` with a simple `chromadb.Client()` call. In chromadb 1.3.4, `chromadb.Client()` without arguments creates an in-memory ephemeral client that works reliably. Persistence is unnecessary — the index rebuilds from JSON on every startup.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py:90-102`
- Modify: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py:118-130`
- Modify: `src/graphs/generic_text2sql/business_rules_vector_store.py:86-96`

- [ ] **Step 1: Fix `text2sql/business_rules_vector_store.py`**

Replace lines 90-102:

```python
# BEFORE:
        try:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
        except Exception as e:
            logger.warning(f"PersistentClient failed ({e}), falling back to EphemeralClient")
            self.client = chromadb.EphemeralClient(
                settings=Settings(anonymized_telemetry=False),
            )

# AFTER:
        self.client = chromadb.Client()
```

Also remove the now-unused `Settings` import if it becomes unused. Check the file's other imports first — `Settings` is imported at the top:
```python
from chromadb.config import Settings
```
Remove this import line if `Settings` is not used elsewhere in the file.

- [ ] **Step 2: Fix `text2sql/term_vector_store.py`**

Replace lines 118-130:

```python
# BEFORE:
        import chromadb
        from chromadb.config import Settings

        try:
            self._client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
        except Exception as e:
            logger.warning(f"PersistentClient failed ({e}), falling back to EphemeralClient")
            self._client = chromadb.EphemeralClient(
                settings=Settings(anonymized_telemetry=False),
            )

# AFTER:
        import chromadb
        self._client = chromadb.Client()
```

Remove the `from chromadb.config import Settings` line (now unused in this block).

- [ ] **Step 3: Fix `generic_text2sql/business_rules_vector_store.py`**

Replace lines 86-96:

```python
# BEFORE:
        try:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
        except Exception as e:
            logger.warning(f"PersistentClient failed ({e}), falling back to EphemeralClient")
            self.client = chromadb.EphemeralClient(
                settings=Settings(anonymized_telemetry=False),
            )

# AFTER:
        self.client = chromadb.Client()
```

Remove `Settings` import if unused elsewhere.

- [ ] **Step 4: Verify import works**

Run: `python -c "from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph; print('OK')"`

Expected: `OK` (no import errors, no ChromaDB errors)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py
git add src/graphs/report_agent/subagents/text2sql/term_vector_store.py
git add src/graphs/generic_text2sql/business_rules_vector_store.py
git commit -m "fix: use chromadb.Client() to avoid singleton conflict in Docker"
```

---

## Task 3: Docker Rebuild & Smoke Test

- [ ] **Step 1: Rebuild Docker image**

```bash
docker compose build --no-cache
```

- [ ] **Step 2: Start container**

```bash
docker compose up -d
```

- [ ] **Step 3: Check logs for report agent build**

```bash
docker compose logs -f chatbot-api 2>&1 | head -80
```

Expected: No `Failed to build report agent` errors. Should see:
- `[SUPERVISOR] ✓ Report subgraph built`
- `[TEXT2SQL] Subgraph v2.2 built`
- No `ODBC Driver 17` errors

- [ ] **Step 4: Send a report query**

```bash
# Start session
curl -s -X POST http://localhost:8089/api/chat/session/start \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test"}' | python -m json.tool

# Send report query (use session_id from above)
curl -s -X POST http://localhost:8089/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"session_id": "SESSION_ID_HERE", "message": "son 1 aydaki toplam ciro nedir"}' | python -m json.tool
```

Expected: Response with SQL query result (not empty, not "Successfully transferred to report" without data)

- [ ] **Step 5: Verify no `branch:to:report` warning in logs**

```bash
docker compose logs chatbot-api 2>&1 | grep "unknown channel"
```

Expected: No output (warning gone because report node now exists in graph)
