"""
Gradio Interface - Refactored Architecture

Clean Gradio UI implementation using the refactored ChatService layer.

Features:
- Uses ChatService (orchestration layer)
- Dependency injection ready
- Async/await support
- Type-safe with API models
- Session management
- Clean error handling
"""

import asyncio
from typing import Optional, List, Tuple

import gradio as gr

from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import (
    SessionStartRequest,
    ChatMessageRequest
)


class GradioInterface:
    """
    Gradio web UI for the refactored chatbot architecture.

    Uses ChatService for all operations (session, messages, history).
    Handles async operations properly for Gradio.

    Attributes:
        chat_service: ChatService instance (injected)
        session_id: Current session ID
        chatbot: Gradio Chatbot component (for state management)
    """

    def __init__(self, chat_service: ChatService, title: str = "Forza Chatbot"):
        """
        Initialize Gradio interface.

        Args:
            chat_service: Configured ChatService instance
            title: Title for the Gradio app
        """
        self.chat_service = chat_service
        self.title = title
        self.session_id: Optional[str] = None
        self.chatbot_component = None  # Will be set during build

    async def _initialize_session(self) -> None:
        """
        Initialize session on first interaction.

        Creates a new session if one doesn't exist.
        """
        if self.session_id:
            return  # Already initialized

        try:
            response = await self.chat_service.start_session_async(
                SessionStartRequest(user_id=None, token=None)
            )
            self.session_id = response.session_id
            print(f"✓ Session started: {self.session_id}")
        except Exception as e:
            print(f"✗ Failed to start session: {str(e)}")
            raise

    async def _handle_message(
        self,
        message: str,
        history: List[List[str]]
    ) -> List[List[str]]:
        """
        Handle user message and return response.

        Args:
            message: User's message text
            history: Current chat history (Gradio format)

        Returns:
            Updated history with assistant response

        Raises:
            Exception: If message processing fails
        """
        # Initialize session if needed
        await self._initialize_session()

        if not message or not message.strip():
            return history

        try:
            # Send message through ChatService
            response = await self.chat_service.send_message_async(
                ChatMessageRequest(
                    session_id=self.session_id,
                    message=message.strip()
                )
            )

            # Add to history (Gradio format: [user_message, assistant_response])
            history.append([message, response.text])
            return history

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            history.append([message, error_msg])
            return history

    async def _get_history(self) -> str:
        """
        Get formatted conversation history.

        Returns:
            Formatted history string
        """
        if not self.session_id:
            return "No session active"

        try:
            response = await self.chat_service.get_history_async(
                self.session_id
            )

            if not response.messages:
                return "No messages in conversation"

            lines = ["=== Conversation History ===\n"]
            for msg in response.messages:
                role = msg.role.upper()
                content = msg.content
                lines.append(f"{role}: {content}\n")

            return "".join(lines)

        except Exception as e:
            return f"Error retrieving history: {str(e)}"

    async def _clear_history_handler(self) -> str:
        """
        Clear conversation history.

        Returns:
            Confirmation message
        """
        if not self.session_id:
            return "No session active"

        try:
            cleared_count = await self.chat_service.clear_history_async(
                self.session_id
            )
            return f"✓ Cleared {cleared_count} messages"

        except Exception as e:
            return f"✗ Error clearing history: {str(e)}"

    async def _get_stats(self) -> str:
        """
        Get chatbot statistics.

        Returns:
            Formatted stats string
        """
        try:
            session_stats = self.chat_service.get_session_stats()
            conv_stats = self.chat_service.get_conversation_stats()
            assistant_config = self.chat_service.get_assistant_config()

            stats_lines = [
                "=== Chatbot Statistics ===\n",
                f"Current Session: {self.session_id or 'None'}\n",
                f"Total Sessions: {session_stats.get('total_sessions', 0)}\n",
                f"Total Conversations: {conv_stats.get('total_conversations', 0)}\n",
                f"Total Messages: {conv_stats.get('total_messages', 0)}\n",
                f"Assistant: {assistant_config.get('assistant_name', 'Unknown')}\n"
            ]
            return "".join(stats_lines)

        except Exception as e:
            return f"Error getting stats: {str(e)}"

    def build(self) -> "gr.Blocks":
        """
        Build Gradio interface.

        Returns:
            Configured Gradio Blocks instance
        """
        with gr.Blocks(title=self.title, theme=gr.themes.Soft()) as demo:
            # Header
            gr.Markdown(f"# {self.title}")
            gr.Markdown("Refactored Architecture with ChatService Layer")

            with gr.Row():
                with gr.Column():
                    # Chat interface
                    self.chatbot_component = gr.Chatbot(
                        label="Chat",
                        height=400,
                        show_copy_button=True
                    )

                    # Input area
                    with gr.Row():
                        message_input = gr.Textbox(
                            label="Message",
                            placeholder="Type your message...",
                            lines=1,
                            scale=4
                        )
                        send_btn = gr.Button("Send", scale=1)

                with gr.Column():
                    # Info panels
                    with gr.Tabs():
                        with gr.Tab("History"):
                            history_output = gr.Textbox(
                                label="Conversation History",
                                interactive=False,
                                lines=10
                            )
                            history_btn = gr.Button("Refresh History")

                        with gr.Tab("Stats"):
                            stats_output = gr.Textbox(
                                label="Statistics",
                                interactive=False,
                                lines=10
                            )
                            stats_btn = gr.Button("Refresh Stats")

                        with gr.Tab("Controls"):
                            clear_btn = gr.Button(
                                "Clear Conversation",
                                variant="stop"
                            )
                            clear_output = gr.Textbox(
                                label="Status",
                                interactive=False
                            )

            # Event handlers
            send_btn.click(
                fn=self._handle_message,
                inputs=[message_input, self.chatbot_component],
                outputs=[self.chatbot_component]
            ).then(
                lambda: "",  # Clear input
                outputs=[message_input]
            )

            # Enter key support
            message_input.submit(
                fn=self._handle_message,
                inputs=[message_input, self.chatbot_component],
                outputs=[self.chatbot_component]
            ).then(
                lambda: "",
                outputs=[message_input]
            )

            # History refresh
            history_btn.click(
                fn=self._get_history,
                outputs=[history_output]
            )

            # Stats refresh
            stats_btn.click(
                fn=self._get_stats,
                outputs=[stats_output]
            )

            # Clear conversation
            clear_btn.click(
                fn=self._clear_history_handler,
                outputs=[clear_output]
            )

            # Load initial stats
            demo.load(
                fn=self._get_stats,
                outputs=[stats_output]
            )

        return demo

    def run(self, share: bool = False, server_name: str = "127.0.0.1", server_port: int = 7860):
        """
        Run Gradio interface.

        Args:
            share: Whether to create a public link
            server_name: Server address
            server_port: Server port
        """
        demo = self.build()

        # Print startup info
        print(f"\n{'='*50}")
        print(f"🚀 Gradio Interface Starting")
        print(f"{'='*50}")
        print(f"Title: {self.title}")
        print(f"Server: {server_name}:{server_port}")
        print(f"Session: {self.session_id or 'Will initialize on first message'}")
        print(f"{'='*50}\n")

        # Launch Gradio
        demo.launch(
            share=share,
            server_name=server_name,
            server_port=server_port,
            show_error=True
        )


# Convenience function for quick testing
def run_gradio_interface(
    chat_service: ChatService,
    title: str = "Forza Chatbot",
    share: bool = False,
    port: int = 7860
):
    """
    Quick start function for Gradio interface.

    Args:
        chat_service: ChatService instance
        title: UI title
        share: Create public link
        port: Server port
    """
    interface = GradioInterface(chat_service, title=title)
    interface.run(share=share, server_port=port)


__all__ = ["GradioInterface", "run_gradio_interface"]
