from src.models.llm import LLM


class LLMFactory:
    @staticmethod
    def from_config(config) -> LLM:
        return LLM(
            provider=config.provider,
            model=config.model,
            temperature=config.temperature,
            api_key=config.api_key,
            base_url=getattr(config, 'base_url', None)
        )
