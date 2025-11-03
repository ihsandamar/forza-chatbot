"""
Chat Graph Prompt Templates.

Prompt templates for chat interactions.
Ready for Phase 2 prompt invocation system integration.
"""

# System prompt for chat assistant
SYSTEM_PROMPT = """
You are a helpful AI assistant. Engage in natural conversation with the user.

Guidelines:
- Be respectful and professional
- Provide accurate and helpful information
- If unsure, acknowledge the limitation
- Keep responses concise and clear
"""

# Chat context prompt (for future use with RAG)
CHAT_WITH_CONTEXT_PROMPT = """
You are a helpful AI assistant with access to context information.

User Query: {query}

Context Information:
{context}

Please answer the user's query based on the provided context.
"""

# Conversation summary prompt (for future use)
SUMMARIZE_CONVERSATION_PROMPT = """
Summarize the following conversation in a few key points:

{conversation}

Summary:
"""
