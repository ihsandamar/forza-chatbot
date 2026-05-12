"""
Chatbot - Single Responsibility: Generic message sending and session management.

Single Responsibility:
- Generic message processing
- Graph orchestration
- Adapter-based state transformation
- Runtime agent settings management (system_prompt, token per sub-agent)

Interface-specific handling moved to interface adapters (GradioAdapter, etc).
"""

from typing import Optional, List, Dict, Any
import asyncio
from langgraph.errors import GraphInterrupt, GraphBubbleUp
from langgraph.types import Command
from src.graphs.base.base_graph import BaseGraph
from src.models.llm import LLM
from src.core.exceptions import (
    ConfigurationException,
    MessageProcessingException,
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
)
from src.core.runtime_agent_settings import RuntimeAgentSettings


class Chatbot:
    """
    Generic chatbot for message processing and graph orchestration.

    Single Responsibility: Generic message sending, NOT interface-specific logic.
    Interface adapters handle Gradio, API, CLI-specific formatting.
    """

    def __init__(
        self,
        llm: LLM,
        graph: BaseGraph,
        config: dict = None,
        runtime_agent_settings: Optional[RuntimeAgentSettings] = None,
    ):
        """
        Initialize chatbot.

        Args:
            llm: Language model instance
            graph: LangGraph instance
            config: Graph configuration
            runtime_agent_settings: Sub-agent runtime settings (system_prompt, token)
        """
        self.llm = llm
        self.graph = graph
        self.config = config if config else {}
        self.runtime_agent_settings = runtime_agent_settings

    def _prepare_config(self, thread_id: str = None) -> dict:
        """
        Prepare full configuration for graph invocation.

        Merges runtime_agent_settings as flat keys into configurable so nodes can read:
            config["configurable"]["routing_token"]
            config["configurable"]["routing_system_prompt"]

        Args:
            thread_id: Session ID — overrides base config thread_id when provided

        Raises:
            ConfigurationException: If config preparation fails

        Returns:
            Full config dict with configurable section
        """
        try:
            if not isinstance(self.config, dict):
                raise ConfigurationException(
                    "Config must be a dictionary",
                    context={"config_type": type(self.config).__name__}
                )
            configurable = dict(self.config.get("configurable", {}))
            if self.runtime_agent_settings:
                configurable.update(self.runtime_agent_settings.to_graph_configurable())
            if thread_id:
                configurable["thread_id"] = thread_id
            return {**self.config, "configurable": configurable}
        except ConfigurationException:
            raise
        except Exception as e:
            raise ConfigurationException(
                f"Failed to prepare configuration: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def extract_response(self, graph_output: Any) -> str:
        """
        Extract response from message-based graph output.

        Args:
            graph_output: Graph output with 'messages' key

        Returns:
            Content of the last assistant message
        """
        if not isinstance(graph_output, dict):
            return str(graph_output)

        messages = graph_output.get("messages", [])
        if not messages:
            return "Bir hata oluştu, lütfen tekrar deneyin."

        # Get last message
        last_message = messages[-1]

        # Handle both dict format and LangChain message objects
        if hasattr(last_message, "content"):
            return last_message.content

        if isinstance(last_message, dict):
            return last_message.get("content", "")

        return str(last_message)

    def _to_api_response(self, graph_output: Any) -> Dict[str, Any]:
        """
        Convert graph output to API response format.

        Args:
            graph_output: Graph output with 'messages' key

        Returns:
            API-friendly response dict
        """
        text_response = self.extract_response(graph_output)

        return {
            "text": text_response,
            "type": "text",
            "confidence": 0.95,
            "action": {"type": "none", "target": "", "params": {}},
        }

    def _invoke_graph(self, graph_state: dict, thread_id: str = None) -> dict:
        """
        Invoke graph with prepared configuration.

        DRY: Extracted common graph invocation logic.

        Args:
            graph_state: State prepared by adapter
            thread_id: Optional thread ID (session_id) for graph execution

        Raises:
            InvalidGraphStateException: If graph state is invalid
            GraphInvocationException: If graph invocation fails

        Returns:
            Graph output
        """
        try:
            if not isinstance(graph_state, dict):
                raise InvalidGraphStateException(
                    "Graph state must be a dictionary",
                    state_type=type(graph_state).__name__
                )

            full_config = self._prepare_config(thread_id=thread_id)
            graph_output = self.graph.invoke(graph_state, config=full_config)

            return graph_output
        except (InvalidGraphStateException, ConfigurationException, GraphInterrupt, GraphBubbleUp):
            raise
        except Exception as e:
            raise GraphInvocationException(
                f"Failed to invoke graph: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def _process_message(self, state: dict, **adapter_kwargs) -> dict:
        """
        Common message processing logic.

        DRY: Extracted repeated message processing from send() and send_structured().

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional parameters (including thread_id)

        Raises:
            MessageProcessingException: If messages extraction fails

        Returns:
            Graph output
        """
        try:
            if not isinstance(state, dict):
                raise MessageProcessingException(
                    "State must be a dictionary",
                    context={"state_type": type(state).__name__}
                )

            messages = state.get("messages", [])
            if not isinstance(messages, list):
                raise MessageProcessingException(
                    "Messages must be a list",
                    context={"messages_type": type(messages).__name__}
                )

            if not messages:
                raise MessageProcessingException(
                    "Messages list is empty",
                    context={"message_count": 0}
                )

            # Pass state directly — chat_service already builds correct structure
            graph_state = state

            # Add token to graph state if provided in adapter_kwargs
            if 'token' in adapter_kwargs:
                graph_state['token'] = adapter_kwargs['token']

            # Extract thread_id from adapter_kwargs if provided
            thread_id = adapter_kwargs.get('thread_id')
            return self._invoke_graph(graph_state, thread_id=thread_id)
        except (MessageProcessingException, ConfigurationException, GraphExecutionException, GraphInterrupt, GraphBubbleUp):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to process message: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def send(self, state: dict, **adapter_kwargs) -> str:
        """
        Generic message sending for all interfaces.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional parameters (token, thread_id, etc)

        Raises:
            MessageProcessingException: If message processing fails
            GraphExecutionException: If graph execution fails
            ConfigurationException: If configuration is invalid

        Returns:
            String response
        """
        try:
            graph_output = self._process_message(state, **adapter_kwargs)
            response_text = self.extract_response(graph_output)
            return response_text
        except (MessageProcessingException, GraphExecutionException, ConfigurationException, GraphInterrupt, GraphBubbleUp):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to send message: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def send_structured(self, state: dict, **adapter_kwargs) -> dict:
        """
        Structured response for API/programmatic use.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional parameters (token, thread_id, etc)

        Raises:
            MessageProcessingException: If message processing fails
            GraphExecutionException: If graph execution fails
            ConfigurationException: If configuration is invalid

        Returns:
            Dict with text, type, confidence, action, metadata
        """
        try:
            graph_output = self._process_message(state, **adapter_kwargs)
            return self._to_api_response(graph_output)
        except (MessageProcessingException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to send structured message: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    # Async versions of above methods for non-blocking execution
    async def _invoke_graph_async(self, graph_state: dict, thread_id: str = None) -> dict:
        """
        Async version of graph invocation.

        Uses graph.ainvoke() if available, otherwise runs blocking graph.invoke() in executor.

        Args:
            graph_state: State prepared by adapter
            thread_id: Optional thread ID (session_id) for graph execution

        Raises:
            InvalidGraphStateException: If graph state is invalid
            GraphInvocationException: If graph invocation fails

        Returns:
            Graph output
        """
        try:
            # Command(resume=...) for HITL graph resumption — skip dict validation
            if not isinstance(graph_state, (dict, Command)):
                raise InvalidGraphStateException(
                    "Graph state must be a dictionary or Command",
                    state_type=type(graph_state).__name__
                )

            full_config = self._prepare_config(thread_id=thread_id)

            # Use async invoke if available
            if hasattr(self.graph, 'ainvoke') and callable(getattr(self.graph, 'ainvoke')):
                graph_output = await self.graph.ainvoke(graph_state, config=full_config)
            else:
                # Fall back to running blocking invoke in executor
                loop = asyncio.get_event_loop()
                graph_output = await loop.run_in_executor(
                    None,
                    self.graph.invoke,
                    graph_state,
                    full_config
                )

            # Subgraphs compiled with checkpointer=True swallow interrupt() — the parent's
            # ainvoke returns normally and stores the interrupt value under '__interrupt__'.
            # Re-raise as GraphInterrupt so chat_service's existing handler fires correctly.
            pending_interrupts = graph_output.get('__interrupt__') if isinstance(graph_output, dict) else None
            if pending_interrupts:
                raise GraphInterrupt(tuple(pending_interrupts))

            return graph_output
        except (InvalidGraphStateException, ConfigurationException, GraphInterrupt, GraphBubbleUp):
            raise
        except Exception as e:
            raise GraphInvocationException(
                f"Failed to invoke graph asynchronously: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    async def _process_message_async(self, state: dict, **adapter_kwargs) -> dict:
        """
        Async version of common message processing logic.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional parameters (including thread_id)

        Raises:
            MessageProcessingException: If messages extraction fails

        Returns:
            Graph output
        """
        try:
            # Command(resume=...) is used to resume an interrupted graph (HITL)
            if isinstance(state, Command):
                thread_id = adapter_kwargs.get('thread_id')
                return await self._invoke_graph_async(state, thread_id=thread_id)

            if not isinstance(state, dict):
                raise MessageProcessingException(
                    "State must be a dictionary",
                    context={"state_type": type(state).__name__}
                )

            messages = state.get("messages", [])
            if not isinstance(messages, list):
                raise MessageProcessingException(
                    "Messages must be a list",
                    context={"messages_type": type(messages).__name__}
                )

            if not messages:
                raise MessageProcessingException(
                    "Messages list is empty",
                    context={"message_count": 0}
                )

            # Pass state directly — chat_service already builds correct structure
            graph_state = state

            # Add token to graph state if provided in adapter_kwargs
            if 'token' in adapter_kwargs:
                graph_state['token'] = adapter_kwargs['token']

            thread_id = adapter_kwargs.get('thread_id')
            return await self._invoke_graph_async(graph_state, thread_id=thread_id)
        except (MessageProcessingException, ConfigurationException, GraphExecutionException, GraphInterrupt, GraphBubbleUp):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to process message asynchronously: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    async def send_async(self, state: dict, **adapter_kwargs) -> str:
        """
        Async version of generic message sending for all interfaces.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters (token, etc)

        Raises:
            MessageProcessingException: If message processing fails
            GraphExecutionException: If graph execution fails
            ConfigurationException: If configuration is invalid

        Returns:
            String response
        """
        try:
            graph_output = await self._process_message_async(state, **adapter_kwargs)
            response_text = self.extract_response(graph_output)
            return response_text
        except (MessageProcessingException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to send message asynchronously: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    async def send_structured_async(self, state: dict, **adapter_kwargs) -> dict:
        """
        Async version of structured response for API/programmatic use.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters

        Raises:
            MessageProcessingException: If message processing fails
            GraphExecutionException: If graph execution fails
            ConfigurationException: If configuration is invalid

        Returns:
            Dict with text, type, confidence, action, metadata
        """
        try:
            graph_output = await self._process_message_async(state, **adapter_kwargs)
            return self._to_api_response(graph_output)
        except (MessageProcessingException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to send structured message asynchronously: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    async def get_graph_output_async(self, state: dict, **adapter_kwargs) -> dict:
        """
        Get full graph output with all messages for session persistence.

        Returns the complete graph output including all messages that were
        processed or generated, allowing the caller to persist the full
        conversation state.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters (token, thread_id, etc)

        Raises:
            MessageProcessingException: If message processing fails
            GraphExecutionException: If graph execution fails
            ConfigurationException: If configuration is invalid

        Returns:
            Dict with "messages" key containing full conversation
        """
        try:
            return await self._process_message_async(state, **adapter_kwargs)
        except (MessageProcessingException, GraphExecutionException, ConfigurationException, GraphInterrupt, GraphBubbleUp):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to get graph output asynchronously: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    async def astream_events_async(
        self,
        state,
        config: dict,
    ):
        """
        Yields raw dicts for SSE streaming:
          {"event_type": "progress", "step": ..., "message": ..., "index": ..., "total": ...}
          {"event_type": "_result_raw", "_graph_output": {...}}
          {"event_type": "result", "text": ..., "type": "question", ..., "_hitl_info": {...}}
          {"event_type": "error", "message": ...}

        Caller (chat_service) converts raw dicts to StreamEvent objects.
        """
        from src.graphs.report_agent.progress_mapper import get_progress_info, TOTAL_STEPS
        from langgraph.errors import GraphInterrupt

        root_run_id = None
        step_counts: dict[str, int] = {}

        try:
            async for event in self.graph.astream_events(state, config=config, version="v2"):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                run_id = event.get("run_id", "")
                parent_ids = event.get("parent_ids", [])

                if root_run_id is None and event_type == "on_chain_start":
                    root_run_id = run_id
                    continue

                if event_type == "on_chain_start" and parent_ids:
                    count = step_counts.get(event_name, 0) + 1
                    step_counts[event_name] = count

                    info = get_progress_info(event_name, count)
                    if info:
                        node_name, message, index = info
                        yield {
                            "event_type": "progress",
                            "step": node_name,
                            "message": message,
                            "index": index,
                            "total": TOTAL_STEPS,
                        }

                elif event_type == "on_chain_end" and run_id == root_run_id:
                    final_output = event.get("data", {}).get("output", {}) or {}

                    pending_interrupts = final_output.get("__interrupt__") if isinstance(final_output, dict) else None
                    if pending_interrupts:
                        interrupt_data = pending_interrupts[0].value if pending_interrupts else {}
                        question_text = interrupt_data.get("question", "Açıklama gerekiyor")
                        options = interrupt_data.get("options", [])
                        context = interrupt_data.get("context", "")
                        interrupt_type = interrupt_data.get("type", "choice")

                        if options:
                            options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
                            full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
                        else:
                            full_text = f"❓ {question_text}"
                        if context:
                            full_text += f"\n\nℹ️ {context}"

                        yield {
                            "event_type": "result",
                            "text": full_text,
                            "type": "question",
                            "confidence": 0.9,
                            "action": {
                                "type": "hitl",
                                "target": "",
                                "params": {
                                    "type": interrupt_type,
                                    "question": question_text,
                                    "options": options,
                                    "context": context,
                                },
                            },
                            "_hitl_info": {
                                "type": interrupt_type,
                                "question": question_text,
                                "options": options,
                                "context": context,
                            },
                        }
                    else:
                        yield {"event_type": "_result_raw", "_graph_output": final_output}

        except GraphInterrupt as e:
            interrupts = e.args[0] if e.args else []
            interrupt_data = interrupts[0].value if interrupts else {}
            question_text = interrupt_data.get("question", "Açıklama gerekiyor")
            options = interrupt_data.get("options", [])
            context = interrupt_data.get("context", "")
            interrupt_type = interrupt_data.get("type", "choice")

            if options:
                options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
                full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
            else:
                full_text = f"❓ {question_text}"
            if context:
                full_text += f"\n\nℹ️ {context}"

            yield {
                "event_type": "result",
                "text": full_text,
                "type": "question",
                "confidence": 0.9,
                "action": {
                    "type": "hitl",
                    "target": "",
                    "params": {
                        "type": interrupt_type,
                        "question": question_text,
                        "options": options,
                        "context": context,
                    },
                },
                "_hitl_info": {
                    "type": interrupt_type,
                    "question": question_text,
                    "options": options,
                    "context": context,
                },
            }

        except Exception as e:
            yield {"event_type": "error", "message": str(e)}

    # ========================================
    # Runtime Settings Management
    # ========================================

    def get_runtime_settings(self) -> Optional[RuntimeAgentSettings]:
        """Get current runtime agent settings."""
        return self.runtime_agent_settings

    def update_runtime_settings(self, new_settings: RuntimeAgentSettings) -> None:
        """Update runtime agent settings (effective on next graph invocation)."""
        self.runtime_agent_settings = new_settings

    def get_config_for_ui(self) -> Dict[str, Any]:
        """Get configuration in UI-friendly format."""
        if self.runtime_agent_settings:
            return {
                "subagents": {
                    name: {
                        "system_prompt": s.system_prompt,
                        "has_token": bool(s.token),
                    }
                    for name, s in self.runtime_agent_settings.subagents.items()
                }
            }
        return {"subagents": {}}
