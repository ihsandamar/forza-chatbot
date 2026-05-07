# MCP Debug Tracer — Design Spec

**Date**: 2026-05-07  
**Status**: Approved

## Problem

`tools/read_trace.py` çalıştırılabilir bir CLI script ama Claude'un programatik kullanımı için uygun değil. Claude'un bir debug oturumunda `read_trace` fonksiyonunu direkt tool olarak çağırabilmesi gerekiyor — CLI çıktısını parse etmeden.

## Çözüm

`tools/mcp_debug_tracer.py` — FastMCP ile proje düzeyinde MCP server. `.mcp.json` ile Claude Code'a tanıtılır. Claude Code proje açıldığında server'ı otomatik başlatır.

---

## Mimari

### Yeni dosyalar

```
tools/mcp_debug_tracer.py   ← FastMCP server
.mcp.json                   ← proje root, Claude'a server tanıtır
```

`read_trace.py` dokunulmaz. `mcp_debug_tracer.py`, `read_trace.py`'deki parse mantığını kopyalamak yerine doğrudan `import` eder.

### Transport

`stdio` — Claude Code, `python tools/mcp_debug_tracer.py` subprocess'ini başlatır, stdin/stdout üzerinden JSON-RPC konuşur. Server crash → Claude Code otomatik restart eder.

### .mcp.json

```json
{
  "mcpServers": {
    "forza-debug-tracer": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/mcp_debug_tracer.py"],
      "env": {
        "DEBUG_TRACE_DIR": "logs/debug"
      }
    }
  }
}
```

---

## Tool: `read_trace`

### Parametreler

| Parametre | Tip | Varsayılan | Açıklama |
|-----------|-----|-----------|----------|
| `session_id` | `str` | zorunlu | Log dosyası adı (`.jsonl` olmadan) |
| `node` | `str \| None` | `None` | Node adına göre filtre |
| `turn` | `int \| None` | `None` | Turn numarasına göre filtre |
| `full` | `bool` | `False` | `True` → tam state JSON, `False` → özet |

### Dönüş

```json
{
  "session_id": "40d39641-17f8-4945-ab90-6ff6bce5c8bf",
  "event_count": 12,
  "summary": "[SESSION] 40d39641...  (12 events)\n========\n[T1] 10:48:19  → classify_intent\n...",
  "events": [
    {
      "ts": "2026-05-07T10:48:19.325475+00:00",
      "node": "classify_intent",
      "event": "enter",
      "turn": 1,
      "state": { "...": "..." }
    }
  ]
}
```

`summary`: `read_trace.py`'nin mevcut terminal formatı — Claude kullanıcıya direkt gösterebilir.  
`events`: Structured list — Claude analiz için kullanır.

### Hata durumları

| Durum | Dönüş |
|-------|-------|
| `logs/debug/` yoksa | `{"events": [], "event_count": 0, "summary": "No trace directory: logs/debug"}` |
| Session ID bulunamazsa | `{"events": [], "event_count": 0, "summary": "Session not found: <id>"}` |
| Bozuk JSONL satırı | Satır atlanır, diğerleri işlenir |

---

## Bağımlılıklar

```
fastmcp>=2.0
```

`requirements.txt`'e eklenir. Kurulum: `pip install fastmcp`.

---

## Kapsam Dışı

- `list_traces` tool'u (gelecekte eklenebilir)
- Kullanıcı düzeyinde MCP config (proje düzeyinde yeterli)
- Tool authentication / API key
