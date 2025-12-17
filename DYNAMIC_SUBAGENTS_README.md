# Dynamic Sub-Agent Detection System

LangGraph Studio gibi, AssistantConfiguration Pydantic Field metadata'sından otomatik sub-agent tespiti.

## Problem

**Eskiden:** Hard-coded graph type kontrolleri
```python
if graph_type == "supervisor":
    runtime_config = runtime_config.add_subagent(...)
elif graph_type == "routing":
    runtime_config = runtime_config.add_subagent(...)
```

**Sorun:**
- ❌ Her yeni graph için kod değişikliği gerekir
- ❌ DRY ihlali (configuration iki yerde: AssistantConfiguration + main.py)
- ❌ Open/Closed prensibine aykırı
- ❌ Bakım zorluğu

## Çözüm: Dynamic Sub-Agent Detection

**Şimdi:** Metadata'dan otomatik tespit
```python
runtime_config = RuntimeConfiguration.from_config_with_assistant(
    config=config,
    assistant_config_class=SupervisorAssistantConfiguration,
    graph_type="supervisor"
)
# Otomatik olarak routing ve chat sub-agent'ları tespit eder!
```

**Avantajlar:**
- ✅ Zero hard-coded checks
- ✅ DRY: Configuration tek yerde (AssistantConfiguration)
- ✅ Open/Closed: Yeni agent'lar için kod değişikliği yok
- ✅ KISS: Basit ve otomatik
- ✅ LangGraph Studio uyumlu

## Nasıl Çalışır?

### 1. AssistantConfiguration'da Field Metadata

```python
class SupervisorAssistantConfiguration(BaseAssistantConfiguration):
    routing_token: str = Field(
        default="",
        description="Forza API token for routing agent",
        json_schema_extra={"langgraph_nodes": ["routing"]}  # 👈 Bu!
    )

    routing_system_prompt: str = Field(
        default="Sen Forza navigasyon asistanısın...",
        json_schema_extra={"langgraph_nodes": ["routing"], "langgraph_type": "prompt"}
    )

    chat_system_prompt: str = Field(
        default="Sen yardımcı bir sohbet asistanısın...",
        json_schema_extra={"langgraph_nodes": ["chat"], "langgraph_type": "prompt"}
    )
```

### 2. Otomatik Sub-Agent Extraction

```python
subagents = RuntimeConfiguration.extract_subagents_from_assistant_config(
    SupervisorAssistantConfiguration
)

# Returns:
# {
#     "routing": SubAgentRuntimeConfig(
#         name="routing",
#         system_prompt="Sen Forza navigasyon asistanısın...",
#         model="anthropic:claude-haiku-4-5",
#         token="<from-env-or-field>"
#     ),
#     "chat": SubAgentRuntimeConfig(
#         name="chat",
#         system_prompt="Sen yardımcı bir sohbet asistanısın...",
#         model="anthropic:claude-haiku-4-5"
#     )
# }
```

### 3. Field Name Pattern

Field adları şu pattern'i takip eder: `{agent_name}_{property}`

```
routing_token       → routing agent, token property
routing_system_prompt → routing agent, system_prompt property
chat_system_prompt  → chat agent, system_prompt property
finance_model       → finance agent, model property
```

### 4. Token Resolution Strategy

Token field için çoklu kaynak desteği:

1. Field value (programatik set edilmişse)
2. Field default (default değer varsa)
3. `{AGENT_NAME}_TOKEN` env variable (örn: `ROUTING_TOKEN`)
4. `FORZA_TOKEN` env variable (routing agent için fallback)

```python
# Örnek:
routing_token: str = Field(default="")

# Sistem şu sırayla arar:
# 1. Field'a set edilen değer
# 2. Field default ("" - boş)
# 3. os.getenv("ROUTING_TOKEN")
# 4. os.getenv("FORZA_TOKEN")  # routing için özel
```

## Kullanım

### Basit Kullanım

```python
from src.core.runtime_config import RuntimeConfiguration
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration

# Otomatik sub-agent detection
runtime_config = RuntimeConfiguration.from_config_with_assistant(
    config=loaded_config,
    assistant_config_class=SupervisorAssistantConfiguration,
    graph_type="supervisor"
)

print(runtime_config.subagents.keys())  # ['routing', 'chat']
```

### main.py İmplementasyonu

```python
def build_chatbot(config_path: str, entrypoint_function: str = None):
    config = ConfigLoader.load_config(config_path)
    graph_type = entrypoint_function or config.chatbot.graph_type

    # Dynamic AssistantConfiguration detection
    assistant_config_class = None
    if graph_type == "supervisor":
        from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration
        assistant_config_class = SupervisorAssistantConfiguration
    elif graph_type == "routing":
        from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration
        assistant_config_class = RoutingAssistantConfiguration

    # Automatic sub-agent detection
    runtime_config = RuntimeConfiguration.from_config_with_assistant(
        config=config,
        assistant_config_class=assistant_config_class,
        graph_type=graph_type
    )

    # No more hard-coded if statements!
    return chatbot, runtime_config
```

## Yeni Sub-Agent Ekleme

### 1. AssistantConfiguration'a Field Ekle

```python
class SupervisorAssistantConfiguration(BaseAssistantConfiguration):
    # Yeni agent: finance
    finance_system_prompt: str = Field(
        default="You are a financial analysis agent",
        json_schema_extra={"langgraph_nodes": ["finance"]}
    )

    finance_model: str = Field(
        default="gpt-4o",
        json_schema_extra={"langgraph_nodes": ["finance"]}
    )

    finance_api_key: str = Field(
        default="",
        json_schema_extra={"langgraph_nodes": ["finance"]}
    )
```

### 2. Hepsi Bu Kadar!

```python
# Otomatik olarak finance agent tespit edilir
runtime_config = RuntimeConfiguration.from_config_with_assistant(
    config=config,
    assistant_config_class=SupervisorAssistantConfiguration
)

print(runtime_config.subagents.keys())
# ['routing', 'chat', 'finance']  # 👈 finance otomatik eklendi!
```

## Test

### Test 1: Sub-Agent Detection

```python
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration

subagents = RuntimeConfiguration.extract_subagents_from_assistant_config(
    SupervisorAssistantConfiguration
)

assert "routing" in subagents
assert "chat" in subagents
assert subagents["routing"].token  # From FORZA_TOKEN env
```

### Test 2: Full Integration

```bash
python test_full_integration.py
```

Output:
```
[OK] Detected 2 sub-agents:
  Agent: routing
    - Token: test-token...
  Agent: chat
    - System Prompt: Sen yardımcı bir sohbet...

[OK] FULL INTEGRATION TEST PASSED!
```

## Karşılaştırma

### Eskiden (Hard-Coded)

```python
# main.py
if graph_type == "supervisor":
    runtime_config = runtime_config.add_subagent(SubAgentRuntimeConfig(
        name="routing",
        system_prompt="Sen Forza navigasyon...",
        token=os.getenv("FORZA_TOKEN")
    ))
    runtime_config = runtime_config.add_subagent(SubAgentRuntimeConfig(
        name="chat",
        system_prompt="Sen yardımcı bir sohbet..."
    ))
```

**Sorunlar:**
- 20+ satır kod
- Her agent için hard-coded if
- DRY ihlali
- Maintenance nightmare

### Şimdi (Dynamic)

```python
# main.py
runtime_config = RuntimeConfiguration.from_config_with_assistant(
    config=config,
    assistant_config_class=SupervisorAssistantConfiguration,
    graph_type="supervisor"
)
```

**Avantajlar:**
- 4 satır kod
- Zero hard-coded checks
- DRY compliant
- Self-documenting

## LangGraph Studio Uyumluluk

Bu sistem, LangGraph Studio'nun kullandığı metadata formatı ile tamamen uyumludur:

```python
Field(
    json_schema_extra={
        "langgraph_nodes": ["node_name"],      # Node mapping
        "langgraph_type": "prompt"             # Field type
    }
)
```

LangGraph Studio bu metadata'yı UI'da gösterir, bizim sistem ise runtime'da sub-agent'ları otomatik tespit eder.

## API

### RuntimeConfiguration.extract_subagents_from_assistant_config()

```python
@classmethod
def extract_subagents_from_assistant_config(
    cls,
    assistant_config_class: Type,
    assistant_config_instance: Optional[Any] = None
) -> Dict[str, SubAgentRuntimeConfig]:
    """
    Dynamically extract sub-agent configurations from AssistantConfiguration.

    Args:
        assistant_config_class: Pydantic model class
        assistant_config_instance: Optional instance with values

    Returns:
        Dict of {agent_name: SubAgentRuntimeConfig}
    """
```

### RuntimeConfiguration.from_config_with_assistant()

```python
@classmethod
def from_config_with_assistant(
    cls,
    config,
    assistant_config_class: Optional[Type] = None,
    assistant_config_instance: Optional[Any] = None,
    graph_type: Optional[str] = None,
    thread_id: Optional[str] = None
) -> 'RuntimeConfiguration':
    """
    Create RuntimeConfiguration with automatic sub-agent detection.

    Args:
        config: Config from ConfigLoader
        assistant_config_class: AssistantConfiguration class
        assistant_config_instance: Optional instance
        graph_type: Graph type
        thread_id: Session thread ID

    Returns:
        RuntimeConfiguration with detected sub-agents
    """
```

## Best Practices

### 1. Consistent Field Naming

```python
# Good
routing_system_prompt
routing_token
routing_model

# Bad
routingSystemPrompt  # camelCase
routing_sys_prompt   # abbreviated
```

### 2. Always Use json_schema_extra

```python
# Good
Field(
    json_schema_extra={"langgraph_nodes": ["routing"]}
)

# Bad - Will not be detected
Field()
```

### 3. Token Field Naming

```python
# For routing agent, use:
routing_token: str = Field(...)

# System will check:
# 1. Field value
# 2. ROUTING_TOKEN env
# 3. FORZA_TOKEN env (fallback)
```

## Migration Guide

### Mevcut Koddan Geçiş

1. **AssistantConfiguration oluştur/güncelle:**
   ```python
   class MyAssistantConfiguration(BaseAssistantConfiguration):
       agent1_system_prompt: str = Field(
           json_schema_extra={"langgraph_nodes": ["agent1"]}
       )
   ```

2. **main.py'daki hard-coded if'leri kaldır:**
   ```python
   # Sil:
   if graph_type == "my_graph":
       runtime_config = runtime_config.add_subagent(...)

   # Ekle:
   runtime_config = RuntimeConfiguration.from_config_with_assistant(
       config=config,
       assistant_config_class=MyAssistantConfiguration
   )
   ```

3. **Test et:**
   ```bash
   python test_dynamic_subagents.py
   ```

## Troubleshooting

### "No sub-agents detected"

**Neden:** Field'larda `json_schema_extra` yok.

**Çözüm:**
```python
Field(json_schema_extra={"langgraph_nodes": ["agent_name"]})
```

### "Token is None"

**Neden:** Environment variable set edilmemiş.

**Çözüm:**
```bash
export FORZA_TOKEN="your-token"
# veya
export ROUTING_TOKEN="your-token"
```

### "Wrong agent name detected"

**Neden:** Field name pattern hatalı.

**Çözüm:** `{agent_name}_{property}` formatını kullan:
```python
# Good
routing_token

# Bad
token_for_routing
```

## Sonuç

Dynamic sub-agent detection sistemi:

- ✅ **Zero Hard-Coded Checks**: If statements yok
- ✅ **DRY**: Configuration tek yerde
- ✅ **SOLID**: Open/Closed prensibi
- ✅ **KISS**: Basit ve otomatik
- ✅ **Scalable**: Sınırsız sub-agent desteği
- ✅ **LangGraph Studio Compatible**: Aynı metadata formatı

Yeni graph/agent eklerken artık sadece AssistantConfiguration'a field eklemeniz yeterli!
