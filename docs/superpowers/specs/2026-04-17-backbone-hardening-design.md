# Backbone Hardening — Design Spec

**Tarih:** 2026-04-17
**Kapsam:** Self-Describing Agent Protocol dışında kalan omurga sorunları
**Durum:** Onaylandı — Implementation bekliyor

---

## 1. Sorunlar

### 1.1 Ölü `base_graph.py` Dosyası (MEDIUM)

**Dosya:** `src/graphs/base_graph.py`

İki farklı `BaseGraph` implementasyonu var:
- `src/graphs/base_graph.py` — eski, basit versiyon (42 satır). **Hiçbir dosya tarafından import edilmiyor.**
- `src/graphs/base/base_graph.py` — gelişmiş versiyon (461 satır, Generic[ConfigT], metadata, async). Tüm graph'lar bunu kullanıyor.

**Risk:** İki farklı `BaseGraph` var olduğu için yeni bir geliştirici yanlış dosyayı import edebilir. Sessiz bir davranış farkı yaratır.

**Çözüm:** `src/graphs/base_graph.py` silinir.

---

### 1.2 `GraphRepository.get()` Karmaşık Graph'lar için Bozuk (HIGH)

**Dosya:** `src/graphs/graph_repository.py`, satır 14

```python
def get(self, graph_type: str):
    return GRAPH_REGISTRY[graph_type](self.llm).build_graph()  # sadece llm geçiyor
```

`report_agent` bu çağrı ile çalışmaz — DB bağlantısı, dosya yolları, chroma dizini gerektirir.

**Mevcut workaround:** `SupervisorGraph._build_report_agent()` repository'yi bypass ederek report agent'ı elle inşa ediyor (supervisor/graph.py:203-230). Bu, iki farklı inşa yolu olduğu anlamına gelir.

**Çözüm:** `BaseGraph.create(llm, app_config)` classmethod protokolü (Self-Describing Agent Protocol spec'inde tanımlandı). `GraphRepository.get()` `cls.create(llm, app_config)` çağrısına güncellenir. `_build_report_agent()` silinerek `repo.get("report_agent")` kullanılır.

**Not:** Bu çözüm Self-Describing Agent Protocol spec'inin bir parçasıdır. Burada ayrıca belgelenmiştir çünkü `_chat_service.py` da `GraphRepository.get()` çağırmaktadır:

```python
# src/launch/_chat_service.py satır 35
graph = GraphRepository(llm).get(config.chatbot.graph_type)
```

Eğer `config.chatbot.graph_type = "report_agent"` set edilirse bu satır çöker. `GraphRepository` `app_config` almadan çağrılıyor — bu da düzeltilmeli.

---

### 1.3 Stale Test: Yanlış Import Yolu (HIGH)

**Dosya:** `tests/graphs/report/test_enhanced_hitl.py`, satır 18

```python
from src.graphs.report.ambiguity_framework import (...)
# ModuleNotFoundError: No module named 'src.graphs.report'
```

Doğru yol: `src.graphs.report_agent`. Refactor sırasında test güncellenmemiş.
368 test collectible ama bu hata tüm test suite'i durduruyor (`--collect-only` kesiliyor).

**Çözüm:** Test dosyası incelenerek ya doğru modüle güncellenir ya da `ambiguity_framework` modülü artık mevcut değilse test silinir.

---

### 1.4 Module-Level I/O: `routing/graph.py` (HIGH)

**Dosya:** `src/graphs/routing/graph.py`, satır 45

```python
config = ConfigLoader.load_config("config/config.yaml")  # import zamanında çalışır
```

Bu satır `RoutingGraph`'ı import eden her modülde config dosyasını okur. Test ortamında, Docker başlangıcında ve PyInstaller'da beklenmedik davranışlara yol açar.

**Çözüm:** `RoutingGraph.create()` classmethod'una taşınır (Self-Describing Agent Protocol spec'inde kapsanmıştır). Burada ayrıca belgelenmiştir.

---

## 2. Etkilenen Dosyalar

| Dosya | Değişiklik | Bağlı Spec |
|---|---|---|
| `src/graphs/base_graph.py` | Silinir | Bu spec |
| `src/graphs/graph_repository.py` | `get()` → `cls.create()` kullanır, `app_config` parametresi eklenir | Agent Protocol |
| `src/graphs/supervisor/graph.py` | `_build_report_agent()` silinir → `repo.get("report_agent")` | Agent Protocol |
| `src/launch/_chat_service.py` | `GraphRepository(llm, app_config=config)` → `app_config` geçilir | Bu spec |
| `src/graphs/routing/graph.py` | Satır 45 kaldırılır, `create()` içine taşınır | Agent Protocol |
| `tests/graphs/report/test_enhanced_hitl.py` | Import düzeltilir veya test silinir | Bu spec |

---

## 3. Başarı Kriterleri

- [ ] `src/graphs/base_graph.py` dosyası yok
- [ ] `pytest --collect-only` hatasız tamamlanır (368 test)
- [ ] `GraphRepository(llm).get("report_agent")` çökmez
- [ ] `routing/graph.py` import edildiğinde sıfır dosya I/O
