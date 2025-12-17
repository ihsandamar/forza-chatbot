# Navigation Response Format

## Genel Bakış

Chat API, routing/navigation içeren mesajları otomatik olarak algılar ve özel bir response formatında döndürür. Bu sayede web sitesi bu mesajların bir yönlendirme olduğunu anlayabilir.

## Response Formatı

### Regular Text Response

Normal sohbet mesajları için:

```json
{
  "success": true,
  "timestamp": "2025-12-03T12:18:27.512946",
  "sessionId": "778a50a6-8f4b-4bfd-a653-8b1142a9315e",
  "response": {
    "text": "Merhaba! Size nasıl yardımcı olabilirim?",
    "type": "text",
    "confidence": 0.95,
    "action": {
      "type": "none",
      "target": "",
      "params": {}
    }
  }
}
```

### Navigation Response

URL içeren routing mesajları için:

```json
{
  "success": true,
  "timestamp": "2025-12-03T12:18:27.512946",
  "sessionId": "778a50a6-8f4b-4bfd-a653-8b1142a9315e",
  "response": {
    "text": "📄 **Cari Evrakları** (Alt Sayfa: Cari Listesi)\n🔗 URL: `https://test.vegaforza.com/apps/customer/view/42263b99-67a9-4740-b27d-13c6f153a345?tab=1`\n\n💡 Bu alt sayfada cari evrakları ile ilgili işlemlerinizi yapabilirsiniz. (Cari Listesi bölümü)\n\n⚙️ **Gerekli Parametreler:**\n  • `customerId` (guid) - Cari Id [○ Opsiyonel]",
    "type": "navigation",
    "confidence": 0.85,
    "action": {
      "type": "routing",
      "target": "https://test.vegaforza.com/apps/customer/view/42263b99-67a9-4740-b27d-13c6f153a345?tab=1",
      "params": {}
    }
  }
}
```

## Nasıl Çalışır?

### 1. Otomatik Detection

`ChatService` mesajları kontrol eder:
- Graph output'tan gelen son 5 mesaja bakar
- Tool message'ları arar
- Tool message içinde URL (http/https) var mı kontrol eder

### 2. URL Extraction

URL bulunursa:
- Regex ile URL extract edilir
- Response type `"navigation"` olarak ayarlanır
- Action type `"routing"` olarak ayarlanır
- URL, `action.target` alanına konur

### 3. Response Generation

```python
if routing_info:
    response_data = ResponseData(
        text=bot_response_text,
        type="navigation",  # ← Navigation olarak işaretlenir
        confidence=0.85,
        action=ActionResponse(
            type="routing",  # ← Routing action
            target=routing_info["url"],  # ← URL buraya
            params={}
        )
    )
```

## Frontend Integration

### Response Type Kontrolü

```typescript
interface ChatResponse {
  success: boolean;
  timestamp: string;
  sessionId: string;
  response: {
    text: string;
    type: "text" | "navigation";
    confidence: number;
    action: {
      type: "none" | "routing";
      target: string;
      params: Record<string, any>;
    };
  };
}

function handleChatResponse(response: ChatResponse) {
  if (response.response.type === "navigation") {
    // Navigation response
    const url = response.response.action.target;

    // Option 1: Redirect
    window.location.href = url;

    // Option 2: Open in new tab
    window.open(url, '_blank');

    // Option 3: Show with link
    showMessageWithLink(response.response.text, url);
  } else {
    // Regular text response
    showMessage(response.response.text);
  }
}
```

### React Example

```tsx
const ChatMessage = ({ response }: { response: ChatResponse }) => {
  const { text, type, action } = response.response;

  if (type === "navigation") {
    return (
      <div className="navigation-message">
        <div className="message-text">{text}</div>
        <a
          href={action.target}
          target="_blank"
          className="navigation-link"
        >
          🔗 Sayfaya Git
        </a>
      </div>
    );
  }

  return <div className="text-message">{text}</div>;
};
```

## API Endpoints

### POST /api/chat/message

**Request:**
```json
{
  "sessionId": "session-uuid",
  "message": "Cari evrakları sayfasına git"
}
```

**Response (Navigation):**
```json
{
  "success": true,
  "timestamp": "2025-12-03T12:18:27.512946",
  "sessionId": "session-uuid",
  "response": {
    "text": "İşte cari evrakları sayfası: ...",
    "type": "navigation",
    "confidence": 0.85,
    "action": {
      "type": "routing",
      "target": "https://test.vegaforza.com/apps/customer/...",
      "params": {}
    }
  }
}
```

## Implementation Details

### ChatService Methods

#### `_extract_url_from_message(content: str) -> Optional[str]`

URL extraction için regex kullanır:
```python
url_pattern = r'https?://[^\s\)\]\}]+'
```

#### `_detect_routing_response(messages: list) -> Optional[dict]`

Tool message'larda URL arar:
- Son 5 mesajı kontrol eder
- Role = "tool" olan mesajları filtreler
- Her tool message'da URL arar
- İlk bulduğu URL'i döndürür

### Code Location

- **Service**: `src/api/services/chat_service.py`
- **Models**: `src/api/models/responses/chat.py`
- **Detection Logic**: `_detect_routing_response()` method

## Testing

### Test Case 1: Regular Message

```python
response = await chat_service.send_message(
    ChatMessageRequest(
        session_id="test-session",
        message="Merhaba!"
    )
)

assert response.response.type == "text"
assert response.response.action.type == "none"
```

### Test Case 2: Navigation Message

```python
response = await chat_service.send_message(
    ChatMessageRequest(
        session_id="test-session",
        message="Stok sayfasına git"
    )
)

assert response.response.type == "navigation"
assert response.response.action.type == "routing"
assert "http" in response.response.action.target
```

## Future Enhancements

### LinkMessage Type (Planned)

İleride özel bir `LinkMessage` tipi eklenebilir:

```python
class LinkMessage(BaseModel):
    """Specialized message for navigation/routing"""
    url: str
    display_text: str
    page_name: str
    parameters: Dict[str, Any]
    metadata: Dict[str, Any]
```

Bu daha zengin navigation bilgisi sağlayabilir:
- Page name
- Required parameters
- Parameter types
- Alternative pages

## Troubleshooting

### URL Bulunamıyor

**Problem:** Navigation response üretilmiyor.

**Çözüm:**
1. Tool message var mı kontrol et: `graph_output["messages"]`
2. Tool message içeriğinde URL var mı kontrol et
3. URL formatı doğru mu? (http/https ile başlamalı)

### Yanlış URL Extract Ediliyor

**Problem:** Yanlış URL alınıyor.

**Çözüm:**
- Regex pattern'i güncelle: `chat_service.py:92`
- URL'in sonunda nokta/parantez varsa trim et

### Frontend URL'i Algılamıyor

**Problem:** Frontend navigation response'u handle etmiyor.

**Çözüm:**
1. `response.response.type === "navigation"` kontrolü var mı?
2. `response.response.action.target` doğru mu?
3. Console'da response'u log'la

## Summary

✅ **Otomatik Detection**: Tool message'larda URL algılanır
✅ **Special Format**: Navigation için özel response formatı
✅ **Frontend Ready**: Type-based handling için hazır
✅ **Backward Compatible**: Mevcut text response'lar etkilenmez
✅ **Extensible**: İleride LinkMessage ile genişletilebilir
