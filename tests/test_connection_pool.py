"""Test connection pooling for SQL executor."""
from unittest.mock import patch, MagicMock


def test_connection_pool_reuses_connections():
    """get_pooled_connection should reuse connections for same connection string."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        get_pooled_connection,
        _connection_pools,
    )

    _connection_pools.clear()

    mock_conn = MagicMock()
    mock_conn.execute = MagicMock()  # for health check
    with patch("src.graphs.report_agent.subagents.text2sql.nodes.pyodbc") as mock_pyodbc:
        mock_pyodbc.connect.return_value = mock_conn
        conn1 = get_pooled_connection("test_conn_str")
        conn2 = get_pooled_connection("test_conn_str")

        assert mock_pyodbc.connect.call_count == 1
        assert conn1 is conn2

    _connection_pools.clear()


def test_connection_pool_different_strings():
    """Different connection strings should get different pool entries."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        get_pooled_connection,
        _connection_pools,
    )

    _connection_pools.clear()

    mock_conn1 = MagicMock()
    mock_conn1.execute = MagicMock()
    mock_conn2 = MagicMock()
    mock_conn2.execute = MagicMock()

    call_count = [0]
    def side_effect(*args, **kwargs):
        call_count[0] += 1
        return mock_conn1 if call_count[0] == 1 else mock_conn2

    with patch("src.graphs.report_agent.subagents.text2sql.nodes.pyodbc") as mock_pyodbc:
        mock_pyodbc.connect.side_effect = side_effect
        conn1 = get_pooled_connection("conn_str_1")
        conn2 = get_pooled_connection("conn_str_2")

        assert conn1 is not conn2
        assert mock_pyodbc.connect.call_count == 2

    _connection_pools.clear()


def test_dead_connection_gets_replaced():
    """If pooled connection is dead, it should be replaced."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        get_pooled_connection,
        _connection_pools,
    )

    _connection_pools.clear()

    dead_conn = MagicMock()
    dead_conn.execute.side_effect = Exception("Connection dead")
    dead_conn.close = MagicMock()

    new_conn = MagicMock()
    new_conn.execute = MagicMock()

    with patch("src.graphs.report_agent.subagents.text2sql.nodes.pyodbc") as mock_pyodbc:
        mock_pyodbc.connect.return_value = new_conn

        # First call creates dead_conn
        _connection_pools["test_str"] = dead_conn

        # get_pooled_connection should detect dead conn and replace
        conn = get_pooled_connection("test_str")
        assert conn is new_conn

    _connection_pools.clear()


def test_execute_sql_uses_conn_timeout_not_cursor_timeout():
    """SQL executor must use conn.timeout (valid pyodbc API), not cursor.timeout (doesn't exist).

    pyodbc.Cursor has no 'timeout' attribute — only pyodbc.Connection does.
    All queries use the same 90s timeout so the shared-connection write is safe in practice.
    """
    nodes_path = "src/graphs/report_agent/subagents/text2sql/nodes.py"
    with open(nodes_path, "r", encoding="utf-8") as f:
        source = f.read()

    start_idx = source.find("async def _execute_sql_async")
    assert start_idx != -1, "_execute_sql_async function not found"
    end_idx = source.find("\nasync def ", start_idx + 1)
    if end_idx == -1:
        end_idx = source.find("\ndef ", start_idx + 1)
    if end_idx == -1:
        end_idx = len(source)
    func_source = source[start_idx:end_idx]

    assert "conn.timeout = 90" in func_source, \
        "conn.timeout = 90 must be present — it is the only valid pyodbc timeout API"
    assert "cursor.timeout" not in func_source, \
        "cursor.timeout does not exist in pyodbc and causes AttributeError at runtime"


def test_init_master_table_runs_only_once_under_concurrent_calls():
    """init_master_table_background must execute table creation exactly once even with concurrent calls.

    VERIFICATION NOTES:
    - Added _table_init_lock = threading.Lock() to globals (line 105)
    - Wrapped check-then-set with: with _table_init_lock:
    - Lock protects only the guard check and set, not the whole function
    - This prevents TOCTOU race where 2+ threads both read _table_init_started=False

    chromadb/OpenTelemetry import issues are resolved by tests/conftest.py which
    injects MagicMock stubs for chromadb and sub-packages before the nodes module loads.
    """
    import threading
    from unittest.mock import patch

    from src.graphs.report_agent.subagents.text2sql.nodes import (
        init_master_table_background,
        _table_init_event,
    )
    import src.graphs.report_agent.subagents.text2sql.nodes as nodes

    # Reset global state
    nodes._table_init_started = False
    nodes._table_init_error = "not_started"
    _table_init_event.clear()
    nodes._table_verified = False

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._check_table_exists_in_db",
        return_value=False,
    ), patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_script_sync"
    ) as mock_exec, patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._parse_connection_string",
        return_value="pyodbc_conn_str",
    ):
        threads = [
            threading.Thread(
                target=init_master_table_background,
                args=("mssql+pyodbc://sa:pwd@server/db", "TestTable", "CREATE TABLE TestTable (id INT)"),
            )
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert mock_exec.call_count == 1, f"Expected 1 execution, got {mock_exec.call_count}"

    # Cleanup global state
    nodes._table_init_started = False
    nodes._table_init_error = "not_started"
    _table_init_event.clear()
    nodes._table_verified = False
