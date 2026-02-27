# Term Resolution v2 + Prompt/Context Engineering — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** TermVectorStore false positive filter'larını 3 katmanlı koruma ile (threshold + parallel LLM gate + restructured prompt context) ortadan kaldırmak; BusinessRulesVectorStore ile sorumluluk ayrımını netleştirmek.

**Architecture:** threshold=0.75 ile kalitesiz eşleşmeler elenir → term_validator_node (LLM, parallel) kalan filter adaylarını onaylar/reddeder → validated_term_filters sql_generator'a aktarılır. TermVectorStore yalnızca metrik/boyut ipuçları + filter_return + filter_treat + ambiguity detection ile sorumlu; IsTableActive/MenuId/IsTreatWasteCancel kuralları BusinessRulesVectorStore'da kalır.

**Tech Stack:** LangGraph, langchain_openai (structured output), ChromaDB (sentence-transformers), Pydantic v2

**Design Doc:** `docs/plans/2026-02-27-term-resolution-v2-design.md`

---

## Bağlam — Mevcut Pipeline

```
term_resolver (TermVectorStore)
  → term_filters (raw, false positive riski)
  → term_hints (advisory)
  ↓
[sql_architect ∥ schema_validator]   ← her ikisi term_hints görür
  ↓
schema_merge → sql_generator (term_filters'ı WHERE'e ekler, LLM override edilir)
```

**Sonra (bu plan):**
```
term_resolver (TermVectorStore, threshold=0.75)
  → term_filters (raw)
  → candidate_filter_terms (term_id + metadata, term_validator için)
  → term_hints (PYTHON-YÖNETİMLİ + KOLON İPUÇLARI bölümleri)
  ↓
[sql_architect ∥ schema_validator ∥ term_validator]   ← zero latency fan-out
                                      ↑ LLM onaylar/reddeder
  ↓
schema_merge → sql_generator (validated_term_filters'ı WHERE'e ekler)
```

---

## Task 1: Threshold Yükselt + term_dictionary.json Temizle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py:36`
- Modify: `src/graphs/report_agent/subagents/text2sql/term_dictionary.json`

### Adım 1: term_vector_store.py — threshold değiştir

`term_vector_store.py` line 34'te:
```python
# ESKİ
_DEFAULT_SIMILARITY_THRESHOLD = 0.60

# YENİ
_DEFAULT_SIMILARITY_THRESHOLD = 0.75
```

### Adım 2: term_dictionary.json — 6 filter term kaldır

**KALDIRILACAK term ID'leri** (BusinessRulesVectorStore / LLM + value_resolver zaten hallediyor):
- `filter_closed_table` → business rule: `kapali_masa_filtre`
- `filter_open_table` → business rule: `acik_masa_filtre`
- `filter_main_product` → business rule: `sadece_ana_urun`
- `filter_normal_sale` → business rule: `sadece_normal_satis`
- `filter_dine_in` → LLM + value_resolver (DocumentKindName)
- `filter_delivery` → LLM + value_resolver (DocumentKindName)

**KALACAK terms (14 adet):**
metric_revenue, metric_quantity, metric_discount, metric_ambiguous_how_much,
dim_document, dim_category, dim_product, dim_branch, dim_cashier, dim_table,
dim_city, dim_customer, **filter_return**, **filter_treat**

`term_dictionary.json`'u aşağıdaki içerikle yaz (kaldırılan terimleri çıkart, kalanları koru):

```json
{
  "version": "2.1",
  "description": "Türkçe iş terimi → DB kolon/değer eşleştirme sözlüğü. Tablo bağımsız. v2.1: Filter terms sadece filter_return + filter_treat (diğerleri business rules / LLM).",
  "terms": [
    {
      "id": "metric_revenue",
      "category": "metric",
      "term": "ciro",
      "aliases": ["satış tutarı", "gelir", "revenue", "tutar", "satış", "kazanç", "hasılat"],
      "column": "RowAmount",
      "specificity": 1.0,
      "hint": "Satış tutarını temsil eder → aggregations: SUM([RowAmount]) kullan",
      "embedding_text": "Ciro, gelir, hasılat, satış tutarı, para birimi cinsinden satış değeri, toplam tutar"
    },
    {
      "id": "metric_quantity",
      "category": "metric",
      "term": "adet",
      "aliases": ["miktar", "quantity", "satış adedi", "satılan", "kaç tane"],
      "column": "Quantity",
      "specificity": 1.0,
      "hint": "Satış adedini temsil eder → aggregations: SUM([Quantity]) kullan",
      "embedding_text": "Satış adedi, miktar, kaç tane, adet, satılan ürün sayısı"
    },
    {
      "id": "metric_discount",
      "category": "metric",
      "term": "indirim",
      "aliases": ["iskonto", "indirim tutarı", "discount"],
      "column": "DiscountAmountTotal",
      "specificity": 1.0,
      "hint": "İndirim tutarı → aggregations: SUM([DiscountAmountTotal]) veya AVG([DiscountAmountTotal]) kullan",
      "embedding_text": "İndirim tutarı, iskonto miktarı, discount, uygulanan indirim"
    },
    {
      "id": "metric_ambiguous_how_much",
      "category": "metric",
      "term": "ne kadar sattı",
      "aliases": [
        "ne kadar", "sattı", "ne kadar satıldı", "ne kadar oldu",
        "satış miktarı nedir", "toplam satış", "satış bilgisi"
      ],
      "specificity": 0.2,
      "ambiguous_columns": [
        {
          "column": "RowAmount",
          "description": "Satış tutarı (TL)",
          "filter_structured": null
        },
        {
          "column": "Quantity",
          "description": "Satış miktarı (Adet)",
          "filter_structured": null
        }
      ],
      "hint": "Kullanıcı seçimine göre belirlenecek",
      "embedding_text": "Satış miktarı veya tutarı belirsiz soru, ne kadar, hangi ölçüt"
    },
    {
      "id": "dim_document",
      "category": "dimension",
      "term": "adisyon",
      "aliases": ["fiş", "sipariş", "belge", "document"],
      "column": "DocumentId",
      "specificity": 1.0,
      "hint": "Adisyon sayısı için → aggregations: COUNT(DISTINCT [DocumentId]) kullan",
      "embedding_text": "Adisyon, fiş, sipariş belgesi, belge sayısı, document count"
    },
    {
      "id": "dim_category",
      "category": "dimension",
      "term": "kategori",
      "aliases": ["kategoriler", "kategoriye göre", "kategorilere göre", "kategoride", "ürün kategorisi"],
      "column": "CategoryName",
      "specificity": 1.0,
      "hint": "Kategori kolonu → group_by veya select: [CategoryName] kullan",
      "embedding_text": "Kategori, ürün grubu, ürün kategorisi, hangi kategoride"
    },
    {
      "id": "dim_product",
      "category": "dimension",
      "term": "ürün",
      "aliases": ["ürünler", "ürüne göre", "ürünlere göre", "ürün adı", "menü ürünü"],
      "column": "ProductName",
      "specificity": 0.8,
      "hint": "Ürün kolonu → group_by veya select: [ProductName] kullan",
      "embedding_text": "Ürün adı, menü ürünü, yemek, hangi ürün"
    },
    {
      "id": "dim_branch",
      "category": "dimension",
      "term": "şube",
      "aliases": ["şubeler", "şubeye göre", "şubelere göre", "şubede", "lokasyon"],
      "column": "BranchName",
      "specificity": 1.0,
      "hint": "Şube kolonu → group_by veya select: [BranchName] kullan",
      "embedding_text": "Şube, lokasyon, restoran şubesi, hangi şubede"
    },
    {
      "id": "dim_cashier",
      "category": "dimension",
      "term": "kasiyer",
      "aliases": ["kasiyerler", "kasiyere göre", "kasiyerlere göre", "kasiyer adı"],
      "column": "CashierName",
      "specificity": 1.0,
      "hint": "Kasiyer kolonu → group_by veya select: [CashierName] kullan",
      "embedding_text": "Kasiyer adı, ödeme alan, kasiyere göre"
    },
    {
      "id": "dim_table",
      "category": "dimension",
      "term": "masa",
      "aliases": ["masa numarası", "masa no", "table no", "masalar"],
      "column": "TableNo",
      "specificity": 0.7,
      "hint": "Masa numarası kolonu → group_by veya select: [TableNo] kullan",
      "embedding_text": "Masa numarası, hangi masada, table no"
    },
    {
      "id": "dim_city",
      "category": "dimension",
      "term": "şehir",
      "aliases": ["şehirler", "şehre göre", "şehirlere göre", "il"],
      "column": "BranchCityName",
      "specificity": 1.0,
      "hint": "Şehir kolonu → group_by veya select: [BranchCityName] kullan",
      "embedding_text": "Şehir, il, bulunduğu şehir, hangi ilde"
    },
    {
      "id": "dim_customer",
      "category": "dimension",
      "term": "cari",
      "aliases": [
        "cariler", "cariye göre", "carilere göre", "caride",
        "müşteri", "müşteriler", "müşteriye göre", "müşterilere göre",
        "müşteri adı", "müşteri bazında", "cari bazında", "cari hesap"
      ],
      "column": "CustomerName",
      "specificity": 1.0,
      "hint": "Cari/müşteri kolonu → group_by veya select: [CustomerName] kullan",
      "embedding_text": "Müşteri, cari hesap, müşteri adı, cari bazında, alıcı"
    },
    {
      "id": "filter_return",
      "category": "status",
      "term": "iade",
      "aliases": ["iade satış", "geri iade", "return", "sadece iade", "iade işlemleri"],
      "column": "DocumentTypeIsReturn",
      "specificity": 1.0,
      "filter_structured": {"column": "DocumentTypeIsReturn", "operator": "=", "value": "1"},
      "hint": "[DocumentTypeIsReturn] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Sadece iade edilen satışlar, geri iade işlemleri, return only, iade satışı filtresi"
    },
    {
      "id": "filter_treat",
      "category": "status",
      "term": "ikram",
      "aliases": ["bedava", "ikram edilen", "ücretsiz", "complimentary", "sadece ikram"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "specificity": 1.0,
      "filter_structured": {"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
      "hint": "[DocumentDetailIsTreatWasteCancel] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "İkram edilen ürün, bedava verilen, ücretsiz ürün, complimentary only, sadece ikram"
    }
  ]
}
```

### Adım 3: ChromaDB koleksiyonu sıfırla

TermVectorStore'un `initialize(force_recreate=True)` çağrısı gerekli çünkü term sayısı değişti.
Bunu `graph.py`'de geçici olarak `force_recreate=True` yapıp bir kez çalıştırarak sağla,
ardından `False`'a geri al (veya ChromaDB persist dizinini elle sil: `./data/vector_store`).

### Adım 4: Commit

```bash
git add src/graphs/report_agent/subagents/text2sql/term_vector_store.py
git add src/graphs/report_agent/subagents/text2sql/term_dictionary.json
git commit -m "feat(term-resolver): raise threshold 0.75, remove 6 overlapping filter terms v2.1"
```

---

## Task 2: State + Configuration

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py`
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/configuration.py`

### Adım 1: text2sql/state.py — iki yeni field

`Text2SQLState` class'ına iki field ekle (satır 31'den sonra):

```python
# Mevcut:
term_filters:      Optional[List[Dict[str, Any]]] # term_resolver → sql_generator (Python garantili WHERE)
term_hints:        Optional[str]                  # term_resolver → sql_architect + schema_validator

# EKLE (sonrasına):
candidate_filter_terms: Optional[List[Dict[str, Any]]]  # term_resolver → term_validator (term_id + metadata)
validated_term_filters: Optional[List[Dict[str, Any]]]  # term_validator → sql_generator (onaylanan filtreler)
```

Ayrıca docstring'deki "Internal keys" satırına da ekle:
```python
# Eski:
#     query_schema, schema_validation, auto_rules, term_filters, term_hints, retry_count, sql_error
# Yeni:
#     query_schema, schema_validation, auto_rules, term_filters, term_hints,
#     candidate_filter_terms, validated_term_filters, retry_count, sql_error
```

### Adım 2: state.py (parent ReportState) — validated_term_filters ekle

`src/graphs/report_agent/state.py` dosyasını aç. Mevcut state class'ına ekle:

```python
validated_term_filters: Optional[List[Dict[str, Any]]]  # term_validator çıktısı
candidate_filter_terms: Optional[List[Dict[str, Any]]]  # term_resolver → term_validator
```

> Not: `state.py`'nin tam içeriğini önce oku, sonra uygun yere ekle.

### Adım 3: configuration.py — business_rules_path ekle

`ReportAgentConfiguration` class'ına yeni field ekle (column_metadata'dan sonra):

```python
business_rules_path: str = Field(
    default="./src/graphs/generic_text2sql/business_rules.json",
    description="Business rules JSON dosya yolu. LangGraph Studio'dan runtime'da override edilebilir.",
)
```

### Adım 4: Commit

```bash
git add src/graphs/report_agent/subagents/text2sql/state.py
git add src/graphs/report_agent/state.py
git add src/graphs/report_agent/configuration.py
git commit -m "feat(state): add candidate_filter_terms + validated_term_filters; config: business_rules_path"
```

---

## Task 3: TermVectorStore — candidate_filter_terms + Restructured Hints

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py`

Bu task'ta `TermResolverOutput`'a yeni field ekleyecek ve `_apply_conflict_resolution` içindeki hint formatını yenileyeceğiz.

### Adım 1: TermResolverOutput'a candidate_filter_terms ekle

`term_vector_store.py`'de `TermResolverOutput` dataclass'ını güncelle:

```python
@dataclass
class TermResolverOutput:
    """
    TermVectorStore.resolve() dönüş tipi.

    term_filters            : Python katmanı tarafından sql_generator'a merge edilir.
    candidate_filter_terms  : term_validator_node için — term_id + metadata ile zenginleştirilmiş.
    hints_text              : LLM prompt'una inject edilir.
    ambiguous               : interrupt() ile kullanıcıya sorulacak terimler.
    """
    term_filters: List[Dict[str, Any]] = field(default_factory=list)
    candidate_filter_terms: List[Dict[str, Any]] = field(default_factory=list)  # YENİ
    hints_text: str = "Özel terim eşleşmesi bulunamadı."
    ambiguous: List[AmbiguousMatch] = field(default_factory=list)
```

### Adım 2: _apply_conflict_resolution — candidate_filter_terms doldur + hints yeniden yapılandır

`_apply_conflict_resolution` metodunu aşağıdaki gibi güncelle.
**Kritik değişiklikler:**
1. `candidate_filter_terms` listesi eklendi
2. `filter_hint_lines` ve `column_hint_lines` ayrı tutuldu
3. hints_text iki bölümlü formatta oluşturuluyor

```python
def _apply_conflict_resolution(
    self,
    candidates: List[TermCandidate],
    user_query: str,
) -> TermResolverOutput:
    sorted_candidates = sorted(candidates, key=lambda c: c.sort_key, reverse=True)

    resolved_columns: Dict[str, TermCandidate] = {}
    term_filters: List[Dict[str, Any]] = []
    candidate_filter_terms: List[Dict[str, Any]] = []  # YENİ
    filter_hint_lines: List[str] = []     # Python-managed filter hints
    column_hint_lines: List[str] = []     # Metric/dimension hints for LLM
    ambiguous: List[AmbiguousMatch] = []

    for candidate in sorted_candidates:

        # --- Unambiguous term ---
        if not candidate.is_ambiguous and candidate.column:
            if candidate.column not in resolved_columns:
                resolved_columns[candidate.column] = candidate

                if candidate.filter_structured:
                    # Filter term → Python-managed section
                    fs = dict(candidate.filter_structured)
                    fs.setdefault("logical_operator", "AND")
                    term_filters.append(fs)
                    candidate_filter_terms.append({          # YENİ
                        "term_id": candidate.term_id,
                        "term": candidate.term,
                        "column": candidate.column,
                        "filter_structured": candidate.filter_structured,
                        "hint": candidate.hint,
                    })
                    col_val = f"{candidate.filter_structured.get('column')} {candidate.filter_structured.get('operator')} {candidate.filter_structured.get('value', '')}".strip()
                    filter_hint_lines.append(f"- {col_val}  ({candidate.term})")
                else:
                    # Dimension/metric term → LLM hint section
                    column_hint_lines.append(
                        f'- "{candidate.term}" [{candidate.column}] → {candidate.hint}'
                    )

                logger.debug(
                    f"[TERM_VECTOR_STORE] Resolved: '{candidate.term}' → "
                    f"'{candidate.column}' (sim={candidate.similarity:.2f}, "
                    f"spec={candidate.specificity})"
                )
            continue

        # --- Ambiguous term ---
        if candidate.is_ambiguous:
            amb_cols = [c["column"] for c in candidate.ambiguous_columns]
            already_resolved = [c for c in amb_cols if c in resolved_columns]

            if already_resolved:
                for col in already_resolved:
                    winner = resolved_columns[col]
                    column_hint_lines.append(
                        f'- "{candidate.term}" → "{winner.term}" terimi ile '
                        f'[{col}] olarak çözüldü (interrupt suppressed)'
                    )
                logger.info(
                    f"[TERM_VECTOR_STORE] SUPPRESS: '{candidate.term}' ambiguity suppressed "
                    f"by {[resolved_columns[c].term for c in already_resolved]}"
                )
            else:
                ambiguous.append(AmbiguousMatch(
                    term=candidate.term,
                    user_query=user_query,
                    options=candidate.ambiguous_columns,
                ))
                column_hint_lines.append(
                    f'- "{candidate.term}" → belirsiz kolon, kullanıcıya sorulacak'
                )
                logger.info(
                    f"[TERM_VECTOR_STORE] AMBIGUOUS: '{candidate.term}' → "
                    f"interrupt required ({amb_cols})"
                )

    # --- Hints text — iki bölümlü yapı ---
    hints_sections: List[str] = []

    if filter_hint_lines:
        hints_sections.append(
            "## PYTHON-YÖNETİMLİ FİLTRELER (sen filters'a EKLEME — Python garantili uygular)\n"
            + "\n".join(filter_hint_lines)
        )

    if column_hint_lines:
        hints_sections.append(
            "## KOLON İPUÇLARI (LLM için rehber — aggregations/group_by kararlarında kullan)\n"
            + "\n".join(column_hint_lines)
        )

    hints_text = (
        "\n\n".join(hints_sections)
        if hints_sections
        else "Özel terim eşleşmesi bulunamadı."
    )

    logger.info(
        f"[TERM_VECTOR_STORE] resolve() done: "
        f"{len(term_filters)} filter(s), "
        f"{len(candidate_filter_terms)} filter_candidates, "
        f"{len(column_hint_lines)} hint(s), "
        f"{len(ambiguous)} interrupt(s)"
    )
    return TermResolverOutput(
        term_filters=term_filters,
        candidate_filter_terms=candidate_filter_terms,  # YENİ
        hints_text=hints_text,
        ambiguous=ambiguous,
    )
```

### Adım 3: Commit

```bash
git add src/graphs/report_agent/subagents/text2sql/term_vector_store.py
git commit -m "feat(term-vector-store): add candidate_filter_terms, restructure hints into 2-section format"
```

---

## Task 4: prompts.py — TermValidationResult + TERM_VALIDATOR_PROMPT + Prompt Updates

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py`

### Adım 1: TermValidationResult Pydantic modeli ekle

`BusinessRulesValidationResult`'dan hemen sonra ekle:

```python
class TermValidationResult(BaseModel):
    """
    term_validator_node LLM validation için structured output.
    TermVectorStore'dan gelen aday filter term'lerin hangilerinin
    kullanıcı tarafından gerçekten kastetildiğine karar verir.
    """
    approved_filter_ids: List[str]
    """
    Kullanıcının AÇIKÇA kastettiği filter term ID'leri.
    Emin olmadığın → EKLEME. False positive doğru pozitiften tehlikelidir.
    """
    reasoning: str
    """Kısa açıklama: hangi terimleri neden kabul/reddettim."""
```

### Adım 2: TERM_VALIDATOR_PROMPT ekle (SQL_ARCHITECT_PROMPT'tan önce)

```python
TERM_VALIDATOR_PROMPT = """Sen bir filtre terimi doğrulayıcısısın. Kullanıcı sorgusunu analiz et ve ADAY FİLTRE TERİMLERİ'nden hangilerinin kullanıcı tarafından AÇIKÇA kastetildiğini belirle.

## KULLANICI SORUSU
{user_query}

## ADAY FİLTRE TERİMLERİ (TermVectorStore semantic eşleşmesi)
{candidate_filters}

---

## KARAR KRİTERLERİ

**Filtre ONAYLANIR eğer:**
- Kullanıcı o kavramı sorguda AÇIKÇA belirtmişse
- Örnek: "sadece iade satışları göster" → filter_return ONAY ✓
- Örnek: "ikram edilen ürünler ne kadar?" → filter_treat ONAY ✓
- Örnek: "iade hariç ciro" → filter_return ONAY ✓ (iade açıkça geçiyor)

**Filtre REDDEDİLİR eğer:**
- Kullanıcı o kavramı hiç belirtmemişse — yalnızca semantik benzerlik var
- Örnek: "ödemesi alınan masalarda ciro" → filter_return RED ✗ ("iade" kelimesi geçmiyor)
- Örnek: "hangi ürün en çok sattı" → filter_treat RED ✗ ("ikram" geçmiyor)
- Örnek: "son 1 yılda satışlar" → filter_return RED ✗ (genel satış sorusu)

approved_filter_ids'e sadece kullanıcının gerçekten kastettiği ID'leri yaz.
Emin olmadığında → listeye EKLEME (false positive sonuçsuz sorgu demek).
"""
```

### Adım 3: SQL_ARCHITECT_PROMPT — KURAL 0 güncelle

`SQL_ARCHITECT_PROMPT`'ta KURAL 0'ı bul ve şöyle güncelle:

```python
### KURAL 0 — Terim Eşleştirmeleri (EN YÜKSEK ÖNCELİK)
term_hints iki bölümden oluşur:

"PYTHON-YÖNETİMLİ FİLTRELER" bölümü: Bu kolonları filters'a ASLA EKLEME.
Python garantili olarak WHERE'e eklenecek — sen tekrar eklersen çelişki çıkar.

"KOLON İPUÇLARI" bölümü: Bu eşleştirmeleri MUTLAKA aggregations ve group_by'da kullan.
"KULLANICI METRİK KOLON SEÇİMİ" varsa o kolon ZORUNLU OLARAK tüm aggregations'larda kullanılmalıdır.
```

### Adım 4: SCHEMA_VALIDATOR_PROMPT — KURAL 5.5 ekle

`SCHEMA_VALIDATOR_PROMPT`'ta KURAL 5'ten sonra yeni kural ekle:

```python
## KURAL 5.5 — Python-Managed Filtreler (KRİTİK)
term_hints'teki "PYTHON-YÖNETİMLİ FİLTRELER" bölümündeki kolonları
filters listene ASLA ekleme. Python zaten uygulayacak — sen ekleyince çelişki yaratır.

YANLIŞ ❌:
  term_hints: "PYTHON-YÖNETİMLİ: DocumentTypeIsReturn = 1 (iade)"
  → filters: [{{column: DocumentTypeIsReturn, value: 1}}]   ← Python zaten ekliyor!

DOĞRU ✅:
  term_hints: "PYTHON-YÖNETİMLİ: DocumentTypeIsReturn = 1 (iade)"
  → filters listene EKLEME — Python hallediyor.
```

### Adım 5: prompts.py import'a List ekle (gerekirse)

`from typing import List, Literal, Optional` satırını kontrol et, `List` var mı bak.

### Adım 6: Commit

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat(prompts): add TermValidationResult + TERM_VALIDATOR_PROMPT; update KURAL 0 + KURAL 5.5"
```

---

## Task 5: nodes.py — term_validator_node + term_resolver güncelle + sql_generator güncelle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

### Adım 1: Import'a TermValidationResult ekle

`nodes.py`'nin import bölümünde:
```python
from src.graphs.report_agent.subagents.text2sql.prompts import (
    QuerySchema,
    SchemaValidationResult,
    BusinessRulesValidationResult,
    TermValidationResult,          # YENİ
    SQL_ARCHITECT_PROMPT,
    SCHEMA_VALIDATOR_PROMPT,
    BUSINESS_RULES_VALIDATOR_PROMPT,
    TERM_VALIDATOR_PROMPT,         # YENİ
)
```

### Adım 2: create_term_validator_node fonksiyonu ekle

`create_term_resolver_node`'dan hemen SONRA ekle:

```python
def create_term_validator_node(llm) -> Callable:
    """
    Parallel LLM gate: term_resolver'ın ürettiği filter adaylarını doğrular.

    BusinessRulesValidationResult ile aynı pattern:
      - structured output → approved_filter_ids
      - Onaylanmayan filter'lar validated_term_filters'a GİRMEZ
      - sql_generator term_filters yerine validated_term_filters okur

    term_resolver ile PARALLEL çalışır (schema_merge fan-in'i bekler).
    Latency: 0 — schema_merge zaten sql_architect + schema_validator bekliyor.
    """
    structured_llm = llm.with_structured_output(TermValidationResult)

    def _format_candidate_filters(candidate_filter_terms: list) -> str:
        """term_validator prompt için okunabilir format."""
        if not candidate_filter_terms:
            return "Aday filtre terimi yok."
        lines = []
        for cft in candidate_filter_terms:
            fs = cft.get("filter_structured") or {}
            col = fs.get("column", "?")
            op = fs.get("operator", "=")
            val = fs.get("value", "")
            where_desc = f"{col} {op} {val}".strip()
            lines.append(
                f"  - ID: {cft['term_id']}\n"
                f"    Terim: \"{cft['term']}\"\n"
                f"    Eklenecek WHERE: {where_desc}"
            )
        return "\n".join(lines)

    async def term_validator_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        candidate_filter_terms = state.get("candidate_filter_terms") or []

        # Aday yoksa → doğrulama atla, boş döndür
        if not candidate_filter_terms:
            logger.info("[TERM_VALIDATOR] No filter candidates, skipping validation")
            return {"validated_term_filters": []}

        candidate_filters_text = _format_candidate_filters(candidate_filter_terms)
        prompt = TERM_VALIDATOR_PROMPT.format(
            user_query=user_query,
            candidate_filters=candidate_filters_text,
        )

        logger.info(
            f"[TERM_VALIDATOR] Validating {len(candidate_filter_terms)} filter candidate(s) "
            f"for: {user_query[:80]}"
        )

        try:
            result: TermValidationResult = await structured_llm.ainvoke(prompt)
        except Exception as e:
            logger.error(f"[TERM_VALIDATOR] LLM error: {e} — falling back to empty")
            return {"validated_term_filters": []}

        approved_ids = set(result.approved_filter_ids)
        validated_term_filters = [
            {**cft["filter_structured"], "logical_operator": "AND"}
            for cft in candidate_filter_terms
            if cft.get("term_id") in approved_ids and cft.get("filter_structured")
        ]

        logger.info(
            f"[TERM_VALIDATOR] {len(candidate_filter_terms)} candidates → "
            f"{len(validated_term_filters)} approved: {result.approved_filter_ids} | "
            f"{result.reasoning[:100]}"
        )
        return {"validated_term_filters": validated_term_filters}

    return term_validator_node
```

### Adım 3: create_term_resolver_node — candidate_filter_terms state'e yaz

`term_resolver_node`'un return bloğunu güncelle:

```python
# ESKİ:
return {
    "term_filters": term_filters,
    "term_hints":   hints_text,
}

# YENİ:
return {
    "term_filters":           term_filters,
    "candidate_filter_terms": result.candidate_filter_terms,  # YENİ — term_validator için
    "term_hints":             hints_text,
}
```

> `result` burada `term_vector_store.resolve(user_query)` dönüş değeri.
> `result.candidate_filter_terms` Task 3'te eklendi.

### Adım 4: sql_generator_node — validated_term_filters oku

`sql_generator_node` içinde `term_filters` okuyan satırı güncelle:

```python
# ESKİ (satır ~577):
term_filters = state.get("term_filters") or []

# YENİ:
validated_term_filters = state.get("validated_term_filters")
# validated_term_filters None ise (term_validator çalışmamış/crash) → [] ile devam
# term_filters'a FALLBACK YAPMA — false positive riskini önlemek için
term_filters = validated_term_filters if validated_term_filters is not None else []

if validated_term_filters is None:
    logger.warning(
        "[SQL_GENERATOR] validated_term_filters None — term_validator may not have run. "
        "Using empty list (LLM handles filters via prompts)."
    )
```

### Adım 5: logger satırını güncelle

Aynı fonksiyonun `logger.info` satırını güncelle:
```python
# ESKİ:
f"[SQL_GENERATOR] term_filters merged: {[tf['column'] for tf in term_filters]}"
# YENİ:
f"[SQL_GENERATOR] validated_term_filters merged: {[tf['column'] for tf in term_filters]}"
```

### Adım 6: Commit

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(nodes): add create_term_validator_node; update term_resolver + sql_generator for validated_term_filters"
```

---

## Task 6: graph.py — term_validator Node + Edge + business_rules_path

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py`
- Modify: `src/graphs/report_agent/graph.py`

### Adım 1: text2sql/graph.py — import güncelle

```python
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_schema_validator_node,
    create_sql_architect_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,
    create_term_validator_node,   # YENİ
    create_value_resolver_node,
    schema_merge_node,
)
```

### Adım 2: text2sql/graph.py — term_validator node ve edge ekle

`build_text2sql_graph` fonksiyonunda, `term_resolver` ile `schema_merge` arasına ekle:

```python
# --- Node factories ---
# ... (mevcut node'lar aynen kalır) ...
term_resolver       = create_term_resolver_node(term_vector_store)
term_validator      = create_term_validator_node(llm)          # YENİ
sql_architect       = create_sql_architect_node(llm, column_metadata)
# ...

# --- Graph nodes ---
graph.add_node("term_resolver",     term_resolver)
graph.add_node("term_validator",    term_validator)            # YENİ
graph.add_node("sql_architect",     sql_architect)
# ...

# --- Edges ---
# Fan-out: term_resolver → sql_architect + schema_validator + term_validator (paralel)
graph.add_edge("term_resolver",     "sql_architect")
graph.add_edge("term_resolver",     "schema_validator")
graph.add_edge("term_resolver",     "term_validator")          # YENİ

# Fan-in: her üçü tamamlandığında → schema_merge
graph.add_edge("sql_architect",     "schema_merge")
graph.add_edge("schema_validator",  "schema_merge")
graph.add_edge("term_validator",    "schema_merge")            # YENİ
```

### Adım 3: text2sql/graph.py — log satırını güncelle

```python
# ESKİ:
"[TEXT2SQL] Subgraph v2.1 built: ..."
# YENİ:
"[TEXT2SQL] Subgraph v2.2 built: "
"create_table → business_rules → term_resolver "
"→ [sql_architect ∥ schema_validator ∥ term_validator] → schema_merge "
"→ value_resolver → sql_generator → sql_executor → cleanup_table (max 2 retry)"
```

### Adım 4: report_agent/graph.py — build_report_agent_graph business_rules_path configurable

`build_report_agent_graph` içinde, `build_text2sql_graph` çağrısından önce:

```python
from src.graphs.report_agent.configuration import ReportAgentConfiguration

def build_report_agent_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
    chroma_persist_dir: str,
    checkpointer=None,
):
    # business_rules_path artık ReportAgentConfiguration.business_rules_path default'u ile
    # override edilebilir (Studio configurable panelinden). Build-time default kullanılır.
    default_business_rules_path = (
        ReportAgentConfiguration.model_fields["business_rules_path"].default
    )
    effective_business_rules_path = business_rules_path or default_business_rules_path

    text2sql = build_text2sql_graph(
        llm,
        table_name,
        column_metadata,
        connection_string,
        effective_business_rules_path,   # değişti
        chroma_persist_dir,
    )
    # ... geri kalan aynen kalır
```

### Adım 5: text2sql/graph.py docstring güncelle

Graph başındaki docstring'i güncelle:
```python
"""
Text2SQL Subagent Graph (v2.2)

START → create_table → business_rules → term_resolver
        ├── sql_architect (LLM)    ──┐
        ├── schema_validator (LLM) ──┼→ schema_merge → value_resolver
        └── term_validator (LLM)   ──┘
        → sql_generator → sql_executor ──────────────────────────────┐
                               ↑ (retry, max 2)                      │
                               └─────────────────────────────────────┘
                                                                      ↓
                                                          cleanup_table → END

term_validator: Parallel LLM gate — filter adaylarını onaylar/reddeder (approved_filter_ids).
sql_generator: validated_term_filters okur (term_validator onaylıları). LLM yok.
"""
```

### Adım 6: Commit

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git add src/graphs/report_agent/graph.py
git commit -m "feat(graph): add term_validator parallel node; business_rules_path via ReportAgentConfiguration v2.2"
```

---

## Task 7: Rebuild ChromaDB + Doğrulama

**Files:** Hiç değişmez — bu verification task'ı.

### Adım 1: ChromaDB koleksiyonunu sıfırla

`term_vector_store.py`'de `_DEFAULT_COLLECTION = "term_dictionary"`.
Term sayısı değiştiği için eski collection'ı temizle:

```bash
# Seçenek A: persist dizinini elle sil (server kapalıyken)
rm -rf ./data/vector_store

# Seçenek B: graph.py'de geçici force_recreate
# term_vector_store.initialize(force_recreate=True) yapıp bir kez başlat, sonra False'a al
```

### Adım 2: Sunucuyu başlat

```bash
langgraph dev
```

### Adım 3: Failing query'yi test et

LangGraph Studio'da yeni thread, query:
```
Son 1 senede ödemesi alınan masalarda en çok hangi ürün ne kadar ciro yaptı
```

**Beklenen state:**
- `candidate_filter_terms`: `[]` (filter_closed_table artık TermVectorStore'da yok; filter_return 0.75 geçemez)
- `validated_term_filters`: `[]`
- `term_hints`: "KOLON İPUÇLARI" bölümünde `ciro → RowAmount`, `ürün → ProductName`
- `auto_rules`: `kapali_masa_filtre` (BusinessRulesVectorStore bulur), `iade_dusulmus` (default)

**Beklenen SQL:**
```sql
SELECT TOP 1 [ProductName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-27')
    AND [IsTableActive] = 0
GROUP BY [ProductName]
ORDER BY [ToplamCiro] DESC
```

**Kontrol listesi:**
- [ ] `DocumentTypeIsReturn = 1` WHERE'de YOK ✓
- [ ] `DocumentKindName = 'Masa'` WHERE'de YOK ✓
- [ ] `MenuId IS NULL` WHERE'de YOK ✓
- [ ] `IsTableActive = 0` var (business rule) ✓
- [ ] `CASE WHEN DocumentTypeIsReturn` SELECT'te var (business rule) ✓

### Adım 4: İkinci test — explicit iade sorgusu

```
Son 1 ayda sadece iade satışların toplamı ne kadar?
```

**Beklenen:**
- `candidate_filter_terms`: `[{term_id: filter_return, ...}]`
- `validated_term_filters`: `[{column: DocumentTypeIsReturn, operator: =, value: 1}]`
- SQL'de: `AND [DocumentTypeIsReturn] = 1` ✓

### Adım 5: Son commit (gerekirse cleanup)

```bash
git add -A
git commit -m "chore: term-resolution v2.2 verification complete"
```
