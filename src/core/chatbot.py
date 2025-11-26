"""
Chatbot - Single Responsibility: Generic message sending and session management.

Single Responsibility:
- Generic message processing
- Graph orchestration
- Adapter-based state transformation

Interface-specific handling moved to interface adapters (GradioAdapter, etc).
"""

from typing import Optional, List, Dict, Any
import asyncio
from src.core.exceptions.chatbot_exception import AdapterException, StateAdaptationException
from src.graphs.base_graph import BaseGraph
from src.models.llm import LLM
from src.core.exceptions import (
    ConfigurationException,
    MessageProcessingException,
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
)


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
        assistant_config: dict = None
    ):
        """
        Initialize chatbot.

        Args:
            llm: Language model instance
            graph: LangGraph instance
            config: Graph configuration
            assistant_config: Assistant-specific configuration
        """
        self.llm = llm
        self.graph = graph
        self.config = config if config else {}
        self.assistant_config = assistant_config if assistant_config else {}

    def _prepare_config(self, thread_id: str = None) -> dict:
        """
        Prepare full configuration with assistant_config and thread_id.

        DRY: Extracted common config preparation logic.

        Args:
            thread_id: Optional thread ID for graph execution (session_id)

        Raises:
            ConfigurationException: If config preparation fails

        Returns:
            Full config dict with configurable section
        """
        try:
            assistant_config_dict = (
                self.assistant_config.to_dict()
                if hasattr(self.assistant_config, 'to_dict')
                else self.assistant_config
            )

            if not isinstance(self.config, dict):
                raise ConfigurationException(
                    "Config must be a dictionary",
                    context={"config_type": type(self.config).__name__}
                )

            full_config = self.config.copy()
            if "configurable" not in full_config:
                full_config["configurable"] = {}
            full_config["configurable"]["assistant_config"] = assistant_config_dict

            # Add thread_id if provided (use session_id as thread_id)
            if thread_id:
                full_config["configurable"]["thread_id"] = thread_id

            return full_config
        except ConfigurationException:
            raise
        except Exception as e:
            raise ConfigurationException(
                f"Failed to prepare configuration: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def _to_graph_state(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Convert messages to standard graph state format.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            State dict with messages key
        """
        return {"messages": messages}

    def _from_graph_state(self, graph_output: Any) -> str:
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
        text_response = self._from_graph_state(graph_output)

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
        except (InvalidGraphStateException, ConfigurationException):
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

            graph_state = self._to_graph_state(messages)
            # Extract thread_id from adapter_kwargs if provided
            thread_id = adapter_kwargs.get('thread_id')
            return self._invoke_graph(graph_state, thread_id=thread_id)
        except (MessageProcessingException, ConfigurationException, GraphExecutionException):
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
            response_text = self._from_graph_state(graph_output)
            return response_text
        except (MessageProcessingException, GraphExecutionException, ConfigurationException):
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
            if not isinstance(graph_state, dict):
                raise InvalidGraphStateException(
                    "Graph state must be a dictionary",
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
            return graph_output
        except (InvalidGraphStateException, ConfigurationException):
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

            graph_state = self._to_graph_state(messages)
            thread_id = adapter_kwargs.get('thread_id')
            return await self._invoke_graph_async(graph_state, thread_id=thread_id)
        except (MessageProcessingException, ConfigurationException, GraphExecutionException):
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
            response_text = self._from_graph_state(graph_output)
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