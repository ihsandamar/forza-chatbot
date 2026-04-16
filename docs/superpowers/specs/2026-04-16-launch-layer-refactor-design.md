# Launch Layer Refactor — Design Spec

**Tarih:** 2026-04-16  
**Branch:** refactor/cleanup-and-consolidation  
**Durum:** Onaylandı — implementasyon bekliyor

---

## Motivasyon

Şu an FastAPI, Gradio ve CLI başlatma mantığı üç ayrı entry point'a (`main.py`, `api_app.py`, `src/api/main.py`) dağılmış durumda. Config üç yerde bağımsız yükleniyor, iki ayrı `ChatService` implementasyonu var, `langgraph.json` silinmiş grafları referans ediyor, port tanımı iki yerde çelişiyor.

**Hedef:** Esnekliği koruyarak (PyInstaller desteği dahil) her başlatma yolunu tek, okunabilir bir yerden yönetmek.

---

## Kapsam

| Dahil | Dışarıda |
|-------|---------|
| `src/launch/` modülü oluşturma | `src/api/routes/` içeriği |
| Config singleton | `src/graphs/` graph mantığı |
| Unified ChatService | Gradio UI tasarımı |
| langgraph.json güncelleme | HITL / LangGraph node mantığı |
| main.py + api_app.py sadeleştirme | |
| di_container.py kaldırma | |

---

## Mimari

### Dosya Yapısı — Yeni

```
src/launch/
    __init__.py              ← get_launcher(interface, config_path) factory
    api_launcher.py          ← FastAPI + uvicorn başlatma
    gradio_launcher.py       ← Gradio demo başlatma
    cli_launcher.py          ← CLI dev başlatma

src/core/app_config.py       ← get_config() singleton (YENİ)
```

### Dosya Yapısı — Değişen

```
main.py                      ← ~25 satır (sadece argparse + get_launcher())
api_app.py                   ← ~15 satır (PyInstaller: ApiLauncher wrapper)
src/api/main.py              ← sadece FastAPI app factory, config yükleme kalkacak
src/interfaces/cli_interface.py  ← broken import düzeltilir, unified ChatService kullanır
src/__init__.py              ← di_container export kalkacak
langgraph.json               ← 3 stale graf temizlenir
```

### Dosya Yapısı — Silinecek

```
src/api/chat_service.py      ← canonical → api/services/chat_service.py
src/di_container.py          ← mantığı build_chat_service() factory'ye taşınır
```

---

## Bileşen Tasarımı

### 1. Config Singleton — `src/core/app_config.py`

```python
from typing import Optional
from src.services.config_loader import ConfigLoader, AppConfig  # mevcut tip

_config: Optional[AppConfig] = None

def get_config(path: str = "config/config.yaml") -> AppConfig:
    global _config
    if _config is None:
        _config = ConfigLoader.load_config(path)
    return _config

def reset_config() -> None:
    """Test izolasyonu için — production kodunda çağrılmaz."""
    global _config
    _config = None
```

Şu an `ConfigLoader.load_config()` çağrılan 3 yer → hepsi `get_config()` kullanacak:
- `main.py:45`
- `api_app.py:34-71`
- `src/api/main.py:28`

---

### 2. Unified ChatService Factory — `src/launch/_chat_service.py`

Tüm launcher'ların ortak kullandığı factory. `di_container.py`'deki bağımlılık ağacı buraya taşınır:

```python
from src.core.app_config import get_config
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository

def build_chat_service(config=None) -> ChatService:
    """
    Tüm launcher'lar için ortak ChatService factory.
    Canonical implementasyon: src/api/services/chat_service.py
    """
    if config is None:
        config = get_config()

    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
    )
    graph = GraphRepository(llm).get(config.chatbot.graph_type)
    chatbot = Chatbot(llm=llm.get_chat(), graph=graph)
    return ChatService(chatbot=chatbot)
```

---

### 3. ApiLauncher — `src/launch/api_launcher.py`

```python
import uvicorn
from src.core.app_config import get_config
from src.api.main import build_fastapi_app   # mevcut app factory

DEFAULT_PORT = 8089

class ApiLauncher:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def get_asgi_app(self):
        """PyInstaller / api_app.py için ASGI app döner."""
        return build_fastapi_app(self.config)

    def run(self, port: int = DEFAULT_PORT):
        """Doğrudan çalıştırma için uvicorn başlatır."""
        if not self.config.llm.api_key:
            raise RuntimeError("OPENAI_API_KEY eksik — config/.env kontrol et")
        uvicorn.run(self.get_asgi_app(), host="0.0.0.0", port=port)
```

---

### 4. GradioLauncher — `src/launch/gradio_launcher.py`

```python
from src.core.app_config import get_config
from src.launch._chat_service import build_chat_service
from src.interfaces.gradio_interface import GradioInterface

class GradioLauncher:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def run(self):
        chat_service = build_chat_service(self.config)
        GradioInterface(chat_service).launch(server_port=7860)
```

---

### 5. CliLauncher — `src/launch/cli_launcher.py`

```python
from src.core.app_config import get_config
from src.launch._chat_service import build_chat_service
from src.interfaces.cli_interface import CliInterface

class CliLauncher:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def run(self):
        chat_service = build_chat_service(self.config)
        CliInterface(chat_service).run()
```

---

### 6. `src/launch/__init__.py` — Factory

```python
from src.launch.api_launcher import ApiLauncher
from src.launch.gradio_launcher import GradioLauncher
from src.launch.cli_launcher import CliLauncher

_LAUNCHERS = {
    "api": ApiLauncher,
    "gradio": GradioLauncher,
    "cli": CliLauncher,
}

def get_launcher(interface: str, config_path: str = "config/config.yaml"):
    if interface not in _LAUNCHERS:
        raise ValueError(f"Bilinmeyen interface: {interface}. Seçenekler: {list(_LAUNCHERS)}")
    return _LAUNCHERS[interface](config_path)
```

---

### 7. `main.py` — Sonuç Hali (~25 satır)

```python
"""
Forza Chatbot — CLI entry point.

Kullanım:
    python main.py --interface api      (varsayılan, production)
    python main.py --interface gradio   (demo)
    python main.py --interface cli      (geliştirme)
"""
import argparse
from src.launch import get_launcher

def main():
    parser = argparse.ArgumentParser(description="Forza Chatbot")
    parser.add_argument(
        "--interface",
        choices=["api", "gradio", "cli"],
        default="api",
        help="Başlatılacak interface"
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Config dosyası yolu"
    )
    args = parser.parse_args()
    get_launcher(args.interface, args.config).run()

if __name__ == "__main__":
    main()
```

---

### 8. `api_app.py` — Sonuç Hali (~15 satır, PyInstaller)

```python
"""
api_app.py — PyInstaller entry point.

Bu dosya YALNIZCA PyInstaller native executable build için var.
Normal çalıştırma için: python main.py --interface api
"""
from src.launch.api_launcher import ApiLauncher

# uvicorn bu 'app' değişkenini okur
launcher = ApiLauncher()
app = launcher.get_asgi_app()

if __name__ == "__main__":
    launcher.run()
```

---

### 9. `src/api/main.py` Değişimi

Şu an config yükleme + FastAPI app creation + startup event tek dosyada karışık.

Sonuç: `build_fastapi_app(config)` fonksiyonu export edilir, config yükleme kaldırılır:

```python
# src/api/main.py — sadece app factory
def build_fastapi_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="Forza Chatbot API")
    # CORS, exception handlers, routers — değişmez
    return app
```

Startup event'teki config yükleme `ApiLauncher.__init__` üzerine taşınır.

---

### 10. `langgraph.json` Güncelleme

```json
{
  "dependencies": ["."],
  "graphs": {
    "supervisor":   "src/graphs/graph_entrypoints.py:supervisor_graph",
    "routing":      "src/graphs/graph_entrypoints.py:routing_graph",
    "report_agent": "src/graphs/graph_entrypoints.py:report_agent_graph"
  },
  "env": "config/.env"
}
```

Kaldırılanlar: `generic_text2sql_graph`, `data_visualization_graph` (fonksiyonlar artık yok).

---

## Veri Akışı

```
[python main.py --interface api]
        │
        ▼
  get_launcher("api")
        │
        ▼
  ApiLauncher.__init__()
    └── get_config()          ← tek yükleme, singleton
        │
        ▼
  ApiLauncher.run()
    └── build_fastapi_app()   ← FastAPI app factory
    └── uvicorn.run()

[api_app.py — PyInstaller]
        │
        ▼
  ApiLauncher()
    └── get_config()          ← aynı singleton
    └── get_asgi_app()        ← uvicorn bu app'i kullanır
```

---

## Hata Yönetimi

| Hata Senaryosu | Davranış |
|----------------|---------|
| `OPENAI_API_KEY` eksik | `ApiLauncher.run()` anlamlı mesajla `RuntimeError` fırlatır |
| Geçersiz `--interface` | `get_launcher()` `ValueError` fırlatır, seçenekleri listeler |
| Config dosyası bulunamadı | `get_config()` mevcut `ConfigLoader` exception'ını iletir |
| DB bağlantısı başarısız | Mevcut exception handler'lar korunur |

---

## Test Planı

```python
# Config singleton testi
def test_get_config_returns_same_instance():
    reset_config()
    assert get_config() is get_config()

def test_reset_config_clears_singleton():
    get_config()
    reset_config()
    # Sonraki çağrı yeniden yükler
    assert get_config() is not None

# Launcher factory testi
def test_get_launcher_invalid_interface():
    with pytest.raises(ValueError, match="Bilinmeyen interface"):
        get_launcher("unknown")

# ApiLauncher testi — gerçek servis başlatmadan
def test_api_launcher_builds_asgi_app(mock_config):
    launcher = ApiLauncher()
    app = launcher.get_asgi_app()
    assert app is not None

# build_chat_service testi
def test_build_chat_service_returns_chat_service(mock_config):
    service = build_chat_service()
    assert isinstance(service, ChatService)
```

---

## Migration Notları

### `di_container.py` Silinirken Dikkat

`src/__init__.py:11` şu an `di_container`'ı export ediyor:
```python
from src.di_container import create_chatbot_dependencies
```
Bu satır kaldırılacak. Eğer dışarıdan `create_chatbot_dependencies` import eden kod varsa `build_chat_service()` kullanacak şekilde güncellenir.

### CLI Broken Import Düzeltmesi

`src/interfaces/cli_interface.py:16`:
```python
# ESKI (broken):
from src.api.chat_service import ChatService

# YENİ:
from src.api.services.chat_service import ChatService
```

### ChatService Constructor Farkı

`src/api/chat_service.py` (eski, silinecek): `__init__(chatbot, session_manager, conversation_manager, assistant_manager)`  
`src/api/services/chat_service.py` (canonical): `__init__(chatbot: Chatbot)`

`build_chat_service()` factory canonical constructor'ı kullanır.

---

## Başarı Kriterleri

- [ ] `python main.py --interface api` çalışır
- [ ] `python main.py --interface gradio` çalışır
- [ ] `python main.py --interface cli` çalışır
- [ ] `api_app.py` PyInstaller ile build edilebilir
- [ ] `langgraph dev` komutu `langgraph.json` ile çalışır (3 graf görünür)
- [ ] Config sadece bir kez yüklenir (singleton doğrulanır)
- [ ] Tüm launcher testleri geçer
- [ ] `src/api/chat_service.py` ve `di_container.py` silinmiş
