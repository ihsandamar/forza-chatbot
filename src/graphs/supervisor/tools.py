"""
Supervisor Tools - Tools available for the supervisor agent
"""
from langchain_core.tools import tool
from datetime import datetime
from src.graphs.supervisor.utilities import create_handoff_tool

@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def get_supervisor_status() -> str:
    """Get the current status of the supervisor system."""
    return "Supervisor is operational and ready to assist."



# Create handoff tools for sub-agents
assign_to_chat_agent = create_handoff_tool(
    agent_name="chat",
    description="Assign task to chat agent for chat and conversation tasks.",
)

assign_to_routing_agent = create_handoff_tool(
    agent_name="routing",
    description="Assign task to routing agent for Forza page routing and navigation tasks.",
)

assign_to_report_agent = create_handoff_tool(
    agent_name="report",
    description="Assign task to report agent for data analysis, SQL queries, reports, visualizations, charts, and master report queries.",
)
