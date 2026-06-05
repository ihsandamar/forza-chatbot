from langgraph.graph import END, START, StateGraph

from .nodes import create_clarity_analyzer_node
from .state import QueryClarifierState


def build_query_clarifier_graph(
    llm,
    clarity_threshold: float = 0.65,
    enable_clarifier: bool = True,
):
    """Compile and return the query_clarifier subgraph."""
    clarity_analyzer = create_clarity_analyzer_node(
        llm,
        clarity_threshold=clarity_threshold,
        enable_clarifier=enable_clarifier,
    )

    graph = StateGraph(QueryClarifierState)
    graph.add_node("clarity_analyzer", clarity_analyzer)
    graph.add_edge(START, "clarity_analyzer")
    graph.add_edge("clarity_analyzer", END)

    return graph.compile()
