"""Tests for compute_results_node — pure Python, no LLM."""
import pytest


@pytest.fixture
def sample_results():
    return [
        {"ProductName": "Vegan Dürüm", "TotalQuantity": 100.0, "TotalAmount": 500.0},
        {"ProductName": "Klasik Dürüm", "TotalQuantity": 200.0, "TotalAmount": 1000.0},
        {"ProductName": "Tavuk Dürüm",  "TotalQuantity": 150.0, "TotalAmount": 750.0},
    ]


@pytest.mark.asyncio
async def test_compute_sum(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "sum"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "450" in result["final_response"]   # TotalQuantity sum (100+200+150=450)
    assert "2250" in result["final_response"]  # TotalAmount sum (500+1000+750=2250)


@pytest.mark.asyncio
async def test_compute_avg(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "avg"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "150" in result["final_response"]   # TotalQuantity avg


@pytest.mark.asyncio
async def test_compute_count(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "count"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "3" in result["final_response"]


@pytest.mark.asyncio
async def test_compute_min(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "min"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "100" in result["final_response"]   # TotalQuantity min


@pytest.mark.asyncio
async def test_compute_max(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "max"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "200" in result["final_response"]   # TotalQuantity max


@pytest.mark.asyncio
async def test_compute_empty_results():
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": [], "compute_operation": "sum"}
    result = await compute_results_node(state)
    assert "bulunamadı" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_no_numeric_cols():
    from src.graphs.report_agent.nodes import compute_results_node
    state = {
        "active_results": [{"ProductName": "A"}, {"ProductName": "B"}],
        "compute_operation": "sum",
    }
    result = await compute_results_node(state)
    assert "sayısal" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_default_operation_is_sum(sample_results):
    """compute_operation yoksa sum varsayılan olmalı."""
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results}  # compute_operation yok
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "450" in result["final_response"]  # TotalQuantity sum (100+200+150=450)
