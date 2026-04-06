# Table Existence Check — Single Table Approach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `create_table_node` DB'yi sorgulayarak tablonun var olup olmadığını kontrol etsin; varsa oluşturma, yoksa oluştur. Session bazlı tablo yönetimi ve force_refresh tamamen kaldırılsın.

**Architecture:** Process-level `_table_verified: bool` flag, ilk request'te `INFORMATION_SCHEMA.TABLES` ile DB'yi sorgular. Flag `True` olduktan sonra sunucu restart edilene kadar 0 ekstra DB call. `cleanup_table_node` no-op. `force_refresh` ve keyword detection tamamen silindi.

**Tech Stack:** Python, pyodbc, asyncio, LangGraph

**Note:** Tests are explicitly out of scope per user decision.

---

## File Map

| Dosya | Değişiklik |
|-------|-----------|
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | `_table_verified` flag, `_check_table_exists_in_db`, `create_create_table_node` yeniden yaz, `cleanup_table_node` no-op, background init güncelle |
| `src/graphs/report_agent/nodes.py` | `classify_intent_node` içinden `_REFRESH_KEYWORDS` bloğu ve `_force_table_refresh` reset satırını sil |
| `src/graphs/report_agent/state.py` | `_force_table_refresh` field kaldır |
| `src/graphs/report_agent/subagents/text2sql/state.py` | `_force_table_refresh` field kaldır |

---

### Task 1: `nodes.py` — `_table_verified` flag ve `_check_table_exists_in_db` helper ekle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:83-87` (module-level globals)

- [ ] **Step 1: `_table_verified` flag'ini module-level globals bloğuna ekle**

Mevcut satırlar 83-87 arası:
```python
# Background table init state
_table_init_event = threading.Event()
_table_init_error: Optional[str] = "not_started"
_table_init_table_name: Optional[str] = None
_table_init_started = False  # Guard: background init only runs once
```

Sonrasına ekle (88. satırdan sonra, 89. satır olarak):
```python
_table_verified: bool = False  # True = table confirmed in DB; reset on process restart
```

- [ ] **Step 2: `_check_table_exists_in_db` helper'ını `init_master_table_background` fonksiyonunun hemen üstüne ekle (satır 90 civarı)**

```python
def _check_table_exists_in_db(pyodbc_conn_str: str, table_name: str) -> bool:
    """
    DB'de tablonun varlığını senkron olarak kontrol et.
    get_pooled_connection kullanır — run_in_executor ile çağrılır.
    """
    conn = get_pooled_connection(pyodbc_conn_str)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ? AND TABLE_TYPE = 'BASE TABLE'",
            table_name
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()  # connection pool'da kalır, kapatılmaz
```

- [ ] **Step 3: Dosyayı kaydet — syntax hatası yok mu doğrula**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/subagents/text2sql/nodes.py').read()); print('OK')"
```

---

### Task 2: `nodes.py` — `init_master_table_background`'a `_table_verified = True` ekle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:96-111` (init_master_table_background)

- [ ] **Step 1: `global` satırına `_table_verified` ekle ve başarı durumunda set et**

Mevcut kod (satır 96-111):
```python
    global _table_init_error, _table_init_table_name, _table_init_started
    if _table_init_started:
        logger.info(f"[TABLE_INIT] Background init already started, skipping")
        return
    _table_init_started = True
    _table_init_table_name = table_name
    try:
        logger.info(f"[TABLE_INIT] Background table creation started for '{table_name}'")
        _execute_script_sync(connection_string, sql_script)
        _table_init_error = None
        logger.info(f"[TABLE_INIT] Background table creation completed for '{table_name}'")
    except Exception as e:
        _table_init_error = str(e)
        logger.error(f"[TABLE_INIT] Background table creation failed: {e}")
    finally:
        _table_init_event.set()
```

Değiştir:
```python
    global _table_init_error, _table_init_table_name, _table_init_started, _table_verified
    if _table_init_started:
        logger.info(f"[TABLE_INIT] Background init already started, skipping")
        return
    _table_init_started = True
    _table_init_table_name = table_name
    try:
        logger.info(f"[TABLE_INIT] Background table creation started for '{table_name}'")
        _execute_script_sync(connection_string, sql_script)
        _table_init_error = None
        _table_verified = True
        logger.info(f"[TABLE_INIT] Background table creation completed for '{table_name}'")
    except Exception as e:
        _table_init_error = str(e)
        logger.error(f"[TABLE_INIT] Background table creation failed: {e}")
    finally:
        _table_init_event.set()
```

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/subagents/text2sql/nodes.py').read()); print('OK')"
```

---

### Task 3: `nodes.py` — `create_create_table_node` yeniden yaz

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1352-1447`

- [ ] **Step 1: `create_create_table_node` ve iç `create_table_node` + `_create_and_register` fonksiyonlarını tamamen değiştir**

Mevcut satırlar 1352-1447 (tamamı) yerine:

```python
def create_create_table_node(connection_string: str, default_table_name: str) -> Callable:
    """
    DB-check-aware table creation node.

    Flow:
    1. _table_verified == True → skip (0 DB call)
    2. Background init hâlâ çalışıyorsa → bekle (max 180s)
    3. DB'de INFORMATION_SCHEMA.TABLES kontrolü
       - Var → _table_verified = True, skip
       - Yok → SQL script çalıştır, _table_verified = True
    """

    async def create_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        global _table_verified
        table_name = _get_configurable(config, "table_name", default_table_name)

        # --- Fast path: already verified this process lifetime ---
        if _table_verified:
            logger.info(f"[CREATE_TABLE] '{table_name}' already verified, skipping")
            return {}

        # --- Wait for background init if still running ---
        if not _table_init_event.is_set():
            logger.info("[CREATE_TABLE] Waiting for background init to complete...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _table_init_event.wait, 180)

        try:
            loop = asyncio.get_event_loop()
            pyodbc_conn_str = _parse_connection_string(connection_string)

            # --- DB existence check ---
            exists = await loop.run_in_executor(
                _db_executor, _check_table_exists_in_db, pyodbc_conn_str, table_name
            )
            if exists:
                _table_verified = True
                logger.info(f"[CREATE_TABLE] '{table_name}' exists in DB, skipping creation")
                return {}

            # --- Table does not exist → create ---
            query = _get_configurable(config, "query", "")
            if not query or not query.strip():
                sql_file = Path(__file__).parent.parent.parent.parent / "generic_text2sql" / "master_table_creation.sql"
                if sql_file.exists():
                    query = sql_file.read_text(encoding="utf-8")
                    logger.info(f"[CREATE_TABLE] Loaded SQL from file ({len(query)} chars)")
                else:
                    logger.warning("[CREATE_TABLE] No query available, skipping table creation")
                    return {}

            logger.info(f"[CREATE_TABLE] Creating table '{table_name}' ({len(query)} chars)")
            await loop.run_in_executor(_db_executor, _execute_script_sync, connection_string, query)
            _table_verified = True
            logger.info(f"[CREATE_TABLE] '{table_name}' created successfully")
            return {}

        except Exception as e:
            logger.error(f"[CREATE_TABLE] Error: {e}")
            return {"error": f"Tablo kontrol/oluşturma hatası: {e}"}

    return create_table_node
```

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/subagents/text2sql/nodes.py').read()); print('OK')"
```

---

### Task 4: `nodes.py` — `create_cleanup_table_node` no-op yap

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1454-1476`

- [ ] **Step 1: `create_cleanup_table_node` içeriğini no-op ile değiştir**

Mevcut satırlar 1454-1476 (tamamı) yerine:

```python
def create_cleanup_table_node(connection_string: str, default_table_name: str) -> Callable:
    """No-op: table is permanent, no cleanup performed."""

    async def cleanup_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        return {}

    return cleanup_table_node
```

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/subagents/text2sql/nodes.py').read()); print('OK')"
```

- [ ] **Step 3: `get_table_registry` import'u artık bu dosyada kullanılmıyor — kaldır**

**Not:** Bu adım yalnızca Task 3 Step 1 (create_create_table_node) ve Task 4 Step 1 (create_cleanup_table_node) tamamlandıktan sonra güvenlidir.

Satır 44:
```python
from src.graphs.generic_text2sql.table_registry import get_table_registry
```
Bu satırı sil.

- [ ] **Step 4: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/subagents/text2sql/nodes.py').read()); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat: replace registry-based table check with DB existence check

- Add _table_verified process-level flag
- Add _check_table_exists_in_db helper (INFORMATION_SCHEMA.TABLES)
- create_table_node: check DB first, create only if missing
- cleanup_table_node: no-op, table is now permanent
- Remove force_refresh logic, session_id usage, registry lookups
- Background init sets _table_verified=True on success"
```

---

### Task 5: `report_agent/nodes.py` — `_REFRESH_KEYWORDS` bloğu ve `_force_table_refresh` reset satırını kaldır

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:117-137, 241`

- [ ] **Step 1: Satır 117-137 arasındaki tüm bloğu sil**

Silinecek kod (satır 117-137):
```python
        # --- Table refresh detection (before LLM call) ---
        _REFRESH_KEYWORDS = {"verileri güncelle", "tabloyu güncelle", "verileri yenile", "tabloyu yenile", "veriyi güncelle", "veriyi yenile"}
        user_lower = user_query.lower().strip()
        is_refresh_request = any(kw in user_lower for kw in _REFRESH_KEYWORDS)

        if is_refresh_request:
            logger.info(f"[CLASSIFY] Table refresh detected: '{user_query}'")
            return {
                "user_query": user_query,
                "intent_type": "NEW_QUERY",
                "query_type": "SINGLE",
                "intent_confidence": 1.0,
                "wants_visualization": False,
                "requested_chart_type": None,
                "use_result_type": None,
                "compute_operation": None,
                "visualization_output": None,
                "pre_built_sql": None,
                "modification_hints": None,
                "_force_table_refresh": True,
            }
```

Bu bloğun silinmesinden sonra `history_parts = []` satırı (eski satır 139) direkt `extracted_from_messages = False` bloğundan sonra gelmelidir. `user_lower` ve `is_refresh_request` değişkenleri de bu blokla birlikte (satır 119-120) silinir — başka yerde kullanılmamaktadır.

- [ ] **Step 2: Satır 241'deki `_force_table_refresh` reset satırını sil**

```python
            "_force_table_refresh": False,
```
Bu satırı return_dict'ten sil.

- [ ] **Step 3: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/nodes.py').read()); print('OK')"
```

---

### Task 6: State dosyalarından `_force_table_refresh` field'ını kaldır

**Files:**
- Modify: `src/graphs/report_agent/state.py:32`
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py:26`

- [ ] **Step 1: `state.py` (report_agent) satır 32'deki field'ı sil**

```python
    _force_table_refresh: Optional[bool]  # True = DROP + recreate master table
```
Bu satırı sil.

- [ ] **Step 2: `state.py` (text2sql) satır 26'daki field'ı sil**

```python
    _force_table_refresh: Optional[bool]  # True = DROP + recreate master table
```
Bu satırı sil.

- [ ] **Step 3: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/graphs/report_agent/state.py').read()); print('OK')" && python -c "import ast; ast.parse(open('src/graphs/report_agent/subagents/text2sql/state.py').read()); print('OK')"
```

- [ ] **Step 4: `_force_table_refresh` referansı kalmadığını doğrula**

```bash
grep -r "_force_table_refresh" src/graphs/report_agent/
```

Expected: no output. `create_initial_state()` fonksiyonu bu field'ı initialize etmiyordu, güncelleme gerektirmez. Test dosyası `tests/graphs/report/test_table_caching.py` referans içerebilir — testler kapsam dışı olduğundan o dosyaya dokunma.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py src/graphs/report_agent/state.py src/graphs/report_agent/subagents/text2sql/state.py
git commit -m "feat: remove force_refresh and _REFRESH_KEYWORDS entirely

- Delete _REFRESH_KEYWORDS + is_refresh_request block in classify_intent_node
- Remove _force_table_refresh from return dicts in classify_intent_node
- Remove _force_table_refresh field from report_agent and text2sql state"
```

---

### Task 7: Son doğrulama

- [ ] **Step 1: Tüm import'ların çalıştığını doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_create_table_node, create_cleanup_table_node, init_master_table_background; print('imports OK')"
```

- [ ] **Step 2: `_force_table_refresh` referansı kalmadığını tüm projede doğrula**

```bash
grep -r "_force_table_refresh" src/
```

Expected: no output

- [ ] **Step 3: `get_table_registry` import'unun text2sql/nodes.py'den kalktığını doğrula**

```bash
grep "get_table_registry" src/graphs/report_agent/subagents/text2sql/nodes.py
```

Expected: no output

- [ ] **Step 4: Mevcut testleri çalıştır — bozulan var mı?**

```bash
pytest tests/ -x -q --tb=short 2>&1 | tail -20
```
