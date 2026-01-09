"""
Report Graph State Definition

This graph orchestrates the complete report generation pipeline:
1. Accepts user messages
2. Converts to SQL query via text2sql graph
3. Visualizes results via visualization graph
"""

from typing import TypedDict, List, Optional, Any, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ReportState(TypedDict):
    """
    State for report generation graph.

    Uses LangChain messages for flexible input/output.
    """

    # Input: User messages (required)
    messages: Annotated[List[BaseMessage], add_messages]

    # Intermediate: Text2SQL output
    text2sql_output: Optional[dict]

    # Final: Visualization output
    visualization_output: Optional[dict]

    # Message when no records found (set by check_results_node)
    no_records_message: Optional[str]

    # Error tracking
    error: Optional[str]
