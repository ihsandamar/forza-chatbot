"""Tests for compute_results_node — LLM tool selection + pure Python execution."""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def sample_results():
    return [
        {"ProductName": "Vegan Dürüm", "TotalQuantity": 100.0, "TotalAmount": 500.0},
        {"ProductName": "Klasik Dürüm", "TotalQuantity": 200.0, "TotalAmount": 1000.0},
        {"ProductName": "Tavuk Dürüm", "TotalQuantity": 150.0, "TotalAmount": 750.0},
    ]


# ---------------------------------------------------------------------------
# Tool execution unit tests (pure Python, no LLM)
# ---------------------------------------------------------------------------
def test_tool_find_max(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "find_max", "TotalAmount", ["ProductName", "TotalAmount"])
    assert result["row"]["ProductName"] == "Klasik Dürüm"
    assert result["row"]["TotalAmount"] == 1000.0
    assert result["value"] == 1000.0


def test_tool_find_min(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "find_min", "TotalAmount", ["ProductName", "TotalAmount"])
    assert result["row"]["ProductName"] == "Vegan Dürüm"
    assert result["value"] == 500.0


def test_tool_sum(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "sum_column", "TotalAmount", ["TotalAmount"])
    assert result["value"] == 2250.0
    assert result["row"] is None


def test_tool_avg(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "avg_column", "TotalAmount", ["TotalAmount"])
    assert result["value"] == 750.0
    assert result["row"] is None


def test_tool_count(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "count_rows", "TotalAmount", [])
    assert result["value"] == 3
    assert result["row"] is None


# ---------------------------------------------------------------------------
# Full node tests (mocked LLM)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_compute_node_find_max_includes_row(sample_results):
    """find_max cevabında ilişkili satır bilgisi (ProductName) olmalı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    class FakeSelection:
        tool = "find_max"
        target_column = "TotalAmount"
        display_columns = ["ProductName", "TotalAmount"]

    async def fake_ainvoke(prompt):
        return FakeSelection()

    mock_structured = MagicMock()
    mock_structured.ainvoke = fake_ainvoke

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    node_fn = create_compute_results_node(mock_llm)
    state = {"active_results": sample_results, "user_query": "en çok satış yapan ürün"}
    result = await node_fn(state)

    assert result["error"] is None
    assert "Klasik Dürüm" in result["final_response"]
    assert "1000" in result["final_response"] or "1,000" in result["final_response"]


@pytest.mark.asyncio
async def test_compute_node_sum(sample_results):
    """sum cevabı toplam değeri içermeli."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    class FakeSelection:
        tool = "sum_column"
        target_column = "TotalAmount"
        display_columns = ["TotalAmount"]

    async def fake_ainvoke(prompt):
        return FakeSelection()

    mock_structured = MagicMock()
    mock_structured.ainvoke = fake_ainvoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    node_fn = create_compute_results_node(mock_llm)
    state = {"active_results": sample_results, "user_query": "toplam tutar"}
    result = await node_fn(state)

    assert result["error"] is None
    assert "2250" in result["final_response"] or "2,250" in result["final_response"]


@pytest.mark.asyncio
async def test_compute_node_empty_results():
    """Boş sonuç → hata mesajı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    mock_llm = MagicMock()
    node_fn = create_compute_results_node(mock_llm)
    state = {"active_results": [], "user_query": "topla"}
    result = await node_fn(state)

    assert "bulunamadı" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_node_no_numeric_cols():
    """Sayısal kolon yoksa → hata mesajı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    mock_llm = MagicMock()
    node_fn = create_compute_results_node(mock_llm)
    state = {
        "active_results": [{"ProductName": "A"}, {"ProductName": "B"}],
        "user_query": "topla",
    }
    result = await node_fn(state)

    assert "sayısal" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_node_fallback_without_llm(sample_results):
    """LLM hata verirse compute_operation fallback'i çalışmalı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    async def failing_ainvoke(prompt):
        raise Exception("LLM error")

    mock_structured = MagicMock()
    mock_structured.ainvoke = failing_ainvoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    node_fn = create_compute_results_node(mock_llm)
    state = {
        "active_results": sample_results,
        "user_query": "en çok satan",
        "compute_operation": "max",
    }
    result = await node_fn(state)

    # Fallback: eski davranış — en azından sayısal değer dönsün
    assert result["error"] is None
    assert "200" in result["final_response"]  # TotalQuantity max
