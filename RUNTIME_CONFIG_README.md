# Runtime Configuration System

Dinamik runtime configuration sistemi ile chatbot'unuzu çalışma anında yapılandırabilirsiniz.

## Genel Bakış

Bu sistem, KISS (Keep It Simple, Stupid) ve SOLID prensipleri ile tasarlanmış, runtime'da değiştirilebilir yapılandırma mekanizması sağlar.

### Özellikler

- ✅ **Dinamik Yapılandırma**: LLM modeli, temperature, API key gibi ayarları runtime'da değiştirin
- ✅ **Sub-Agent Yönetimi**: Her alt-agent için ayrı yapılandırma (routing, chat, vs.)
- ✅ **Thread-Safe**: Immutable update pattern ile güvenli güncellemeler
- ✅ **Interface Desteği**: Gradio UI'da ayarlar sekmesi
- ✅ **KISS Prensibi**: Basit, anlaşılır API
- ✅ **SOLID Prensibi**: Clean architecture ve separation of concerns

## Mimari

```
main.py
  └─> RuntimeConfiguration (from config file + env)
       ├─> LLMRuntimeConfig (model, temperature, api_key)
       ├─> SubAgentRuntimeConfig (routing: token, system_prompt)
       └─> SubAgentRuntimeConfig (chat: system_prompt)
            └─> ChatbotBuilder.with_runtime_config()
                 └─> Chatbot (with runtime_config)
                      └─> Interface (Gradio, FastAPI, CLI)
                           └─> Settings UI (update config at runtime)
```

## Kullanım

### 1. Temel Kullanım (main.py)

```python
from src.core.runtime_config import (
    RuntimeConfiguration,
    LLMRuntimeConfig,
    SubAgentRuntimeConfig
)

# Config'den oluştur
config = RuntimeConfiguration.from_config_loader(
    config=loaded_config,
    graph_type="supervisor",
    thread_id="session-123"
)

# Sub-agent ekle
config = config.add_subagent(SubAgentRuntimeConfig(
    name="routing",
    system_prompt="You are a routing assistant",
    token=os.getenv("FORZA_TOKEN")
))

# Builder ile chatbot oluştur
chatbot = (
    ChatbotBuilder(dependency_factory, adapter_factory)
    .with_runtime_config(config)
    .build()
)
```

### 2. Runtime'da Güncelleme

```python
# LLM ayarlarını güncelle
new_config = config.update_llm(
    model="gpt-4o",
    temperature=0.7
)

# Sub-agent ayarlarını güncelle
new_config = new_config.update_subagent(
    "routing",
    token="new-token",
    system_prompt="Updated prompt"
)

# Chatbot'a uygula
chatbot.update_runtime_config(new_config)
```

### 3. Method Chaining

```python
config = (
    RuntimeConfiguration(llm=llm_config, graph_type="chat")
    .add_subagent(routing_config)
    .add_subagent(chat_config)
    .update_llm(temperature=0.7)
)
```

### 4. Gradio Interface

Gradio arayüzünde **Ayarlar** sekmesinden:

1. **LLM Yapılandırması**
   - Model seçimi
   - Temperature ayarı

2. **Alt-Agent Yapılandırması**
   - Routing agent token'ı
   - System prompt'lar

3. **Kaydet** butonu ile değişiklikleri uygulayın

## API Referansı

### RuntimeConfiguration

#### Metodlar

- `update_llm(**kwargs)` - LLM ayarlarını güncelle
- `update_graph(graph_type, thread_id)` - Graph ayarlarını güncelle
- `add_subagent(config)` - Sub-agent ekle
- `update_subagent(name, **kwargs)` - Sub-agent'ı güncelle
- `get_subagent(name)` - Sub-agent'ı getir
- `to_dict()` - Dictionary'e çevir
- `to_builder_params()` - Builder parametrelerine çevir
- `to_graph_configurable()` - LangGraph configurable'a çevir

#### Class Methods

- `from_config_loader(config, graph_type, thread_id)` - ConfigLoader'dan oluştur
- `from_dict(data)` - Dictionary'den oluştur

### Chatbot

#### Runtime Config Metodları

- `get_runtime_config()` - Mevcut config'i al
- `update_runtime_config(new_config)` - Config'i güncelle
- `get_config_for_ui()` - UI-friendly config al (masked secrets)

## Akış Diyagramı

```
Program Başlatma:
  main.py
    ↓
  ConfigLoader.load_config()
    ↓
  RuntimeConfiguration.from_config_loader()
    ↓
  Add sub-agents (routing, chat)
    ↓
  ChatbotBuilder.with_runtime_config()
    ↓
  Chatbot instance (with runtime_config)
    ↓
  Interface (Gradio, FastAPI, CLI)

Runtime Güncelleme:
  Gradio Settings UI
    ↓
  User updates config
    ↓
  config.update_llm() / config.update_subagent()
    ↓
  chatbot.update_runtime_config(new_config)
    ↓
  Next graph execution uses new config
```

## Dosya Yapısı

```
src/
├── core/
│   ├── runtime_config.py          # RuntimeConfiguration sınıfları
│   └── chatbot.py                 # runtime_config desteği eklendi
├── builders/
│   └── chatbot_builder.py         # with_runtime_config() metodu
├── interfaces/
│   └── gradio_interface.py        # Settings UI eklendi
└── ...

main.py                            # RuntimeConfiguration kullanımı
test_runtime_config.py            # Test script
```

## Örnek Senaryolar

### Senaryo 1: Token Güncelleme

```python
# Yeni token al
new_token = input("Enter new Forza token: ")

# Config'i güncelle
new_config = chatbot.runtime_config.update_subagent(
    "routing",
    token=new_token
)

# Uygula
chatbot.update_runtime_config(new_config)
```

### Senaryo 2: Model Değiştirme

```python
# Model değiştir
new_config = chatbot.runtime_config.update_llm(
    model="gpt-4o",
    temperature=0.3
)

chatbot.update_runtime_config(new_config)
```

### Senaryo 3: System Prompt Güncelleme

```python
# Chat agent prompt'unu güncelle
new_config = chatbot.runtime_config.update_subagent(
    "chat",
    system_prompt="Yeni sistem mesajı buraya"
)

chatbot.update_runtime_config(new_config)
```

## Yazılım Prensipleri

### KISS (Keep It Simple, Stupid)

- ✅ Basit, anlaşılır API
- ✅ Method chaining desteği
- ✅ Sezgisel method isimleri
- ✅ Minimal complexity

### SOLID

1. **Single Responsibility**
   - `RuntimeConfiguration`: Sadece config yönetimi
   - `LLMRuntimeConfig`: Sadece LLM ayarları
   - `SubAgentRuntimeConfig`: Sadece sub-agent ayarları

2. **Open/Closed**
   - Extension'a açık (yeni sub-agent'lar eklenebilir)
   - Modification'a kapalı (mevcut kod değişmez)

3. **Liskov Substitution**
   - Config sınıfları birbirinin yerine kullanılabilir

4. **Interface Segregation**
   - Küçük, focused interface'ler
   - Her interface sadece ihtiyacı olanı expose eder

5. **Dependency Inversion**
   - Abstract config interface'lerine bağımlı
   - Concrete implementation'lara değil

## Test

Test scriptini çalıştırın:

```bash
python test_runtime_config.py
```

Tüm testler geçmelidir:
- ✅ Config creation
- ✅ Runtime updates
- ✅ Sub-agent management
- ✅ Builder integration
- ✅ KISS principle
- ✅ SOLID principles

## Notlar

1. **Model değişiklikleri**: LLM model değişiklikleri yeni oturumlarda geçerli olur (mevcut graph rebuild gerektirmez)
2. **Sub-agent değişiklikleri**: Token ve prompt değişiklikleri bir sonraki graph execution'da kullanılır
3. **Thread-safety**: Immutable update pattern kullanıldığı için thread-safe
4. **UI masking**: API key'ler ve token'lar UI'da maskelenir (ilk 4 + son 4 karakter)

## İlerisi İçin

Potansiyel geliştirmeler:

1. **Validation**: Config değerlerini validate et
2. **Persistence**: Config değişikliklerini kaydet
3. **History**: Config değişiklik geçmişi tut
4. **Rollback**: Önceki config'e geri dön
5. **Export/Import**: Config'leri dışa/içe aktar
6. **Hot Reload**: Model değişikliklerinde otomatik reload

## Yardım

Sorunlar için:
- `test_runtime_config.py` scriptini çalıştırın
- Log'ları kontrol edin
- Issue oluşturun

## Lisans

Proje lisansına tabidir.
