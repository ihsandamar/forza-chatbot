"""
CLI Interface - Refactored Architecture

Simple command-line interface for the refactored chatbot.

Features:
- Uses ChatService (orchestration layer)
- Sync operation (blocking input/output)
- Easy to test
- Minimal dependencies
"""

import asyncio
from typing import Optional

from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import (
    SessionStartRequest,
    ChatMessageRequest,
)


class CLIInterface:
    """
    Command-line interface for the refactored chatbot.

    Features:
    - Interactive chat loop
    - Commands: /history, /clear, /config, /stats, /exit
    - Clean error handling
    - Session management

    Usage:
        interface = CLIInterfaceRefactored(chat_service)
        interface.run()
    """

    def __init__(self, chat_service: ChatService, prompt: str = "You"):
        """
        Initialize CLI interface.

        Args:
            chat_service: ChatService instance
            prompt: Display name for user input
        """
        self.chat_service = chat_service
        self.session_id: Optional[str] = None
        self.prompt = prompt
        self.running = True

    async def _initialize_session(self) -> bool:
        """
        Initialize session.

        Returns:
            True if successful, False otherwise
        """
        try:
            response = await self.chat_service.start_session(
                SessionStartRequest(user_id=None, token=None)
            )
            self.session_id = response.session_id
            print(f"[OK] Session started: {self.session_id}\n")
            return True
        except Exception as e:
            print(f"[FAIL] Failed to start session: {str(e)}\n")
            return False

    def _print_header(self):
        """Print interface header."""
        print("\n" + "="*60)
        print("Forza Chatbot - CLI Interface (Refactored)")
        print("="*60)
        print("Commands: /history, /clear, /config, /stats, /help, /exit")
        print("="*60 + "\n")

    def _print_help(self):
        """Print help message."""
        help_text = """
Commands:
  /history    - Show conversation history
  /clear      - Clear conversation
  /config     - Show assistant config
  /stats      - Show statistics
  /help       - Show this help message
  /exit       - Exit the chat

Type your message and press Enter to send.
        """
        print(help_text)

    async def _show_history(self):
        """Show conversation history."""
        if not self.session_id:
            print("[FAIL] No active session\n")
            return

        try:
            response = await self.chat_service.get_session_history(self.session_id)

            if not response.messages:
                print("(No messages yet)\n")
                return

            print("\n" + "="*60)
            print("Conversation History")
            print("="*60)

            for msg in response.messages:
                role = msg.role.upper()
                content = msg.content
                print(f"\n[{role}]")
                print(f"{content}")

            print("\n" + "="*60 + "\n")

        except Exception as e:
            print(f"[FAIL] Error retrieving history: {str(e)}\n")

    async def _clear_history(self):
        """Clear conversation."""
        if not self.session_id:
            print("[FAIL] No active session\n")
            return

        try:
            cleared_count = self.chat_service.clear_conversation(self.session_id)
            print(f"[OK] Cleared {cleared_count} messages\n")
        except Exception as e:
            print(f"[FAIL] Error clearing history: {str(e)}\n")

    def _show_config(self):
        """Show assistant configuration."""
        try:
            config = self.chat_service.get_assistant_config()

            print("\n" + "="*60)
            print("Assistant Configuration")
            print("="*60)

            for key, value in config.items():
                if key == "system_prompt":
                    print(f"\n{key}:")
                    print(f"  {value[:100]}...")
                else:
                    print(f"{key}: {value}")

            print("\n" + "="*60 + "\n")

        except Exception as e:
            print(f"[FAIL] Error getting config: {str(e)}\n")

    def _show_stats(self):
        """Show statistics."""
        try:
            session_stats = self.chat_service.get_session_stats()
            conv_stats = self.chat_service.get_conversation_stats()

            print("\n" + "="*60)
            print("Statistics")
            print("="*60)
            print(f"Current Session: {self.session_id}")
            print(f"Total Sessions: {session_stats.get('total_sessions', 0)}")
            print(f"Total Conversations: {conv_stats.get('total_conversations', 0)}")
            print(f"Total Messages: {conv_stats.get('total_messages', 0)}")
            print(f"Avg Messages/Conv: {conv_stats.get('avg_messages_per_conversation', 0):.1f}")
            print("="*60 + "\n")

        except Exception as e:
            print(f"[FAIL] Error getting stats: {str(e)}\n")

    async def _handle_message(self, user_input: str) -> bool:
        """
        Handle user message.

        Args:
            user_input: User's input

        Returns:
            True if should continue, False if should exit
        """
        # Handle commands
        if user_input.startswith("/"):
            command = user_input.lower()

            if command == "/exit":
                print("\n[OK] Goodbye!\n")
                return False

            elif command == "/history":
                await self._show_history()
                return True

            elif command == "/clear":
                await self._clear_history()
                return True

            elif command == "/config":
                self._show_config()
                return True

            elif command == "/stats":
                self._show_stats()
                return True

            elif command == "/help":
                self._print_help()
                return True

            else:
                print(f"[FAIL] Unknown command: {command}")
                print("Type /help for available commands\n")
                return True

        # Handle regular message
        if not self.session_id:
            print("[FAIL] No active session\n")
            return True

        if not user_input.strip():
            return True

        try:
            response = await self.chat_service.send_message(
                ChatMessageRequest(
                    session_id=self.session_id,
                    message=user_input.strip()
                )
            )

            print(f"\nBot: {response.text}\n")

        except Exception as e:
            print(f"[FAIL] Error: {str(e)}\n")

        return True

    async def run(self):
        """Run the CLI interface."""
        self._print_header()

        # Initialize session
        if not await self._initialize_session():
            return

        print("Type your message or /help for commands\n")

        # Chat loop
        while self.running:
            try:
                user_input = input(f"{self.prompt}: ").strip()

                if user_input:
                    if not await self._handle_message(user_input):
                        break

            except KeyboardInterrupt:
                print("\n\n[OK] Chat closed\n")
                break

            except Exception as e:
                print(f"[FAIL] Error: {str(e)}\n")

        # Cleanup (no end_session in canonical ChatService)
        pass


def run_cli_interface(chat_service: ChatService, prompt: str = "You"):
    """
    Quick start function for CLI interface.

    Args:
        chat_service: ChatService instance
        prompt: Display name for user input
    """
    interface = CLIInterface(chat_service, prompt=prompt)
    asyncio.run(interface.run())


__all__ = ["CLIInterface", "run_cli_interface"]
