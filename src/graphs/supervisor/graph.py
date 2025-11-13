"""
Supervisor Graph - Multi-agent supervisor with research and portfolio agents
Routes requests between research and portfolio agents using handoff pattern.
"""
from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.graphs.chat.graph import ChatGraph
from src.graphs.forza_routing_graph import VegaforzaNavigationGraph

from src.graphs.routing.graph import RoutingGraph
from src.graphs.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT
from src.graphs.supervisor.tools import (
    get_current_time,
    get_supervisor_status,
    assign_to_chat_agent,
    assign_to_routing_agent
)


def create_supervisor_graph(llm):
    """
    Create a supervisor graph that routes requests to research or portfolio agents.

    The supervisor uses multi-destination pattern:
    1. Receives user messages
    2. Decides to route to research or portfolio agent
    3. Agents process requests and route back to supervisor
    4. Response sent to user

    Graph Structure:
        START
          |
          v
      supervisor (ReAct Agent with handoff tools)
         / \\
        /   \\
       v     v
    research portfolio
       \\   /
        \\ /
         v
      supervisor (decision point)
         |
         v
        END

    Args:
        llm: Language model instance (must have get_chat() method)

    Returns:
        Compiled LangGraph graph with supervisor, research, and portfolio nodes
    """

    # Create supervisor agent with handoff tools
    supervisor_agent = create_react_agent(
        model=llm.get_chat(),
        tools=[
            get_current_time,
            get_supervisor_status,
            assign_to_chat_agent,
            assign_to_routing_agent
        ],
        prompt=SUPERVISOR_SYSTEM_PROMPT,
        name="supervisor"
    )

    routing_agent = RoutingGraph(llm=llm).build_graph()
    # routing_agent = VegaforzaNavigationGraph(llm=llm).build_graph()

    chat_agent = ChatGraph(llm=llm).build_graph()

    # Build the graph with multi-destination pattern
    builder = StateGraph(MessagesState)

    # Add nodes
    builder.add_node("supervisor", supervisor_agent, destinations=["routing", "chat"])
    builder.add_node("routing", routing_agent)
    builder.add_node("chat", chat_agent)

    # Define edges - return back pattern
    builder.add_edge(START, "supervisor")
    builder.add_edge("routing", "supervisor")  # Research routes back to supervisor
    builder.add_edge("chat", "supervisor")  # Portfolio routes back to supervisor
    builder.add_edge("supervisor", END)

    # Compile with memory
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


