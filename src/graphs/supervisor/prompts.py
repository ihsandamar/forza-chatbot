"""
Supervisor Agents - LLM agents for the supervisor system
"""
from langchain_core.messages import SystemMessage
from src.graphs.supervisor.tools import get_current_time, get_supervisor_status


SUPERVISOR_SYSTEM_PROMPT = """You are a helpful supervisor agent that coordinates between different specialist agents.
Your role is to:
1. Understand the user's request
2. Route to the appropriate specialist agent
3. Collect results and provide comprehensive responses

Be friendly, professional, and proactive in helping users."""


