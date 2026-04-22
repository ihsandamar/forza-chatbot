# Bug Audit Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** İnceleme raporunda tespit edilen 11 bug/güvenlik açığını öncelik sırasıyla (yüksek etki / düşük efor önce) düzelt.

**Architecture:** Her task bağımsız, atomik bir değişiklik setini kapsar. Hiçbir task diğerinin bitmesini beklemez — paralel çalıştırılabilirler. Her task kendi commit'ini alır.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, pyodbc, ChromaDB, threading, asyncio

---

## Öncelik Sırası (Etki / Efor Matrisi)

| Task | Sorun | Etki | Efor |
|------|-------|------|------|
| 1 | `asyncio.get_event_loop()` deprecated | Orta | 1 satır |
| 2 | `pyodbc.connect()` timeout eksik (2 yer) | Yüksek | 2 satır |
| 3 | Unstaged deletions commit | Düşük | git op |
| 4 | `graph_entrypoints` + `LLM.get_chat()` `base_url` eksik | Yüksek | 4 satır |
| 5 | `EmbeddingFactory` `HF_HUB_OFFLINE` unconditional delete | Orta | 5 satır |
| 6 | `BusinessRulesStore.initialize()` tek collection kontrolü | Orta | 2 satır |
| 7 | `BusinessRulesStore.search_rules()` init guard eksik | Yüksek | 6 satır |
| 8 | `conn.timeout` paylaşımlı connection'da race condition | Kritik | 1 satır |
| 9 | `_table_init_started` lock'suz TOCTOU race | Kritik | 10 satır |
| 10 | `BaseException` Python built-in'ini gizliyor | Kritik | çok dosya |
| 11 | `value_resolver_service.py` hardcoded credentials | Güvenlik | sil |

---

## Task 1: asyncio.get_event_loop() → get_running_loop()

**Sorun:** `table_registry.py:260` Python 3.10+'da deprecated olan `get_event_loop()` çağrısı. Coroutine içinden çağrıldığında `DeprecationWarning` fırlatır, 3.12'de hata olabilir.

**Files:**
- Modify: `src/graphs/report_agent/table_registry.py:260`
- Test: `tests/test_connection_pool.py` (mevcut testler yeterli — değişiklik davranışsal değil)

- [ ] **Step 1: Fix the one-liner**

`src/graphs/report_agent/table_registry.py` satır 260'ta:

```python
# Before (deprecated):
loop = _asyncio.get_event_loop()

# After:
loop = _asyncio.get_running_loop()
```

- [ ] **Step 2: Run existing tests to confirm no regression**

```bash
pytest tests/test_connection_pool.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/table_registry.py
git commit -m "fix(table_registry): replace deprecated get_event_loop with get_running_loop"
```

---

## Task 2: pyodbc.connect() eksik timeout (2 yer)

**Sorun:** `sessions.py:79` ve `table_registry.py:254`'te `pyodbc.connect()` çağrıları `timeout=` parametresi almıyor. Network hiccup olursa bu endpointler süresiz askıda kalır. Diğer tüm `pyodbc.connect()` çağrıları (ör. `nodes.py:71`) `timeout=30` kullanıyor.

**Files:**
- Modify: `src/api/routes/sessions.py:79`
- Modify: `src/graphs/report_agent/table_registry.py:254`

- [ ] **Step 1: Fix sessions.py**

`src/api/routes/sessions.py` satır 79:

```python
# Before:
conn = pyodbc.connect(conn_str, autocommit=True)

# After:
conn = pyodbc.connect(conn_str, autocommit=True, timeout=30)
```

- [ ] **Step 2: Fix table_registry.py**

`src/graphs/report_agent/table_registry.py` satır 254:

```python
# Before:
conn = pyodbc.connect(db_connection_string, autocommit=True)

# After:
conn = pyodbc.connect(db_connection_string, autocommit=True, timeout=30)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -k "session or table_registry or connection" -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/sessions.py src/graphs/report_agent/table_registry.py
git commit -m "fix(db): add timeout=30 to bare pyodbc.connect() calls in sessions and table_registry"
```

---

## Task 3: Unstaged Deletion'ları Commit Et

**Sorun:** `src/adapters/__init__.py` ve `src/builders/__init__.py` dosyaları silindi ama staging'e alınmadı. `git status` bunları `D` (unstaged deletion) olarak gösteriyor.

**Files:**
- Delete (commit): `src/adapters/__init__.py`
- Delete (commit): `src/builders/__init__.py`

- [ ] **Step 1: Verify nothing imports from these packages**

```bash
grep -r "from src.adapters" src/ tests/ --include="*.py"
grep -r "from src.builders" src/ tests/ --include="*.py"
```

Expected: Hiçbir çıktı — her iki paket de kullanılmıyor.

- [ ] **Step 2: Stage and commit the deletions**

```bash
git add src/adapters/__init__.py src/builders/__init__.py
git commit -m "chore: commit deletion of empty adapters/ and builders/ packages"
```

---

## Task 4: graph_entrypoints + LLM.get_chat() eksik base_url

**Sorun:** İki ayrı ama bağlantılı bug:

1. `graph_entrypoints.py:_make_graph()` `config.llm.base_url`'yi `LLM()` constructor'ına geçirmiyor.
2. `models/llm.py:LLM.get_chat()` openai provider için `base_url`'yi `ChatOpenAI()`'a geçirmiyor.

Sonuç: `config.yaml`'da `base_url: https://custom.endpoint.com` ayarlanmış olsa bile LangGraph Studio / test entrypoint'leri vanilla OpenAI'ya bağlanır.

**Files:**
- Modify: `src/graphs/graph_entrypoints.py:16-24`
- Modify: `src/models/llm.py:17-18`
- Test: `tests/unit/test_runtime_agent_settings.py` (mevcut tests, regression kontrolü)

- [ ] **Step 1: Write failing test for base_url propagation**

`tests/unit/test_graph_entrypoints.py` (yeni dosya):

```python
from unittest.mock import patch, MagicMock


def test_make_graph_passes_base_url_to_llm():
    mock_config = MagicMock()
    mock_config.llm.provider = "openai"
    mock_config.llm.model = "gpt-4"
    mock_config.llm.temperature = 0
    mock_config.llm.api_key = "sk-test"
    mock_config.llm.base_url = "https://custom.api.com/v1"

    captured = {}

    def fake_llm(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch("src.graphs.graph_entrypoints.ConfigLoader.load_config", return_value=mock_config), \
         patch("src.graphs.graph_entrypoints.LLM", side_effect=lambda **kw: captured.update(kw) or MagicMock()), \
         patch("src.graphs.graph_entrypoints.GraphRepository"):
        from src.graphs.graph_entrypoints import _make_graph
        import importlib
        import src.graphs.graph_entrypoints as ge
        ge._config_cache = None  # reset cache
        _make_graph("supervisor")

    assert captured.get("base_url") == "https://custom.api.com/v1"


def test_llm_get_chat_openai_passes_base_url():
    from src.models.llm import LLM
    with patch("src.models.llm.ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm = LLM(provider="openai", model="gpt-4", api_key="sk-test", base_url="https://custom.api.com/v1")
        llm.get_chat()
    call_kwargs = mock_openai.call_args[1]
    assert call_kwargs.get("base_url") == "https://custom.api.com/v1"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/unit/test_graph_entrypoints.py -v
```

Expected: FAIL — `base_url` not passed.

- [ ] **Step 3: Fix graph_entrypoints.py**

`src/graphs/graph_entrypoints.py` satır 19-24:

```python
def _make_graph(name: str):
    """Generic factory: registry'den graph oluşturur."""
    config = _get_config()
    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
        base_url=getattr(config.llm, "base_url", None),
    )
    repo = GraphRepository(llm=llm, app_config=config)
    return repo.get(name)
```

- [ ] **Step 4: Fix LLM.get_chat() for openai provider**

`src/models/llm.py` satır 17-18:

```python
if self.provider == "openai":
    self._chat_instance = ChatOpenAI(
        model=self.model,
        temperature=self.temperature,
        api_key=self.api_key,
        base_url=self.base_url,
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_graph_entrypoints.py tests/unit/test_runtime_agent_settings.py -v
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/graphs/graph_entrypoints.py src/models/llm.py tests/unit/test_graph_entrypoints.py
git commit -m "fix(llm): propagate base_url from config through graph_entrypoints and LLM.get_chat()"
```

---

## Task 5: EmbeddingFactory HF_HUB_OFFLINE Unconditional Delete

**Sorun:** `embedding_factory.py:44-45` — `os.environ.setdefault("HF_HUB_OFFLINE", "1")` sadece env'de yoksa set eder (doğru). Ama `del os.environ["HF_HUB_OFFLINE"]` her zaman siler — deployment ortamında kasıtlı set edilmişse bile. Offline deployment'ta ilk model yükü sonrası `HF_HUB_OFFLINE` silinir, sonraki çağrılar online erişim dener.

**Files:**
- Modify: `src/factories/embedding_factory.py:41-45`
- Test: `tests/unit/test_embedding_factory.py` (mevcut + yeni test ekle)

- [ ] **Step 1: Write failing test**

`tests/unit/test_embedding_factory.py` sonuna ekle:

```python
def test_create_sentence_transformer_preserves_existing_hf_hub_offline():
    """If HF_HUB_OFFLINE was already set before the call, it must remain set after."""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"HF_HUB_OFFLINE": "1"}):
        with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction", return_value=MagicMock()):
            from src.factories.embedding_factory import EmbeddingFactory
            EmbeddingFactory.create_sentence_transformer()
        assert os.environ.get("HF_HUB_OFFLINE") == "1", "Pre-existing HF_HUB_OFFLINE must not be deleted"


def test_create_sentence_transformer_cleans_up_hf_hub_offline_it_set():
    """If HF_HUB_OFFLINE was NOT set before the call, it must be cleaned up after."""
    import os
    from unittest.mock import patch

    env_without = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
    with patch.dict(os.environ, env_without, clear=True):
        with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction", return_value=MagicMock()):
            from src.factories.embedding_factory import EmbeddingFactory
            EmbeddingFactory.create_sentence_transformer()
        assert "HF_HUB_OFFLINE" not in os.environ, "Temporarily set HF_HUB_OFFLINE must be cleaned up"
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/unit/test_embedding_factory.py::test_create_sentence_transformer_preserves_existing_hf_hub_offline -v
```

Expected: FAIL.

- [ ] **Step 3: Fix embedding_factory.py**

`src/factories/embedding_factory.py` satır 41-46:

```python
try:
    _was_set = "HF_HUB_OFFLINE" in os.environ
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)
    if not _was_set and os.environ.get("HF_HUB_OFFLINE") == "1":
        del os.environ["HF_HUB_OFFLINE"]
    return fn
```

- [ ] **Step 4: Run all embedding tests**

```bash
pytest tests/unit/test_embedding_factory.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/factories/embedding_factory.py tests/unit/test_embedding_factory.py
git commit -m "fix(embedding): only delete HF_HUB_OFFLINE if it was set by us, not by the deployment env"
```

---

## Task 6: BusinessRulesStore.initialize() — Her İki Collection'ı Kontrol Et

**Sorun:** `business_rules_store.py:82` sadece `rules_collection.count() == 0` kontrol ediyor. `default_rules_collection` boş kalsa da `_build_index()` çağrılmaz — default kurallar sessizce kaybolur.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py:82`
- Test: `tests/unit/test_base_vector_store.py` (yeni test ekle)

- [ ] **Step 1: Write failing test**

`tests/unit/test_base_vector_store.py` sonuna ekle:

```python
def test_business_rules_store_rebuilds_when_default_collection_empty():
    """initialize() must call _build_index() when default_rules_collection is empty."""
    from unittest.mock import MagicMock, patch
    from src.graphs.report_agent.subagents.text2sql.stores.business_rules_store import BusinessRulesStore

    store = BusinessRulesStore.__new__(BusinessRulesStore)
    store._client = MagicMock()
    store._embedding_fn = MagicMock()
    store.rules_file_path = MagicMock()
    store.rules_data = {"business_logic_rules": []}

    mock_rules_col = MagicMock()
    mock_rules_col.count.return_value = 5  # rules_collection dolu
    mock_default_col = MagicMock()
    mock_default_col.count.return_value = 0  # default_rules_collection BOŞ

    store._client.get_or_create_collection.side_effect = [mock_rules_col, mock_default_col]
    store._build_index = MagicMock()

    store.initialize()

    store._build_index.assert_called_once()
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/unit/test_base_vector_store.py::test_business_rules_store_rebuilds_when_default_collection_empty -v
```

Expected: FAIL.

- [ ] **Step 3: Fix initialize() condition**

`src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py` satır 82:

```python
# Before:
if self.rules_collection.count() == 0:

# After:
if self.rules_collection.count() == 0 or self.default_rules_collection.count() == 0:
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_base_vector_store.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py tests/unit/test_base_vector_store.py
git commit -m "fix(business_rules_store): check both collections in initialize() to prevent empty default rules"
```

---

## Task 7: BusinessRulesStore.search_rules() — Uninitialized Guard

**Sorun:** `search_rules()` metodu `self.default_rules_collection.query(...)` ve `self.rules_collection.query(...)` çağrıyor. Her ikisi `__init__`'te `None` olarak set ediliyor, sadece `initialize()` çağrıldıktan sonra atanıyor. `initialize()` öncesi çağrı yapılırsa `AttributeError: 'NoneType' object has no attribute 'query'` fırlatır. `TermStore._semantic_search()` aynı pattern için guard'a sahip.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py:161-172`
- Test: `tests/unit/test_base_vector_store.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_base_vector_store.py` sonuna ekle:

```python
def test_business_rules_store_search_raises_if_not_initialized():
    """search_rules() must raise RuntimeError (not AttributeError) if called before initialize()."""
    import pytest
    from src.graphs.report_agent.subagents.text2sql.stores.business_rules_store import BusinessRulesStore

    store = BusinessRulesStore.__new__(BusinessRulesStore)
    store.rules_collection = None
    store.default_rules_collection = None

    with pytest.raises(RuntimeError, match="initialize"):
        store.search_rules("test query")
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/unit/test_base_vector_store.py::test_business_rules_store_search_raises_if_not_initialized -v
```

Expected: FAIL with `AttributeError` (not `RuntimeError`).

- [ ] **Step 3: Add guard to search_rules()**

`src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py` satır 161'den hemen sonra (method başına):

```python
def search_rules(
    self,
    query: str,
    n_results: int = 5,
    include_defaults: bool = True,
    table_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    if self.rules_collection is None or self.default_rules_collection is None:
        raise RuntimeError(
            "BusinessRulesStore.initialize() must be called before search_rules()"
        )
    results = []
    # ... rest of method unchanged
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_base_vector_store.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py tests/unit/test_base_vector_store.py
git commit -m "fix(business_rules_store): raise RuntimeError in search_rules() if called before initialize()"
```

---

## Task 8: conn.timeout → cursor.timeout (Thread-Safety)

**Sorun:** `nodes.py:372` — `conn.timeout = 90` shared pooled connection üzerinde set ediliyor. `pyodbc`'de `Connection.timeout` query timeout'unu connection level'da set eder ve thread-safe değildir. `ThreadPoolExecutor(max_workers=3)` ile eş zamanlı 3 query çalışırken bir thread'in timeout ayarı diğerine sızar. Düzeltme: timeout'u `cursor` üzerinde set etmek.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:370-378`
- Test: `tests/test_connection_pool.py`

- [ ] **Step 1: Write failing test**

`tests/test_connection_pool.py` sonuna ekle:

```python
def test_execute_sql_sets_timeout_on_cursor_not_connection():
    """conn.timeout must NOT be set; cursor.timeout must be set instead."""
    import asyncio
    from unittest.mock import patch, MagicMock

    mock_conn = MagicMock()
    mock_conn.execute = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("col",)]
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor

    async def run():
        with patch("src.graphs.report_agent.subagents.text2sql.nodes.get_pooled_connection", return_value=mock_conn):
            from src.graphs.report_agent.subagents.text2sql.nodes import _execute_sql_async
            await _execute_sql_async("mssql+pyodbc://sa:pwd@server/db", "SELECT 1")

    asyncio.run(run())

    # connection.timeout must NOT be set
    assert mock_conn.timeout != 90, "conn.timeout should not be mutated (shared pooled connection)"
    # cursor.timeout must be set
    assert mock_cursor.timeout == 90, "cursor.timeout must be set to 90"
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/test_connection_pool.py::test_execute_sql_sets_timeout_on_cursor_not_connection -v
```

Expected: FAIL.

- [ ] **Step 3: Fix _execute_sql_async**

`src/graphs/report_agent/subagents/text2sql/nodes.py` satır 370-378:

```python
def _run():
    conn = get_pooled_connection(pyodbc_conn_str)
    cursor = conn.cursor()
    cursor.timeout = 90  # set on cursor, not shared connection
    cursor.execute(sql)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    cursor.close()
    return [_serialize_row(columns, row) for row in rows]
```

- [ ] **Step 4: Run all connection pool tests**

```bash
pytest tests/test_connection_pool.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/test_connection_pool.py
git commit -m "fix(sql_executor): set query timeout on cursor not shared pooled connection (thread-safe)"
```

---

## Task 9: _table_init_started TOCTOU Race Condition → threading.Lock

**Sorun:** `nodes.py:134-137` — `_table_init_started` global bayrağı `threading.Lock` olmadan check-then-set yapıyor. `init_master_table_background` bir `threading.Thread` içinde çalışıyor. Eş zamanlı çağrıda iki thread aynı anda `if _table_init_started: return` geçip tablo oluşturmayı iki kez tetikleyebilir. `_pool_lock` mevcut pattern'i zaten gösteriyor — aynı pattern uygulanacak.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:100-137`
- Test: `tests/test_connection_pool.py`

- [ ] **Step 1: Write failing test**

`tests/test_connection_pool.py` sonuna ekle:

```python
def test_init_master_table_runs_only_once_under_concurrent_calls():
    """init_master_table_background must execute table creation exactly once even with concurrent calls."""
    import threading
    from unittest.mock import patch, MagicMock
    from src.graphs.report_agent.subagents.text2sql import nodes

    # Reset global state
    nodes._table_init_started = False
    nodes._table_init_error = "not_started"
    nodes._table_init_event.clear()

    call_count = [0]
    original_execute = nodes._execute_script_sync if hasattr(nodes, '_execute_script_sync') else None

    with patch("src.graphs.report_agent.subagents.text2sql.nodes._check_table_exists_in_db", return_value=False), \
         patch("src.graphs.report_agent.subagents.text2sql.nodes._execute_script_sync") as mock_exec:

        threads = [
            threading.Thread(
                target=nodes.init_master_table_background,
                args=("mssql+pyodbc://sa:pwd@server/db", "TestTable", "CREATE TABLE TestTable (id INT)")
            )
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert mock_exec.call_count == 1, f"Expected 1 execution, got {mock_exec.call_count}"

    # Cleanup
    nodes._table_init_started = False
    nodes._table_init_error = "not_started"
    nodes._table_init_event.clear()
```

- [ ] **Step 2: Run to confirm failure (or flakiness)**

```bash
pytest tests/test_connection_pool.py::test_init_master_table_runs_only_once_under_concurrent_calls -v --count=5
```

Expected: At least occasionally FAIL with call_count > 1 (race is timing-dependent).

- [ ] **Step 3: Add lock for _table_init_started**

`src/graphs/report_agent/subagents/text2sql/nodes.py` satır 100-106 arasına yeni lock ekle:

```python
# Background table init state
_table_init_event = threading.Event()
_table_init_error: Optional[str] = "not_started"
_table_init_table_name: Optional[str] = None
_table_init_started = False  # Guard: background init only runs once
_table_init_lock = threading.Lock()  # Protects _table_init_started check-then-set
_table_verified: bool = False
_verified_table_name: Optional[str] = None
```

`src/graphs/report_agent/subagents/text2sql/nodes.py` satır 127-137, `init_master_table_background` başı:

```python
def init_master_table_background(connection_string: str, table_name: str, sql_script: str) -> None:
    global _table_init_error, _table_init_table_name, _table_init_started, _table_verified, _verified_table_name
    with _table_init_lock:
        if _table_init_started:
            logger.info(f"[TABLE_INIT] Background init already started, skipping")
            return
        _table_init_started = True
    _table_init_table_name = table_name
    try:
        # ... rest of function unchanged from line 140 onwards
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_connection_pool.py -v
```

Expected: All PASS, including concurrent test.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/test_connection_pool.py
git commit -m "fix(table_init): protect _table_init_started with threading.Lock to prevent TOCTOU race"
```

---

## Task 10: BaseException Rename → AppBaseException

**Sorun:** `src/core/exceptions/exceptions.py:22` — `class BaseException(Exception)` Python'ın built-in `BaseException`'ını gizliyor. Bu modülü import eden herhangi bir yerde `except BaseException` Python'ın kendi built-in'ini değil proje sınıfını yakalamaya çalışır. Bu subtly yanlış exception semantiği ve static analyzers için false positive üretir.

**Etkilenen dosyalar (tümü güncellenmeli):**
- Rename in: `src/core/exceptions/exceptions.py:22`
- Update import/export: `src/core/exceptions/__init__.py:15,31`
- Update import: `src/core/exceptions/chatbot_exception.py:47`
- Update re-export check: `src/core/__init__.py` (eğer re-export varsa)

**Files:**
- Modify: `src/core/exceptions/exceptions.py`
- Modify: `src/core/exceptions/__init__.py`
- Modify: `src/core/exceptions/chatbot_exception.py`
- Test: `tests/core/test_exception_hierarchy.py`

- [ ] **Step 1: Check all usages of BaseException from this project**

```bash
grep -rn "from src.core.exceptions import.*BaseException\|from src.core.exceptions.exceptions import.*BaseException" src/ tests/ --include="*.py"
```

Note down every file listed — each needs updating.

- [ ] **Step 2: Write test for rename**

`tests/core/test_exception_hierarchy.py` sonuna ekle:

```python
def test_app_base_exception_does_not_shadow_builtin():
    """AppBaseException must not shadow Python's built-in BaseException."""
    from src.core.exceptions import AppBaseException
    # Python's built-in must still be accessible
    try:
        raise ValueError("test")
    except BaseException as e:  # This must use Python's built-in, not ours
        assert isinstance(e, ValueError)

    # Our class must not be Python's built-in
    assert AppBaseException is not BaseException


def test_app_base_exception_is_importable():
    from src.core.exceptions import AppBaseException
    exc = AppBaseException(message="test", error_code="TEST")
    assert exc.message == "test"
    assert exc.error_code == "TEST"
    assert str(exc) == "[TEST] test"
```

- [ ] **Step 3: Run to confirm fail (AppBaseException doesn't exist yet)**

```bash
pytest tests/core/test_exception_hierarchy.py::test_app_base_exception_is_importable -v
```

Expected: FAIL with ImportError.

- [ ] **Step 4: Rename in exceptions.py**

`src/core/exceptions/exceptions.py` satır 22:

```python
# Before:
class BaseException(Exception):

# After:
class AppBaseException(Exception):
```

Aynı dosyada docstring'de de geçiyorsa güncelle.

- [ ] **Step 5: Update __init__.py**

`src/core/exceptions/__init__.py`:

```python
from src.core.exceptions.exceptions import AppBaseException, create_exception_context
# ...
__all__ = [
    "AppBaseException",
    "create_exception_context",
    # ... rest unchanged
]
```

- [ ] **Step 6: Update chatbot_exception.py**

`src/core/exceptions/chatbot_exception.py` satır 47:

```python
from src.core.exceptions import AppBaseException


class ChatbotBaseException(AppBaseException):
    # ... unchanged
```

- [ ] **Step 7: Update any other files found in Step 1**

For each file found: replace `BaseException` import/usage with `AppBaseException` where it refers to the project class (not the Python built-in).

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/core/ tests/graphs/ -v
```

Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add src/core/exceptions/ tests/core/test_exception_hierarchy.py
git commit -m "fix(exceptions): rename BaseException → AppBaseException to stop shadowing Python built-in"
```

---

## Task 11: value_resolver_service.py Hardcoded Credentials Kaldır

**Sorun:** `src/graphs/report_agent/subagents/text2sql/value_resolver_service.py:653-680` — Gerçek bir MSSQL sunucusuna hardcoded bağlantı dizesi (`mssql+pyodbc://sa:Vega1234@DESKTOP-TIEAGO8/harbi`) ve production kaynak kodunda `async def main()` fonksiyonu var. Bu credentials git history'de görünür durumda.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/value_resolver_service.py:649-680`

- [ ] **Step 1: Delete the test main() block**

`src/graphs/report_agent/subagents/text2sql/value_resolver_service.py` dosyasından satır 649-680'i (yorum bloğu dahil) tamamen sil:

```python
# Silinen blok:
# ============================================
# KULLANIM ÖRNEĞİ
# ============================================

async def main():
    resolver = ValueResolverService("mssql+pyodbc://sa:Vega1234@DESKTOP-TIEAGO8/harbi?driver=ODBC+Driver+17+for+SQL+Server")
    await resolver.initialize()
    tests = [...]
    ...
```

Dosya `ValueResolverService` sınıf tanımının kapanma parantezinden sonra bitecek.

- [ ] **Step 2: Verify no other file calls the main() function**

```bash
grep -rn "value_resolver_service.*main\|from.*value_resolver.*import.*main" src/ tests/ --include="*.py"
```

Expected: Hiçbir çıktı.

- [ ] **Step 3: Run related tests**

```bash
pytest tests/ -k "value_resolver or text2sql" -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/value_resolver_service.py
git commit -m "security: remove hardcoded DB credentials and test main() from value_resolver_service"
```

---

## Self-Review Checklist

- [x] Tüm task'lar bağımsız, sırayla veya paralel çalıştırılabilir
- [x] Her task kendi commit'ini alıyor
- [x] Test önce yazılıyor (TDD), mevcut test dosyaları kullanılıyor
- [x] Her code değişikliği tam kod içeriyor (placeholder yok)
- [x] Exact dosya yolları ve satır numaraları belirtildi
- [x] Type/method isim tutarlılığı: `AppBaseException` Task 10 boyunca tutarlı
- [x] Task 3 (git commit) Task 1-2 gibi kod değişikliği gerektirmediği için test adımı yok
- [x] Tüm 11 kritik/önemli bulgu kapsandı
