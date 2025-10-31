# main.py
import argparse
from src.models.models import LLM
from src.services.config_loader import ConfigLoader
from src.services.container import ServiceContainer
from src.graphs.graph_repository import GraphRepository
from src.builders.chatbot_builder import ChatbotBuilder

from src.interfaces.cli_interface import run_cli
from src.interfaces.gradio_interface_v2 import GradioInterface
from src.interfaces.fastapi_interface import FastAPIInterface
from src.interfaces.flask_interface import run_flask


def build_chatbot(config_path: str, entrypoint_function: str = None):

    config = ConfigLoader.load_config(config_path)

    container = ServiceContainer()

    llm_config = config.llm
    container.register("llm", lambda: LLM(
        model=llm_config.model,
        temperature=llm_config.temperature,
        api_key=llm_config.api_key
    ))

    container.register("graph_repo", lambda: GraphRepository(container.resolve("llm")))

    # Determine graph type: use parameter if provided, otherwise fall back to config
    graph_type = entrypoint_function if entrypoint_function else config.chatbot.graph_type

    # 🔹 Chatbot oluşturuluyor
    chatbot = (
        ChatbotBuilder(container)
        .with_model(llm_config.model, llm_config.temperature, llm_config.api_key)
        .with_graph(graph_type)
        .with_graph_config({"configurable": {"thread_id": config.chatbot.thread_id}})
        .with_assistant_configuration(getattr(config, 'sql_agent_configuration', None))
        .build()
    )
    return chatbot


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", choices=["cli", "gradio", "api","fastapi"], default="gradio",
                        help="Choose the interface to run the chatbot: cli, gradio, or api")

    parser.add_argument("--config", type=str, default="config/config.yaml",
                        help="Path to the configuration YAML file")
    
    parser.add_argument("--entrypoint", type=str, default=None,
                        help="Entrypoint function name to use (overrides config graph_type)")

    args = parser.parse_args()

    chatbot = build_chatbot(args.config, args.entrypoint)

    if args.interface == "cli":
        run_cli(chatbot)
    elif args.interface == "gradio":
        # Use new GradioInterface (Phase 2.1)
        interface = GradioInterface(
            chatbot=chatbot,
            title="🤖 Forza Chatbot",
            port=7860,
            share=False,
            theme="default"
        )
        interface.run()
    elif args.interface == "api":
        run_flask(chatbot)
    elif args.interface == "fastapi":
        # Use new FastAPIInterface (Phase 2.2)
        interface = FastAPIInterface(
            chatbot=chatbot,
            title="Forza Chatbot API",
            version="2.0"
        )
        interface.run(host="0.0.0.0", port=8000, reload=False)