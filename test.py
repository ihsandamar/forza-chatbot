

from src.models.llm import LLM
from src.services.config_loader import ConfigLoader



config = ConfigLoader.load_config("config/config.yaml")
llm = LLM(provider=config.llm.provider, model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key, base_url=getattr(config.llm, 'base_url', None))


result = llm.get_chat().invoke([{"role": "user", "content": "Hello, how are you?"}])
print(result)