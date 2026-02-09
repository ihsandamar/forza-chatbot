# Business Rules Vector Store

## 🎯 Amaç

Text-to-SQL sistemlerinde en büyük sorun: **LLM'in şirketin iş kurallarını bilmemesi**.

- "Gelir nedir?" → Her şirkette farklı
- "Premium müşteri kim?" → Farklı tanımlar
- "Aktif kullanıcı?" → Farklı kriterler

### ❌ Geleneksel Yaklaşım Problemleri

1. **Tüm kuralları her sorguda prompt'a koy**
   - Token israfı (binlerce token)
   - "Lost in the middle" problemi
   - Yüksek maliyet
   - Yavaş yanıt

### ✅ Vector Store Çözümü

**Semantic search** ile kullanıcı sorusuna en alakalı 3-5 kuralı otomatik seç:

```
Query: "Premium müşterilerin aylık cirosu"
↓
Vector Store:
✅ "Premium = Gold/Platinum tier" (similarity: 0.92)
✅ "Ciro = SUM(amount) WHERE completed" (similarity: 0.88)
✅ "Aylık = GROUP BY month" (similarity: 0.85)
↓
LLM'e minimal ama yeterli context
```

**Sonuç**: Kısa prompt, düşük maliyet, yüksek doğruluk!

---

## 🏗️ Mimari Kararlar

### 1️⃣ Sadece Description + Modules Embed Et (🔴 Kritik)

**Neden?**
- SQL syntax'ı semantic anlam taşımaz
- "SUM(amount)" embed etmek = token israfı
- İş mantığı description'da zaten var

```python
# ✅ DOĞRU
embedding_text = "Toplam gelir hesaplaması. Anahtar: gelir, ciro, revenue"

# ❌ YANLIŞ
embedding_text = "SUM(amount) WHERE status='completed'"
```

### 2️⃣ SQL'i Metadata'da Sakla (🔴 Kritik)

SQL components metadata olarak:
```python
metadata = {
    "sql_aggregation": "SUM(amount)",
    "sql_filter": "status = 'completed'",
    "sql_group_by": None,
    ...
}
```

**Avantajları**:
- Embedding'de yer kaplamaz
- Direkt kullanılabilir
- Merge edilebilir

### 3️⃣ Default Kurallar Ayrı Collection (🟡 Önemli)

`is_default: true` kurallar her sorguya uygulanır:

```json
{
  "id": "exclude_test_orders",
  "description": "Test siparişleri hariç tut",
  "is_default": true,
  "sql": {
    "filter": "is_test = false"
  }
}
```

**Neden ayrı collection?**
- Her sorguda garantili dahil edilir
- Semantic search'e gerek yok
- Performans optimizasyonu

### 4️⃣ Hybrid Search (🟡 Önemli)

**Semantic Search** + **Keyword Search**

```python
# Semantic: "premium müşteri" → finds "Gold/Platinum tier"
semantic_results = search_rules(query, n_results=5)

# Keyword: "ARR" → direct match "arr_calculation"
keyword_results = keyword_search(['ARR'], n_results=3)

# Combine
final_results = deduplicate(semantic + keyword)
```

### 5️⃣ SQL Merge Mantığı (🔴 Kritik)

Birden fazla kuraldan gelen SQL'leri birleştir:

```python
Rule 1: filter = "status = 'completed'"
Rule 2: filter = "is_test = false"
Rule 3: filter = "tier IN ('Gold', 'Platinum')"

Merged:
WHERE (status = 'completed') AND (is_test = false) AND (tier IN ('Gold', 'Platinum'))
```

**Logic**:
- `filter`, `having` → `AND` ile birleştir
- `group_by`, `select` → `,` ile birleştir
- `join` → yan yana ekle
- `aggregation` → ilkini al

### 6️⃣ Similarity Threshold (🟡 Önemli)

`threshold = 0.7` → Alakasız kuralları filtrele

```python
Results:
- Rule A: similarity 0.92 ✅
- Rule B: similarity 0.78 ✅
- Rule C: similarity 0.65 ❌ (filtered)
- Rule D: similarity 0.45 ❌ (filtered)
```

### 7️⃣ Table-Aware Filtering (🢧 Nice-to-have)

Sadece ilgili tablolara ait kuralları getir:

```python
Query: "Müşteri sayısı"
Detected tables: ['customers']

# Bu kuralla match eder
{
  "id": "premium_customer",
  "related_tables": ["customers"]  ✅
}

# Bu kural filtrelenir
{
  "id": "order_count",
  "related_tables": ["orders"]  ❌
}
```

---

## 📦 Kurulum

### 1. Bağımlılıkları Yükle

```bash
pip install -r requirements.txt
```

Gerekli paketler:
- `chromadb==1.1.1`
- `sentence-transformers==2.2.2`

### 2. Vector Store'u Initialize Et

```python
from business_rules_vector_store import BusinessRulesVectorStore

# Initialize
store = BusinessRulesVectorStore(
    rules_file_path="business_rules.json",
    similarity_threshold=0.7
)

# Index oluştur
store.rebuild_index()
```

### 3. Test Et

```bash
cd src/graphs/generic_text2sql
python business_rules_vector_store.py
```

---

## 🚀 Kullanım

### Basit Search

```python
# Alakalı kuralları ara
results = store.search_rules(
    query="Premium müşterilerin toplam geliri",
    n_results=5,
    include_defaults=True,
    table_filter=['customers', 'orders']
)

for rule in results:
    print(f"{rule['rule_id']}: {rule['similarity']:.2f}")
```

### SQL ile Birlikte Kullan

```python
# Kuralları bul ve SQL'leri merge et
result = store.get_relevant_rules_for_query(
    user_query="Bu ayki premium müşteri geliri",
    detected_tables=['customers', 'orders'],
    n_results=5
)

print("Merged SQL:")
print(result['merged_sql'])
# {
#   'filter': "(status = 'completed') AND (is_test = false) AND (tier IN ('Gold', 'Platinum'))",
#   'aggregation': "SUM(amount)"
# }
```

### Text-to-SQL Entegrasyonu

```python
from business_rules_integration_example import Text2SQLWithBusinessRules

# Initialize
text2sql = Text2SQLWithBusinessRules()

# Generate SQL with business rules
result = text2sql.generate_sql_with_rules(
    user_query="Premium müşterilerin bu ayki toplam geliri",
    schema=your_db_schema,
    detected_tables=['customers', 'orders'],
    llm_function=your_llm  # OpenAI, Anthropic, etc.
)

print(result['sql'])
print(result['applied_rules'])
print(result['business_context'])  # LLM'e gönderilen context
```

---

## 📊 Demo

```bash
# Vector Store demo
python business_rules_vector_store.py

# Integration demo
python business_rules_integration_example.py
```

### Expected Output:

```
🔍 Query: Premium müşterilerin bu ayki cirosu nedir?
------------------------------------------------------------
📊 Stats:
   - Default rules: 3
   - Semantic rules: 2
   - Total rules: 5

📋 Found Rules:
   - [premium_customer_definition] (similarity: 0.920)
   - [revenue_total] (similarity: 0.885)
   - [current_month_filter] (similarity: 0.812)
   - [exclude_cancelled_refunded] (similarity: 0.750) [DEFAULT]
   - [exclude_test_orders] (similarity: 0.750) [DEFAULT]

🔧 Merged SQL:
   filter: (tier IN ('Gold', 'Platinum')) AND (order_date >= DATE_TRUNC('month', CURRENT_DATE)) AND (status NOT IN ('cancelled', 'refunded')) AND (is_test = false)
   aggregation: SUM(amount)
```

---

## 🔧 Graph'a Entegrasyon

### Adım 1: State'e Business Rules Ekle

```python
class GraphState(TypedDict):
    user_query: str
    schema: str
    detected_tables: List[str]
    business_rules_context: str  # ← Yeni
    merged_sql_components: Dict  # ← Yeni
    generated_sql: str
```

### Adım 2: Yeni Node Ekle

```python
def retrieve_business_rules(state: GraphState) -> GraphState:
    """Alakalı business rules'ı bul"""

    result = vector_store.get_relevant_rules_for_query(
        user_query=state['user_query'],
        detected_tables=state['detected_tables'],
        n_results=5
    )

    # Context oluştur
    context = format_rules_for_llm(result['rules'])

    return {
        **state,
        'business_rules_context': context,
        'merged_sql_components': result['merged_sql']
    }
```

### Adım 3: SQL Generator Node'u Güncelle

```python
def generate_sql(state: GraphState) -> GraphState:
    """Business rules ile SQL generate et"""

    prompt = f"""
Generate SQL for: {state['user_query']}

Schema: {state['schema']}

Business Rules:
{state['business_rules_context']}

Apply these SQL components:
{state['merged_sql_components']}
"""

    sql = llm.invoke(prompt)
    return {**state, 'generated_sql': sql}
```

### Adım 4: Graph Flow'a Ekle

```python
workflow.add_node("retrieve_business_rules", retrieve_business_rules)
workflow.add_node("generate_sql", generate_sql)

workflow.add_edge("detect_tables", "retrieve_business_rules")
workflow.add_edge("retrieve_business_rules", "generate_sql")
```

---

## 📈 Performance Optimizasyonu

### Caching

Index bir kere oluşturulur, sonra persist edilir:

```python
# İlk sefer: index oluştur
store.rebuild_index()

# Sonraki çalıştırmalar: var olan index'i kullan
store = BusinessRulesVectorStore(...)  # Auto-loads
```

### Batch Processing

Çok fazla sorgu varsa batch olarak işle:

```python
queries = ["query1", "query2", "query3", ...]

results = []
for query in queries:
    result = store.get_relevant_rules_for_query(query)
    results.append(result)
```

### Threshold Tuning

Production'da optimal threshold bul:

```python
# Development: düşük threshold (daha fazla kural)
threshold = 0.5

# Production: yüksek threshold (sadece çok alakalı kurallar)
threshold = 0.75
```

---

## 🧪 Test Scenarios

```python
test_cases = [
    {
        'query': 'Premium müşterilerin aylık cirosu',
        'expected_rules': ['premium_customer_definition', 'revenue_total', 'monthly_breakdown'],
        'min_similarity': 0.7
    },
    {
        'query': 'Aktif kullanıcı sayısı',
        'expected_rules': ['active_customer_definition', 'customer_count'],
        'min_similarity': 0.8
    }
]

for test in test_cases:
    result = store.get_relevant_rules_for_query(test['query'])
    assert all(r['similarity'] >= test['min_similarity'] for r in result['rules'])
```

---

## 🎓 Best Practices

1. **Her yeni iş kuralı için business_rules.json'a ekle**
   - Consistent format kullan
   - Description'ı açıklayıcı yaz
   - Modules'a tüm varyasyonları ekle

2. **Default rules'ı minimize et**
   - Sadece gerçekten her sorguya uygulananlar
   - Çok fazla default rule = her sorguya gereksiz overhead

3. **Threshold'u production'da test et**
   - Düşük = çok kural (alakasız dahil)
   - Yüksek = az kural (gerekli kurallar eksik)
   - A/B test yap

4. **Table filtering kullan**
   - Performans artışı
   - Daha alakalı sonuçlar

5. **Index'i periyodik güncelle**
   - business_rules.json değiştiğinde rebuild et
   - Automated pipeline kur

---

## 🔍 Troubleshooting

### Problem: Alakasız kurallar geliyor

**Çözüm**: Threshold'u artır
```python
store = BusinessRulesVectorStore(similarity_threshold=0.8)
```

### Problem: Hiç kural gelmiyor

**Çözüm**:
1. Threshold'u düşür
2. Modules'lara daha fazla keyword ekle
3. Description'ı daha açıklayıcı yap

### Problem: Index yavaş

**Çözüm**:
1. Persist directory kullan (tekrar oluşturma yok)
2. Daha hızlı embedding model: `all-MiniLM-L6-v2`
3. Kuralları sayısını azalt (gereksiz kuralları temizle)

### Problem: SQL merge hatalı

**Çözüm**:
1. `merge_sql_components()` logic'ini kontrol et
2. Placeholder'ları doğru replace et
3. SQL syntax'ı business_rules.json'da kontrol et

---

## 📝 License

MIT

## 👥 Contributors

- DLL (Initial implementation)

---

## 🚀 Roadmap

- [ ] LangGraph entegrasyonu otomatiği
- [ ] Web UI (Gradio) ile rule management
- [ ] A/B testing framework
- [ ] Rule conflict detection
- [ ] Auto-tuning threshold
- [ ] Multi-language support (English, Turkish, etc.)
