# main.py
"""
Main entry point for Forza Chatbot application.

Supports multiple interfaces: CLI, Gradio, API, and FastAPI.
"""

import asyncio
import argparse
import uuid
from src.api.services.chat_service import ChatService
from src.interfaces.gradio_interface import GradioInterface
from src.services.config_loader import ConfigLoader
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory
from src.builders.chatbot_builder import ChatbotBuilder

from src.interfaces.cli_interface import CLIInterface
from src.interfaces.fastapi_interface import FastAPIInterface
from src.interfaces.flask_interface import run_flask


def build_chatbot(config_path: str, entrypoint_function: str = None, session_id: str = None):
    """
    Build chatbot instance with configuration.

    Args:
        config_path: Path to configuration YAML file
        entrypoint_function: Override graph type from config
        session_id: Optional session ID to use as thread_id. If not provided, generates new UUID

    Returns:
        Configured Chatbot instance
    """
    # Load configuration
    config = ConfigLoader.load_config(config_path)

    # Create dependency factories - handles all dependency creation and injection
    dependency_factory = DependencyFactory()
    adapter_factory = AdapterFactory()

    # Get LLM and graph configurations
    llm_config = config.llm
    graph_type = entrypoint_function if entrypoint_function else config.chatbot.graph_type

    # Generate session_id (thread_id) - use provided session_id or generate new UUID
    thread_id = session_id if session_id else str(uuid.uuid4())

    # Build chatbot using dependency injection factories
    chatbot = (
        ChatbotBuilder(dependency_factory, adapter_factory)
        .with_model(llm_config.model, llm_config.temperature, llm_config.api_key)
        .with_graph(graph_type)
        .with_graph_config({"configurable": {"thread_id": thread_id}})
        .with_assistant_configuration(getattr(config, 'sql_agent_configuration', None))
        .build()
    )
    return chatbot


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", choices=["cli", "gradio", "api","fastapi","gradio_refactored"], default="gradio",
                        help="Choose the interface to run the chatbot: cli, gradio, or api")

    parser.add_argument("--config", type=str, default="config/config.yaml",
                        help="Path to the configuration YAML file")
    
    parser.add_argument("--entrypoint", type=str, default=None,
                        help="Entrypoint function name to use (overrides config graph_type)")

    args = parser.parse_args()

    chatbot = build_chatbot(args.config, args.entrypoint)

    if args.interface == "cli":
        chat_service = ChatService(chatbot=chatbot)
        interface = CLIInterface(chat_service=chat_service)
        asyncio.run(interface.run())
    elif args.interface == "gradio":
        chat_service = ChatService(chatbot=chatbot)
        interface = GradioInterface(chat_service=chat_service)
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