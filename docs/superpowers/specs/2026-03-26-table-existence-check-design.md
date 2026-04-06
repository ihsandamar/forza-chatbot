# Design: Table Existence Check — Single Table Approach

**Date:** 2026-03-26
**Status:** Approved
**Scope:** report_agent text2sql subgraph

---

## Problem

`create_table_node` her zaman in-memory `TableRegistry`'yi kontrol eder. Registry,
process-level singleton olduğu için sunucu restart edilince boşalır. Bu durumda
`MasterReportDocumentTable` DB'de zaten var olsa bile yeniden oluşturulmaya çalışılır.

Ek olarak:
- Session bazlı tablo adlandırma (`MasterReportDocumentTable_{session_id}`) gereksiz karmaşıklık.
- `force_refresh` (DROP + recreate) ve keyword detection ("verileri güncelle" vb.) tamamen kaldırılacak.

---

## Hedef

1. Tablo DB'de varsa oluşturma — mevcut tabloyla devam et.
2. `cleanup_table_node`'u no-op yap.
3. `force_refresh` / refresh keyword detection'ı tamamen kaldır.
4. Session bazlı tablo adlandırmayı kaldır (zaten var olan `default_table_name` kullanılır).
5. Kod sadeliğini koru — lock, concurrency yönetimi yok.

---

## Tasarım

### Module-level Flag

```python
_table_verified: bool = False
```

Process başladığında `False`. İlk başarılı doğrulamadan sonra `True`. Sunucu restart
edilene kadar `True` kalır. Eğer tablo dışarıdan drop edilirse, hata SQL execution
sırasında yüzeye çıkar; recovery için sunucu restart gerekir — bu tasarımın kabul
ettiği bir sınırdır.

### `_check_table_exists_in_db` Yardımcı Fonksiyonu

Senkron, modül pool pattern'ına uygun (`get_pooled_connection` + `_db_executor`).
Read-only sorgu olduğu için ayrı bir transaction açmaya gerek yoktur.

```python
def _check_table_exists_in_db(pyodbc_conn_str: str, table_name: str) -> bool:
    conn = get_pooled_connection(pyodbc_conn_str)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ? AND TABLE_TYPE = 'BASE TABLE'",
            table_name
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()  # conn pool'da kalır, kapatılmaz
```

`OBJECT_ID()` yerine `INFORMATION_SCHEMA.TABLES` kullanılır — parameterized query
ODBC driver versiyonundan bağımsız güvenli çalışır.

### `create_create_table_node` Dış Factory Signature'ı

Değişmez: `create_create_table_node(connection_string: str, default_table_name: str) -> Callable`

### `create_table_node` Akışı (iç async fonksiyon)

```
1. _table_verified == True → return {}  (0 DB call)

2. Background init hâlâ çalışıyorsa (_table_init_event is not set):
       loop.run_in_executor(None, _table_init_event.wait, 180)

3. try:
       pyodbc_conn_str = _parse_connection_string(connection_string)
       loop = asyncio.get_running_loop()
       exists = await loop.run_in_executor(
           _db_executor, _check_table_exists_in_db, pyodbc_conn_str, table_name
       )
       if exists:
           _table_verified = True
           return {}

       # Tablo yok → oluştur
       query = _get_configurable(config, "query", "") or <sql_file_fallback>
       await loop.run_in_executor(_db_executor, _execute_script_sync, connection_string, query)
       _table_verified = True
       return {}

   except Exception as e:
       logger.error(f"[CREATE_TABLE] Error: {e}")
       return {"error": f"Tablo kontrol/oluşturma hatası: {e}"}
```

`session_id` referansları kaldırılır. `force_refresh` bloğu (registry drop, unregister)
kaldırılır. `asyncio.get_running_loop()` kullanılır (deprecated `get_event_loop()` yerine).

### Background Init (`init_master_table_background`)

Mevcut davranış korunur. Tablo başarıyla oluşturulursa `_table_verified = True` set edilir:

```python
# _execute_script_sync başarılı olduktan sonra:
global _table_verified
_table_verified = True
_table_init_error = None
_table_init_event.set()
```

### `cleanup_table_node` (no-op)

```python
async def cleanup_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
    return {}
```

---

## Etkilenen Dosyalar

### `src/graphs/report_agent/subagents/text2sql/nodes.py`

- `_table_verified: bool = False` module-level değişkeni ekle
- `_check_table_exists_in_db` senkron helper ekle
- `create_create_table_node` içindeki `create_table_node`:
  - `force_refresh` bloğunu sil (DROP + registry unregister mantığı)
  - Registry lookup'larını sil
  - `session_id` kullanımını sil
  - Yeni akışı uygula (background init wait → DB check → create)
  - `asyncio.get_running_loop()` kullan
- `cleanup_table_node`'u no-op yap
- `init_master_table_background`'a `_table_verified = True` ekle

### `src/graphs/report_agent/nodes.py`

- `classify_intent_node` içinde satır 117–137 arası bloğu sil:
  - `_REFRESH_KEYWORDS` set tanımı
  - `is_refresh_request` hesabı
  - `if is_refresh_request:` early-return bloğu (136. satırda `_force_table_refresh: True` dönen)
- Satır 241'deki `"_force_table_refresh": False` reset satırını sil

### `src/graphs/report_agent/state.py`

- Satır 32: `_force_table_refresh: Optional[bool]` field'ını sil

### `src/graphs/report_agent/subagents/text2sql/state.py`

- Satır 26: `_force_table_refresh: Optional[bool]` field'ını sil

---

## Korunacaklar

- `TableRegistry` sınıfı (`table_registry.py`) — `sessions.py`, `metrics.py`, `nodekit.py` kullanıyor; dokunulmaz.
- `_execute_script_sync` — tablo yoksa hâlâ kullanılır.
- `_table_init_event`, `_table_init_started`, `_table_init_error` — background init mekanizması korunur.
- `get_pooled_connection`, `_db_executor` — `_check_table_exists_in_db` bunları kullanır.

---

## Davranış Karşılaştırması

| Senaryo | Eski | Yeni |
|---------|------|------|
| İlk request, tablo yok | Registry miss → oluştur | DB check → oluştur |
| İlk request, tablo var | Registry miss → oluştur (hata!) | DB check → skip |
| Sonraki request (aynı process) | Registry hit → skip | `_table_verified=True` → skip (0 DB call) |
| Sunucu restart, tablo var | Registry boş → oluştur (hata!) | DB check → skip |
| Sunucu restart, tablo yok | Registry boş → oluştur | DB check → oluştur |
| DB bağlantı hatası | Hata fırlatır | `{"error": "..."}` döner |
| "verileri güncelle" komutu | DROP + recreate | Feature tamamen kaldırıldı |
| Tablo process çalışırken drop edilirse | DROP guard yok | Hata SQL'de yüzeye çıkar; restart gerekir |
