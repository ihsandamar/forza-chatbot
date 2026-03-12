import logging
import uuid

logger = logging.getLogger(__name__)
import re
from datetime import datetime
from typing import Optional, Dict
from langgraph.errors import GraphInterrupt, GraphBubbleUp
from src.api.models.requests.chat import SessionStartRequest, ChatMessageRequest
from src.api.models.responses.chat import (
    SessionStartResponse,
    ChatMessageResponse,
    ResponseData,
    ActionResponse,
    SessionHistoryResponse,
    MessageHistoryItem
)
from src.core.chatbot import Chatbot
from src.core.models import SessionSettings, ResponseFormat


class ChatService:
    """Service for handling chat-related business logic"""

    def __init__(self, chatbot: Chatbot):
        # In-memory session storage (replace with Redis/DB in production)
        self.sessions: Dict[str, dict] = {}
        self.chatbot = chatbot

    async def start_session(self, request: SessionStartRequest) -> SessionStartResponse:
        """
        Start a new chat session

        Args:
            request: SessionStartRequest with optional user_id and token

        Returns:
            SessionStartResponse with session_id and metadata
        """
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        created_at = datetime.now()

        # Store session data with default settings
        settings = SessionSettings()
        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": request.user_id,
            "token": request.token,  # Store token for graph operations
            "created_at": created_at,
            "messages": [],
            "metadata": {},
            "settings": {
                "max_messages": settings.max_messages,
                "response_format": settings.response_format
            }
        }

        return SessionStartResponse(
            session_id=session_id,
            user_id=request.user_id,
            created_at=created_at
        )

    async def start_session_async(self, request: SessionStartRequest) -> SessionStartResponse:
        """
        Async wrapper for start_session (alias for compatibility)

        Args:
            request: SessionStartRequest with optional user_id and token

        Returns:
            SessionStartResponse with session_id and metadata
        """
        return await self.start_session(request)

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get session data by session_id"""
        return self.sessions.get(session_id)

    def session_exists(self, session_id: str) -> bool:
        """Check if session exists"""
        return session_id in self.sessions

    def _extract_url_from_message(self, content: str) -> Optional[str]:
        """
        Extract URL from message content.

        Args:
            content: Message content to search for URLs

        Returns:
            First URL found, or None if no URL exists
        """
        # Regex pattern to match URLs
        url_pattern = r'https?://[^\s\)\]\}]+'
        match = re.search(url_pattern, content)
        if match:
            return match.group(0)
        return None

    def _detect_routing_response(self, messages: list) -> Optional[dict]:
        """
        Detect if messages contain a routing response (tool message with URL).

        Checks the last few messages for tool messages containing URLs,
        which indicates a navigation/routing action.

        Args:
            messages: List of messages from graph output

        Returns:
            Dict with routing info if detected, None otherwise
            Format: {"url": str, "text": str}
        """
        # Check last 5 messages for tool messages with URLs
        check_count = min(5, len(messages))
        recent_messages = messages[-check_count:] if check_count > 0 else []

        for msg in reversed(recent_messages):
            # Parse message to get role and content
            role, content = self._parse_message(msg)

            # Check if it's a tool message
            if role == "tool" and content:
                # Check if content contains URL
                url = self._extract_url_from_message(str(content))
                if url:
                    return {
                        "url": url,
                        "text": str(content)
                    }

        return None

    def _detect_report_response(self, messages: list) -> Optional[dict]:
        """
        Detect if messages contain a report response (AI message with chart HTML).

        First checks additional_kwargs.chart_html (new pattern: HTML stored as metadata,
        not in message content, to avoid bloating LLM context on subsequent turns).
        Falls back to parsing content for legacy iframe detection.

        Args:
            messages: List of messages from graph output

        Returns:
            Dict with report info if detected, None otherwise
            Format: {"html": str, "text": str}
        """
        # Check last 5 messages for AI messages with chart HTML
        check_count = min(5, len(messages))
        recent_messages = messages[-check_count:] if check_count > 0 else []

        for msg in reversed(recent_messages):
            role, content = self._parse_message(msg)

            if role == "assistant" and content:
                # Priority 1: chart_html in additional_kwargs (new pattern — no LLM bloat)
                additional_kwargs = getattr(msg, "additional_kwargs", None) or {}
                chart_html = additional_kwargs.get("chart_html")
                if chart_html:
                    return {
                        "html": chart_html,
                        "text": str(content),
                    }

                # Priority 2: Legacy — parse iframe from content (backward compat)
                content_str = str(content)
                if ("<iframe" in content_str and "base64" in content_str) or \
                   ("<div" in content_str and "plotly" in content_str.lower()):
                    import re
                    iframe_pattern = r'<iframe[^>]*src="[^"]*"[^>]*>.*?</iframe>'
                    iframe_match = re.search(iframe_pattern, content_str, re.DOTALL | re.IGNORECASE)

                    if iframe_match:
                        html_snippet = iframe_match.group(0)
                        text_without_html = re.sub(r'<[^>]+>', '', content_str).strip()
                        text_without_html = re.sub(r'\s+', ' ', text_without_html).strip()
                        return {
                            "html": html_snippet,
                            "text": text_without_html
                        }

        return None

    def _detect_hitl_question(self, graph_output: dict) -> Optional[dict]:
        """
        Detect if graph output contains a HITL (Human-in-the-Loop) question.

        HITL questions occur when the report agent needs clarification from user.
        This happens via interrupt_before pattern in LangGraph.

        Args:
            graph_output: Full graph output state

        Returns:
            Dict with HITL info if detected, None otherwise
            Format: {"question": str, "options": list, "context": str}
        """
        # Check for pending_question in state
        pending_question = graph_output.get("pending_question")
        waiting_for_input = graph_output.get("waiting_for_user_input", False)

        if pending_question and waiting_for_input:
            return {
                "question": pending_question.get("question", ""),
                "options": pending_question.get("options", []),
                "context": pending_question.get("context", "")
            }

        return None

    def _store_hitl_state(self, session_id: str, hitl_info: dict):
        """
        Store HITL state in session for resume.

        Args:
            session_id: Session identifier
            hitl_info: HITL question information
        """
        session = self.get_session(session_id)
        if session:
            session["hitl_pending"] = True
            session["hitl_question"] = hitl_info

    def _get_hitl_state(self, session_id: str) -> Optional[dict]:
        """
        Get pending HITL state from session.

        Args:
            session_id: Session identifier

        Returns:
            HITL info if pending, None otherwise
        """
        session = self.get_session(session_id)
        if session and session.get("hitl_pending"):
            return session.get("hitl_question")
        return None

    def _clear_hitl_state(self, session_id: str):
        """
        Clear HITL state after user responds.

        Args:
            session_id: Session identifier
        """
        session = self.get_session(session_id)
        if session:
            session["hitl_pending"] = False
            session["hitl_question"] = None

    async def send_message(self, request: ChatMessageRequest) -> ChatMessageResponse:
        """
        Send a message to the chatbot

        Supports HITL (Human-in-the-Loop) flow:
        1. If there's a pending HITL question, treat user message as clarification
        2. Otherwise, process as normal message

        Args:
            request: ChatMessageRequest with session_id and message

        Returns:
            ChatMessageResponse with bot response

        Raises:
            ValueError: If session not found
        """
        # Check if session exists
        if not self.session_exists(request.session_id):
            raise ValueError(f"Session not found: {request.session_id}")

        # Get session data
        session = self.get_session(request.session_id)

        # Build message history from session
        messages = session.get("messages", [])

        # Check if there's a pending HITL question
        hitl_pending = self._get_hitl_state(request.session_id)

        # If HITL is pending, handle as clarification with Command pattern
        if hitl_pending:
            # Command-based HITL: Resume graph with Command(resume=...)
            logger.info(f"[CHAT] HITL clarification received: {request.message[:50]}...")

            # Try to use Command(resume=...) if available
            try:
                from langgraph.types import Command

                # Use Command to resume the interrupted graph
                logger.info("[CHAT] Using Command(resume=...) for HITL")

                # Create Command with resume value
                # This will be passed to graph instead of state
                state = Command(resume=request.message)

            except ImportError:
                # Fallback: Message-based HITL (old pattern)
                logger.info("[CHAT] Command not available, using message-based HITL")

                # Keep messages as-is, only set user_clarification
                state = {
                    "messages": messages,
                    "user_clarification": request.message,
                    "waiting_for_user_input": False,
                    "pending_question": hitl_pending,
                }

            # Clear HITL state
            self._clear_hitl_state(request.session_id)

        else:
            # Normal message — send ONLY the new message to graph.
            # MemorySaver checkpointer (keyed by session_id/thread_id) already
            # retains full conversation history. Sending all messages causes
            # the add_messages reducer to re-process N messages instead of 1.
            new_message = {"role": "user", "content": request.message}
            state = {"messages": [new_message]}

            logger.info(f"[CHAT] Normal message received: {request.message[:50]}...")

        # Prepare adapter kwargs (e.g., token for VegaForza)
        adapter_kwargs = {}
        if session.get("token"):
            adapter_kwargs["token"] = session["token"]

        # Pass session_id as thread_id for LangGraph conversation persistence
        adapter_kwargs["thread_id"] = request.session_id

        # Get full graph output with all messages (including agent responses)
        # Only invoke graph ONCE - this is the source of truth
        try:
            graph_output = await self.chatbot.get_graph_output_async(state, **adapter_kwargs)
        except GraphInterrupt as e:
            logger.debug(f"[CHAT] === GraphInterrupt CAUGHT ===")
            logger.debug(f"[CHAT] e.args type={type(e.args)}, len={len(e.args) if e.args else 0}")
            if e.args:
                logger.debug(f"[CHAT] e.args[0] type={type(e.args[0])}, repr={repr(e.args[0])[:500]}")
                if e.args[0]:
                    first = e.args[0][0] if hasattr(e.args[0], '__getitem__') else e.args[0]
                    logger.debug(f"[CHAT] first interrupt type={type(first)}, hasattr value={hasattr(first, 'value')}")
                    if hasattr(first, 'value'):
                        logger.debug(f"[CHAT] first.value={repr(first.value)[:500]}")
            # Graph interrupted (e.g., report agent needs clarification via interrupt())
            # Extract interrupt data and return as HITL question
            interrupts = e.args[0] if e.args else []
            interrupt_data = interrupts[0].value if interrupts else {}
            logger.info(f"[CHAT] GraphInterrupt caught — HITL question: {interrupt_data}")

            interrupt_type = interrupt_data.get("type", "choice")
            hitl_info = {
                "type": interrupt_type,
                "question": interrupt_data.get("question", "Açıklama gerekiyor"),
                "options": interrupt_data.get("options", []),
                "context": interrupt_data.get("context", ""),
            }
            self._store_hitl_state(request.session_id, hitl_info)

            question_text = hitl_info["question"]
            options = hitl_info["options"]
            context = hitl_info.get("context", "")

            if options:
                options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
                full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
            else:
                full_text = f"❓ {question_text}"
            if context:
                full_text += f"\n\nℹ️ {context}"

            response_data = ResponseData(
                text=full_text,
                type="question",
                confidence=0.9,
                action=ActionResponse(
                    type="hitl",
                    target="",
                    params={
                        "type": interrupt_type,
                        "question": question_text,
                        "options": options,
                        "context": context,
                    },
                ),
            )

            return ChatMessageResponse(
                session_id=request.session_id,
                timestamp=datetime.now(),
                response=response_data,
            )

        # Extract all messages from graph output and persist to session
        # This ensures all agent-generated messages are saved
        graph_messages = graph_output.get("messages", [])
        if graph_messages:
            session["messages"] = graph_messages
        else:
            # Fallback: just keep the messages we have
            session["messages"] = messages

        # Check for HITL question in graph output (state-based fallback)
        hitl_info = self._detect_hitl_question(graph_output)
        if hitl_info:
            # Store HITL state for next message
            self._store_hitl_state(request.session_id, hitl_info)

            # Build HITL response
            question_text = hitl_info["question"]
            options = hitl_info["options"]
            context = hitl_info.get("context", "")

            # Format options for display
            options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
            full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
            if context:
                full_text += f"\n\nℹ️ {context}"

            response_data = ResponseData(
                text=full_text,
                type="question",
                confidence=0.9,
                action=ActionResponse(
                    type="hitl",
                    target="",
                    params={
                        "question": question_text,
                        "options": options,
                        "context": context
                    }
                )
            )

            return ChatMessageResponse(
                session_id=request.session_id,
                timestamp=datetime.now(),
                response=response_data
            )

        # Extract text response from graph output (last message)
        # Don't invoke graph again - use the output we already have
        bot_response_text = self.chatbot._from_graph_state(graph_output)

        # Only scan CURRENT TURN messages for detection (not full history)
        # graph_messages contains ALL turns from MemorySaver; scanning all of them
        # causes false positives from previous turns' chart_html or URLs.
        current_turn_msgs = self._get_current_turn_messages(graph_messages)

        # Detect if this is a routing/navigation response
        routing_info = self._detect_routing_response(current_turn_msgs)

        # Detect if this is a report/visualization response
        report_info = self._detect_report_response(current_turn_msgs)

        # Build response based on what was detected (priority: routing > report > text)
        if routing_info:
            # Navigation response with special format
            response_data = ResponseData(
                text=bot_response_text,
                type="navigation",
                confidence=0.85,
                action=ActionResponse(
                    type="routing",
                    target=routing_info["url"],
                    params={}
                )
            )
        elif report_info:
            # Report/visualization response with special format
            response_data = ResponseData(
                text=report_info["text"] or "Grafik oluşturuldu",
                type="report",
                confidence=0.85,
                action=ActionResponse(
                    type="chart",
                    target=report_info["html"],
                    params={}
                )
            )
        else:
            # Regular text response
            response_data = ResponseData(
                text=bot_response_text,
                type="text",
                confidence=0.95,
                action=ActionResponse(
                    type="none",
                    target="",
                    params={}
                )
            )

        return ChatMessageResponse(
            session_id=request.session_id,
            timestamp=datetime.now(),
            response=response_data
        )

    async def send_message_async(self, request: ChatMessageRequest) -> ChatMessageResponse:
        """
        Async wrapper for send_message (alias for compatibility)

        Args:
            request: ChatMessageRequest with session_id and message

        Returns:
            ChatMessageResponse with bot response
        """
        return await self.send_message(request)

    def _filter_messages_by_format(self, messages: list) -> list:
        """
        Filter messages based on LAST_MESSAGE_ONLY format.

        For consecutive assistant messages, keeps only the last one in the group.
        Keeps all other messages (tool, user, system) as-is.
        Maintains original order in conversation.

        Example: [user, asst, asst, asst, tool, asst] → [user, asst, tool, asst]

        Args:
            messages: List of MessageHistoryItem objects

        Returns:
            Filtered list of messages
        """
        if not messages:
            return messages

        filtered = []
        i = 0

        while i < len(messages):
            msg = messages[i]

            # If current message is assistant, check for consecutive assistant messages
            if msg.role == "assistant":
                # Find the end of consecutive assistant messages
                j = i + 1
                while j < len(messages) and messages[j].role == "assistant":
                    j += 1

                # Keep only the last assistant message in this group (at index j-1)
                filtered.append(messages[j - 1])
                i = j
            else:
                # Keep all non-assistant messages
                filtered.append(msg)
                i += 1

        return filtered

    def _parse_message(self, msg) -> tuple:
        """
        Parse message from dict or LangChain message object.

        Handles both:
        - Dict format: {"role": "...", "content": "..."}
        - LangChain objects: HumanMessage, AIMessage, etc.

        Returns:
            Tuple of (role, content)
        """
        if isinstance(msg, dict):
            return msg.get("role", "unknown"), msg.get("content", "")

        # Handle LangChain message objects
        msg_type = getattr(msg, "type", None)

        # Map LangChain message types to role names
        type_to_role = {
            "human": "user",
            "ai": "assistant",
            "tool": "tool",
            "system": "system"
        }

        role = type_to_role.get(msg_type, msg_type or "unknown")
        content = getattr(msg, "content", "")

        return role, content

    def _get_current_turn_messages(self, messages: list) -> list:
        """Extract only messages from the current turn (after last user message)."""
        for i in range(len(messages) - 1, -1, -1):
            role, _ = self._parse_message(messages[i])
            if role == "user":
                return messages[i:]
        return messages

    async def get_session_history(self, session_id: str) -> SessionHistoryResponse:
        """
        Get chat history for a session

        Respects session settings for response format:
        - ALL_MESSAGES: Returns all messages
        - LAST_MESSAGE_ONLY: Returns all tool messages + only the last assistant message

        Args:
            session_id: Session identifier

        Returns:
            SessionHistoryResponse with message history

        Raises:
            ValueError: If session not found
        """
        # Check if session exists
        if not self.session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        # Get session data
        session = self.get_session(session_id)

        # Convert messages to MessageHistoryItem format
        # Handles both dict and LangChain message objects
        messages = []
        for msg in session.get("messages", []):
            role, content = self._parse_message(msg)
            messages.append(MessageHistoryItem(role=role, content=content))

        # Apply response format filtering if needed
        response_format = session.get("settings", {}).get("response_format", ResponseFormat.ALL_MESSAGES)

        if response_format == ResponseFormat.LAST_MESSAGE_ONLY:
            messages = self._filter_messages_by_format(messages)

        return SessionHistoryResponse(
            session_id=session_id,
            user_id=session.get("user_id"),
            created_at=session.get("created_at"),
            message_count=len(messages),
            messages=messages
        )

    async def get_history_async(self, session_id: str) -> SessionHistoryResponse:
        """
        Async wrapper for get_session_history (alias for compatibility)

        Args:
            session_id: Session identifier

        Returns:
            SessionHistoryResponse with message history
        """
        return await self.get_session_history(session_id)

    def clear_conversation(self, session_id: str) -> int:
        """
        Clear conversation history for a session

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared

        Raises:
            ValueError: If session not found
        """
        if not self.session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        session = self.get_session(session_id)
        cleared_count = len(session.get("messages", []))
        session["messages"] = []
        return cleared_count

    async def clear_history_async(self, session_id: str) -> int:
        """
        Async wrapper for clear_conversation (alias for compatibility)

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared
        """
        return self.clear_conversation(session_id)

    def get_session_stats(self) -> dict:
        """
        Get session statistics.

        Returns:
            Dictionary with session stats
        """
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len([s for s in self.sessions.values() if s.get("messages")])
        }

    def get_conversation_stats(self) -> dict:
        """
        Get conversation statistics.

        Returns:
            Dictionary with conversation stats
        """
        total_messages = sum(len(s.get("messages", [])) for s in self.sessions.values())
        return {
            "total_conversations": len(self.sessions),
            "total_messages": total_messages
        }

    def get_assistant_config(self) -> dict:
        """
        Get assistant configuration.

        Returns:
            Dictionary with assistant config
        """
        return {
            "assistant_name": "Forza Chatbot",
            "version": "2.0"
        }

    def list_sessions(self) -> list:
        """
        Get list of all sessions with their metadata.

        Returns:
            List of session dictionaries containing session_id, created_at, and message_count
        """
        sessions_list = []
        for session_id, session_data in self.sessions.items():
            sessions_list.append({
                "session_id": session_id,
                "created_at": session_data.get("created_at"),
                "user_id": session_data.get("user_id"),
                "message_count": len(session_data.get("messages", []))
            })

        # Sort by creation time (newest first)
        sessions_list.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
        return sessions_list

    async def create_new_session(self, user_id: Optional[str] = None) -> SessionStartResponse:
        """
        Create a new chat session.

        Args:
            user_id: Optional user identifier

        Returns:
            SessionStartResponse with session_id and metadata
        """
        request = SessionStartRequest(user_id=user_id, token=None)
        return await self.start_session(request)
