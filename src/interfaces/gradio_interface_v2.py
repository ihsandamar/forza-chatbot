"""
Gradio Interface - Phase 2 Implementation

A modern web interface built with Gradio.
Supports real-time chat, configuration updates, and conversation history.

Features:
  - Modern web UI with Gradio
  - Quick prompt buttons (configurable)
  - Runtime configuration panel
  - Full conversation history
  - Error handling and loading states
  - Mobile-responsive design
  - Dark/light theme support
"""

from typing import List, Tuple, Optional, Dict, Any
import gradio as gr
import yaml
import os
from datetime import datetime

from src.interfaces.base_interface import BaseInterface
from src.models.standard_types import StandardState, StandardResponse, ResponseType


class GradioInterface(BaseInterface):
    """
    Gradio-based web interface for the chatbot.

    Provides a modern web UI with:
    - Chat interface with history
    - Quick prompt suggestions
    - Runtime configuration
    - Theme support
    - Error messages

    Architecture:
        User Input (Gradio) → StandardState → Chatbot → StandardResponse → Display
    """

    def __init__(
        self,
        chatbot: "Chatbot",
        title: str = "🤖 Forza Chatbot",
        description: str = "Multi-agent AI Assistant",
        port: int = 7860,
        share: bool = False,
        quick_prompts_file: Optional[str] = None,
        theme: str = "default",
    ):
        """
        Initialize Gradio interface.

        Args:
            chatbot: Configured Chatbot instance
            title: Browser tab title
            description: Application description
            port: Port to run server on
            share: Whether to create shareable link
            quick_prompts_file: Path to quick prompts YAML file
            theme: Gradio theme ("default", "dark", "soft")

        Raises:
            TypeError: If chatbot is invalid
        """
        super().__init__(chatbot)
        self.title = title
        self.description = description
        self.port = port
        self.share = share
        self.theme = theme

        # Gradio history format: [(user_msg, bot_msg), ...]
        self.gradio_history: List[Tuple[str, str]] = []

        # Load quick prompts
        self.quick_prompts = self._load_quick_prompts(quick_prompts_file)

        # Gradio app (created in run())
        self.demo: Optional[gr.Blocks] = None

        self.logger.info(
            "GradioInterface initialized",
            port=port,
            theme=theme,
            quick_prompts_count=sum(
                len(prompts) for prompts in self.quick_prompts.values()
            ),
        )

    # ========== ABSTRACT METHODS (implements BaseInterface) ==========

    def chat(self, state: StandardState) -> StandardResponse:
        """
        Process chat message via chatbot.

        Converts StandardState to graph format and returns StandardResponse.

        Args:
            state: StandardState with messages

        Returns:
            StandardResponse with text and metadata
        """
        try:
            self._validate_state(state)
            return self._safe_chat(state)
        except Exception as e:
            self.logger.error(f"Chat error: {str(e)}")
            return self._handle_error(e, context="chat")

    def configure(self, config: Dict[str, Any]) -> None:
        """
        Reconfigure assistant at runtime.

        Like LangGraph Studio, allows updating:
        - system_prompt
        - temperature
        - model
        - etc.

        Args:
            config: Configuration dict with updates
        """
        try:
            self.chatbot.configure(config)
            self.logger.info("Configuration updated via Gradio", config=config)
        except Exception as e:
            self.logger.error(f"Configuration error: {str(e)}")
            raise

    def get_history(self) -> List[Dict[str, Any]]:
        """Get conversation history."""
        return self.chatbot.get_history()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.chatbot.clear_history()
        self.gradio_history = []
        self.logger.info("History cleared via Gradio")

    def run(self) -> None:
        """
        Launch Gradio web interface (blocking).

        Creates and launches the Gradio app with:
        - Chat interface
        - Configuration panel
        - Quick prompts
        - History management
        """
        self._build_ui()
        self.demo.launch(
            server_name="0.0.0.0",
            server_port=self.port,
            share=self.share,
            show_error=True,
        )

    # ========== UI BUILDING ==========

    def _build_ui(self) -> None:
        """Build the Gradio UI components."""
        theme_map = {
            "default": gr.themes.Default(),
            "dark": gr.themes.Soft(primary_hue="slate"),
            "soft": gr.themes.Soft(),
        }
        selected_theme = theme_map.get(self.theme, gr.themes.Default())

        self.demo = gr.Blocks(
            title=self.title,
            theme=selected_theme,
            css=self._get_custom_css(),
        )

        with self.demo:
            # ===== HEADER =====
            gr.Markdown(f"# {self.title}\n{self.description}")

            # ===== MAIN LAYOUT =====
            with gr.Row():
                # Left column: Chat
                with gr.Column(scale=3):
                    self._build_chat_section()

                # Right column: Config + Quick prompts
                with gr.Column(scale=1, min_width=300):
                    self._build_config_section()
                    self._build_quick_prompts_section()

            # ===== FOOTER =====
            self._build_footer_section()

    def _build_chat_section(self) -> None:
        """Build the main chat interface section."""
        # Chat display
        self.chat_display = gr.Chatbot(
            label="💬 Chat",
            type="tuples",  # (user_msg, bot_msg) format
            height=500,
            show_copy_button=True,
            show_share_button=True,
            show_label=True,
        )

        # Input area
        with gr.Row():
            self.user_input = gr.Textbox(
                label="Message",
                placeholder="Type your message here...",
                lines=2,
                max_lines=5,
                show_label=False,
            )

        # Buttons
        with gr.Row():
            self.send_button = gr.Button("Send", variant="primary", scale=2)
            self.clear_button = gr.Button("Clear", variant="secondary", scale=1)

        # ===== EVENT HANDLERS =====

        # Send button click
        self.send_button.click(
            fn=self._handle_send,
            inputs=[self.chat_display, self.user_input],
            outputs=[self.chat_display],
        ).then(
            fn=lambda: gr.update(value=""),
            outputs=[self.user_input],
        )

        # Enter key in input
        self.user_input.submit(
            fn=self._handle_send,
            inputs=[self.chat_display, self.user_input],
            outputs=[self.chat_display],
        ).then(
            fn=lambda: gr.update(value=""),
            outputs=[self.user_input],
        )

        # Clear button
        self.clear_button.click(
            fn=self._handle_clear,
            outputs=[self.chat_display],
        )

    def _build_config_section(self) -> None:
        """Build the configuration panel."""
        with gr.Accordion("⚙️ Configuration", open=False):
            current_config = self._get_config()

            # System prompt
            self.config_system_prompt = gr.Textbox(
                label="System Prompt",
                value=current_config.get("system_prompt", ""),
                lines=3,
                max_lines=6,
            )

            # Temperature
            self.config_temperature = gr.Slider(
                label="Temperature",
                minimum=0,
                maximum=2,
                step=0.1,
                value=current_config.get("temperature", 0.7),
            )

            # Assistant name
            self.config_name = gr.Textbox(
                label="Assistant Name",
                value=current_config.get("assistant_name", "Assistant"),
            )

            # Update button
            update_button = gr.Button("Update Configuration", variant="primary")

            update_button.click(
                fn=self._handle_config_update,
                inputs=[
                    self.config_system_prompt,
                    self.config_temperature,
                    self.config_name,
                ],
                outputs=[],
            )

    def _build_quick_prompts_section(self) -> None:
        """Build the quick prompts section."""
        if not self.quick_prompts:
            return

        with gr.Accordion("⚡ Quick Prompts", open=False):
            for group_name, prompts in self.quick_prompts.items():
                if prompts:
                    with gr.Group():
                        gr.Markdown(f"**{group_name}**")
                        for prompt in prompts:
                            btn = gr.Button(
                                prompt,
                                size="sm",
                                variant="secondary",
                            )
                            btn.click(
                                fn=self._handle_quick_prompt,
                                inputs=[self.chat_display, btn],
                                outputs=[self.chat_display],
                            )

    def _build_footer_section(self) -> None:
        """Build the footer section with info and history."""
        with gr.Accordion("📊 Session Info", open=False):
            session_info = self._get_session_info()

            gr.Markdown(
                f"""
            **Session ID:** `{session_info['session_id']}`

            **Messages:** {session_info['message_count']}

            **Assistant:** {session_info['assistant_name']}
            """
            )

            # Export buttons
            with gr.Row():
                export_json_btn = gr.Button("📥 Export as JSON", scale=1)
                export_json_btn.click(
                    fn=self._export_history_json,
                    outputs=[gr.Textbox(label="JSON Export", lines=10)],
                )

    # ========== EVENT HANDLERS ==========

    def _handle_send(
        self, gradio_history: List[Tuple[str, str]], user_message: str
    ) -> List[Tuple[str, str]]:
        """
        Handle user message and update chat display.

        Converts Gradio format to StandardState, processes via chatbot,
        converts back to Gradio format.

        Args:
            gradio_history: Current chat history in Gradio format
            user_message: New user message

        Returns:
            Updated Gradio history
        """
        if not user_message.strip():
            return gradio_history

        try:
            start_time = datetime.now()

            # Convert Gradio format to StandardState
            messages = self._convert_from_gradio(gradio_history, user_message)
            state = StandardState(
                messages=messages,
                session_id=self._get_session_id(),
            )

            # Get response from chatbot
            response = self.chat(state)

            # Update local history
            self.gradio_history.append((user_message, response.text))

            # Calculate duration
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Log interaction
            self._log_interaction(user_message, response, duration_ms)

            # Convert back to Gradio format
            return self._convert_to_gradio(self.gradio_history)

        except Exception as e:
            self.logger.error(f"Send error: {str(e)}")
            error_msg = f"❌ Error: {str(e)}"
            gradio_history.append((user_message, error_msg))
            return gradio_history

    def _handle_clear(self) -> List[Tuple[str, str]]:
        """Handle clear history button."""
        self.clear_history()
        return []

    def _handle_quick_prompt(
        self, gradio_history: List[Tuple[str, str]], prompt_text: str
    ) -> List[Tuple[str, str]]:
        """Handle quick prompt button click."""
        return self._handle_send(gradio_history, prompt_text)

    def _handle_config_update(
        self, system_prompt: str, temperature: float, assistant_name: str
    ) -> None:
        """Handle configuration update."""
        config = {
            "system_prompt": system_prompt,
            "temperature": temperature,
            "assistant_name": assistant_name,
        }
        self.configure(config)

    def _export_history_json(self) -> str:
        """Export conversation history as JSON."""
        return self.export_history(format="json")

    # ========== HELPER METHODS ==========

    def _convert_from_gradio(
        self, gradio_history: List[Tuple[str, str]], new_message: str
    ) -> List[Dict[str, str]]:
        """
        Convert Gradio history format to StandardState messages.

        Gradio format: [(user_msg, bot_msg), ...]
        StandardState format: [{"role": "user", "content": "..."}, ...]

        Args:
            gradio_history: Gradio chat history
            new_message: New user message

        Returns:
            List of message dicts in StandardState format
        """
        messages = []

        # Convert existing history
        for user_msg, bot_msg in gradio_history:
            messages.append({"role": "user", "content": user_msg})
            if bot_msg:  # Only add bot message if it exists
                messages.append({"role": "assistant", "content": bot_msg})

        # Add new user message
        messages.append({"role": "user", "content": new_message})

        return messages

    def _convert_to_gradio(
        self, messages_list: List[Tuple[str, str]]
    ) -> List[Tuple[str, str]]:
        """
        Convert messages list back to Gradio format.

        Simply returns the tuple list as-is (already in Gradio format).

        Args:
            messages_list: List of (user, bot) tuples

        Returns:
            Same list (already in Gradio format)
        """
        return messages_list

    def _load_quick_prompts(
        self, prompts_file: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        Load quick prompts from YAML file.

        Args:
            prompts_file: Path to YAML file with quick prompts

        Returns:
            Dictionary of {group_name: [prompts]}
        """
        # Default locations to check
        default_locations = [
            prompts_file,
            "config/default_prompts.yaml",
            "config/prompts.yaml",
        ]

        for location in default_locations:
            if location and os.path.exists(location):
                try:
                    with open(location, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                        prompts = config.get("groups", {})
                        if prompts:
                            self.logger.info(f"Loaded quick prompts from {location}")
                            return prompts
                except Exception as e:
                    self.logger.warning(
                        f"Failed to load prompts from {location}: {str(e)}"
                    )

        # Return default if nothing loaded
        return {
            "General": [
                "Hello! How can you help?",
                "Show me recent data",
            ],
        }

    def _get_custom_css(self) -> str:
        """Get custom CSS for styling."""
        return """
        .gradio-container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .gradio-chatbot {
            font-size: 14px;
        }

        #chat_display {
            height: 500px;
        }

        .send-button {
            background-color: #4CAF50;
        }
        """

    # ========== STRING REPRESENTATIONS ==========

    def __str__(self) -> str:
        """String representation."""
        return (
            f"GradioInterface(port={self.port}, "
            f"session={self._get_session_id()})"
        )


def run_gradio_legacy(chatbot: "Chatbot") -> None:
    """
    Legacy entry point for backward compatibility.

    Redirects to new GradioInterface.

    Args:
        chatbot: Chatbot instance
    """
    import warnings

    warnings.warn(
        "run_gradio() is deprecated. Use GradioInterface directly.",
        DeprecationWarning,
    )
    interface = GradioInterface(chatbot)
    interface.run()


__all__ = ["GradioInterface", "run_gradio_legacy"]
