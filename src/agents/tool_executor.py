# src/agents/tool_executor.py
from src.models.models import State
from langchain_core.tools import BaseTool
from typing import Dict, Any
from src.tools.assistance_tools import AssistanceToolkit
from src.tools.math_tools import MathToolkit  # Gerekirse başka toolkitler de buraya eklenebilir
from src.tools.date_tool import DateToolkit  # Tarih işlemleri için eklenen toolkit


class ToolExecutor:
    def __init__(self):
        # Tüm kullanılabilir tool'ları bir araya getir
        self.available_tools = self._load_all_tools()

    def _load_all_tools(self) -> Dict[str, BaseTool]:
        """
        Tüm toolkit'lerden tool'ları al ve isimlerine göre bir dict oluştur.
        """
        all_toolkits = [
            MathToolkit(),  # gelecekte başka toolkitler eklenebilir
            DateToolkit(),  # Tarih işlemleri için eklenen toolkit
            AssistanceToolkit()  # Yardımcı araçlar için eklenen toolkit
        ]
        tool_dict = {}
        for toolkit in all_toolkits:
            for tool in toolkit.get_tools():
                tool_name = getattr(tool, "name", None)
                if tool_name:
                    tool_dict[tool_name] = tool
                else:
                    print(f"[ToolExecutor] Tool name bulunamadı: {tool}")
        return tool_dict

    def run(self, state: State) -> State:
        messages = state["messages"]
        tool_calls = state.get("tool_calls", [])
        tool_outputs = []

        if not tool_calls:
            return {"messages": messages, "tool_calls": []}

        for call in tool_calls:
            tool_name = call.get("name")
            args = call.get("args", {})
            tool_call_id = call.get("id") or call.get("tool_call_id")

            tool = self.available_tools.get(tool_name)
            if not tool:
                result = f"🚫 Tool '{tool_name}' bulunamadı."
            else:
                try:
                    result = tool.invoke(args)
                except Exception as e:
                    result = f"[ERROR] Tool '{tool_name}' hatası: {str(e)}"

            tool_outputs.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": str(result),
            })

        updated_messages = messages + tool_outputs

        return {
            "messages": updated_messages,
            "tool_calls": [],
        }
