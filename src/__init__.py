"""
Forza Chatbot - Refactored Architecture

Main entry point for the chatbot application.

Usage:
    from src import create_chatbot_dependencies
    chat_service = create_chatbot_dependencies()
"""

from src.di_container import create_chatbot_dependencies

__all__ = ["create_chatbot_dependencies"]
