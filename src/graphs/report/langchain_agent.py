"""
LangChain Report Agent

LangChain Agent-based implementation of the report agent with custom middleware.

Replaces the previous LangGraph-based implementation with:
- Tool-based architecture
- Custom middleware for HITL, context management, and intent classification
- Cleaner separation of concerns

Architecture:
    User Message
        ↓
    IntentClassificationMiddleware (before_model)
        ↓
    Agent (decides tools)
        ↓
    ContextManagementMiddleware (wrap_tool_call)
        ↓
    MetadataCheckMiddleware (wrap_tool_call)
        ↓
    Tool Execution
        ↓
    Response
"""

import logging
from typing import Dict, Any, Optional, List

# Try different import paths for agent creation
try:
    # Modern LangChain (0.1.0+)
    from langchain.agents import create_openai_tools_agent, AgentExecutor
    AGENT_CREATOR = create_openai_tools_agent
except ImportError:
    try:
        # Alternative: create_react_agent
        from langchain.agents import create_react_agent, AgentExecutor
        AGENT_CREATOR = create_react_agent
    except ImportError:
        # Fallback: create_structured_chat_agent
        from langchain.agents import create_structured_chat_agent, AgentExecutor
        AGENT_CREATOR = create_structured_chat_agent

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from .agent_tools import REPORT_AGENT_TOOLS
from .middleware.context_management import ContextManagementMiddleware
from .middleware.metadata_check import MetadataCheckMiddleware, format_hitl_question
from .middleware.intent_classification import IntentClassificationMiddleware

logger = logging.getLogger(__name__)


# =============================================================================
# AGENT PROMPT
# =============================================================================

REPORT_AGENT_SYSTEM_PROMPT = """Sen bir akıllı veri analiz asistanısın. Kullanıcıların doğal dilde sorduğu sorulardan SQL sorguları oluşturup, verileri analiz edip görselleştiriyorsun.

## Yeteneklerin:

1. **text2sql_tool**: Doğal dilden SQL sorgusu oluştur ve çalıştır
   - Yeni sorgular oluşturabilir
   - Mevcut sorguları modifiye edebilir (filtre ekleme/çıkarma, gruplama değiştirme)
   - Context-aware: Önceki sorguya referans varsa context kullanır

2. **visualization_tool**: SQL sonuçlarından grafik oluştur
   - Otomatik grafik tipi seçimi
   - Plotly ile interaktif grafikler

3. **rollback_tool**: Önceki sorguya geri dön
   - Checkpoint history'den geri alma
   - Hatalı sorgu sonrası recovery

4. **get_context_tool**: Aktif sorgu bağlamını öğren
   - Mevcut SQL, filtreler, sonuç sayısı

## İşlem Akışı:

1. **Intent Analizi**: Kullanıcı yeni sorgu mu istiyor yoksa mevcut sorguyu mu değiştiriyor?
   - Context reference var mı? ("burdaki", "bunun", "peki", "gösterdiğin")
   - Modification trigger var mı? ("sadece", "ekle", "çıkar", "hariç")

2. **Tool Seçimi**:
   - NEW_QUERY → text2sql_tool (context olmadan)
   - MODIFY_* → text2sql_tool (context ile)
   - VISUALIZE → visualization_tool
   - ROLLBACK → rollback_tool

3. **HITL (Human-in-the-Loop)**:
   - Metadata ambiguity varsa kullanıcıya soru sor
   - Column/value belirsizliği durumunda seçenekler sun

4. **Context Management**:
   - Başarılı sorguları checkpoint olarak kaydet
   - Query history'yi tut (son 10)
   - Modification sorgularında context'i kullan

## Önemli Kurallar:

- Kullanıcı "burdaki", "bunun", "peki" gibi referanslar kullanıyorsa → Mevcut context'i KULLAN
- Boş sonuç gelirse → rollback öner veya filtreleri genişletmeyi öner
- Metadata ambiguity varsa → Kullanıcıya seçenekler sun, devam etme
- Her başarılı sorgu → checkpoint oluştur
- Tool çağrılarını akıllıca seç, gereksiz çağrı yapma"""


# =============================================================================
# AGENT BUILDER
# =============================================================================

def create_report_agent(
    llm: BaseChatModel,
    session_store: Optional[Dict] = None
) -> AgentExecutor:
    """
    Create LangChain Report Agent with custom middleware.

    Args:
        llm: Language model for agent
        session_store: Optional session storage for context persistence

    Returns:
        Configured AgentExecutor with middleware
    """
    logger.info("[REPORT_AGENT] Creating LangChain agent with middleware...")

    # Create prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", REPORT_AGENT_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    # Create agent (using available agent creator)
    logger.info(f"[REPORT_AGENT] Using agent creator: {AGENT_CREATOR.__name__}")

    agent = AGENT_CREATOR(
        llm=llm,
        tools=REPORT_AGENT_TOOLS,
        prompt=prompt
    )

    # Create middleware instances
    context_middleware = ContextManagementMiddleware(session_store=session_store)
    metadata_middleware = MetadataCheckMiddleware()
    intent_middleware = IntentClassificationMiddleware(llm=llm)

    # Create executor with middleware
    executor = AgentExecutor(
        agent=agent,
        tools=REPORT_AGENT_TOOLS,
        middleware=[
            intent_middleware,      # First: Classify intent
            context_middleware,     # Second: Manage context
            metadata_middleware,    # Third: Check metadata (HITL)
        ],
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=10,
        return_intermediate_steps=True
    )

    logger.info("[REPORT_AGENT] Agent created with 3 middleware layers")
    return executor


# =============================================================================
# AGENT WRAPPER (For compatibility with existing chatbot interface)
# =============================================================================

class ReportAgentWrapper:
    """
    Wrapper around LangChain agent for compatibility with existing chatbot interface.

    Provides async ainvoke method that handles:
    - Message formatting
    - HITL detection and flow
    - Response formatting
    """

    def __init__(self, executor: AgentExecutor, session_store: Optional[Dict] = None):
        """
        Initialize agent wrapper.

        Args:
            executor: Configured AgentExecutor
            session_store: Session storage reference
        """
        self.executor = executor
        self.session_store = session_store or {}
        logger.info("[REPORT_AGENT_WRAPPER] Initialized")

    async def ainvoke(
        self,
        state: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Invoke agent with state (compatible with LangGraph interface).

        Args:
            state: State dict with messages
            config: Optional runtime config

        Returns:
            Updated state with agent response
        """
        messages = state.get("messages", [])

        # Get last user message
        user_message = None
        for msg in reversed(messages):
            if isinstance(msg, dict):
                if msg.get("role") == "user":
                    user_message = msg.get("content")
                    break
            elif isinstance(msg, HumanMessage):
                user_message = msg.content
                break

        if not user_message:
            logger.error("[REPORT_AGENT_WRAPPER] No user message found")
            return {"messages": messages, "error": "No user message"}

        logger.info(f"[REPORT_AGENT_WRAPPER] Processing: {user_message[:50]}...")

        # Check if user is providing clarification
        user_clarification = state.get("user_clarification")

        if user_clarification:
            logger.info(f"[REPORT_AGENT_WRAPPER] User clarification received: {user_clarification}")

            # Get metadata middleware from executor
            metadata_middleware = self._get_metadata_middleware()

            if metadata_middleware:
                # Process clarification
                metadata_middleware.process_user_clarification(
                    user_clarification,
                    metadata_middleware.state
                )

                # Update user message to retry with clarification
                user_message = f"Önceki sorguyu tekrar çalıştır (kullanıcı '{user_clarification}' seçti)"

        # Build chat history
        chat_history = []
        for msg in messages[:-1]:  # Exclude last message (already in input)
            if isinstance(msg, dict):
                if msg.get("role") == "user":
                    chat_history.append(HumanMessage(content=msg["content"]))
                elif msg.get("role") == "assistant":
                    chat_history.append(AIMessage(content=msg["content"]))
            else:
                chat_history.append(msg)

        # Invoke agent
        try:
            result = await self.executor.ainvoke(
                {
                    "input": user_message,
                    "chat_history": chat_history
                },
                config=config
            )

            logger.info("[REPORT_AGENT_WRAPPER] Agent execution completed")

            # Check for HITL in intermediate steps
            intermediate_steps = result.get("intermediate_steps", [])
            hitl_detected = False
            pending_question = None

            for action, observation in intermediate_steps:
                if isinstance(observation, dict):
                    if observation.get("hitl_required"):
                        hitl_detected = True
                        pending_question = observation.get("pending_question")
                        logger.info("[REPORT_AGENT_WRAPPER] HITL detected in tool output")
                        break

            # If HITL detected, return with pending question
            if hitl_detected and pending_question:
                return {
                    "messages": messages + [AIMessage(content="Bir sorun var...")],
                    "pending_question": pending_question,
                    "waiting_for_user_input": True,
                    "user_clarification": None
                }

            # Normal response
            agent_output = result.get("output", "İşlem tamamlandı")

            return {
                "messages": messages + [AIMessage(content=agent_output)],
                "pending_question": None,
                "waiting_for_user_input": False,
                "user_clarification": None
            }

        except Exception as e:
            logger.error(f"[REPORT_AGENT_WRAPPER] Error: {e}", exc_info=True)
            return {
                "messages": messages + [AIMessage(content=f"❌ Hata: {str(e)}")],
                "error": str(e)
            }

    def _get_metadata_middleware(self) -> Optional[MetadataCheckMiddleware]:
        """Get metadata middleware instance from executor."""
        for mw in self.executor.middleware:
            if isinstance(mw, MetadataCheckMiddleware):
                return mw
        return None
