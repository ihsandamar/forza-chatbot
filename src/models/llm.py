from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic


class LLM:
    def __init__(self, provider: str = "openai", model: str = "gpt-4o-mini", temperature: float = 0.0, api_key: str = None, base_url: str = None):
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url
        self._chat_instance = None

    def get_chat(self):
        if self._chat_instance is not None:
            return self._chat_instance
        if self.provider == "openai":
            self._chat_instance = ChatOpenAI(model=self.model, temperature=self.temperature, api_key=self.api_key)
        elif self.provider == "anthropic":
            self._chat_instance = ChatAnthropic(model=self.model, temperature=self.temperature, api_key=self.api_key)
        elif self.provider == "ollama":
            from langchain_ollama import ChatOllama
            self._chat_instance = ChatOllama(model=self.model, temperature=self.temperature, base_url=self.base_url)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
        return self._chat_instance