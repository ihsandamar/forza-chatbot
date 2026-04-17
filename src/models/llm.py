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

    @classmethod
    def from_override(cls, base: "LLM", model_string: str) -> "LLM":
        """Create a new LLM inheriting base settings but overriding provider/model.

        Args:
            base: Base LLM — temperature, api_key, base_url inherited from here.
            model_string: "provider:model" (e.g. "anthropic:claude-haiku-4-5")
                          or plain "model" (e.g. "gpt-4.1-mini", provider from base).

        Returns:
            New LLM instance — base is not mutated.
        """
        if ":" in model_string:
            provider, model = model_string.split(":", 1)
            if not provider or not model:
                raise ValueError(
                    f"Invalid model_string {model_string!r}: expected 'provider:model' or plain 'model'"
                )
        else:
            if not model_string:
                raise ValueError(
                    "model_string must not be empty"
                )
            provider, model = base.provider, model_string

        return cls(
            provider=provider,
            model=model,
            temperature=base.temperature,
            api_key=base.api_key,
            base_url=base.base_url if provider == base.provider else None,
        )