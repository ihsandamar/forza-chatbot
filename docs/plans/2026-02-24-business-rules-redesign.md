# Business Rules Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `business_rules.json` yapısını sadeleştir (triggers kaldır, description zenginleştir); ChromaDB semantic RAG'ın kendi gücüyle doğru kuralları bulmasını sağla; `business_rules_context` formatını individual rules + ID'ler olarak değiştir; `sql_architect` hangi rule ID'lerini seçeceğini net anlasın.

**Architecture:** `description` tek embedding kaynağı olarak kalır — ama domain diline uygun, doğal Türkçe ifadeler içerecek şekilde zenginleştirilir. ChromaDB semantic search → individual rules with IDs → `business_rules_context` → LLM ID seçer → `applied_rule_ids` → `sql_generator` SQL'e uygular.

**Tech Stack:** Python 3.12, ChromaDB, sentence-transformers/all-MiniLM-L6-v2

**Design Kararları:**
- `triggers` array YOK — description'ın kendisi semantik tetikleyici
- `example_queries` YOK — description doğal dilde yazılır, model iş yapar
- Individual rules formatı: `[id] [VARSAYILAN?] description\n  SQL: ...hint...`
- LLM bu listeden seçim yapar, ID'leri `applied_rule_ids`'e yazar
- `sql_generator` ID'lere göre tam SQL bileşenlerini uygular (mevcut mantık korunur)
- Index rebuild gerekli (new descriptions → yeni embedding'ler)

---

## Referans Dosyalar

Değiştirilecek:
- `src/graphs/generic_text2sql/business_rules.json`
- `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py`
- `src/graphs/report_agent/subagents/text2sql/nodes.py` (`create_business_rules_node`)
- `src/graphs/report_agent/subagents/text2sql/prompts.py` (KURAL 6)

---

## Task 1: business_rules.json — Triggers kaldır, description zenginleştir

**File:** `src/graphs/generic_text2sql/business_rules.json`

**Yaklaşım:** Her rule'un description'ı, o kuralın ne zaman devreye gireceğini anlatan doğal Türkçe cümleler içermelidir. `ChromaDB all-MiniLM-L6-v2` modeli bu zengin description'lardan semantik benzerlik hesaplar.

**Step 1: Dosyayı tamamen yeniden yaz**

```json
{
  "business_logic_rules": [
    {
      "id": "iade_dusulmus",
      "description": "Ciro, satış tutarı veya gelir hesaplanırken iade işlemlerinin toplam tutardan düşülmesi gerekir. Net ciro, iade hariç ciro, iade düşülmüş satış tutarı sorgularında uygulanır. DocumentTypeIsReturn = 1 olan kayıtlar negatif alınarak hesaplamaya katılır.",
      "modules": ["MasterReports"],
      "sql": {
        "aggregation": "SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)",
        "filter": null,
        "group_by": null,
        "select": null,
        "join": null,
        "having": null
      },
      "is_default": true
    },
    {
      "id": "kapali_masa_filtre",
      "description": "Ödemesi alınmış, hesabı kapanmış, tamamlanmış masalara ait kayıtları filtrelemek için kullanılır. Kullanıcı ödemesi alınan masalar, kapalı masalar, hesabı ödenen masalar, tamamlanan masa siparişleri gibi ifadeler kullandığında uygulanır. IsTableActive = 0 değeri masanın kapalı ve ödemesinin alınmış olduğunu gösterir.",
      "modules": ["MasterReports"],
      "sql": {
        "aggregation": null,
        "filter": "[IsTableActive] = 0",
        "group_by": null,
        "select": null,
        "join": null,
        "having": null
      },
      "is_default": false
    },
    {
      "id": "acik_masa_filtre",
      "description": "Henüz ödemesi alınmamış, aktif devam eden, masada oturan müşterilere ait açık masa kayıtlarını filtrelemek için kullanılır. Açık masalar, aktif masalar, ödemesi alınmamış siparişler, hâlâ masada olan müşteriler ifadelerinde uygulanır. IsTableActive = 1 değeri masanın hâlâ aktif olduğunu gösterir.",
      "modules": ["MasterReports"],
      "sql": {
        "aggregation": null,
        "filter": "[IsTableActive] = 1",
        "group_by": null,
        "select": null,
        "join": null,
        "having": null
      },
      "is_default": false
    },
    {
      "id": "sadece_normal_satis",
      "description": "Sadece gerçek satış işlemlerini dahil etmek için ikram, zayi (fire) ve iptal kayıtlarını dışarıda bırakır. Gerçek satışlar, standart satışlar, ikram hariç, zayi olmayan, iptal olmayan kayıtlar sorgulandığında uygulanır. DocumentDetailIsTreatWasteCancel NULL olan kayıtlar normal satıştır.",
      "modules": ["MasterReports"],
      "sql": {
        "aggregation": null,
        "filter": "[DocumentDetailIsTreatWasteCancel] IS NULL",
        "group_by": null,
        "select": null,
        "join": null,
        "having": null
      },
      "is_default": false
    },
    {
      "id": "sadece_ana_urun",
      "description": "Menü içi yan seçenekleri ve alt ürünleri hariç tutarak sadece bağımsız ana ürünleri filtrelemek için kullanılır. Ana ürünler, menü seçeneği olmayan ürünler, bağımsız ürünler, yan ürün olmayan kayıtlar sorgulandığında uygulanır. MenuId NULL veya boş GUID olan kayıtlar ana üründür.",
      "modules": ["MasterReports"],
      "sql": {
        "aggregation": null,
        "filter": "([MenuId] IS NULL OR [MenuId] = '00000000-0000-0000-0000-000000000000')",
        "group_by": null,
        "select": null,
        "join": null,
        "having": null
      },
      "is_default": false
    }
  ],
  "metadata": {
    "version": "3.0",
    "last_updated": "2026-02-24",
    "total_rules": 5,
    "default_rules_count": 1,
    "database_type": "MSSQL",
    "application": "Forza ERP - Master Report System",
    "embedding_strategy": "description only - rich natural language descriptions enable strong semantic search",
    "sql_components": {
      "aggregation": "SELECT içindeki aggregate fonksiyonlar (SUM, COUNT, AVG, etc.)",
      "filter": "WHERE koşulları — sql_generator AND ile birleştirir",
      "group_by": "GROUP BY kolonları",
      "select": "SELECT'e eklenecek ek kolonlar",
      "join": "JOIN ifadeleri",
      "having": "HAVING koşulları"
    }
  }
}
```

**Step 2: Commit**

```bash
git add src/graphs/generic_text2sql/business_rules.json
git commit -m "feat(business-rules): enrich descriptions for semantic RAG, remove triggers (v3.0)"
```

---

## Task 2: business_rules_vector_store.py — Individual rules döndür

**File:** `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py`

**Mevcut durumu anla:** `get_relevant_rules_for_query` şu an `merged_sql` dict döndürüyor. `sql_generator` bunu kullanıyor. Buna dokunmadan `individual_rules` listesi EKLENİR.

**Step 1: `get_relevant_rules_for_query` return değerine `individual_rules` ekle**

Mevcut return:
```python
return {
    "merged_sql": merged,
    "total_count": total_count,
    "default_count": ...,
    "semantic_count": ...,
}
```

Yeni return (mevcut kod korunur, `individual_rules` eklenir):

Fonksiyonun içinde, `return` öncesine şunu ekle:

```python
# Individual rules listesi (business_rules_node için — LLM ID seçer)
individual_rules = []

# Default rules
for rule in collected_default_rules:   # mevcut değişken adına göre ayarla
    individual_rules.append({
        "id": rule.get("id", "?"),
        "description": rule.get("description", ""),
        "sql": rule.get("sql", {}),
        "is_default": True,
        "source": "default",
    })

# Semantic / keyword rules (duplicate ID'leri atla)
seen_ids = {r["id"] for r in individual_rules}
for rule in collected_semantic_rules:   # mevcut değişken adına göre ayarla
    if rule.get("id") not in seen_ids:
        individual_rules.append({
            "id": rule.get("id", "?"),
            "description": rule.get("description", ""),
            "sql": rule.get("sql", {}),
            "is_default": False,
            "source": "semantic",
        })
        seen_ids.add(rule.get("id"))

return {
    "individual_rules": individual_rules,   # ← YENİ
    "merged_sql": merged,                   # ← KORUNDU (sql_generator için)
    "total_count": total_count,
    "default_count": default_count,
    "semantic_count": semantic_count,
}
```

> **Not:** `collected_default_rules` ve `collected_semantic_rules` değişken adları mevcut kodun içine bakarak ayarlanmalı. Bunlar `index_rules()` metodundan gelen ve `search_rules()` ile toplanan rule listelerdir.

**Step 2: Yeni description'lar için index yeniden oluştur**

```python
# Uygulama başlamadan önce (langgraph dev çalışmıyorken):
# chroma_persist_dir içini temizle — vector_store initialize_collections()'da yeniden oluşturacak
import shutil
shutil.rmtree("<chroma_persist_dir>", ignore_errors=True)
```

Veya `rebuild_index()` metodunu çağır:

```python
vector_store.rebuild_index()
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py
git commit -m "feat(business-rules): return individual_rules list from get_relevant_rules_for_query"
```

---

## Task 3: nodes.py — `create_business_rules_node` formatını güncelle

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: `business_rules_node` async fonksiyonu içini güncelle**

Mevcut: `merged_sql` dict'ten string üretiyor.

Yeni: `individual_rules` listesinden ID'li format üretir:

```python
async def business_rules_node(state: dict) -> dict:
    user_query = state.get("user_query", "")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _db_executor,
        lambda: vector_store.get_relevant_rules_for_query(
            user_query=user_query,
            n_results=5,
            use_hybrid=True,
        ),
    )

    individual_rules = result.get("individual_rules", [])

    if not individual_rules:
        logger.info("[BUSINESS_RULES] No relevant rules found")
        return {"business_rules_context": "Uygulanacak kural bulunamadı."}

    # Individual rules formatı: LLM ID seçebilsin
    parts = []
    for rule in individual_rules:
        rule_id   = rule.get("id", "?")
        desc      = rule.get("description", "")
        is_def    = rule.get("is_default", False)
        sql_hint  = _format_rule_sql_hint(rule.get("sql", {}))
        tag       = " [VARSAYILAN — HER ZAMAN UYGULA]" if is_def else ""
        parts.append(f"[{rule_id}]{tag}\n  Açıklama: {desc}\n  SQL: {sql_hint}")

    context = "\n\n".join(parts)
    logger.info(
        f"[BUSINESS_RULES] {result['total_count']} rules "
        f"({result['default_count']} default, {result['semantic_count']} semantic)"
    )
    return {"business_rules_context": context}
```

**Step 2: `_format_rule_sql_hint` helper ekle**

`create_business_rules_node` dışına, module seviyesine ekle:

```python
def _format_rule_sql_hint(sql: Dict[str, Any]) -> str:
    """Rule SQL bileşenlerini kısa okunabilir hint'e çevirir."""
    parts = []
    if sql.get("aggregation"):
        parts.append(f"AGG: {sql['aggregation'][:80]}")
    if sql.get("filter"):
        parts.append(f"FILTER: {sql['filter']}")
    if sql.get("group_by"):
        parts.append(f"GROUP_BY: {sql['group_by']}")
    if sql.get("having"):
        parts.append(f"HAVING: {sql['having']}")
    return " | ".join(parts) if parts else "(SQL bileşeni yok)"
```

**Step 3: Örnek `business_rules_context` çıktısı**

```
[iade_dusulmus] [VARSAYILAN — HER ZAMAN UYGULA]
  Açıklama: Ciro, satış tutarı veya gelir hesaplanırken iade işlemlerinin...
  SQL: AGG: SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)

[kapali_masa_filtre]
  Açıklama: Ödemesi alınmış, hesabı kapanmış, tamamlanmış masalara ait...
  SQL: FILTER: [IsTableActive] = 0
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(text2sql): business_rules_node emits individual rules with IDs for LLM selection"
```

---

## Task 4: prompts.py — KURAL 6 güncelle

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

**Step 1: KURAL 6'yı değiştir**

Mevcut KURAL 6 → şununla değiştir:

```
### KURAL 6 — Business Rules Seçimi (KRİTİK)
"UYGULANACAK İŞ KURALLARI" bölümünde kurallar [id] formatında listelenmiştir.

Uygulama adımları:
  1. [VARSAYILAN — HER ZAMAN UYGULA] etiketli rule ID'lerini applied_rule_ids'e MUTLAKA ekle
  2. Diğer rule'ların Açıklama'sını kullanıcı sorgusuyla karşılaştır
  3. Sorguyla örtüşen her rule'un ID'sini applied_rule_ids'e ekle
  4. SQL bileşenlerini (WHERE, SUM, GROUP BY) KENDİN YAZMA — Python uygular

Örnekler:
  Sorgu: "ödemesi alınan masaların cirosu" →
    applied_rule_ids: ["iade_dusulmus", "kapali_masa_filtre"]

  Sorgu: "toplam satış tutarı" →
    applied_rule_ids: ["iade_dusulmus"]

  Sorgu: "açık masalardaki normal satışlar" →
    applied_rule_ids: ["iade_dusulmus", "acik_masa_filtre", "sadece_normal_satis"]
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat(text2sql): update KURAL 6 with clear rule ID selection instructions + examples"
```

---

## Task 5: Uçtan uca test + index rebuild

**Step 1: ChromaDB index yeniden oluştur**

```bash
# langgraph dev kapalıyken chroma_persist_dir'ı temizle
# dizin yolu build_text2sql_graph'a geçilen chroma_persist_dir parametresinden okunur
rm -rf <chroma_persist_dir>
```

Sonra `langgraph dev` başlatıldığında `initialize_collections()` yeni embedding'leri oluşturur.

**Step 2: Sorgu testleri — LangGraph Studio**

Test 1 — Ana senaryo:
```
"Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori nedir?"
```
Beklenen `business_rules_context`:
- `[iade_dusulmus]` var (default)
- `[kapali_masa_filtre]` var (semantic match)

Beklenen `applied_rule_ids`: `["iade_dusulmus", "kapali_masa_filtre"]`

Beklenen SQL:
```sql
SELECT TOP 1 [CategoryName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [IsTableActive] = 0
  AND [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-24')
GROUP BY [CategoryName]
ORDER BY [ToplamCiro] DESC
```

Test 2 — Açık masa:
```
"Şu an açık masalardaki toplam ciro"
```
Beklenen `applied_rule_ids`: `["iade_dusulmus", "acik_masa_filtre"]`

Test 3 — Sadece default kural:
```
"Toplam satış tutarı nedir?"
```
Beklenen `applied_rule_ids`: `["iade_dusulmus"]`

**Step 3: Final commit**

```bash
git add -p
git commit -m "feat(business-rules): complete redesign - rich descriptions, individual rules format, KURAL 6 update"
```
