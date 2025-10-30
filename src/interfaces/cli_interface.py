# interfaces/cli_interface.py
import os
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich.live import Live
from rich.spinner import Spinner
from rich import print as rprint
import time
from datetime import datetime

class ModernCLI:
    def __init__(self, chatbot):
        # Force UTF-8 encoding for Windows
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        
        # Initialize console with safe settings for Windows
        self.console = Console(
            force_terminal=True,
            legacy_windows=False,
            safe_box=True,
            width=120
        )
        self.chatbot = chatbot
        
    def show_welcome(self):
        """Display welcome screen"""
        welcome_text = Text()
        welcome_text.append("AI Chatbot", style="bold blue")
        welcome_text.append(" - Gelişmiş Sohbet Asistanı", style="dim")
        
        info_panel = Panel.fit(
            welcome_text,
            style="bright_blue",
            padding=(1, 2)
        )
        
        help_text = Text()
        help_text.append("Komutlar: ", style="bold")
        help_text.append("'exit', 'quit' - Çıkış | ", style="green")
        help_text.append("'clear' - Ekranı temizle | ", style="yellow")
        help_text.append("'help' - Yardım", style="cyan")
        
        commands_panel = Panel.fit(
            help_text,
            title="Kullanım",
            style="bright_green"
        )
        
        self.console.print(info_panel)
        self.console.print(commands_panel)
        self.console.print()
        
    def show_thinking(self, message="Düşünüyor..."):
        """Show thinking animation"""
        return Spinner("dots", text=message, style="cyan")
    
    def format_user_message(self, message):
        """Format user message"""
        timestamp = datetime.now().strftime("%H:%M")
        user_panel = Panel(
            message,
            title=f"[bold green]Siz[/bold green] [dim]({timestamp})[/dim]",
            style="green",
            width=80
        )
        return Align.left(user_panel)
    
    def format_bot_response(self, response):
        """Format bot response"""
        timestamp = datetime.now().strftime("%H:%M")
        
        # Try to render as markdown if it contains formatting
        if any(marker in response for marker in ['**', '*', '#', '```', '- ']):
            content = Markdown(response)
        else:
            content = Text(response, style="white")
        
        bot_panel = Panel(
            content,
            title=f"[bold blue]AI Asistan[/bold blue] [dim]({timestamp})[/dim]",
            style="blue",
            width=80
        )
        return Align.right(bot_panel)
    
    def show_help(self):
        """Show help information"""
        help_content = """
# Yardım

## Kullanılabilir Komutlar:
- **exit** veya **quit**: Uygulamadan çık
- **clear**: Ekranı temizle  
- **help**: Bu yardım mesajını göster

## Kullanım İpuçları:
- Doğal dille sorularınızı sorun
- Uzun metinler için markdown formatını destekler
- Ctrl+C ile acil çıkış yapabilirsiniz

## Örnekler:
- "Bugün hava nasıl?"
- "Python'da liste nasıl oluşturulur?"
- "SQL sorgusu yazmama yardım et"
        """
        
        help_panel = Panel(
            Markdown(help_content.strip()),
            title="Yardım",
            style="bright_yellow"
        )
        self.console.print(help_panel)
    
    def run(self):
        """Main CLI loop with rich interface"""
        try:
            self.show_welcome()
            
            while True:
                try:
                    # Get user input with rich prompt
                    user_input = Prompt.ask(
                        "[bold green]>>[/bold green]",
                        console=self.console
                    )
                    
                    # Handle commands
                    if user_input.lower() in {"exit", "quit"}:
                        goodbye_panel = Panel.fit(
                            Text("Görüşmek üzere!", style="bold green"),
                            style="bright_green"
                        )
                        self.console.print(goodbye_panel)
                        break
                        
                    elif user_input.lower() == "clear":
                        self.console.clear()
                        self.show_welcome()
                        continue
                        
                    elif user_input.lower() == "help":
                        self.show_help()
                        continue
                        
                    elif not user_input.strip():
                        continue
                    
                    # Display user message
                    self.console.print(self.format_user_message(user_input))
                    
                    # Show thinking animation while processing
                    with Live(
                        self.show_thinking("AI yanıt hazırlıyor..."),
                        console=self.console,
                        refresh_per_second=10
                    ):
                        try:
                            response = self.chatbot.send({
                                "messages": [{"role": "user", "content": user_input}]
                            })
                        except Exception as e:
                            response = f"Hata oluştu: {str(e)}"
                    
                    # Display bot response
                    self.console.print(self.format_bot_response(response))
                    self.console.print()  # Add spacing
                    
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Çıkmak için 'exit' yazın[/yellow]")
                    continue
                    
                except Exception as e:
                    error_panel = Panel.fit(
                        f"Hata: {str(e)}",
                        style="bright_red",
                        title="Error"
                    )
                    self.console.print(error_panel)
                    
        except KeyboardInterrupt:
            self.console.print("\n[bright_red]Program sonlandırıldı[/bright_red]")

def run_cli(chatbot):
    """Legacy function for backwards compatibility"""
    cli = ModernCLI(chatbot)
    cli.run()
