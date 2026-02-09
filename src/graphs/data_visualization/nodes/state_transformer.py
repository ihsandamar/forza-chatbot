# data_visualization/nodes/state_transformer.py

import logging
from typing import Dict, Any, List, Optional

from ..state import DataVisualizationState

# Text2SQL state import (senin mevcut state'in)
from ...generic_text2sql.state import GenericText2SQLState, ParsedIntent

logger = logging.getLogger(__name__)


class StateTransformer:
    """
    Transforms Text2SQL state to DataVisualization state.
    No LLM usage - pure data transformation.
    """
    
    def transform(self, text2sql_state: GenericText2SQLState) -> DataVisualizationState:
        """
        Main transformation method.

        Args:
            text2sql_state: Output from Text2SQL graph

        Returns:
            DataVisualizationState: Initial state for visualization graph
        """

        # ─────────────────────────────────────────────────────────
        # Extract data from Text2SQL state
        # ─────────────────────────────────────────────────────────

        user_query: str = text2sql_state.get("user_query", "")
        results: Optional[List[Dict[str, Any]]] = text2sql_state.get("results")
        parsed_intent: Optional[ParsedIntent] = text2sql_state.get("parsed_intent")
        error: Optional[str] = text2sql_state.get("error")
        sql_queries: Optional[List[str]] = text2sql_state.get("sql_queries")

        # Debug logging
        logger.info(f"Transforming Text2SQL state for query: {user_query[:100]}...")
        logger.info(f"Text2SQL state keys: {list(text2sql_state.keys())}")
        logger.info(f"SQL queries field: {sql_queries}")
        logger.info(f"Results field: type={type(results)}, value={results}")
        logger.info(f"Error from Text2SQL: {error}")

        # Log full state for debugging
        import json
        try:
            logger.debug(f"Full Text2SQL state: {json.dumps({k: str(v)[:200] if v else None for k, v in text2sql_state.items()}, indent=2)}")
        except Exception as e:
            logger.debug(f"Could not serialize state: {e}")
        
        # ─────────────────────────────────────────────────────────
        # Extract query intent description
        # ─────────────────────────────────────────────────────────
        
        query_intent: Optional[str] = None
        if parsed_intent:
            query_intent = parsed_intent.get("final_output")
        
        # ─────────────────────────────────────────────────────────
        # Handle error state
        # ─────────────────────────────────────────────────────────
        
        if error:
            return DataVisualizationState(
                user_query=user_query,
                query_intent=query_intent,
                raw_data=[],
                data_profile=None,
                viz_decision=None,
                chart_config=None,
                visualization_output=None,
                error=f"Text2SQL error: {error}"
            )
        
        # ─────────────────────────────────────────────────────────
        # Handle empty results
        # ─────────────────────────────────────────────────────────

        if results is None or len(results) == 0:
            # Empty results - will be handled by report graph's check_results_node
            logger.info("Empty results from SQL execution - skipping visualization")
            return DataVisualizationState(
                user_query=user_query,
                query_intent=query_intent,
                raw_data=[],
                data_profile=None,
                viz_decision=None,
                chart_config=None,
                visualization_output=None,
                error=None  # Not an error - report graph will handle this
            )
        
        # ─────────────────────────────────────────────────────────
        # Process results
        # ─────────────────────────────────────────────────────────
        
        raw_data = self._extract_raw_data(results)
        
        # ─────────────────────────────────────────────────────────
        # Build initial visualization state
        # ─────────────────────────────────────────────────────────
        
        return DataVisualizationState(
            user_query=user_query,
            query_intent=query_intent,
            raw_data=raw_data,
            data_profile=None,           # Filled by DataAnalyzer
            viz_decision=None,           # Filled by VisualizationDecider
            chart_config=None,           # Filled by ChartConfigBuilder
            visualization_output=None,   # Filled by ResponseBuilder
            error=None
        )
    
    def _extract_raw_data(self, results: Any) -> List[Dict[str, Any]]:
        """
        Extract raw data from results.
        Handles both single and multi-step query results.
        
        Args:
            results: Query results (could be nested for multi-step queries)
            
        Returns:
            List of dictionaries representing rows
        """
        
        if not results:
            return []
        
        # Check if results is a list
        if not isinstance(results, list):
            return []
        
        # Check if it's nested (multi-step query results)
        # Multi-step: [[{row1}, {row2}], [{row1}, {row2}]]
        # Single-step: [{row1}, {row2}]
        
        if len(results) > 0:
            first_item = results[0]
            
            # If first item is also a list, it's multi-step results
            if isinstance(first_item, list):
                # Take the last step's results (final output)
                last_step_results = results[-1]
                if isinstance(last_step_results, list):
                    return last_step_results
                return []
            
            # If first item is a dict, it's single-step results
            elif isinstance(first_item, dict):
                return results
        
        return []


# ============================================================
# LangGraph Node Function
# ============================================================

def state_transformer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node wrapper for state transformation.
    
    This node serves as the entry point for the visualization graph.
    It transforms the Text2SQL output into the visualization state format.
    
    Usage in graph:
        graph.add_node("transform_state", state_transformer_node)
    
    Args:
        state: Either GenericText2SQLState or already transformed state
        
    Returns:
        DataVisualizationState as dictionary
    """
    
    # Check if already transformed (has 'raw_data' key)
    if "raw_data" in state:
        # Already in visualization state format, return as-is
        return state
    
    # Transform from Text2SQL state
    transformer = StateTransformer()
    viz_state = transformer.transform(state)
    
    return viz_state