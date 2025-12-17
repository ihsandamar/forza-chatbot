"""
Two-Tier Supervisor Architecture - Example Implementation

Bu dosya, router ve synthesizer supervisor'ların nasıl ayrılacağını gösterir.
Production'a geçmeden önce test edilmeli.
"""
import logging
from typing import Optional, Literal
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from langchain_core.tools import tool

from src.models.llm import LLM
from src.graphs.routing.graph import RoutingGraph
from src.graphs.chat.graph import ChatGraph
from src.services.config_loader import ConfigLoader

config = ConfigLoader.load_config()
api_key = config.llm.api_key
logger = logging.getLogger(__name__)

# ============================================
# TIER 1: Router Supervisor
# ============================================

ROUTER_SUPERVISOR_PROMPT = """You are a ROUTING SUPERVISOR.

Your ONLY responsibility is to analyze user intent and forward requests to the appropriate specialist agent.

Available agents:
1. **ROUTING AGENT** - For navigation, page finding, document retrieval
   - Use when: "where is", "find page", "navigate to", "show me"

2. **CHAT AGENT** - For conversations, questions, explanations
   - Use when: general questions, discussions, explanations

CRITICAL RULES:
- You do NOT generate responses
- You do NOT synthesize or summarize
- You ONLY route using the handoff tools
- Make routing decision immediately

Use the appropriate handoff tool NOW."""


# ============================================
# TIER 2: Synthesizer Supervisor
# ============================================

SYNTHESIZER_SUPERVISOR_PROMPT_TRANSPARENT = """You are a SYNTHESIS SUPERVISOR in TRANSPARENT mode.

Your job: Forward agent responses directly to the user without modification.

RULES:
- DO NOT add commentary
- DO NOT summarize
- DO NOT regenerate content
- ALWAYS use forward_message tool

The agent's response is already complete. Just forward it."""


SYNTHESIZER_SUPERVISOR_PROMPT_SYNTHESIZED = """You are a SYNTHESIS SUPERVISOR in SYNTHESIZED mode.

Your job: Analyze agent responses and create a unified, high-quality response.

When to synthesize:
- Multiple agents provided responses
- Response needs context or clarification
- Response needs better formatting
- Response has issues or gaps

Guidelines:
1. Review all agent responses
2. Identify key information
3. Create a coherent, unified response
4. Maintain accuracy of agent information
5. Add context where helpful

Be concise but comprehensive."""


SYNTHESIZER_SUPERVISOR_PROMPT_ADAPTIVE = """You are a SYNTHESIS SUPERVISOR in ADAPTIVE mode.

Your job: Decide whether to forward or synthesize based on response quality.

Decision criteria:

FORWARD (use forward_message) when:
- Agent response is complete and clear
- No additional context needed
- Single agent call with good result
- User question fully answered

SYNTHESIZE when:
- Response is too brief or unclear
- Multiple agents were involved
- Response needs context or clarification
- Error occurred or response is incomplete

Make your decision and act accordingly."""


# ============================================
# Tools
# ============================================

@tool
def assign_to_routing_agent():
    """
    Forward request to the routing agent for navigation and document retrieval.

    Use when user needs:
    - Find pages or documents
    - Navigate to specific locations
    - Search for information
    """
    logger.info("[ROUTER] Assigning to routing agent")
    return "routing"


@tool
def assign_to_chat_agent():
    """
    Forward request to the chat agent for conversation and questions.

    Use when user needs:
    - General conversation
    - Questions and explanations
    - Discussion and clarification
    """
    logger.info("[ROUTER] Assigning to chat agent")
    return "chat"


@tool
def forward_message(reason: str = "Agent response is complete"):
    """
    Forward agent's response directly to user without modification.

    Args:
        reason: Brief explanation why forwarding is appropriate

    Use when the agent's response is already complete and clear.
    """
    logger.info(f"[SYNTHESIZER] Forwarding message: {reason}")
    # Return special flag to indicate no synthesis needed
    return {"action": "forward", "reason": reason}


@tool
def synthesize_response(synthesis_goal: str):
    """
    Create a synthesized response from agent outputs.

    Args:
        synthesis_goal: What you aim to achieve with synthesis
                       (e.g., "combine both responses", "add context", "clarify")

    Use when agent responses need improvement, context, or combination.
    """
    logger.info(f"[SYNTHESIZER] Synthesis requested: {synthesis_goal}")
    # Return special flag to trigger supervisor's own response
    return {"action": "synthesize", "goal": synthesis_goal}


# ============================================
# Helper Functions
# ============================================

def handle_routing_node(routing_agent):
    """Wrapper for routing agent (same as before)."""
    async def wrapped_routing(state: MessagesState) -> MessagesState:
        logger.info("[SUPERVISOR] Invoking routing agent...")
        messages = state.get("messages", [])

        user_message = None
        for msg in reversed(messages):
            if hasattr(msg, '__class__') and msg.__class__.__name__ == 'HumanMessage':
                user_message = msg
                break

        routing_state = {
            "message": user_message,
            "messages": messages,
        }

        routing_output = await routing_agent.ainvoke(routing_state)

        if isinstance(routing_output, dict):
            if "most_relevant_page" in routing_output:
                state["most_relevant_page"] = routing_output.get("most_relevant_page")
            if "page_parameters" in routing_output:
                state["page_parameters"] = routing_output.get("page_parameters")
            if "retrieved_documents" in routing_output:
                state["retrieved_documents"] = routing_output.get("retrieved_documents")
            if "messages" in routing_output:
                state["messages"] = routing_output.get("messages")

        logger.info("[SUPERVISOR] Routing agent completed")
        return state

    from langchain_core.runnables import RunnableLambda
    return RunnableLambda(wrapped_routing)


def should_forward_or_synthesize(state: MessagesState) -> Literal["end", "synthesize"]:
    """
    Determine if synthesizer should forward or synthesize based on last tool call.

    If synthesizer used forward_message tool → go to end
    If synthesizer used synthesize_response tool → stay in synthesizer to generate response
    """
    messages = state.get("messages", [])

    # Check last message for tool calls
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            last_tool = msg.tool_calls[-1]
            tool_name = last_tool.get("name", "")

            if tool_name == "forward_message":
                logger.info("[GRAPH] Forwarding - going to END")
                return "end"
            elif tool_name == "synthesize_response":
                logger.info("[GRAPH] Synthesizing - staying in synthesizer")
                return "synthesize"

    # Default: end
    return "end"


# ============================================
# Graph Builder
# ============================================

class TwoTierSupervisorGraph:
    """
    Two-tier supervisor architecture with separate router and synthesizer.
    """

    def __init__(
        self,
        llm: LLM,
        synthesis_strategy: Literal["transparent", "synthesized", "adaptive"] = "transparent"
    ):
        """
        Initialize two-tier supervisor.

        Args:
            llm: Language model instance
            synthesis_strategy: How synthesizer should behave
                - transparent: Always forward
                - synthesized: Always synthesize
                - adaptive: Decide based on quality
        """
        self.llm = llm
        self.synthesis_strategy = synthesis_strategy

        # Select appropriate synthesizer prompt
        if synthesis_strategy == "transparent":
            self.synthesizer_prompt = SYNTHESIZER_SUPERVISOR_PROMPT_TRANSPARENT
        elif synthesis_strategy == "synthesized":
            self.synthesizer_prompt = SYNTHESIZER_SUPERVISOR_PROMPT_SYNTHESIZED
        else:  # adaptive
            self.synthesizer_prompt = SYNTHESIZER_SUPERVISOR_PROMPT_ADAPTIVE

        logger.info(f"[TWO-TIER] Initialized with synthesis_strategy={synthesis_strategy}")

    def build_graph(self) -> StateGraph:
        """Build and compile the two-tier supervisor graph."""

        logger.info("[TWO-TIER] Building graph...")

        # ============================================
        # Create Agents
        # ============================================

        # Router Supervisor - Only routing
        router_supervisor = create_agent(
            model=self.llm.get_chat(),
            tools=[assign_to_routing_agent, assign_to_chat_agent],
            system_prompt=ROUTER_SUPERVISOR_PROMPT,
            name="router_supervisor"
        )

        # Synthesizer Supervisor - Only synthesis
        synthesizer_supervisor = create_agent(
            model=self.llm.get_chat(),
            tools=[forward_message, synthesize_response],
            system_prompt=self.synthesizer_prompt,
            name="synthesizer_supervisor"
        )

        # Sub-agents
        routing_agent = RoutingGraph(llm=self.llm).build_graph()
        chat_agent = ChatGraph(llm=self.llm).build_graph()

        # ============================================
        # Build Graph Structure
        # ============================================

        builder = StateGraph(MessagesState)

        # Add nodes
        logger.info("[TWO-TIER] Adding nodes:")
        logger.info("  - router_supervisor (Tier 1)")
        logger.info("  - routing, chat (Workers)")
        logger.info("  - synthesizer_supervisor (Tier 2)")

        builder.add_node("router_supervisor", router_supervisor,
                        destinations=["routing", "chat"])
        builder.add_node("routing", handle_routing_node(routing_agent))
        builder.add_node("chat", chat_agent)
        builder.add_node("synthesizer_supervisor", synthesizer_supervisor)

        # Add edges
        logger.info("[TWO-TIER] Adding edges:")
        logger.info("  START → router_supervisor")
        logger.info("  router_supervisor → {routing, chat}")
        logger.info("  {routing, chat} → synthesizer_supervisor")
        logger.info("  synthesizer_supervisor → {END, synthesizer_supervisor}")

        builder.add_edge(START, "router_supervisor")
        builder.add_edge("routing", "synthesizer_supervisor")
        builder.add_edge("chat", "synthesizer_supervisor")

        # Conditional edge for synthesizer
        # If forward_message → END
        # If synthesize_response → stay in synthesizer to generate response
        builder.add_conditional_edges(
            "synthesizer_supervisor",
            should_forward_or_synthesize,
            {"end": END, "synthesize": "synthesizer_supervisor"}
        )

        logger.info("[TWO-TIER] Compiling graph...")
        compiled = builder.compile()
        logger.info("[TWO-TIER] Graph compiled successfully ✓")

        return compiled


# ============================================
# Factory Function
# ============================================

def create_two_tier_supervisor_graph(
    llm: LLM,
    synthesis_strategy: Literal["transparent", "synthesized", "adaptive"] = "transparent"
):
    """
    Create a two-tier supervisor graph.

    Args:
        llm: Language model instance
        synthesis_strategy: Synthesis behavior (transparent/synthesized/adaptive)

    Returns:
        Compiled graph

    Examples:
        # Transparent mode - fast, direct forwarding
        graph = create_two_tier_supervisor_graph(llm, "transparent")

        # Synthesized mode - always improve responses
        graph = create_two_tier_supervisor_graph(llm, "synthesized")

        # Adaptive mode - decide based on quality
        graph = create_two_tier_supervisor_graph(llm, "adaptive")
    """
    return TwoTierSupervisorGraph(llm, synthesis_strategy).build_graph()


# ============================================
# Usage Example
# ============================================

if __name__ == "__main__":
    from src.models.llm import LLM

    # Initialize LLM
    llm = LLM(provider="openai", model="gpt-4", api_key=api_key)

    # Create graph with adaptive strategy
    graph = create_two_tier_supervisor_graph(
        llm=llm,
        synthesis_strategy="adaptive"
    )

    # Test
    result = graph.invoke({
        "messages": [
            HumanMessage(content="Stok sayfasına gitmek istiyorum")
        ]
    })



    # Result as chat messages format
    for msg in result["messages"]:
        print(f"{msg.__class__.__name__}: {msg.content}")
    # If synthesizer forwarded directly, final action will be in last message
    if isinstance(result["messages"][-1], AIMessage):
        final_msg = result["messages"][-1]
        if hasattr(final_msg, "tool_calls") and final_msg.tool_calls:
            last_tool = final_msg.tool_calls[-1]
            if last_tool.get("name") == "forward_message":
                output = last_tool.get("arguments", {}).get("output", "")
                print(f"\n[FINAL OUTPUT FORWARDED]: {output}")


