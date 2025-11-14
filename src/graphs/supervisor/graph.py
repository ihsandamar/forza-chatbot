"""
Supervisor Graph - Multi-agent supervisor with research and portfolio agents
Routes requests between research and portfolio agents using handoff pattern.
"""
import logging
from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent

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

logger = logging.getLogger(__name__)


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
    logger.info("[SUPERVISOR] Creating supervisor graph...")

    # Create supervisor agent with handoff tools
    logger.info("[SUPERVISOR] Creating ReAct agent with handoff tools:")
    logger.info("[SUPERVISOR]   - assign_to_chat_agent")
    logger.info("[SUPERVISOR]   - assign_to_routing_agent")
    logger.info("[SUPERVISOR]   - get_current_time")
    logger.info("[SUPERVISOR]   - get_supervisor_status")

    supervisor_agent = create_agent(
        model=llm.get_chat(),
        tools=[
            get_current_time,
            get_supervisor_status,
            assign_to_chat_agent,
            assign_to_routing_agent
        ],
        
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        name="supervisor"
    )

    logger.info("[SUPERVISOR] Building routing agent...")
    routing_agent = RoutingGraph(llm=llm).build_graph()
    logger.info("[SUPERVISOR] Routing agent built successfully")

    # routing_agent = VegaforzaNavigationGraph(llm=llm).build_graph()

    logger.info("[SUPERVISOR] Building chat agent...")
    chat_agent = ChatGraph(llm=llm).build_graph()
    logger.info("[SUPERVISOR] Chat agent built successfully")

    # Build the graph with multi-destination pattern
    logger.info("[SUPERVISOR] Building supervisor graph structure...")
    builder = StateGraph(MessagesState)

    # Add nodes
    logger.info("[SUPERVISOR] Adding nodes:")
    logger.info("[SUPERVISOR]   - supervisor (with destinations: routing, chat)")
    logger.info("[SUPERVISOR]   - routing")
    logger.info("[SUPERVISOR]   - chat")

    builder.add_node("supervisor", supervisor_agent, destinations=["routing", "chat"])
    builder.add_node("routing", routing_agent)
    builder.add_node("chat", chat_agent)

    # Define edges - return back pattern
    logger.info("[SUPERVISOR] Defining edges:")
    logger.info("[SUPERVISOR]   START → supervisor")
    logger.info("[SUPERVISOR]   supervisor → {routing, chat}")
    logger.info("[SUPERVISOR]   routing → supervisor")
    logger.info("[SUPERVISOR]   chat → supervisor")
    logger.info("[SUPERVISOR]   supervisor → END")

    builder.add_edge(START, "supervisor")
    builder.add_edge("routing", "supervisor")  # Research routes back to supervisor
    builder.add_edge("chat", "supervisor")  # Portfolio routes back to supervisor
    builder.add_edge("supervisor", END)

    # Compile with memory
    logger.info("[SUPERVISOR] Compiling supervisor graph...")
    memory = MemorySaver()
    compiled_graph = builder.compile(checkpointer=memory)
    logger.info("[SUPERVISOR] Supervisor graph compiled successfully ✓")

    return compiled_graph


