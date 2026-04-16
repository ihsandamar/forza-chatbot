"""Forza Chatbot — CLI entry point. Usage: python main.py [--interface api|gradio|cli] [--config PATH]"""
import argparse
from src.launch import get_launcher


def main():
    parser = argparse.ArgumentParser(description="Forza Chatbot")
    parser.add_argument(
        "--interface",
        choices=["api", "gradio", "cli"],
        default="api",
        help="Interface to launch (default: api)",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config YAML (default: config/config.yaml)",
    )
    args = parser.parse_args()
    get_launcher(args.interface, args.config).run()


if __name__ == "__main__":
    main()
