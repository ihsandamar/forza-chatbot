"""
VegaForza Navigation State Adapter

Adapter for the VegaForza navigation graph which uses a custom state format
focused on navigation, document retrieval, and parameter filling.
"""

import json
from typing import Any, Dict, List
from src.adapters.base_state_adapter import BaseStateAdapter


class VegaforzaStateAdapter(BaseStateAdapter):
    """
    Adapter for VegaForza navigation graph.

    Converts between standard message format and NavigationState format.

    NavigationState format:
    {
        "user_input": str,
        "token": str,
        "related_pages": List[tuple],
        "most_related_document": Document,
        "has_parameters": bool,
        "filled_parameters": Dict,
        "tool_results_valid": bool,
        ...
    }

    NavigationOutput format:
    {
        "page_id": str,
        "page_title": str,
        "url": str,
        "requires_parameters": bool,
        "confidence": float,
        ...
    }
    """

    def to_graph_state(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """
        Convert messages to NavigationState format.

        Args:
            messages: List of message dicts
            **kwargs: Must contain 'token' for API authentication

        Returns:
            NavigationState dictionary

        Raises:
            ValueError: If 'token' not provided in kwargs

        Example:
            >>> adapter = VegaforzaStateAdapter()
            >>> messages = [{"role": "user", "content": "Müşteri listesi"}]
            >>> state = adapter.to_graph_state(messages, token="abc123")
            >>> print(state)
            {
                "user_input": "Müşteri listesi",
                "token": "abc123",
                "related_pages": [],
                ...
            }
        """
        # Extract token from kwargs
        token = kwargs.get("token")
        if not token:
            raise ValueError("VegaforzaStateAdapter requires 'token' parameter")

        # Extract user input from last message
        user_input = ""
        if messages:
            last_message = messages[-1]
            user_input = last_message.get("content", "")

        # Create NavigationState
        state = {
            "user_input": user_input,
            "token": token,
            "related_pages": [],
            "most_related_document": None,
            "has_parameters": False,
            "filled_parameters": None,
            "tool_results": None,
            "tool_results_valid": None,
            "tried_page_ids": None,
            "retry_count": None,
            "no_more_alternatives": None,
        }

        return state

    def from_graph_state(self, graph_output: Any) -> str:
        """
        Convert NavigationOutput to user-friendly response.

        Args:
            graph_output: NavigationOutput dict from graph

        Returns:
            Formatted string response for user

        Example:
            >>> output = {
            ...     "page_title": "Müşteri Listesi",
            ...     "url": "/customers",
            ...     "suggestion_text": "Bu sayfada müşteri listesini görebilirsiniz",
            ...     "confidence": 0.95
            ... }
            >>> response = adapter.from_graph_state(output)
            >>> print(response)
            '''
            📄 **Müşteri Listesi**
            🔗 URL: /customers

            💡 Bu sayfada müşteri listesini görebilirsiniz
            '''
        """
        if not isinstance(graph_output, dict):
            return str(graph_output)

        # Extract key information
        page_title = graph_output.get("page_title", "Sayfa")
        url = graph_output.get("url", "")
        suggestion_text = graph_output.get("suggestion_text", "")
        requires_parameters = graph_output.get("requires_parameters", False)
        parameters = graph_output.get("parameters", {})
        filled_parameters = graph_output.get("filled_parameters", {})
        confidence = graph_output.get("confidence", 0.0)
        is_sub_page = graph_output.get("is_sub_page", False)
        parent_page_title = graph_output.get("parent_page_title", "")
        full_path = graph_output.get("full_path", "")

        # Build response
        response_parts = []

        # Title section
        if is_sub_page and parent_page_title:
            response_parts.append(f"📄 **{page_title}** (Alt Sayfa: {parent_page_title})")
            if full_path:
                response_parts.append(f"📂 {full_path}")
        else:
            response_parts.append(f"📄 **{page_title}**")

        # URL section
        if url:
            response_parts.append(f"🔗 URL: `{url}`")

        # Suggestion text
        if suggestion_text:
            response_parts.append(f"\n💡 {suggestion_text}")

        # Parameter information
        if requires_parameters and parameters:
            response_parts.append(f"\n⚙️ **Gerekli Parametreler:**")
            for param_name, param_info in parameters.items():
                param_desc = param_info.get("description", "")
                param_type = param_info.get("type", "string")
                required = "[CHECK] Zorunlu" if param_info.get("required", False) else "○ Opsiyonel"
                response_parts.append(f"  • `{param_name}` ({param_type}) - {param_desc} [{required}]")

        # Filled parameters (if any)
        if filled_parameters:
            response_parts.append(f"\n[OK] **Doldurulmuş Parametreler:**")
            for param_name, param_data in filled_parameters.items():
                if isinstance(param_data, dict):
                    value = param_data.get("value", "")
                    display = param_data.get("display_name", "")
                    if display:
                        response_parts.append(f"  • `{param_name}`: {display} ({value})")
                    else:
                        response_parts.append(f"  • `{param_name}`: {value}")

        # Confidence indicator (only if low)
        if confidence < 0.7:
            response_parts.append(f"\n[WARNING] Eşleşme güveni düşük: {confidence:.0%}")

        return "\n".join(response_parts)

    def get_required_params(self) -> List[str]:
        """
        Get required parameters for this adapter.

        Returns:
            List containing 'token'
        """
        return ["token"]

    def to_api_response(self, graph_output: Any) -> Dict[str, Any]:
        """
        Convert NavigationOutput to API response format.

        This is a bonus method specifically for API responses,
        keeping the structured data intact.

        Args:
            graph_output: NavigationOutput dict from graph

        Returns:
            API-friendly response dict

        Example:
            >>> output = {"page_title": "Customers", "url": "/customers"}
            >>> api_response = adapter.to_api_response(output)
            >>> print(api_response)
            {
                "text": "📄 **Customers**...",
                "type": "navigation",
                "confidence": 0.85,
                "action": {
                    "type": "navigation",
                    "target": "/customers",
                    "params": {}
                },
                "metadata": {
                    "page_title": "Customers",
                    "url": "/customers",
                    ...
                }
            }
        """
        if not isinstance(graph_output, dict):
            return {
                "text": str(graph_output),
                "type": "text",
                "confidence": 0.0,
                "action": {"type": "none", "target": "", "params": {}},
            }

        # Generate text response
        text_response = self.from_graph_state(graph_output)

        # Build action object
        action = {
            "type": "routing",
            "target": graph_output.get("url", ""),
            "params": graph_output.get("filled_parameters", {}),
        }

        # Extract confidence and ensure it's not None
        confidence = graph_output.get("confidence", 0.85)
        if confidence is None:
            confidence = 0.85

        return {
            "text": text_response,
            "type": "navigation",
            "confidence": confidence,
            "action": action,
            "metadata": graph_output,  # Include full output as metadata
        }
