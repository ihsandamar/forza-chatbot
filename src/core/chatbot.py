
from typing import List, Tuple, Optional
from src.graphs.base_graph import BaseGraph
from src.graphs.chat_graph import ChatGraph
from src.models.models import LLM
from src.adapters.base_state_adapter import BaseStateAdapter
from src.adapters.default_state_adapter import DefaultStateAdapter


class Chatbot:
    def __init__(
        self,
        llm: LLM,
        graph: BaseGraph,
        config: dict = None,
        assistant_config: dict = None,
        adapter: Optional[BaseStateAdapter] = None
    ):
        self.llm = llm
        self.graph = graph
        self.history = []
        self.config = config if config else {}
        self.assistant_config = assistant_config if assistant_config else {}
        # Use provided adapter or default to DefaultStateAdapter
        self.adapter = adapter if adapter else DefaultStateAdapter()

    def response_handler(self, history: List[Tuple[str, str]], message: str) -> List[Tuple[str, str]]:
        """
        Response handler for Gradio 'chat' type.
        message: single message from the user
        history: [(user_msg: str, bot_msg: str), ...]
        Returns the history in the same format [(user_msg, bot_msg)].
        """

        # LangGraph'e uygun mesaj listesi oluştur
        messages = []
        for user_msg, bot_msg in history:
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if bot_msg:
                messages.append({"role": "assistant", "content": bot_msg})

        # Yeni gelen kullanıcı mesajını da ekle

        messages.append({"role": "user", "content": message})

        # State hazırla ve invoke et
        state = {"messages": messages}
        # Config'e assistant_config'i ekle (LangGraph configurable içinde)
        assistant_config_dict = self.assistant_config.to_dict() if hasattr(self.assistant_config, 'to_dict') else self.assistant_config
        full_config = self.config.copy()
        if "configurable" not in full_config:
            full_config["configurable"] = {}
        full_config["configurable"]["assistant_config"] = assistant_config_dict
        response = self.graph.invoke(state, config=full_config)

        # Asistan cevabını al
        if "messages" in response and isinstance(response["messages"], list):
            last = response["messages"][-1]
            content = last.content if hasattr(last, "content") else last.get("content", "")
            # Yeni çifti geçmişe ekleyip döndür
            history.append((message, content))
            return history

        # Hata varsa kullanıcıya mesaj döndür
        history.append((message, "Bir hata oluştu, lütfen tekrar deneyin."))
        return history
    
    def send(self, state: dict, **adapter_kwargs) -> str:
        """
        Tüm arayüzlerde kullanılabilecek sade mesaj gönderici fonksiyonu.
        Adapter pattern kullanarak farklı graph state formatlarını destekler.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Adapter'a iletilecek ek parametreler (örn: token)

        Returns:
            string cevap
        """
        # Extract messages from state
        messages = state.get("messages", [])

        # Convert messages to graph-specific state using adapter
        graph_state = self.adapter.to_graph_state(messages, **adapter_kwargs)

        # Prepare config with assistant_config
        assistant_config_dict = self.assistant_config.to_dict() if hasattr(self.assistant_config, 'to_dict') else self.assistant_config
        full_config = self.config.copy()
        if "configurable" not in full_config:
            full_config["configurable"] = {}
        full_config["configurable"]["assistant_config"] = assistant_config_dict

        # Invoke graph with adapted state
        graph_output = self.graph.invoke(graph_state, config=full_config)

        # Convert graph output back to standard format using adapter
        response_text = self.adapter.from_graph_state(graph_output)

        return response_text

    def send_structured(self, state: dict, **adapter_kwargs) -> dict:
        """
        Structured response döndüren mesaj gönderici fonksiyonu.
        API responses için kullanılır.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Adapter'a iletilecek ek parametreler (örn: token)

        Returns:
            dict with text, type, confidence, action, metadata
        """
        # Extract messages from state
        messages = state.get("messages", [])

        # Convert messages to graph-specific state using adapter
        graph_state = self.adapter.to_graph_state(messages, **adapter_kwargs)

        # Prepare config with assistant_config
        assistant_config_dict = self.assistant_config.to_dict() if hasattr(self.assistant_config, 'to_dict') else self.assistant_config
        full_config = self.config.copy()
        if "configurable" not in full_config:
            full_config["configurable"] = {}
        full_config["configurable"]["assistant_config"] = assistant_config_dict

        # Invoke graph with adapted state
        graph_output = self.graph.invoke(graph_state, config=full_config)

        # Use adapter's to_api_response if available, otherwise fallback to text
        if hasattr(self.adapter, 'to_api_response'):
            return self.adapter.to_api_response(graph_output)
        else:
            # Fallback to text-only response
            response_text = self.adapter.from_graph_state(graph_output)
            return {
                "text": response_text,
                "type": "text",
                "confidence": 0.95,
                "action": {"type": "none", "target": "", "params": {}}
            }