# Supervisor Mesaj Stratejisi

## Genel Bakış

Supervisor, agent'lar arasında yönlendirme yaparken iki farklı mesaj stratejisi kullanabilir:

1. **Transparent Mode**: Agent'ların mesajlarını direkt gösterir, supervisor kendi cevabını üretmez
2. **Synthesized Mode**: Agent'ların cevaplarını toplar ve supervisor kendi sentezlenmiş cevabını üretir

---

## Konfigürasyon

### Config Dosyasına Ekleme

`config/config.yaml`:

```yaml
chatbot:
  graph_type: supervisor
  message_strategy: transparent  # veya "synthesized"
```

### Seçenekler

- `transparent`: Agent'ların mesajlarını direkt kullanıcıya ilet (varsayılan)
- `synthesized`: Supervisor agent'ların cevaplarını analiz ederek kendi cevabını üret

---

## İmplementasyon

### 1. Config Schema'ya Ekle

`src/graphs/supervisor/config.yaml`:

```yaml
message_strategy: transparent  # transparent | synthesized
```

### 2. Supervisor Prompt'una Ekle

`src/graphs/supervisor/prompts.py`:

**Transparent Mode için:**
```python
SUPERVISOR_SYSTEM_PROMPT_TRANSPARENT = """...(mevcut prompt)...

IMPORTANT: You are only a router. DO NOT generate responses yourself.
- Route the request to the appropriate agent
- Return the agent's response directly to the user
- Do not add commentary or summarization
"""
```

**Synthesized Mode için:**
```python
SUPERVISOR_SYSTEM_PROMPT_SYNTHESIZED = """...(mevcut prompt)...

After receiving agent responses:
- Analyze the agent's answer
- Synthesize a comprehensive response
- Add context or clarification if needed
- Ensure consistency across multiple agent calls
"""
```

### 3. Graph Logic'e Ekle

`src/graphs/supervisor/graph.py`:

```python
def should_generate_response(state: MessagesState) -> str:
    """Mesaj stratejisine göre END'e git ya da supervisor'a dön."""
    config = get_config()  # Config'den oku
    strategy = config.get("message_strategy", "transparent")

    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None

    # Agent tool message ise
    if isinstance(last_message, ToolMessage):
        if strategy == "transparent":
            return END  # Direkt bitir
        else:
            return "supervisor"  # Supervisor sentezlesin

    return END
```

**Graph yapısını güncelle:**

```python
# Conditional edge ekle
builder.add_conditional_edges(
    "chat",
    should_generate_response,
    {END: END, "supervisor": "supervisor"}
)

builder.add_conditional_edges(
    "process_routing_output",
    should_generate_response,
    {END: END, "supervisor": "supervisor"}
)
```

---

## Best Practices

### Transparent Mode Kullan

- Basit routing senaryolarında
- Agent'ların cevapları zaten net olduğunda
- Düşük latency gerektiğinde
- Her agent'ın kendi specialty'si açık olduğunda

**Örnek:** Routing agent zaten URL döndürüyor, ek açıklama gereksiz.

### Synthesized Mode Kullan

- Çoklu agent çağrıları olduğunda
- Agent cevapları tutarsız olabilecekse
- Kullanıcıya unified bir deneyim sunmak istendiğinde
- Context ekleme veya açıklama gerektiğinde

**Örnek:** Hem routing hem chat agent kullanıldı, supervisor bunları birleştirip tutarlı cevap üretmeli.

---

## Örnekler

### Transparent Mode

**Kullanıcı:** "Stok sayfasına git"

```
Flow:
1. Supervisor → Routing Agent
2. Routing Agent → URL döndür
3. [END] - Kullanıcıya direkt URL gösterilir
```

**Çıktı:** `[URL: https://example.com/stok]`

### Synthesized Mode

**Kullanıcı:** "Stok sayfasına git ve nasıl kullanılır anlat"

```
Flow:
1. Supervisor → Routing Agent (URL bulur)
2. Supervisor → Chat Agent (Kullanım anlatır)
3. Supervisor → Sentezleyip birleştirilmiş cevap üretir
4. [END]
```

**Çıktı:**
```
Stok sayfasına gitmek için şu linki kullanabilirsiniz: https://example.com/stok

Bu sayfada stok miktarlarını görebilir, filtreleyebilir ve...
```

---

## Migration Kılavuzu

### Mevcut Sistemden Geçiş

1. `config/config.yaml`'a `message_strategy: transparent` ekle
2. Mevcut davranış korunur (değişiklik yok)
3. İhtiyaç olursa `synthesized` moda geç

### Test Etme

```python
# Transparent test
config = {"message_strategy": "transparent"}
# Agent mesajı direkt dönmeli

# Synthesized test
config = {"message_strategy": "synthesized"}
# Supervisor ek bir mesaj üretmeli
```

---

## Notlar

- **Varsayılan:** `transparent` (geriye dönük uyumluluk)
- **Performans:** Transparent daha hızlı (extra LLM çağrısı yok)
- **Maliyet:** Transparent daha ucuz (daha az token)
- **Esneklik:** Synthesized daha esnek (custom logic eklenebilir)
