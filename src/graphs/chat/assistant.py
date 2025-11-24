"""
Chat Assistant - Runnable Wrapper with Tool Execution.

Manages interactions with chat runnable, executes tools, and ensures valid responses.
"""

import asyncio
import inspect
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage

from .state import ChatState
from .tools import CHAT_TOOLS


class ChatAssistant:
    """
    Manages interactions with a runnable and ensures valid responses.

    Invokes the runnable, executes tools if called, and validates responses.
    If response is invalid (no content and no tool calls), retries with prompt.

    Attributes:
        runnable (Runnable): The runnable instance for chat processing.
        tools (dict): Mapping of tool names to tool functions.

    Methods:
        __call__(state: ChatState, config: RunnableConfig) -> dict:
            Invokes runnable with tool execution and returns result with messages.
    """

    def __init__(self, runnable: Runnable):
        """
        Initialize ChatAssistant with a runnable.

        Args:
            runnable (Runnable): The runnable instance to invoke.
        """
        self.runnable = runnable
        # Create tool mapping for execution
        self.tools = {tool.name: tool for tool in CHAT_TOOLS}

    async def __call__(self, state: ChatState, config: RunnableConfig = None):
        """
        Execute the runnable with tool execution and validation.

        Invokes runnable, executes tools if called, and validates response.
        If invalid (no content and no tool_calls), retries with prompt.

        Args:
            state (ChatState): Current state with messages.
            config (RunnableConfig): Optional runnable configuration.

        Returns:
            dict: Dictionary with messages including tool results.

        Example:
            result = assistant(state, config)
        """
        messages = list(state.get("messages", []))

        while True:
            # Invoke runnable with current messages
            result = await self.runnable.ainvoke(
                {"messages": messages},
                config=config
            )

            # Add AI response to messages (with tool_calls if any)
            messages.append(result)

            # Execute tools if any tool calls
            if result.tool_calls:
                for tool_call in result.tool_calls:
                    tool_name = tool_call.get("name")
                    tool_input = tool_call.get("args", {})

                    # Execute tool (async or sync)
                    if tool_name in self.tools:
                        try:
                            tool = self.tools[tool_name]
                            # Check if tool has async invoke method
                            if hasattr(tool, 'ainvoke') and callable(getattr(tool, 'ainvoke')):
                                tool_result = await tool.ainvoke(tool_input)
                            elif hasattr(tool, 'invoke') and callable(getattr(tool, 'invoke')):
                                # Check if invoke is async
                                invoke_method = getattr(tool, 'invoke')
                                if inspect.iscoroutinefunction(invoke_method):
                                    tool_result = await invoke_method(tool_input)
                                else:
                                    # Run sync invoke in executor
                                    loop = asyncio.get_event_loop()
                                    tool_result = await loop.run_in_executor(
                                        None,
                                        invoke_method,
                                        tool_input
                                    )
                            else:
                                tool_result = "Tool has no invoke method"
                            tool_result_str = str(tool_result)
                        except Exception as e:
                            tool_result_str = f"Error executing tool: {str(e)}"
                    else:
                        tool_result_str = f"Tool '{tool_name}' not found"

                    # Add tool result to messages
                    messages.append(
                        ToolMessage(
                            content=tool_result_str,
                            tool_call_id=tool_call.get("id", tool_name)
                        )
                    )

                # Continue loop to get final response after tool execution
                continue

            # No tool calls - validate response content
            if not result.content or (
                isinstance(result.content, list)
                and (len(result.content) == 0 or not result.content[0].get("text"))
            ):
                # Invalid response - update state with retry prompt
                messages.append(HumanMessage(content="Respond with a real output."))
            else:
                # Valid response - break loop
                break

        return {"messages": messages}
