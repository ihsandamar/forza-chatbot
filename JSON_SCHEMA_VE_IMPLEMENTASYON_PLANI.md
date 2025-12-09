# JSON Schema Yapısal Sorunlar ve İmplementasyon Planı

**Tarih:** 2025-12-05
**Durum:** Vector Store Düzenlemeye Hazırlık

---

## 1. MEVCUT DÜZENLEMELER ANALİZİ

### ✅ İyi Yapılan Değişiklikler

#### 1.1 Root Level Metadata
```json
{
  "name": "FORZA ERP WEB SAYFASI JSON",
  "version": "0.0.0",
  "updated_date": "2025-12-05 14:17:31",
  ...
}
```

**Artıları:**
- Version tracking mümkün
- Update history takibi
- Duplicate detection için kullanılabilir

**Öneriler:**
- Semantic versioning kullan: `"0.1.0"` (major.minor.patch)
- `updated_by` alanı ekle
- `total_pages` count ekle (validation için)

#### 1.2 URL Parameter Endpoint Mapping
```json
"url_parameters": {
  "customerId": {
    "type": "guid",
    "description": "Cari Id",
    "required": true,
    "endpoint": "customers/getall"  // 👈 YENİ!
  }
}
```

**Artıları:**
- Tool'un hangi endpoint'i kullanacağı açık
- Otomatik tool mapping mümkün
- API-driven parameter extraction

**Kritik Sorun:**
```
endpoint: "customers/getall"
```
- Ama hangi TOOL bu endpoint'i kullanıyor?
- Tool ismi ne? get_customer_id_names mi?
- Tool'a hangi PARAMETRE gönderilmeli?

**Eksik Alan:**
```json
"customerId": {
  "type": "guid",
  "description": "Cari Id",
  "required": true,
  "endpoint": "customers/getall",
  "tool_name": "get_customer_id_names",     // 👈 EKLE
  "tool_parameter": "name",                  // 👈 EKLE
  "extraction_strategy": "user_input_match" // 👈 EKLE
}
```

---

## 2. KALAN YAPISAL SORUNLAR

### 🔴 KRİTİK: Schema Standardizasyonu Yok

**Sorun:** Her sayfa farklı field'lara sahip olabilir

```json
// Bazı sayfalar
"structured_data": {
  "functions": [...],
  "keywords": [...],
  "related_terms": [...],  // ❓ Optional mu?
  "user_types": [...]      // ❓ Optional mu?
}

// Bazı sayfalar
"structured_data": {
  "functions": [],  // Boş
  "keywords": []    // related_terms yok!
}
```

**Etki:**
- json_loader validation yapamıyor
- Eksik fieldlar runtime error verebilir
- Veri kalitesi kontrol edilemiyor

**Çözüm: JSON Schema Tanımla**

---

### 🔴 KRİTİK: Tool Integration Eksik

**Mevcut Durum:**
```json
"endpoint": "customers/getall"
```

**Sorular:**
1. Bu endpoint'i hangi tool kullanıyor?
   - `forza_routing_toolkit.py`'de 4 tool var
   - Hangisi customers endpoint'ini kullanıyor?
   - `get_customer_id_names` ✅

2. Tool'a ne parametre gönderilmeli?
   - Tool signature: `get_customer_id_names(name: str)`
   - User input'tan "name" nasıl extract edilecek?

3. Tool sonucu nasıl map edilecek?
   - Tool response: `{"customers": [{"customerId": "...", "name": "..."}]}`
   - Hangi field URL'ye gidecek? `customerId` ✅

**Eksik Schema:**
```json
"customerId": {
  "type": "guid",
  "description": "Cari Id",
  "required": true,

  // API Mapping
  "endpoint": "customers/getall",

  // Tool Mapping
  "tool_name": "get_customer_id_names",
  "tool_input_field": "name",
  "tool_output_field": "customerId",

  // Extraction Strategy
  "extraction_from": "user_input",
  "extraction_pattern": "customer_name",
  "extraction_prompt": "Kullanıcı hangi cariyi belirtti?"
}
```

---

### 🔴 KRİTİK: Parent-Child Relationship Belirsiz

**Mevcut:**
```json
"page_type": "sub_page",
"parent_page_id": "customer"
```

**Sorun:**
- `parent_page_id: "customer"` ama bu ID mevcut mu?
- `web_pages_catalog` içinde `page_id: "customer"` olan bir sayfa var mı?
- Cross-reference validation yok

**Senaryolar:**
```
Senaryo A: Parent sayfa eksik
  → Sub-page orphan kalır
  → json_loader hatası vermeli

Senaryo B: Parent sayfa yanlış ID
  → "customer" değil "customer-list" olmalıydı
  → Validation catch etmeli
```

**Çözüm:**
```python
def validate_parent_child_relationships(catalog):
    page_ids = {page['metadata']['page_id'] for page in catalog}

    for page in catalog:
        if page['metadata']['page_type'] == 'sub_page':
            parent_id = page['metadata'].get('parent_page_id')

            if not parent_id:
                raise ValueError(f"Sub-page {page['metadata']['page_id']} missing parent_page_id")

            if parent_id not in page_ids:
                raise ValueError(f"Parent page '{parent_id}' not found for {page['metadata']['page_id']}")
```

---

### 🟡 ÖNEMLI: Embedding Content Optimization Eksik

**Mevcut:**
```json
"embedding_content": "İlgili raporda carinin hareketlerini görüntüleyen özel dinamik rapor sayfasıdır"
```

**Sorunlar:**

1. **Çok Kısa (10 kelime)**
   - Embedding model için yetersiz context
   - Semantic richness düşük

2. **Keyword Tekrarı Yok**
   - "cari" 1 kez
   - "rapor" 1 kez
   - Embedding'de underrepresented

3. **Synonym Yok**
   - "cari" = müşteri, ticari hesap
   - "rapor" = analiz, listeleme

**Optimizasyon Stratejisi:**
```json
"embedding_content": {
  "primary": "Cari Raporu - Dinamik Rapor Görüntüleme. Bu sayfada seçili cariye ait tüm hareketleri özel dinamik raporlar üzerinden analiz edebilirsiniz.",

  "secondary": "Müşteri bazlı raporlama. Ticari hesap hareketleri. Cari analizi. Dinamik listeleme.",

  "keywords_weighted": "cari raporu, müşteri raporu, dinamik rapor, cari hareketleri, müşteri analizi",

  "use_cases": "Belirli bir carinin işlem geçmişini raporlamak. Müşteri bazlı finansal analiz yapmak."
}
```

**Alternatif (Basit):**
```json
"embedding_content": "Cari Raporu - Dinamik Rapor Sayfası\n\nBu sayfa belirli bir carinin (müşteri, ticari hesap) tüm hareketlerini dinamik raporlar üzerinden görüntülemenizi sağlar. Cari bazlı finansal analiz, işlem geçmişi raporlama ve müşteri hareketleri listeleme işlemlerini bu sayfadan yapabilirsiniz.\n\nAnahtar kavramlar: cari raporu, müşteri raporu, dinamik rapor, cari hareketleri, müşteri analizi, ticari hesap raporu"
```

**json_loader.py'de Processing:**
```python
def prepare_embedding_content(page):
    """Optimize content for embedding"""

    if isinstance(page['embedding_content'], dict):
        # Multi-field approach
        parts = [
            page['embedding_content']['primary'],
            page['embedding_content']['secondary'],
            page['embedding_content']['keywords_weighted']
        ]
        content = "\n\n".join(parts)
    else:
        # Simple string
        content = page['embedding_content']

    # Add keyword repetition (weighted embedding)
    keywords = page['structured_data'].get('keywords', [])
    if keywords:
        keyword_boost = " ".join(keywords[:5] * 2)  # Top 5 keywords, 2x
        content = f"{content}\n\n{keyword_boost}"

    return content
```

---

### 🟡 ÖNEMLI: User Expressions Validation

**Mevcut:**
```json
"user_expressions": [
  "'Cari Adı' carisi için 'Dinamik rapor Adı' raporunu görüntülemek istiyorum."
]
```

**Sorunlar:**

1. **Placeholder Notation Belirsiz**
   - `'Cari Adı'` - single quote kullanılmış
   - Ama bu bir variable mı yoksa literal text mi?
   - Parser nasıl anlayacak?

2. **Template vs Example**
   - Bu bir template mi yoksa example mı?
   - Template ise variable'lar nasıl extract edilecek?

**Standartlaştırma:**
```json
"user_expressions": {
  "templates": [
    "{customer_name} carisi için {report_name} raporunu görüntüle",
    "{customer_name} müşterisinin {report_name} raporu"
  ],
  "examples": [
    "Ahmet Yılmaz carisi için Satış Analizi raporunu görüntüle",
    "ABC Ltd müşterisinin Ciro raporu"
  ],
  "patterns": [
    "cari raporu",
    "müşteri raporu görüntüle",
    "dinamik rapor aç"
  ]
}
```

**Basit Alternatif (Backward Compatible):**
```json
"user_expressions": [
  "Ahmet Yılmaz carisi için Satış Analizi raporunu görüntüle",
  "ABC Ltd müşterisinin Ciro raporunu göster",
  "Cari bazlı dinamik rapor aç",
  "Müşteri raporu görüntüle",
  "Belirli carinin raporunu göster"
]
```

---

## 3. STANDART JSON SCHEMA

### 3.1 Complete Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "FORZA ERP Web Pages Catalog",
  "type": "object",
  "required": ["name", "version", "updated_date", "web_pages_catalog"],

  "properties": {
    "name": {
      "type": "string",
      "description": "Catalog name"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$",
      "description": "Semantic version (major.minor.patch)"
    },
    "updated_date": {
      "type": "string",
      "format": "date-time",
      "description": "Last update timestamp"
    },
    "updated_by": {
      "type": "string",
      "description": "Who updated (optional)"
    },
    "total_pages": {
      "type": "integer",
      "description": "Total page count (for validation)"
    },

    "web_pages_catalog": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/WebPage"
      }
    }
  },

  "definitions": {
    "WebPage": {
      "type": "object",
      "required": ["metadata", "embedding_content", "structured_data"],

      "properties": {
        "metadata": {
          "$ref": "#/definitions/PageMetadata"
        },
        "embedding_content": {
          "oneOf": [
            {"type": "string", "minLength": 50, "maxLength": 2000},
            {"$ref": "#/definitions/EmbeddingContentMultiField"}
          ]
        },
        "structured_data": {
          "$ref": "#/definitions/StructuredData"
        },
        "user_expressions": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 3,
          "description": "At least 3 user expression examples"
        }
      }
    },

    "PageMetadata": {
      "type": "object",
      "required": ["page_id", "title", "url_route", "category", "page_type"],

      "properties": {
        "page_id": {
          "type": "string",
          "pattern": "^[a-z0-9-]+$",
          "description": "Unique page identifier (kebab-case)"
        },
        "title": {
          "type": "string",
          "minLength": 3
        },
        "url_route": {
          "type": "string",
          "pattern": "^\\{baseUrl\\}",
          "description": "Must start with {baseUrl}"
        },
        "category": {
          "type": "string",
          "enum": ["dashboard", "customer", "product", "master-report", "dynamic_reports"]
        },
        "page_type": {
          "type": "string",
          "enum": ["main_page", "sub_page"]
        },
        "parent_page_id": {
          "type": "string",
          "description": "Required if page_type is sub_page"
        },
        "sub_page_type": {
          "type": "string",
          "enum": ["tab", "link"],
          "description": "Required if page_type is sub_page"
        },
        "url_parameters": {
          "type": "object",
          "additionalProperties": {
            "$ref": "#/definitions/URLParameter"
          }
        }
      },

      "if": {
        "properties": {"page_type": {"const": "sub_page"}}
      },
      "then": {
        "required": ["parent_page_id", "sub_page_type"]
      }
    },

    "URLParameter": {
      "type": "object",
      "required": ["type", "description", "required"],

      "properties": {
        "type": {
          "type": "string",
          "enum": ["guid", "string", "integer", "boolean"]
        },
        "description": {
          "type": "string",
          "minLength": 5
        },
        "required": {
          "type": "boolean"
        },
        "endpoint": {
          "type": "string",
          "description": "API endpoint path"
        },
        "tool_name": {
          "type": "string",
          "description": "LangChain tool name"
        },
        "tool_input_field": {
          "type": "string",
          "description": "Tool input parameter name"
        },
        "tool_output_field": {
          "type": "string",
          "description": "Field to extract from tool response"
        },
        "extraction_strategy": {
          "type": "string",
          "enum": ["user_input_match", "tool_search", "user_prompt"],
          "default": "tool_search"
        }
      }
    },

    "StructuredData": {
      "type": "object",
      "required": ["keywords"],

      "properties": {
        "functions": {
          "type": "array",
          "items": {"type": "string"}
        },
        "keywords": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 5,
          "description": "At least 5 keywords"
        },
        "related_terms": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Synonyms, translations, alternatives"
        },
        "user_types": {
          "type": "array",
          "items": {"type": "string"}
        }
      }
    }
  }
}
```

---

## 4. GELIŞTIRILMIŞ JSON ÖRNEĞI

### 4.1 Tam Şema ile Örnek

```json
{
  "name": "FORZA ERP WEB SAYFASI JSON",
  "version": "0.1.0",
  "updated_date": "2025-12-05T14:17:31Z",
  "updated_by": "System Admin",
  "total_pages": 1,

  "web_pages_catalog": [
    {
      "metadata": {
        "page_id": "customer-dynamic-report",
        "title": "Cari Raporu",
        "url_route": "{baseUrl}/apps/dynamic-report/view/{reportId}/%20/%7B%22CustomerId%22:%7B%22value%22:%22{customerId}%22%7D%7D",
        "category": "customer",
        "page_type": "sub_page",
        "parent_page_id": "customer-list",
        "sub_page_type": "link",
        "full_path": "Cari Raporu > Cari Listesi",

        "url_parameters": {
          "customerId": {
            "type": "guid",
            "description": "Cari ID (Müşteri/Tedarikçi benzersiz kimliği)",
            "required": true,
            "endpoint": "customers/getall",
            "tool_name": "get_customer_id_names",
            "tool_input_field": "name",
            "tool_output_field": "customerId",
            "extraction_strategy": "tool_search",
            "extraction_prompt": "Kullanıcının belirttiği cari/müşteri adını tool'a gönder"
          },
          "reportId": {
            "type": "guid",
            "description": "Dinamik Rapor ID (Rapor şablonu kimliği)",
            "required": true,
            "endpoint": "templates/getall",
            "tool_name": "get_template_list",
            "tool_input_field": "group_name",
            "tool_output_field": "id",
            "extraction_strategy": "tool_search",
            "extraction_prompt": "Kullanıcının belirttiği rapor adını tool'a gönder"
          }
        }
      },

      "embedding_content": "Cari Raporu - Dinamik Rapor Görüntüleme Sayfası\n\nBu sayfa belirli bir carinin (müşteri, ticari hesap, tedarikçi) tüm hareketlerini dinamik raporlar üzerinden görüntülemenizi sağlar. Seçilen cari için özel dinamik rapor şablonlarını kullanarak detaylı analiz yapabilirsiniz.\n\nİşlevler: Cari bazlı raporlama, müşteri hareketleri analizi, dinamik rapor görüntüleme, ticari hesap raporu, müşteri işlem geçmişi\n\nKullanım senaryoları: Belirli bir müşterinin satış raporunu görüntülemek, carinin ödeme geçmişini analiz etmek, özel rapor şablonları ile müşteri performansını değerlendirmek",

      "structured_data": {
        "functions": [
          "Cari bazlı dinamik rapor görüntüleme",
          "Müşteri hareketleri raporlama",
          "Rapor şablonu seçimi",
          "Cari analizi"
        ],
        "keywords": [
          "cari raporu",
          "müşteri raporu",
          "dinamik rapor",
          "cari hareketleri",
          "müşteri analizi",
          "ticari hesap raporu",
          "customer report",
          "dynamic report",
          "cari filtresi",
          "rapor görüntüleme"
        ],
        "related_terms": [
          "müşteri", "customer", "cari", "ticari hesap",
          "rapor", "report", "analiz", "analysis",
          "dinamik", "dynamic", "özel rapor", "custom report"
        ],
        "user_types": [
          "Muhasebe",
          "Finans Müdürü",
          "Satış Müdürü"
        ]
      },

      "user_expressions": [
        "Ahmet Yılmaz müşterisinin satış raporunu göster",
        "ABC Ltd carisi için ciro analizi raporu",
        "Mehmet Demir'in ödeme geçmişi raporunu aç",
        "Müşteri bazlı dinamik rapor görüntüle",
        "Cari için özel rapor aç",
        "XYZ Tedarikçi raporunu göster",
        "Belirli carinin hareketlerini raporla"
      ]
    }
  ]
}
```

---

## 5. JSON_LOADER.PY GEREKLİ DÜZENLEMELER

### 5.1 Schema Validation Ekleme

```python
# json_loader.py - Başlangıç
import jsonschema
from jsonschema import validate

SCHEMA_PATH = "data/forza_schema.json"

def load_and_validate_json(json_path):
    """Load and validate JSON against schema"""

    # Load schema
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    # Load catalog
    with open(json_path, 'r', encoding='utf-8') as f:
        catalog_data = json.load(f)

    # Validate
    try:
        validate(instance=catalog_data, schema=schema)
        print("✅ JSON schema validation passed")
    except jsonschema.ValidationError as e:
        print(f"❌ JSON validation failed: {e.message}")
        print(f"   Path: {' > '.join(str(p) for p in e.path)}")
        raise

    return catalog_data
```

### 5.2 Parent-Child Relationship Validation

```python
def validate_parent_child_relationships(catalog_data):
    """Validate sub-pages have existing parent pages"""

    pages = catalog_data['web_pages_catalog']
    page_ids = {page['metadata']['page_id'] for page in pages}

    errors = []

    for page in pages:
        metadata = page['metadata']

        if metadata['page_type'] == 'sub_page':
            parent_id = metadata.get('parent_page_id')

            if not parent_id:
                errors.append(f"❌ {metadata['page_id']}: Missing parent_page_id")
            elif parent_id not in page_ids:
                errors.append(f"❌ {metadata['page_id']}: Parent '{parent_id}' not found")

    if errors:
        print("\n".join(errors))
        raise ValueError("Parent-child relationship validation failed")

    print(f"✅ Parent-child relationships validated")
```

### 5.3 Tool Mapping Validation

```python
from src.tools.forza_routing_toolkit import ForzaRoutingToolkit

def validate_tool_mappings(catalog_data, toolkit: ForzaRoutingToolkit):
    """Validate tool names in url_parameters exist in toolkit"""

    available_tools = {tool.name for tool in toolkit.get_tools()}
    errors = []

    for page in catalog_data['web_pages_catalog']:
        url_params = page['metadata'].get('url_parameters', {})

        for param_name, param_config in url_params.items():
            tool_name = param_config.get('tool_name')

            if tool_name and tool_name not in available_tools:
                errors.append(
                    f"❌ {page['metadata']['page_id']}.{param_name}: "
                    f"Tool '{tool_name}' not found in toolkit"
                )

    if errors:
        print("\n".join(errors))
        raise ValueError("Tool mapping validation failed")

    print(f"✅ Tool mappings validated")
```

### 5.4 Content Quality Checks

```python
def check_content_quality(catalog_data):
    """Check embedding content and keywords quality"""

    warnings = []

    for page in catalog_data['web_pages_catalog']:
        page_id = page['metadata']['page_id']
        content = page.get('embedding_content', '')
        keywords = page['structured_data'].get('keywords', [])

        # Check content length
        if len(content) < 50:
            warnings.append(f"⚠️  {page_id}: Content too short ({len(content)} chars)")

        # Check keywords count
        if len(keywords) < 5:
            warnings.append(f"⚠️  {page_id}: Too few keywords ({len(keywords)})")

        # Check user expressions
        user_exprs = page.get('user_expressions', [])
        if len(user_exprs) < 3:
            warnings.append(f"⚠️  {page_id}: Too few user expressions ({len(user_exprs)})")

    if warnings:
        print("\n📊 Content Quality Warnings:\n")
        print("\n".join(warnings))
    else:
        print("✅ Content quality checks passed")
```

### 5.5 Enhanced Content Preparation

```python
def prepare_embedding_content(page):
    """Prepare optimized content for embedding with keyword weighting"""

    # Base content
    base_content = page.get('embedding_content', '')

    # Keyword boosting (repeat important keywords)
    keywords = page['structured_data'].get('keywords', [])
    if keywords:
        # Top 5 keywords, repeat 2x for embedding weight
        keyword_boost = " ".join(keywords[:5] * 2)
        base_content = f"{base_content}\n\n{keyword_boost}"

    # Add related terms
    related = page['structured_data'].get('related_terms', [])
    if related:
        base_content = f"{base_content}\n{' '.join(related)}"

    return base_content
```

### 5.6 Updated Main Flow

```python
def load_json_catalog_to_chroma():
    """Load JSON with full validation and optimization"""

    json_path = "data/forza.json"

    # 1. Load and validate schema
    print("📋 Step 1: Loading and validating JSON schema...")
    catalog_data = load_and_validate_json(json_path)

    # 2. Validate relationships
    print("\n🔗 Step 2: Validating parent-child relationships...")
    validate_parent_child_relationships(catalog_data)

    # 3. Validate tool mappings (if toolkit available)
    print("\n🔧 Step 3: Validating tool mappings...")
    try:
        toolkit = ForzaRoutingToolkit(
            base_url=config.forza.base_url,
            token=config.forza.token
        )
        validate_tool_mappings(catalog_data, toolkit)
    except Exception as e:
        print(f"⚠️  Tool validation skipped: {e}")

    # 4. Content quality checks
    print("\n📊 Step 4: Checking content quality...")
    check_content_quality(catalog_data)

    # 5. Prepare documents
    print("\n📝 Step 5: Preparing documents...")
    documents = []

    for page in catalog_data['web_pages_catalog']:
        # Optimize content for embedding
        optimized_content = prepare_embedding_content(page)

        # Create document (existing logic but with optimized content)
        if page['metadata']['page_type'] == 'main_page':
            doc = create_main_page_document(page, optimized_content)
        else:
            doc = create_sub_page_document(page, optimized_content, ...)

        documents.append(doc)

    # 6. Load to vectorstore (existing logic)
    print("\n🚀 Step 6: Loading to Chroma...")
    # ... (existing vectorstore logic)
```

---

## 6. IMPLEMENTATION CHECKLIST

### Phase 1: JSON Schema Setup (2 hours)

- [ ] Create `data/forza_schema.json` with full schema definition
- [ ] Add schema validation to json_loader.py
- [ ] Test schema validation with current JSON
- [ ] Fix any validation errors in JSON

### Phase 2: Enhanced Validation (3 hours)

- [ ] Implement parent-child relationship validation
- [ ] Implement tool mapping validation
- [ ] Implement content quality checks
- [ ] Add validation report generation

### Phase 3: Content Optimization (4 hours)

- [ ] Implement keyword weighting in embedding content
- [ ] Add related terms to embedding
- [ ] Optimize content preparation function
- [ ] Test embedding quality with sample queries

### Phase 4: Tool Integration Enhancement (4 hours)

- [ ] Update all URL parameters with tool mapping fields
- [ ] Update nodes.py to use tool_name from JSON
- [ ] Implement extraction_strategy logic
- [ ] Test tool execution with new schema

### Phase 5: Testing & Documentation (3 hours)

- [ ] Create test dataset (10-15 pages)
- [ ] Run validation suite
- [ ] Test vector search quality
- [ ] Document schema and usage

**Total Estimated Time: 16 hours**

---

## 7. ÖRNEK UPDATED JSON (Düzeltilmiş)

```json
{
  "name": "FORZA ERP WEB SAYFASI JSON",
  "version": "0.1.0",
  "updated_date": "2025-12-05T14:17:31Z",
  "updated_by": "DLL",
  "total_pages": 1,

  "web_pages_catalog": [
    {
      "metadata": {
        "page_id": "customer-dynamic-report",
        "title": "Cari Raporu",
        "url_route": "{baseUrl}/apps/dynamic-report/view/{reportId}/%20/%7B%22CustomerId%22:%7B%22value%22:%22{customerId}%22%7D%7D",
        "category": "customer",
        "page_type": "sub_page",
        "parent_page_id": "customer-list",
        "sub_page_type": "link",
        "full_path": "Cari Raporu > Cari Listesi",

        "url_parameters": {
          "customerId": {
            "type": "guid",
            "description": "Cari ID",
            "required": true,
            "endpoint": "customers/getall",
            "tool_name": "get_customer_id_names",
            "tool_input_field": "name",
            "tool_output_field": "customerId",
            "extraction_strategy": "tool_search"
          },
          "reportId": {
            "type": "guid",
            "description": "Dinamik Rapor ID",
            "required": true,
            "endpoint": "templates/getall",
            "tool_name": "get_template_list",
            "tool_input_field": "group_name",
            "tool_output_field": "id",
            "extraction_strategy": "tool_search"
          }
        }
      },

      "embedding_content": "Cari Raporu - Dinamik Rapor Görüntüleme. Bu sayfa belirli bir carinin (müşteri, ticari hesap) tüm hareketlerini dinamik raporlar üzerinden görüntülemenizi sağlar. Cari bazlı raporlama, müşteri hareketleri analizi, dinamik rapor görüntüleme işlemlerini yapabilirsiniz.",

      "structured_data": {
        "functions": [
          "Cari bazlı rapor görüntüleme",
          "Müşteri hareketleri raporlama"
        ],
        "keywords": [
          "cari raporu",
          "müşteri raporu",
          "dinamik rapor",
          "cari hareketleri",
          "müşteri analizi",
          "customer report",
          "dynamic report",
          "cari filtresi"
        ],
        "related_terms": [
          "müşteri", "customer", "cari", "ticari hesap",
          "rapor", "report", "analiz", "dinamik"
        ],
        "user_types": ["Muhasebe", "Finans Müdürü"]
      },

      "user_expressions": [
        "Ahmet Yılmaz müşterisinin satış raporunu göster",
        "ABC Ltd carisi için rapor aç",
        "Müşteri bazlı dinamik rapor görüntüle",
        "Cari için özel rapor göster",
        "Belirli müşterinin raporunu aç"
      ]
    }
  ]
}
```

---

## 8. SONRAKI ADIMLAR

### Immediate Actions

1. **JSON Schema File Oluştur**
   - `data/forza_schema.json` dosyasını yukarıdaki schema ile oluştur

2. **json_loader.py Güncelle**
   - Schema validation ekle
   - Enhanced validation functions ekle
   - Content optimization ekle

3. **Mevcut JSON'u Güncelle**
   - Tool mapping fields ekle
   - Content'leri optimize et
   - Validation geç

### Testing

```bash
# Schema validation test
python scripts/json_loader.py --validate-only

# Full load test
python scripts/json_loader.py

# Search quality test
python scripts/test_vector_search.py
```

---

**HAZIR - Implementation Başlayabilir!**
