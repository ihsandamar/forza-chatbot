# main.py
"""
Main entry point for Forza Chatbot application.

Supports multiple interfaces: CLI, Gradio, API, and FastAPI.
"""

import asyncio
import argparse
import uuid
import os
from src.api.services.chat_service import ChatService
from src.interfaces.gradio_interface import GradioInterface
from src.services.config_loader import ConfigLoader
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory
from src.builders.chatbot_builder import ChatbotBuilder
from src.core.runtime_config import (
    RuntimeConfiguration,
    LLMRuntimeConfig
)

from src.interfaces.cli_interface import CLIInterface
from src.interfaces.fastapi_interface import FastAPIInterface
from src.interfaces.flask_interface import run_flask


def build_chatbot(config_path: str, entrypoint_function: str = None, session_id: str = None):
    """
    Build chatbot instance with RuntimeConfiguration.

    Uses dynamic sub-agent detection from AssistantConfiguration metadata.
    No hard-coded graph type checks needed - automatically discovers sub-agents
    from Pydantic Field json_schema_extra metadata.

    Args:
        config_path: Path to configuration YAML file
        entrypoint_function: Override graph type from config
        session_id: Optional session ID to use as thread_id. If not provided, generates new UUID

    Returns:
        Tuple of (Chatbot instance, RuntimeConfiguration instance)
    """
    # Load configuration from file
    config = ConfigLoader.load_config(config_path)

    # Generate session_id (thread_id)
    thread_id = session_id if session_id else str(uuid.uuid4())

    # Determine graph type
    graph_type = entrypoint_function if entrypoint_function else config.chatbot.graph_type

    # Dynamic AssistantConfiguration detection
    assistant_config_class = None
    try:
        # Import AssistantConfiguration based on graph type
        if graph_type == "supervisor":
            from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration
            assistant_config_class = SupervisorAssistantConfiguration
        elif graph_type == "routing":
            from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration
            assistant_config_class = RoutingAssistantConfiguration
        elif graph_type == "chat":
            from src.graphs.chat.assistant_configuration import ChatAssistantConfiguration
            assistant_config_class = ChatAssistantConfiguration
    except ImportError:
        # No AssistantConfiguration for this graph type
        pass

    # Create RuntimeConfiguration with automatic sub-agent detection
    if assistant_config_class:
        # Create instance from class
        assistant_config_instance = assistant_config_class()

        runtime_config = RuntimeConfiguration.from_config_with_assistant(
            config=config,
            assistant_config_instance=assistant_config_instance,
            graph_type=graph_type,
            thread_id=thread_id
        )
        print(f"[OK] Dynamically detected sub-agents: {list(runtime_config.subagents.keys())}")
    else:
        # Fallback: No sub-agents
        runtime_config = RuntimeConfiguration.from_config_loader(
            config=config,
            graph_type=graph_type,
            thread_id=thread_id
        )

    # Create dependency factories
    dependency_factory = DependencyFactory()
    adapter_factory = AdapterFactory()

    # Build chatbot using RuntimeConfiguration
    chatbot = (
        ChatbotBuilder(dependency_factory, adapter_factory)
        .with_runtime_config(runtime_config)
        .with_assistant_configuration(getattr(config, 'sql_agent_configuration', None))
        .build()
    )

    return chatbot, runtime_config


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", choices=["cli", "gradio", "api","fastapi","gradio_refactored"], default="gradio",
                        help="Choose the interface to run the chatbot: cli, gradio, or api")

    parser.add_argument("--config", type=str, default="config/config.yaml",
                        help="Path to the configuration YAML file")
    
    parser.add_argument("--entrypoint", type=str, default=None,
                        help="Entrypoint function name to use (overrides config graph_type)")

    args = parser.parse_args()

    # Build chatbot with runtime configuration
    chatbot, runtime_config = build_chatbot(args.config, args.entrypoint)

    if args.interface == "cli":
        chat_service = ChatService(chatbot=chatbot)
        interface = CLIInterface(chat_service=chat_service)
        asyncio.run(interface.run())
    elif args.interface == "gradio":
        chat_service = ChatService(chatbot=chatbot)
        # Pass runtime_config to Gradio for settings UI
        interface = GradioInterface(
            chat_service=chat_service,
            runtime_config=runtime_config
        )
        interface.run(server_name="0.0.0.0", server_port=7860)
    elif args.interface == "api":
        run_flask(chatbot)
    elif args.interface == "fastapi":
        # Use new FastAPIInterface (Phase 2.2)
        interface = FastAPIInterface(
            chatbot=chatbot,
            title="Forza Chatbot API",
            version="2.0"
        )
        interface.run(host="0.0.0.0", port=8089, reload=False)