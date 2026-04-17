"""
Supervisor Utility Tools — agent yönlendirme araçları değil,
yardımcı araçlar. Yönlendirme araçları SupervisorGraph.build_graph()
içinde dinamik olarak üretilir.
"""
from langchain_core.tools import tool
from datetime import datetime


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def get_supervisor_status() -> str:
    """Get the current status of the supervisor system."""
    return "Supervisor is operational and ready to assist."
