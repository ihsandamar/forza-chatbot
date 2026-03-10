"""Test connection pooling for SQL executor."""
import pytest
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
