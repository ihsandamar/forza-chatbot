"""
Report Graph Nodes

Orchestrates text2sql and visualization graphs to generate complete reports.
"""

import logging
from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from .state import ReportState

logger = logging.getLogger(__name__)


async def immediate_acknowledgment_node(state: ReportState) -> Dict[str, Any]:
    """
    Immediately send acknowledgment message to user.

    This node runs first to provide instant feedback while processing happens.
    """
    logger.info("Sending immediate acknowledgment...")

    ack_msg = AIMessage(content="🔄 Sorgunuz işleniyor...")

    return {
        "messages": [ack_msg]
    }


async def extract_query_node(state: ReportState) -> Dict[str, Any]:
    """
    Extract user query from messages.

    Takes the last user message as the query input.
    """
    messages = state.get("messages", [])

    if not messages:
        logger.error("No messages provided in state")
        return {
            "error": "No messages provided"
        }

    # Get last human message
    user_query = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    if not user_query:
        logger.error("No user message found in messages")
        return {
            "error": "No user message found in messages"
        }

    logger.info(f"Extracted query: {user_query[:100]}...")

    # Return updated state (no changes yet, just validation)
    return {}


def create_text2sql_node(text2sql_graph):
    """
    Factory to create text2sql invocation node.

    Args:
        text2sql_graph: Compiled text2sql graph instance
    """
    async def invoke_text2sql_node(state: ReportState) -> Dict[str, Any]:
        """
        Invoke text2sql graph with user query.

        Transforms ReportState -> GenericText2SQLState -> ainvoke -> store result
        """
        messages = state.get("messages", [])

        # Extract user query
        user_query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content
                break

        if not user_query:
            logger.error("No user query found in messages")
            return {
                "error": "No user query found",
                "text2sql_output": None
            }

        logger.info("Invoking text2sql graph...")

        try:
            # Create text2sql input state
            text2sql_input = {
                "user_query": user_query,
                "parsed_intent": None,
                "enriched_metadata": None,
                "resolved_steps": None,
                "resolution_metadata": None,
                "sql_queries": None,
                "results": None,
                "final_response": None,
                "error": None
            }

            # Async invoke text2sql graph
            text2sql_result = await text2sql_graph.ainvoke(text2sql_input)

            logger.info("Text2SQL completed successfully")
            logger.debug(f"Text2SQL result keys: {text2sql_result.keys()}")

            # Log important fields
            sql_queries = text2sql_result.get("sql_queries")
            results = text2sql_result.get("results")
            error = text2sql_result.get("error")

            logger.info(f"Text2SQL Summary:")
            logger.info(f"  - SQL Queries: {len(sql_queries) if sql_queries else 0}")
            if sql_queries:
                for i, query in enumerate(sql_queries, 1):
                    logger.info(f"    [{i}] {query[:100]}...")
            logger.info(f"  - Results: {len(results) if results else 0} rows")
            logger.info(f"  - Error: {error if error else 'None'}")

            return {
                "text2sql_output": text2sql_result,
                "error": text2sql_result.get("error")
            }

        except Exception as e:
            logger.error(f"Text2SQL invocation error: {str(e)}", exc_info=True)
            return {
                "error": f"Text2SQL error: {str(e)}",
                "text2sql_output": None
            }

    return invoke_text2sql_node


def create_visualization_node(visualization_graph):
    """
    Factory to create visualization invocation node.

    Args:
        visualization_graph: Compiled visualization graph instance
    """
    async def invoke_visualization_node(state: ReportState) -> Dict[str, Any]:
        """
        Invoke visualization graph with text2sql results.

        Transforms Text2SQLState -> DataVisualizationState -> ainvoke -> store result
        """
        text2sql_output = state.get("text2sql_output")

        if not text2sql_output:
            logger.error("No text2sql output available")
            return {
                "error": "No text2sql output available",
                "visualization_output": None
            }

        # Check for text2sql errors
        if text2sql_output.get("error"):
            logger.error(f"Text2SQL error: {text2sql_output['error']}")
            return {
                "error": f"Cannot visualize due to text2sql error: {text2sql_output['error']}",
                "visualization_output": None
            }

        logger.info("Invoking visualization graph...")

        try:
            # Visualization graph expects text2sql state as input
            # The state_transformer_node in viz graph will handle transformation
            viz_result = await visualization_graph.ainvoke(text2sql_output)

            logger.info("Visualization completed successfully")
            logger.debug(f"Visualization result keys: {viz_result.keys()}")

            return {
                "visualization_output": viz_result,
                "error": viz_result.get("error")
            }

        except Exception as e:
            logger.error(f"Visualization invocation error: {str(e)}", exc_info=True)
            return {
                "error": f"Visualization error: {str(e)}",
                "visualization_output": None
            }

    return invoke_visualization_node


async def build_response_node(state: ReportState) -> Dict[str, Any]:
    """
    Build final response message with visualization output.

    Adds an AI message to the messages list with the complete report.
    """
    viz_output = state.get("visualization_output")
    error = state.get("error")

    if error:
        # Add error message
        logger.error(f"Building error response: {error}")
        error_msg = AIMessage(content=f"❌ Rapor oluşturulurken hata: {error}")
        return {
            "messages": [error_msg]
        }

    if not viz_output:
        logger.warning("No visualization output found")
        error_msg = AIMessage(content="⚠️ Görselleştirme çıktısı bulunamadı")
        return {
            "messages": [error_msg]
        }

    # Extract visualization summary and data
    viz_final_output = viz_output.get("visualization_output", {})
    summary = viz_final_output.get("summary", "Rapor hazır")
    output_type = viz_final_output.get("output_type", "table")
    needs_graph = viz_final_output.get("needs_graph", False)
    data = viz_final_output.get("data", [])

    # Extract Plotly info
    plotly_code = viz_output.get("plotly_code")
    plotly_figure = viz_output.get("plotly_figure")

    logger.info(f"Building response: type={output_type}, needs_graph={needs_graph}, data_points={len(data)}")
    logger.info(f"Plotly: code={'✓' if plotly_code else '✗'}, figure={'✓' if plotly_figure else '✗'}")

    # Build response message
    response_parts = [
        "📊 Rapor Sonucu:",
        f"• Görselleştirme Tipi: {output_type}",
        f"• Grafik Gerekli: {'✓ Evet' if needs_graph else '✗ Hayır'}",
        f"• Veri Noktası: {len(data)}",
        f"• {summary}"
    ]

    # Add Plotly info
    if plotly_figure:
        response_parts.append(f"• Plotly Grafiği: ✓ Oluşturuldu")
    elif needs_graph:
        response_parts.append(f"• Plotly Grafiği: ✗ Oluşturulamadı")

    response_msg = AIMessage(content="\n".join(response_parts))

    return {
        "messages": [response_msg]
    }
