"""
Report V2 Orchestrator — Network Architecture

Bridge Node Pattern:
  Each agent node is a bridge function.
  OrchestratorState → create_*_input() → agent.ainvoke() → update OrchestratorState.

Network Routing:
  Classify result intent_type drives routing.
  Agents do NOT call each other — orchestrator manages routing.
"""

import logging
from typing import Optional

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graphs.report_v2.agents.analysis_agent import (
    build_analysis_agent,
    create_analysis_input,
)
from src.graphs.report_v2.agents.classify_agent import (
    build_classify_agent,
    create_classify_input,
)
from src.graphs.report_v2.agents.response_agent import (
    build_response_agent,
    create_response_input,
)
from src.graphs.report_v2.agents.sql_agent import build_sql_agent, create_sql_input
from src.graphs.report_v2.state import AnalysisResult, OrchestratorState, SQLResult

logger = logging.getLogger(__name__)


# ─── Bridge Factories ─────────────────────────────────────────────────────────


def make_classify_bridge(classify_agent):
    async def node(state: OrchestratorState) -> dict:
        result = await classify_agent.ainvoke(create_classify_input(state))
        return {"classify_result": result.get("classify_result")}

    return node


def make_sql_bridge(sql_agent):
    async def node(state: OrchestratorState) -> dict:
        classify_result = state["classify_result"]
        result = await sql_agent.ainvoke(create_sql_input(state, classify_result))
        sql_result = result.get("sql_result")
        updates = {"sql_result": sql_result}
        if sql_result and sql_result.get("updated_active_context"):
            updates["active_context"] = sql_result["updated_active_context"]
        if sql_result and sql_result.get("conversation_entry"):
            history = list(state.get("conversation_history", []))
            history.append(sql_result["conversation_entry"])
            updates["conversation_history"] = history[-20:]
        return updates

    return node


def make_analysis_bridge(analysis_agent):
    async def node(state: OrchestratorState) -> dict:
        classify_result = state["classify_result"]
        sql_result = state.get("sql_result") or SQLResult(
            results=[],
            sql_query="",
            no_records_message=None,
            updated_active_context=None,
            conversation_entry=None,
            error=None,
        )
        result = await analysis_agent.ainvoke(
            create_analysis_input(state, classify_result, sql_result)
        )
        return {"analysis_result": result.get("analysis_result")}

    return node


def make_viz_bridge(visualization_graph):
    """Calls data_visualization subgraph with sql results + viz decision.

    Input field alignment notes:
    - DataVisualizationState.raw_data is the canonical data field for the
      visualization pipeline. Passing ``raw_data`` (instead of ``results``)
      triggers state_transformer_node's fast path ("raw_data" in state →
      return as-is), which preserves the pre-populated ``viz_decision`` from
      the analysis agent.  Passing only ``results`` would cause the transformer
      to rebuild the state from scratch and discard ``viz_decision``.
    - ``viz_decision`` is passed from AnalysisResult so the visualization
      subgraph honours the orchestrator's decision rather than making a second
      redundant LLM call.
    - ``user_query`` maps directly to DataVisualizationState.user_query.
    """

    async def node(state: OrchestratorState) -> dict:
        sql_result = state.get("sql_result") or {}
        analysis_result = state.get("analysis_result") or {}
        classify_result = state.get("classify_result") or {}
        viz_input = {
            # Use raw_data (not results) to trigger the fast path in
            # state_transformer_node, keeping viz_decision intact.
            "raw_data": sql_result.get("results", []),
            "viz_decision": analysis_result.get("viz_decision", {}),
            "user_query": classify_result.get("user_query", ""),
        }
        viz_output = await visualization_graph.ainvoke(viz_input)
        return {"viz_artifact": viz_output}

    return node


def make_response_bridge(response_agent):
    async def node(state: OrchestratorState) -> dict:
        classify_result = state["classify_result"]
        sql_result = state.get("sql_result") or SQLResult(
            results=[],
            sql_query="",
            no_records_message=None,
            updated_active_context=None,
            conversation_entry=None,
            error=None,
        )
        analysis_result = state.get("analysis_result") or AnalysisResult(
            should_visualize=False,
            viz_decision={"needs_graph": False},
            business_insights=None,
            viz_reasoning=None,
        )
        result = await response_agent.ainvoke(
            create_response_input(state, classify_result, sql_result, analysis_result)
        )
        final_response = result.get("final_response", "")
        return {
            "final_response": final_response,
            "messages": [AIMessage(content=final_response)],
        }

    return node


async def rollback_bridge_node(state: OrchestratorState) -> dict:
    """Roll back to previous checkpoint."""
    query_history = state.get("query_history", [])
    if not query_history:
        return {"error": "Geri alinacak sorgu bulunamadi."}
    last = query_history[-1]
    return {
        "active_context": last.get("active_context"),
        "sql_result": None,
        "analysis_result": None,
    }


# ─── Routing ──────────────────────────────────────────────────────────────────


def route_after_classify(state: OrchestratorState) -> str:
    classify_result = state.get("classify_result")
    if not classify_result:
        return "response_agent"
    intent = classify_result.get("intent_type", "new_query")
    if intent == "rollback":
        return "rollback"
    if intent == "visualize" and state.get("active_context"):
        return "analysis_agent"
    return "sql_agent"


def route_after_sql(state: OrchestratorState) -> str:
    sql_result = state.get("sql_result") or {}
    if sql_result.get("error") or sql_result.get("no_records_message"):
        return "response_agent"
    return "analysis_agent"


def route_after_analysis(state: OrchestratorState) -> str:
    analysis_result = state.get("analysis_result") or {}
    if analysis_result.get("should_visualize"):
        return "viz_bridge"
    return "response_agent"


# ─── Graph Builder ────────────────────────────────────────────────────────────


def build_report_v2_graph(
    node_kit=None,
    llm=None,
    visualization_graph=None,
    checkpointer=None,
):
    """
    Compile the Report V2 network graph.

    Args:
        node_kit: GenericText2SQLNodeKit for SQL pipeline
        llm: LLM instance (None = rule-based fallback for all agents)
        visualization_graph: Compiled data_visualization subgraph
        checkpointer: LangGraph checkpointer (default: MemorySaver)
    """
    logger.info("[REPORT_V2] Building network graph...")

    llm_chat = llm.get_chat() if llm else None

    business_tracker = None
    report_interpreter = None
    response_generator = None

    if llm_chat:
        from src.graphs.report.business_context_tracker import BusinessContextTracker
        from src.graphs.report.report_interpreter import create_report_interpreter
        from src.graphs.report.response_generator import create_response_generator

        business_tracker = BusinessContextTracker(llm=llm_chat)
        report_interpreter = create_report_interpreter(llm=llm_chat)
        response_generator = create_response_generator(llm=llm_chat)

    classify_agent = build_classify_agent(llm=llm_chat)
    sql_agent = build_sql_agent(node_kit=node_kit, llm=llm_chat)
    analysis_agent = build_analysis_agent(
        business_tracker=business_tracker,
        report_interpreter=report_interpreter,
    )
    response_agent = build_response_agent(response_generator=response_generator)

    logger.info("[REPORT_V2] Sub-agents compiled")

    graph = StateGraph(OrchestratorState)

    graph.add_node("classify_agent", make_classify_bridge(classify_agent))
    graph.add_node("sql_agent", make_sql_bridge(sql_agent))
    graph.add_node("analysis_agent", make_analysis_bridge(analysis_agent))
    graph.add_node("response_agent", make_response_bridge(response_agent))
    graph.add_node("rollback", rollback_bridge_node)

    if visualization_graph:
        graph.add_node("viz_bridge", make_viz_bridge(visualization_graph))
        graph.add_edge("viz_bridge", "response_agent")

    graph.add_edge(START, "classify_agent")
    graph.add_conditional_edges(
        "classify_agent",
        route_after_classify,
        {
            "sql_agent": "sql_agent",
            "analysis_agent": "analysis_agent",
            "rollback": "rollback",
            "response_agent": "response_agent",
        },
    )
    graph.add_conditional_edges(
        "sql_agent",
        route_after_sql,
        {
            "analysis_agent": "analysis_agent",
            "response_agent": "response_agent",
        },
    )

    if visualization_graph:
        graph.add_conditional_edges(
            "analysis_agent",
            route_after_analysis,
            {
                "viz_bridge": "viz_bridge",
                "response_agent": "response_agent",
            },
        )
    else:
        graph.add_edge("analysis_agent", "response_agent")

    graph.add_edge("rollback", "response_agent")
    graph.add_edge("response_agent", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("[REPORT_V2] Graph compiled successfully")
    return compiled
