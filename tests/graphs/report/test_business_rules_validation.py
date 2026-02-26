"""Tests for business_rules_node LLM validation."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_llm_validation_filters_conflicting_masa_rules():
    """
    LLM validation, kullanıcı masa belirtmediğinde çelişen
    kapali_masa_filtre + acik_masa_filtre'yi birlikte UYGULAMAZ.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_business_rules_node

    # Vector store: 1 default + 2 çelişen kural döndürüyor
    mock_store = MagicMock()
    mock_store.get_relevant_rules_for_query.return_value = {
        "individual_rules": [
            {
                "id": "iade_dusulmus",
                "is_default": True,
                "description": "Ciro hesaplanırken iade düşülür",
                "sql": {"aggregation": "SUM(CASE WHEN ...)", "filter": None},
            },
            {
                "id": "kapali_masa_filtre",
                "is_default": False,
                "description": "Kapalı masalar filtresi",
                "sql": {"filter": "[IsTableActive] = 0", "aggregation": None},
            },
            {
                "id": "acik_masa_filtre",
                "is_default": False,
                "description": "Açık masalar filtresi",
                "sql": {"filter": "[IsTableActive] = 1", "aggregation": None},
            },
        ],
        "total_count": 3,
        "default_count": 1,
        "semantic_count": 2,
    }

    # LLM validation: masa durumu kullanıcı tarafından belirtilmemiş → boş liste
    from src.graphs.report_agent.subagents.text2sql.prompts import BusinessRulesValidationResult
    mock_validation = BusinessRulesValidationResult(
        applicable_rule_ids=[],
        reasoning="Kullanıcı açıkça masa durumu belirtmemiş, filtre uygulanmaz.",
    )
    mock_structured_llm = AsyncMock(return_value=mock_validation)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured_llm

    node_fn = create_business_rules_node(mock_store, llm=mock_llm)
    result = await node_fn({"user_query": "Son 1 senede carilere göre ciroyu göster"})

    auto_rules = result["auto_rules"]
    rule_ids = [r["id"] for r in auto_rules]

    # Default kural her zaman dahil
    assert "iade_dusulmus" in rule_ids

    # Çelişen kurallar filtrelenmiş
    assert "kapali_masa_filtre" not in rule_ids, \
        "kapali_masa_filtre uygulanmamalı: kullanıcı kapalı masadan bahsetmedi"
    assert "acik_masa_filtre" not in rule_ids, \
        "acik_masa_filtre uygulanmamalı: kullanıcı açık masadan bahsetmedi"


@pytest.mark.asyncio
async def test_llm_validation_keeps_explicitly_mentioned_rule():
    """'Kapalı masaların cirosu' → kapali_masa_filtre uygulanmalı."""
    from src.graphs.report_agent.subagents.text2sql.nodes import create_business_rules_node

    mock_store = MagicMock()
    mock_store.get_relevant_rules_for_query.return_value = {
        "individual_rules": [
            {
                "id": "iade_dusulmus",
                "is_default": True,
                "description": "Ciro iade düşülmüş",
                "sql": {"aggregation": "SUM(CASE WHEN ...)", "filter": None},
            },
            {
                "id": "kapali_masa_filtre",
                "is_default": False,
                "description": "Kapalı masalar filtresi",
                "sql": {"filter": "[IsTableActive] = 0", "aggregation": None},
            },
        ],
        "total_count": 2,
        "default_count": 1,
        "semantic_count": 1,
    }

    from src.graphs.report_agent.subagents.text2sql.prompts import BusinessRulesValidationResult
    mock_validation = BusinessRulesValidationResult(
        applicable_rule_ids=["kapali_masa_filtre"],
        reasoning="Kullanıcı 'kapalı masalar' dedi → kapali_masa_filtre geçerli.",
    )
    mock_structured_llm = AsyncMock(return_value=mock_validation)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured_llm

    node_fn = create_business_rules_node(mock_store, llm=mock_llm)
    result = await node_fn({"user_query": "Kapalı masaların son ay cirosu"})

    rule_ids = [r["id"] for r in result["auto_rules"]]
    assert "kapali_masa_filtre" in rule_ids


@pytest.mark.asyncio
async def test_no_llm_skips_validation():
    """llm=None ise LLM validation atlanır, tüm kurallar döner (backward compat)."""
    from src.graphs.report_agent.subagents.text2sql.nodes import create_business_rules_node

    mock_store = MagicMock()
    mock_store.get_relevant_rules_for_query.return_value = {
        "individual_rules": [
            {"id": "r1", "is_default": True, "description": "d1", "sql": {}},
            {"id": "r2", "is_default": False, "description": "d2", "sql": {}},
        ],
        "total_count": 2,
        "default_count": 1,
        "semantic_count": 1,
    }

    node_fn = create_business_rules_node(mock_store, llm=None)
    result = await node_fn({"user_query": "test"})

    rule_ids = [r["id"] for r in result["auto_rules"]]
    assert "r1" in rule_ids
    assert "r2" in rule_ids
