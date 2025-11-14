"""
Chatbot - Single Responsibility: Generic message sending and session management.

Single Responsibility:
- Generic message processing
- Graph orchestration
- Adapter-based state transformation

Interface-specific handling moved to interface adapters (GradioAdapter, etc).
"""

from typing import Optional
import asyncio
from src.graphs.base_graph import BaseGraph
from src.models.models import LLM
from src.adapters.base_state_adapter import BaseStateAdapter
from src.adapters.default_state_adapter import DefaultStateAdapter
from src.core.exceptions import (
    ConfigurationException,
    MessageProcessingException,
    MessageExtractionException,
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
    AdapterException,
    StateAdaptationException,
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
        assistant_config: dict = None,
        adapter: Optional[BaseStateAdapter] = None
    ):
        """
        Initialize chatbot.

        Args:
            llm: Language model instance
            graph: LangGraph instance
            config: Graph configuration
            assistant_config: Assistant-specific configuration
            adapter: State adapter for graph transformation
        """
        self.llm = llm
        self.graph = graph
        self.config = config if config else {}
        self.assistant_config = assistant_config if assistant_config else {}
        # Use provided adapter or default to DefaultStateAdapter
        self.adapter = adapter if adapter else DefaultStateAdapter()

    def _prepare_config(self) -> dict:
        """
        Prepare full configuration with assistant_config.

        DRY: Extracted common config preparation logic.

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
            return full_config
        except ConfigurationException:
            raise
        except Exception as e:
            raise ConfigurationException(
                f"Failed to prepare configuration: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def _invoke_graph(self, graph_state: dict) -> dict:
        """
        Invoke graph with prepared configuration.

        DRY: Extracted common graph invocation logic.

        Args:
            graph_state: State prepared by adapter

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

            full_config = self._prepare_config()
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
            **adapter_kwargs: Additional adapter parameters

        Raises:
            MessageProcessingException: If messages extraction fails
            StateAdaptationException: If state adaptation fails

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

            graph_state = self.adapter.to_graph_state(messages, **adapter_kwargs)
            return self._invoke_graph(graph_state)
        except (MessageProcessingException, StateAdaptationException, ConfigurationException, GraphExecutionException):
            raise
        except Exception as e:
            raise MessageProcessingException(
                f"Failed to process message: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def send(self, state: dict, **adapter_kwargs) -> str:
        """
        Generic message sending for all interfaces.

        SRP: Delegates interface-specific formatting to adapter.
        If adapter implements send(), uses that. Otherwise uses from_graph_state().

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters (token, etc)

        Raises:
            MessageProcessingException: If message processing fails
            StateAdaptationException: If state adaptation fails
            AdapterException: If adapter operation fails

        Returns:
            String response
        """
        try:
            # SRP: Let adapter handle interface-specific formatting if it can
            if hasattr(self.adapter, 'send'):
                return self.adapter.send(state, **adapter_kwargs)

            # Fallback: Use standard processing pipeline
            graph_output = self._process_message(state, **adapter_kwargs)
            response_text = self.adapter.from_graph_state(graph_output)
            return response_text
        except (MessageProcessingException, StateAdaptationException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise AdapterException(
                f"Failed to send message: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    def send_structured(self, state: dict, **adapter_kwargs) -> dict:
        """
        Structured response for API/programmatic use.

        SRP: Delegates interface-specific formatting to adapter.
        If adapter implements send_structured(), uses that.
        Otherwise tries to_api_response(), with fallback formatting.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters

        Raises:
            MessageProcessingException: If message processing fails
            StateAdaptationException: If state adaptation fails
            AdapterException: If adapter operation fails

        Returns:
            Dict with text, type, confidence, action, metadata
        """
        try:
            # SRP: Let adapter handle interface-specific formatting if it can
            if hasattr(self.adapter, 'send_structured'):
                return self.adapter.send_structured(state, **adapter_kwargs)

            # Process message through adapter and graph
            graph_output = self._process_message(state, **adapter_kwargs)

            # Use adapter's to_api_response if available
            if hasattr(self.adapter, 'to_api_response'):
                return self.adapter.to_api_response(graph_output)
            else:
                # Fallback: Create standard structured response
                response_text = self.adapter.from_graph_state(graph_output)
                return {
                    "text": response_text,
                    "type": "text",
                    "confidence": 0.95,
                    "action": {"type": "none", "target": "", "params": {}}
                }
        except (MessageProcessingException, StateAdaptationException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise AdapterException(
                f"Failed to send structured message: {str(e)}",
                context={"original_error": str(e)}
            ) from e

    # Async versions of above methods for non-blocking execution
    async def _invoke_graph_async(self, graph_state: dict) -> dict:
        """
        Async version of graph invocation.

        Uses graph.ainvoke() if available, otherwise runs blocking graph.invoke() in executor.

        Args:
            graph_state: State prepared by adapter

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

            full_config = self._prepare_config()

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
            **adapter_kwargs: Additional adapter parameters

        Raises:
            MessageProcessingException: If messages extraction fails
            StateAdaptationException: If state adaptation fails

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

            # Use async adapter method if available
            graph_state = await self.adapter.to_graph_state_async(messages, **adapter_kwargs)
            return await self._invoke_graph_async(graph_state)
        except (MessageProcessingException, StateAdaptationException, ConfigurationException, GraphExecutionException):
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
            StateAdaptationException: If state adaptation fails
            AdapterException: If adapter operation fails

        Returns:
            String response
        """
        try:
            # SRP: Let adapter handle interface-specific formatting if it can
            if hasattr(self.adapter, 'send') and callable(getattr(self.adapter, 'send')):
                # Check if adapter's send is async
                import inspect
                send_method = getattr(self.adapter, 'send')
                if inspect.iscoroutinefunction(send_method):
                    return await send_method(state, **adapter_kwargs)
                else:
                    # Run sync send in executor
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None,
                        send_method,
                        state,
                        adapter_kwargs
                    )

            # Fallback: Use standard async processing pipeline
            graph_output = await self._process_message_async(state, **adapter_kwargs)
            response_text = await self.adapter.from_graph_state_async(graph_output)
            return response_text
        except (MessageProcessingException, StateAdaptationException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise AdapterException(
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
            StateAdaptationException: If state adaptation fails
            AdapterException: If adapter operation fails

        Returns:
            Dict with text, type, confidence, action, metadata
        """
        try:
            # SRP: Let adapter handle interface-specific formatting if it can
            if hasattr(self.adapter, 'send_structured') and callable(getattr(self.adapter, 'send_structured')):
                import inspect
                send_structured_method = getattr(self.adapter, 'send_structured')
                if inspect.iscoroutinefunction(send_structured_method):
                    return await send_structured_method(state, **adapter_kwargs)
                else:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None,
                        send_structured_method,
                        state,
                        adapter_kwargs
                    )

            # Process message through adapter and graph
            graph_output = await self._process_message_async(state, **adapter_kwargs)

            # Use adapter's to_api_response if available
            if hasattr(self.adapter, 'to_api_response'):
                return self.adapter.to_api_response(graph_output)
            else:
                # Fallback: Create standard structured response
                response_text = await self.adapter.from_graph_state_async(graph_output)
                return {
                    "text": response_text,
                    "type": "text",
                    "confidence": 0.95,
                    "action": {"type": "none", "target": "", "params": {}}
                }
        except (MessageProcessingException, StateAdaptationException, GraphExecutionException, ConfigurationException):
            raise
        except Exception as e:
            raise AdapterException(
                f"Failed to send structured message asynchronously: {str(e)}",
                context={"original_error": str(e)}
            ) from e