# Generic Text2SQL Mimari Tasarım Dokümanı

## 📋 Genel Bakış

Bu doküman, context-aware, esnek ve token-efficient bir Text2SQL sistemi için mimari tasarımı açıklar.

---

## 🎯 Mevcut Durum

### Akış
```
intent_parser → intent_matching → metadata_enrichment → value_resolver → sql_query_builder → sql_executor
```

### Node'ların Görevleri

1. **intent_parser_node**: Generic intent parsing (tablo-agnostic)
2. **intent_matching_node**: Field hints → DB column mapping
3. **metadata_enrichment_node**: Sadece kullanılan kolonlar için metadata
4. **value_resolver_node**: Value fuzzy matching ve resolution
5. **sql_query_builder_node**: SQL generation
6. **sql_executor_node**: SQL execution

---

## 🚨 Yeni İhtiyaç: Context-Aware Business Rules

### Problem
Bazı durumlarda kolonlar birlikte kullanılmalı veya ek kurallar uygulanmalı:

**Örnek 1: DocumentId Gruplama**
```
Kullanıcı: "Her adisyonun toplam tutarı"
Gerekli: GROUP BY DocumentId
Ama aynı zamanda: SELECT DocumentDate, TableNo (context için)
```

**Örnek 2: IsTableActive Kullanımı**
```
Kullanıcı: "Açık masaların tutarı"
Gerekli: WHERE IsTableActive = True
Ama aynı zamanda: SELECT TableNo, DocumentDate (hangi masa, ne zamandan beri açık)
```

**Örnek 3: Menu Ürünleri**
```
Kullanıcı: "Menü ürünlerinin satışı"
Gerekli: WHERE MenuId IS NOT NULL
Ama aynı zamanda: JOIN gerekebilir (ana ürün bilgisi için)
```

---

## 🏗️ Mimari Seçenekler

### Seçenek 1: Rule Engine Node ❌

**Yapı:**
```
metadata_enrichment → rules_engine_node → value_resolver
```

**Artıları:**
- Ayrı bir node, modüler
- Test edilebilir
- Python code ile esnek kurallar

**Eksileri:**
- Yeni bir node (complexity artar)
- Token kullanımı artar
- SQL builder'a rule output göndermek gerekir

---

### Seçenek 2: Metadata-Driven Simple ❌

**Yapı:**
```python
COLUMN_METADATA_DETAILED = {
    "DocumentId": {
        "description": "...",
        "when_grouped_add_columns": ["DocumentDate", "TableNo"]
    }
}
```

**Artıları:**
- Tek yerde metadata
- Ek node yok

**Eksileri:**
- Metadata şişer
- Karmaşık rule'lar zor
- Bakımı zorlaşır

---

### Seçenek 3: Prompt-Driven ❌

**Yapı:**
SQL_QUERY_BUILDER_PROMPT'a tüm kuralları ekle

**Artıları:**
- Basit implementasyon
- LLM karar verir

**Eksileri:**
- Token israfı (her seferinde tüm kurallar)
- Güvenilirlik düşük
- Kontrol azalır

---

### ✅ Seçenek 4: HYBRID CONTEXT-AWARE (ÖNERİLEN)

**Konsept:**
- **Lightweight rules** metadata'da
- **metadata_enrichment_node** context-aware olur
- **Sadece ilgili rules** SQL builder'a gider

#### Yapı

```python
# prompts.py veya config.py
CONTEXT_RULES = {
    "DocumentId": {
        "when_grouped": {
            "add_to_select": ["DocumentDate", "TableNo", "BranchName"],
            "reason": "Adisyon context bilgisi için gerekli"
        }
    },
    "IsTableActive": {
        "when_filtered": {
            "add_to_select": ["TableNo", "DocumentDate", "DocumentId"],
            "reason": "Masa durumu context bilgisi"
        }
    },
    "MenuId": {
        "when_filtered": {
            "add_to_select": ["ProductName"],
            "suggest_note": "MenuId ile ilişkili ana ürün bilgisi önemlidir"
        }
    },
    "DocumentDetailIsTreatWasteCancel": {
        "when_filtered": {
            "add_to_select": ["ProductName", "Quantity", "RowAmount"],
            "reason": "İkram/zayi/iptal detayları için ürün bilgisi gerekli"
        }
    }
}
```

#### metadata_enrichment_node Güncellemesi

```python
async def metadata_enrichment_node(state: GenericText2SQLState) -> GenericText2SQLState:
    # ... mevcut kod ...

    # Context-aware rules uygula
    context_hints = {}

    for step in parsed_intent["steps"]:
        # GROUP BY kontrolü
        if "group_by" in step and step["group_by"]:
            for field in step["group_by"]:
                if field in CONTEXT_RULES and "when_grouped" in CONTEXT_RULES[field]:
                    rule = CONTEXT_RULES[field]["when_grouped"]
                    context_hints[field] = {
                        "add_to_select": rule.get("add_to_select", []),
                        "reason": rule.get("reason", "")
                    }

        # FILTER kontrolü
        if "filters" in step:
            for filter_def in step["filters"]:
                field = filter_def.get("field_hint")
                if field in CONTEXT_RULES and "when_filtered" in CONTEXT_RULES[field]:
                    rule = CONTEXT_RULES[field]["when_filtered"]
                    context_hints[field] = {
                        "add_to_select": rule.get("add_to_select", []),
                        "reason": rule.get("reason", "")
                    }

    # State'e ekle
    state["context_hints"] = context_hints

    # Enriched metadata'ya context bilgisi ekle
    for field, hint in context_hints.items():
        for additional_col in hint.get("add_to_select", []):
            if additional_col in COLUMN_METADATA_DETAILED:
                enriched_metadata[additional_col] = COLUMN_METADATA_DETAILED[additional_col]

    return state
```

#### SQL Builder Güncellemesi

```python
async def sql_query_builder_node(state: GenericText2SQLState) -> GenericText2SQLState:
    # ... mevcut kod ...

    # Context hints'i formatla
    context_hints = state.get("context_hints", {})
    context_text = ""

    if context_hints:
        context_text = "\n\n## CONTEXT-AWARE KURALLAR\n"
        for field, hint in context_hints.items():
            context_text += f"\n### {field} kullanıldığında:\n"
            context_text += f"- SELECT'e ekle: {', '.join(hint['add_to_select'])}\n"
            context_text += f"- Neden: {hint['reason']}\n"

    response = await chain.ainvoke({
        "resolved_steps": steps_json,
        "enriched_metadata": metadata_text,
        "context_rules": context_text  # Yeni!
    })
```

---

## 📊 Token Karşılaştırması

### Önceki (Tüm kurallar her seferinde)
```
TABLO BİLGİSİ: 200 tokens
TÜM KURALLAR: 500 tokens
RESOLVED STEPS: 300 tokens
---
TOPLAM: 1000 tokens
```

### Hybrid (Sadece ilgili kurallar)
```
TABLO BİLGİSİ: (yok, sadece kullanılan kolonlar)
KULLANILAN KOLONLAR METADATA: 100 tokens
CONTEXT RULES (2-3 kural): 50 tokens
RESOLVED STEPS: 300 tokens
---
TOPLAM: 450 tokens (%55 tasarruf!)
```

---

## 🎯 Avantajlar

### 1. Token Efficient ✅
Sadece kullanılan kolonlar için kurallar gönderilir.

### 2. Esnek ✅
Yeni kurallar kolayca eklenebilir:
```python
CONTEXT_RULES["NewColumn"] = {
    "when_grouped": {...}
}
```

### 3. Bakımı Kolay ✅
Tek bir yerde (CONTEXT_RULES), okunabilir format.

### 4. Test Edilebilir ✅
Her kural bağımsız test edilebilir.

### 5. LLM-Friendly ✅
SQL builder'a giden kurallar doğal dil formatında.

---

## 🔄 Örnek Akış

### Kullanıcı: "Her adisyonun toplam tutarı nedir"

#### 1. intent_parser
```json
{
  "group_by": ["adisyon_id"],
  "aggregations": [{"function": "SUM", "field_hint": "tutar"}]
}
```

#### 2. intent_matching
```json
{
  "group_by": ["DocumentId"],
  "aggregations": [{"function": "SUM", "field_hint": "RowAmount"}]
}
```

#### 3. metadata_enrichment (Context-Aware!)
```python
used_columns = ["DocumentId", "RowAmount"]

# DocumentId GROUP BY olduğu için context rule tetiklenir
context_hints = {
    "DocumentId": {
        "add_to_select": ["DocumentDate", "TableNo", "BranchName"],
        "reason": "Adisyon context bilgisi için gerekli"
    }
}

# Ek kolonlar metadata'ya eklenir
enriched_metadata = {
    "DocumentId": "Adisyon ID...",
    "RowAmount": "Satış tutarı...",
    "DocumentDate": "Satış tarihi...",  # Context!
    "TableNo": "Masa numarası...",       # Context!
    "BranchName": "Şube adı..."          # Context!
}
```

#### 4. SQL Builder'a Giden Prompt
```
## KULLANILAN KOLONLAR
- DocumentId: Adisyon ID...
- RowAmount: Satış tutarı...
- DocumentDate: Satış tarihi...
- TableNo: Masa numarası...
- BranchName: Şube adı...

## CONTEXT-AWARE KURALLAR
### DocumentId kullanıldığında:
- SELECT'e ekle: DocumentDate, TableNo, BranchName
- Neden: Adisyon context bilgisi için gerekli

## RESOLVED STEPS
{...}
```

#### 5. SQL Output
```sql
SELECT
    DocumentId,
    DocumentDate,     -- Context rule!
    TableNo,          -- Context rule!
    BranchName,       -- Context rule!
    SUM(RowAmount) AS TotalAmount
FROM MasterReportDocumentTable
GROUP BY DocumentId, DocumentDate, TableNo, BranchName
```

---

## 🛠️ Implementasyon Planı

### Adım 1: CONTEXT_RULES Tanımla
`src/graphs/generic_text2sql/context_rules.py` oluştur

### Adım 2: metadata_enrichment_node Güncelle
Context-aware logic ekle

### Adım 3: State Güncelle
`context_hints` field ekle

### Adım 4: SQL Builder Güncelle
Context rules kullan

### Adım 5: Test
Her kural için test case'ler

---

## 🎨 Alternatif: Gelişmiş Rule Engine

Eğer çok karmaşık kurallar gerekirse:

```python
class RuleEngine:
    def __init__(self):
        self.rules = []

    def add_rule(self, condition, action):
        self.rules.append((condition, action))

    def apply(self, context):
        for condition, action in self.rules:
            if condition(context):
                action(context)

# Örnek kullanım
engine = RuleEngine()

engine.add_rule(
    condition=lambda ctx: "DocumentId" in ctx.group_by,
    action=lambda ctx: ctx.add_to_select(["DocumentDate", "TableNo"])
)
```

Ama şu an için **Hybrid Context-Aware** yaklaşımı yeterli.

---

## 📝 Sonuç ve Öneri

### ✅ Önerilen Yaklaşım: Hybrid Context-Aware

**Neden?**
1. Token efficient (%50+ tasarruf)
2. Esnek ve genişletilebilir
3. Bakımı kolay
4. Test edilebilir
5. Ek node gerektirmiyor (sadece metadata_enrichment güncellenir)

**Nasıl?**
1. CONTEXT_RULES config oluştur
2. metadata_enrichment_node'u context-aware yap
3. SQL builder'a context hints gönder

**Ne zaman?**
Hemen! Mevcut yapıya kolayca entegre olur.

---

## 🔮 Gelecek Genişletmeler

1. **Performance Rules**: INDEX hint'leri
2. **Data Quality Rules**: NULL check, validation
3. **Security Rules**: Row-level security
4. **Caching Rules**: Frequently used queries

---

**Tarih:** 2025-12-23
**Versiyon:** 1.0
**Durum:** Öneri - Implementasyon Bekliyor
