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
- Modern ChatBot UI/UX with sidebar layout
"""

import asyncio
from typing import Optional, List, Tuple
from datetime import datetime
import os

import gradio as gr

from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import (
    SessionStartRequest,
    ChatMessageRequest
)
from src.core.models import ResponseFormat
from src.core.runtime_config import RuntimeConfiguration


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

    def __init__(
        self,
        chat_service: ChatService,
        runtime_config: Optional[RuntimeConfiguration] = None,
        title: str = "Forza Chatbot"
    ):
        """
        Initialize Gradio interface.

        Args:
            chat_service: Configured ChatService instance
            runtime_config: RuntimeConfiguration for dynamic settings UI
            title: Title for the Gradio app
        """
        self.chat_service = chat_service
        self.runtime_config = runtime_config
        self.title = title
        self.session_id: Optional[str] = None
        self.current_session_id: Optional[str] = None  # Track currently selected session
        self.chatbot_component = None  # Will be set during build
        self.token: Optional[str] = None  # Authentication token for API calls

    async def _initialize_session(self) -> None:
        """
        Initialize session on first interaction.

        Creates a new session if one doesn't exist.
        Uses the token from the UI if available.
        """
        if self.session_id:
            return  # Already initialized

        try:
            response = await self.chat_service.start_session_async(
                SessionStartRequest(user_id=None, token=self.token)
            )
            self.session_id = response.session_id
            token_info = f" (token: {self.token[:10]}...)" if self.token else " (no token)"
            print(f"✓ Session started: {self.session_id}{token_info}")
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

        # Validate session_id
        if not self.session_id or not isinstance(self.session_id, str):
            error_msg = f"Error: Session not properly initialized. session_id={self.session_id}"
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": error_msg})
            return history

        try:
            # Send message through ChatService with token
            response = await self.chat_service.send_message_async(
                ChatMessageRequest(
                    session_id=self.session_id,
                    message=message.strip(),
                    token=self.token
                )
            )

            # Load full history from session (includes all messages: user, assistant, tool, etc.)
            # This ensures all agent-generated messages and tool calls are included
            updated_history = await self._load_session_history(self.session_id)
            return updated_history

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": error_msg})
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

    def _get_current_datetime_info(self) -> str:
        """Get current date, time and day information."""
        now = datetime.now()
        day_name = now.strftime("%A")
        date_str = now.strftime("%d.%m.%Y")
        time_str = now.strftime("%H:%M")
        return f"{day_name}\n{date_str}\n{time_str}"

    def _update_response_format(self, format_value: str) -> None:
        """
        Update session response format setting.

        Args:
            format_value: The selected response format value
        """
        if not self.session_id:
            return

        try:
            # Get session and update settings
            session = self.chat_service.get_session(self.session_id)
            if session:
                session["settings"]["response_format"] = format_value
        except Exception as e:
            print(f"Error updating response format: {str(e)}")

    def _update_token(self, token_value: str) -> str:
        """
        Update authentication token for API calls.

        Args:
            token_value: The token string entered by user

        Returns:
            Confirmation message
        """
        try:
            # Update token in memory
            self.token = token_value if token_value and token_value.strip() else None

            if self.token:
                # Store in session if one exists
                if self.session_id:
                    session = self.chat_service.get_session(self.session_id)
                    if session and "settings" in session:
                        session["settings"]["token"] = self.token
                        print(f"✓ Token updated in session")
                return f"✓ Token kaydedildi ({self.token[:10]}...)"
            else:
                return "✓ Token temizlendi"

        except Exception as e:
            error_msg = f"✗ Token güncellemesi başarısız: {str(e)}"
            print(error_msg)
            return error_msg

    def _get_chat_history_list(self) -> List[str]:
        """Get list of active sessions from ChatService."""
        if not self.chat_service:
            return []

        try:
            sessions = self.chat_service.list_sessions()
            if not sessions:
                return []

            display_sessions = []
            for session in sessions:
                session_id = session.get("session_id")
                created_at = session.get("created_at")
                message_count = session.get("message_count", 0)

                if created_at:
                    time_str = created_at.strftime("%H:%M")
                    display_name = f"{session_id[:8]}... ({time_str}) - {message_count} msg"
                else:
                    display_name = f"{session_id[:8]}... - {message_count} msg"

                display_sessions.append(display_name)

            return display_sessions
        except Exception as e:
            print(f"Error fetching sessions: {e}")
            return []

    def _format_sessions_list(self) -> str:
        """Format sessions list as Markdown with session details."""
        if not self.chat_service:
            return "*Aktif sohbet yok*"

        try:
            sessions = self.chat_service.list_sessions()
            if not sessions:
                return "*Aktif sohbet yok*"

            sessions_md = ""
            for session in sessions:
                session_id = session.get("session_id")
                created_at = session.get("created_at")
                message_count = session.get("message_count", 0)

                if created_at:
                    time_str = created_at.strftime("%H:%M")
                    sessions_md += f"• **{session_id[:12]}**... ({time_str}) - {message_count} msg\n"
                else:
                    sessions_md += f"• **{session_id[:12]}**... - {message_count} msg\n"

            return sessions_md if sessions_md else "*Aktif sohbet yok*"
        except Exception as e:
            print(f"Error formatting sessions: {e}")
            return "*Hata: Sohbetler yüklenemedi*"

    def _get_asset_path(self, filename: str) -> str:
        """Get path to asset file."""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", filename)

    async def _create_new_session(self):
        """
        Create a new chat session.

        Returns:
            None (UI will need to be refreshed manually)
        """
        try:
            response = await self.chat_service.create_new_session()
            self.session_id = response.session_id
            print(f"✓ New session created: {self.session_id}")
        except Exception as e:
            print(f"✗ Error creating session: {e}")

    async def _load_session_history(self, session_id: str) -> List[dict]:
        """
        Load history for a specific session.

        Args:
            session_id: Session identifier to load

        Returns:
            Chat history in Gradio messages format (list of dicts)
        """
        if not session_id:
            return []

        try:
            # Validate session exists
            if not self.chat_service.session_exists(session_id):
                return []

            # Set current session
            self.session_id = session_id

            # Get session history
            history_response = await self.chat_service.get_history_async(session_id)

            # Convert to Gradio messages format (type="messages")
            # Handle tool messages with special metadata format
            chat_history = []
            for msg in history_response.messages:
                if msg.role == "tool":
                    # Format tool messages with thinking metadata
                    chat_history.append({
                        "role": "assistant",
                        "content": "",
                        "metadata": {
                            "title": f"⏳Thinking: {msg.content}"
                        }
                    })
                else:
                    # Regular messages
                    chat_history.append({
                        "role": msg.role,
                        "content": msg.content
                    })

            return chat_history
        except Exception as e:
            print(f"Error loading session: {e}")
            return []

    def _get_session_dropdown_choices(self) -> list:
        """Get list of session IDs for dropdown."""
        try:
            sessions = self.chat_service.list_sessions()
            choices = []
            for session in sessions:
                session_id = session.get("session_id")
                created_at = session.get("created_at")
                message_count = session.get("message_count", 0)

                if created_at:
                    time_str = created_at.strftime("%H:%M")
                    display = f"{session_id[:8]}... ({time_str}) - {message_count} msg"
                else:
                    display = f"{session_id[:8]}... - {message_count} msg"

                choices.append((display, session_id))

            return choices
        except Exception:
            return []

    def _get_sessions_info(self) -> List[Tuple[str, str]]:
        """Get sessions as list of (display_name, session_id) tuples for buttons."""
        try:
            sessions = self.chat_service.list_sessions()
            print(f"DEBUG: Retrieved sessions: {sessions}")

            if not sessions:
                print("DEBUG: No sessions found")
                return []

            sessions_info = []
            for session in sessions:
                session_id = session.get("session_id")
                created_at = session.get("created_at")
                message_count = session.get("message_count", 0)

                if created_at:
                    time_str = created_at.strftime("%H:%M")
                    display = f"{session_id[:8]}... ({time_str}) - {message_count} msg"
                else:
                    display = f"{session_id[:8]}... - {message_count} msg"

                sessions_info.append((display, session_id))
                print(f"DEBUG: Added session button: {display}")

            print(f"DEBUG: Total sessions_info: {len(sessions_info)}")
            return sessions_info
        except Exception as e:
            print(f"ERROR in _get_sessions_info: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def _load_session_by_button(self, session_id: str) -> List[List[str]]:
        """
        Load session history when a session button is clicked.

        Args:
            session_id: The session ID to load

        Returns:
            Chat history in Gradio format
        """
        if session_id:
            # Update current session
            self.current_session_id = session_id
            self.session_id = session_id
            print(f"DEBUG: Current session changed to: {self.current_session_id}")
            return await self._load_session_history(session_id)
        return []

    def _load_session_and_refresh_list(self, session_input) -> Tuple[List[List[str]], str]:
        """
        Load session history and refresh the sessions list to show selection.

        Args:
            session_input: The session ID (string) or tuple from dropdown

        Returns:
            Tuple of (chat_history, updated_sessions_html)
        """
        print(f"DEBUG: _load_session_and_refresh_list input type: {type(session_input)}, value: {session_input}")

        # Handle both string and tuple inputs (dropdown can return tuple)
        session_id = session_input
        if isinstance(session_input, tuple):
            session_id = session_input[1] if len(session_input) > 1 else session_input[0]
        elif isinstance(session_input, list):
            # Handle list input (shouldn't happen but be safe)
            session_id = session_input[0] if session_input else None

        print(f"DEBUG: Extracted session_id: {session_id}, type: {type(session_id)}")

        if session_id and isinstance(session_id, str):
            # Update current session
            self.current_session_id = session_id
            self.session_id = session_id
            print(f"DEBUG: Current session changed to: {self.current_session_id}")
            # Return both updated history and sessions HTML
            history = asyncio.run(self._load_session_history(session_id))
            sessions_html = self._render_sessions_html()
            print(f"DEBUG: Returning history length: {len(history)}, sessions_html length: {len(sessions_html)}")
            return history, sessions_html

        print(f"DEBUG: session_id invalid, returning empty")
        return [], self._render_sessions_html()

    def _render_sessions_html(self) -> str:
        """
        Render sessions as interactive HTML with buttons.
        Highlights the currently selected session.

        Returns:
            HTML string with session buttons
        """
        sessions_info = self._get_sessions_info()
        print(f"DEBUG: _render_sessions_html - {len(sessions_info)} sessions, current: {self.current_session_id}")

        if not sessions_info:
            return """
            <div style="
                padding: 12px;
                text-align: center;
                color: #888;
                font-style: italic;
                background-color: #f5f5f5;
                border-radius: 6px;
                border: 1px solid #e0e0e0;
                font-size: 13px;
            ">
                Aktif sohbet yok
            </div>
            """

        html = "<div style='display: flex; flex-direction: column; gap: 6px;' id='sessions_container'>"
        for display_name, session_id in sessions_info:
            # Check if this session is currently selected
            is_selected = self.current_session_id == session_id

            # Different styles for selected vs unselected
            if is_selected:
                bg_color = "#e8e8e8"
                border_color = "#bbb"
                text_color = "#222"
                font_weight = "500"
                hover_bg = "#dcdcdc"
                hover_border = "#aaa"
            else:
                bg_color = "#f5f5f5"
                border_color = "#e0e0e0"
                text_color = "#333"
                font_weight = "400"
                hover_bg = "#efefef"
                hover_border = "#d0d0d0"

            # Create HTML button that triggers session loading via data attribute
            html += f"""
            <button
                class="session-btn"
                data-session-id="{session_id}"
                onclick="
                    event.preventDefault();
                    var sessionId = this.getAttribute('data-session-id');
                    console.log('Session button clicked. ID:', sessionId);

                    var textboxes = document.querySelectorAll('textarea, input[type=\"text\"]');
                    var sessionSelector = null;

                    for (var i = 0; i < textboxes.length; i++) {{
                        var label = textboxes[i].parentElement.querySelector('label');
                        if (label && label.textContent.includes('session_selector')) {{
                            sessionSelector = textboxes[i];
                            break;
                        }}
                    }}

                    if (!sessionSelector) {{
                        var allTextboxes = document.querySelectorAll('textarea, input[type=\"text\"]');
                        for (var i = 0; i < allTextboxes.length; i++) {{
                            if (allTextboxes[i].offsetHeight === 0 || allTextboxes[i].offsetWidth === 0) {{
                                sessionSelector = allTextboxes[i];
                                break;
                            }}
                        }}
                    }}

                    if (sessionSelector) {{
                        console.log('Found session selector, setting value to:', sessionId);
                        sessionSelector.value = sessionId;
                        sessionSelector.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        sessionSelector.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }} else {{
                        console.log('Could not find session selector');
                    }}
                "
                style="
                    padding: 9px 11px;
                    border: 1px solid {border_color};
                    border-radius: 5px;
                    background-color: {bg_color};
                    color: {text_color};
                    cursor: pointer;
                    text-align: left;
                    font-size: 13px;
                    transition: all 0.15s ease;
                    white-space: normal;
                    word-break: break-word;
                    font-weight: {font_weight};
                    font-family: inherit;
                "
                onmouseover="this.style.backgroundColor='{hover_bg}'; this.style.borderColor='{hover_border}';"
                onmouseout="this.style.backgroundColor='{bg_color}'; this.style.borderColor='{border_color}';"
            >
                {display_name}
            </button>
            """
        html += "</div>"

        return html

    def build(self) -> "gr.Blocks":
        """
        Build clean Gradio interface with sidebar layout.

        Returns:
            Configured Gradio Blocks instance
        """
        with gr.Blocks(title=self.title, theme=gr.themes.Soft()) as demo:
            with gr.Row():
                # Left Sidebar
                with gr.Column(scale=1, min_width=250):
                    gr.Markdown("### Forza Chatbot")

                    # Date/Time info
                    datetime_display = gr.Textbox(
                        value=self._get_current_datetime_info(),
                        label="📅 Tarih & Saat",
                        interactive=False,
                        lines=3
                    )

                    # New Chat Button
                    new_chat_btn = gr.Button("➕ Yeni Sohbet", variant="primary")

                    # Chat History - Session Selection
                    gr.Markdown("**Sohbetler**")

                    # Sessions dropdown - simple Gradio native
                    session_dropdown = gr.Dropdown(
                        choices=self._get_session_dropdown_choices(),
                        value=None,
                        label="",
                        show_label=False,
                        interactive=True
                    )

                    # Refresh sessions button
                    refresh_sessions_btn = gr.Button(
                        "🔄 Yenile",
                        size="sm"
                    )

                # Main Chat Area
                with gr.Column(scale=3):
                    gr.Markdown("## Chat")

                    # Chat display with native avatars
                    user_avatar = self._get_asset_path("user_white.png")
                    ai_avatar = self._get_asset_path("ai_white.png")

                    self.chatbot_component = gr.Chatbot(
                        value=[],
                        label="",
                        show_label=False,
                        height=500,
                        show_copy_button=True,
                        avatar_images=(user_avatar, ai_avatar),
                        type="messages"
                    )

                    # Input section
                    with gr.Row():
                        message_input = gr.Textbox(
                            label="",
                            placeholder="Mesajınızı yazın...",
                            show_label=False,
                            scale=5
                        )
                        send_btn = gr.Button("Gönder", variant="primary", scale=1)

                # Right Sidebar
                with gr.Column(scale=1, min_width=250):
                    with gr.Tabs():
                        with gr.Tab("📊 İstatistikler"):
                            stats_output = gr.Textbox(
                                label="",
                                interactive=False,
                                lines=12,
                                show_label=False
                            )
                            stats_refresh_btn = gr.Button("Yenile", size="sm")

                        with gr.Tab("⚙️ Ayarlar"):
                            # Runtime Configuration Section
                            if self.runtime_config:
                                gr.Markdown("### 🤖 LLM Yapılandırması")

                                llm_model_input = gr.Textbox(
                                    label="Model",
                                    value=self.runtime_config.llm.model,
                                    placeholder="gpt-4o-mini",
                                    info="Kullanılacak LLM modeli"
                                )
                                llm_temp_slider = gr.Slider(
                                    minimum=0,
                                    maximum=1,
                                    value=self.runtime_config.llm.temperature,
                                    label="Sıcaklık",
                                    step=0.1,
                                    info="Model yaratıcılık derecesi"
                                )

                                # Sub-Agent Configurations
                                gr.Markdown("### 🔧 Alt-Agent Yapılandırması")

                                # Routing Agent Config
                                routing_config = self.runtime_config.get_subagent("routing")
                                gr.Markdown("**Routing Agent**")
                                routing_token_input = gr.Textbox(
                                    label="Token",
                                    value=getattr(routing_config, 'token', '') if routing_config else '',
                                    placeholder="Forza API token...",
                                    type="password",
                                    info="Routing agent için API token",
                                    interactive=True
                                )

                                routing_prompt_input = gr.Textbox(
                                    label="System Prompt",
                                    value=routing_config.system_prompt if routing_config else '',
                                    lines=3,
                                    info="Routing agent için sistem mesajı",
                                    interactive=True
                                )

                                # Chat Agent Config
                                chat_config = self.runtime_config.get_subagent("chat")
                                gr.Markdown("**Chat Agent**")
                                chat_prompt_input = gr.Textbox(
                                    label="System Prompt",
                                    value=chat_config.system_prompt if chat_config else '',
                                    lines=3,
                                    info="Chat agent için sistem mesajı",
                                    interactive=True
                                )

                                # Save Configuration Button
                                config_save_btn = gr.Button("💾 Yapılandırmayı Kaydet", variant="primary")
                                config_status = gr.Textbox(
                                    label="Durum",
                                    interactive=False,
                                    lines=2,
                                    value="",
                                    show_label=False
                                )

                                gr.Markdown("---")

                            # General UI Settings
                            gr.Markdown("### 🎨 Arayüz Ayarları")
                            response_format_dropdown = gr.Dropdown(
                                choices=[
                                    ("Tüm Mesajlar", ResponseFormat.ALL_MESSAGES),
                                    ("Sadece Son Cevap", ResponseFormat.LAST_MESSAGE_ONLY)
                                ],
                                value=ResponseFormat.ALL_MESSAGES,
                                label="Response Formatı",
                                info="Sohbetlerde gösterilecek mesaj sayısını ayarla"
                            )

                            # Token input section (legacy)
                            gr.Markdown("### 🔑 Kimlik Doğrulama (Eski)")
                            token_input = gr.Textbox(
                                label="Token",
                                placeholder="API token giriniz...",
                                type="password",
                                lines=2,
                                info="İhtiyaç durumunda API çağrıları için kullanılacak token"
                            )
                            token_status = gr.Textbox(
                                label="Durum",
                                interactive=False,
                                lines=2,
                                value="Token girilmemiş",
                                show_label=False
                            )

                        with gr.Tab("🎯 İşlemler"):
                            history_btn = gr.Button("📜 Geçmişi Yükle")
                            gr.Button("💾 Dışa Aktar")
                            clear_btn = gr.Button("🗑️ Temizle", variant="stop")

                            clear_output = gr.Textbox(
                                label="",
                                interactive=False,
                                visible=False
                            )

            # Event handlers

            # Refresh dropdown choices
            def refresh_dropdown():
                return gr.Dropdown(choices=self._get_session_dropdown_choices())

            # Load session history when dropdown selection changes
            async def load_selected_session(session_value):
                """Load the selected session's history"""
                if not session_value:
                    return []

                # session_value is tuple (display_name, session_id)
                if isinstance(session_value, tuple):
                    session_id = session_value[1]
                else:
                    session_id = session_value

                self.current_session_id = session_id
                self.session_id = session_id
                print(f"DEBUG: Session selected - {session_id}")

                return await self._load_session_history(session_id)

            # Dropdown change handler
            session_dropdown.change(
                fn=load_selected_session,
                inputs=[session_dropdown],
                outputs=[self.chatbot_component]
            ).then(
                lambda: "",
                outputs=[message_input]
            )

            # Create new session
            async def create_new_and_refresh():
                await self._create_new_session()
                return gr.Dropdown(choices=self._get_session_dropdown_choices()), []

            new_chat_btn.click(
                fn=create_new_and_refresh,
                outputs=[session_dropdown, self.chatbot_component]
            )

            # Refresh sessions dropdown
            refresh_sessions_btn.click(
                fn=lambda: gr.Dropdown(choices=self._get_session_dropdown_choices()),
                outputs=[session_dropdown]
            )

            send_btn.click(
                fn=self._handle_message,
                inputs=[message_input, self.chatbot_component],
                outputs=[self.chatbot_component]
            ).then(
                lambda: "",
                outputs=[message_input]
            )

            message_input.submit(
                fn=self._handle_message,
                inputs=[message_input, self.chatbot_component],
                outputs=[self.chatbot_component]
            ).then(
                lambda: "",
                outputs=[message_input]
            )

            history_btn.click(
                fn=self._get_history,
                outputs=[stats_output]
            )

            stats_refresh_btn.click(
                fn=self._get_stats,
                outputs=[stats_output]
            )

            clear_btn.click(
                fn=self._clear_history_handler,
                outputs=[clear_output]
            )

            # Response format setting change handler
            response_format_dropdown.change(
                fn=self._update_response_format,
                inputs=[response_format_dropdown]
            )

            # Token input handler
            token_input.change(
                fn=self._update_token,
                inputs=[token_input],
                outputs=[token_status]
            ).then(
                lambda: "",
                outputs=[message_input]
            )

            # Runtime Configuration Handlers
            if self.runtime_config:
                def save_runtime_config(llm_model, llm_temp, routing_token, routing_prompt, chat_prompt):
                    """Save updated runtime configuration"""
                    try:
                        # Update LLM config
                        new_config = self.runtime_config.update_llm(
                            model=llm_model,
                            temperature=llm_temp
                        )

                        # Update routing agent if exists
                        if new_config.get_subagent("routing"):
                            new_config = new_config.update_subagent(
                                "routing",
                                token=routing_token,
                                system_prompt=routing_prompt
                            )

                        # Update chat agent if exists
                        if new_config.get_subagent("chat"):
                            new_config = new_config.update_subagent(
                                "chat",
                                system_prompt=chat_prompt
                            )

                        # Apply new configuration to chatbot
                        self.runtime_config = new_config
                        if self.chat_service.chatbot:
                            self.chat_service.chatbot.update_runtime_config(new_config)

                        return "✓ Yapılandırma başarıyla kaydedildi!\n\nNot: Model değişiklikleri yeni oturumlarda geçerli olacaktır."

                    except Exception as e:
                        return f"✗ Hata: {str(e)}"

                # Build input list - inputs are always available now
                config_inputs = [
                    llm_model_input,
                    llm_temp_slider,
                    routing_token_input,
                    routing_prompt_input,
                    chat_prompt_input
                ]

                config_save_btn.click(
                    fn=save_runtime_config,
                    inputs=config_inputs,
                    outputs=[config_status]
                )

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
            show_error=True,
            favicon_path="assets/boticon.png"
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
