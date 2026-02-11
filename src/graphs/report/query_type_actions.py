"""
Query Type Actions - Context Building & Entity Extraction

Bu modül query_type'a göre SQL generation context'i oluşturur ve
user query'den entity extraction yapar.
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional

from langchain_core.language_models import BaseChatModel

from .state import ReportState
from .query_type_patterns import (
    get_pattern,
    format_pattern_for_prompt,
    get_sql_hints
)

logger = logging.getLogger(__name__)


# =============================================================================
# ENTITY EXTRACTION (LLM-driven)
# =============================================================================

async def extract_entities_from_context(
    user_query: str,
    query_type: str,
    conversation_history: Optional[List],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Extract entities from user query AND previous context.

    Handles:
    - "bu iki kategoriyi" → extract from previous results
    - "içecekler ile kıyasla" → extract "içecekler" + previous category
    - "X ve Y" → extract both entities

    Args:
        user_query: User's natural language query
        query_type: Detected query type
        conversation_history: Previous conversation entries
        llm: Language model for extraction

    Returns:
        {
            "entities": ["DURUMLAR", "ICECEKLER"],
            "entity_column": "CategoryName",
            "entity_source": "mixed",  # "query", "context", "mixed"
            "confidence": 0.9,
            "needs_clarification": False,
            "reasoning": "..."
        }
    """
    # Build context from conversation history
    previous_entities = []
    previous_entity_type = None
    previous_query = None

    if conversation_history:
        last_conv = conversation_history[-1]

        # Try to get from extracted_entities first (new format)
        extracted_ents = last_conv.get("extracted_entities", {})
        if extracted_ents and extracted_ents.get("entities"):
            previous_entities = extracted_ents.get("entities", [])
            previous_entity_type = extracted_ents.get("entity_column") or extracted_ents.get("entity_type")
        else:
            # Fallback: extract from results (old format)
            results = last_conv.get("results", [])
            if results and len(results) > 0:
                # Extract first column entities (usually the grouping column)
                first_key = list(results[0].keys())[0]
                previous_entities = [r.get(first_key) for r in results[:5] if r.get(first_key)]
                previous_entity_type = first_key

        previous_query = last_conv.get("query", "")

    # LLM prompt for entity extraction
    prompt = f"""Sen bir entity extraction uzmanısın. Kullanıcının sorgusundan ve önceki context'ten entity'leri doğru şekilde çıkarmalısın.

🔍 **KULLANICI SORGUSU:** "{user_query}"
📊 **QUERY TYPE:** {query_type}

📜 **ÖNCEKİ CONTEXT:**
Önceki Sorgu: "{previous_query if previous_query else 'YOK'}"
{f'''Önceki Sorgu Sonuçları:
- Entity Type (Column): {previous_entity_type}
- Entity Değerleri: {previous_entities[:5]}
- Toplam: {len(previous_entities)} entity''' if previous_entities else "Önceki context YOK"}

---

## GÖREV

Kullanıcının karşılaştırmak/analiz etmek istediği **ENTITY'LERİ** bul.

### ADIM 1: REFERANS TESPİTİ
Kullanıcı sorgusu önceki sonuçlara referans veriyor mu?

**REFERANS KELİMELERİ:**
- "bunu", "bu", "onu" → TEK entity reference (önceki sonuçtaki ilk entity)
- "bunları", "onları", "bu ikisi", "bu iki" → MULTIPLE entity reference (önceki sonuçtaki entity'ler)
- "ile kıyasla", "ile karşılaştır" → YENİ entity ekleniyor

**ÖRNEKLER:**
- "bunu cajun dürüm ile kıyasla" → Context'ten 1 entity + "cajun dürüm" = 2 entity
- "bu iki kategoriyi" → Context'ten 2 entity
- "bunları karşılaştır" → Context'ten TÜM entity'ler

### ADIM 2: ENTITY ÇIKARMA

**Context'ten entity al:**
{f'Önceki entity\'ler: {previous_entities[:5]}' if previous_entities else 'Context yok'}

**Query'den yeni entity bul:**
- "cajun dürüm ile" → "CAJUN DÜRÜM"
- "klasik dürüm vs cajun" → "KLASİK DÜRÜM", "CAJUN DÜRÜM"
- "İstanbul Ankara" → "İstanbul", "Ankara"

**ÖZEL DURUMLAR:**
- Büyük/küçük harf önemli: Database değerlerine uygun yaz (örn: "KLASİK DÜRÜM", "İstanbul")
- Türkçe karakterler: Doğru kullan (ı, ğ, ş, ü, ö, ç, İ)
- Aynı entity varsa tekrar etme

### ADIM 3: CONFIDENCE HESAPLAMA

**YÜKSEK CONFIDENCE (0.90-1.0):**
- ✅ Her iki entity NET belirtilmiş: "X ve Y'yi karşılaştır"
- ✅ Context'ten 1 + Query'den 1 entity: "bunu Y ile kıyasla"
- ✅ Context'te 2+ entity var ve "bunları" deniyor

**ORTA CONFIDENCE (0.70-0.89):**
- ⚠️ Entity'lerden biri çıkarım ile bulunmuş
- ⚠️ Context'te entity var ama tam eşleşme değil

**DÜŞÜK CONFIDENCE (< 0.70):**
- ❌ "bunları" deniyor ama context YOK
- ❌ Entity ismi belirsiz veya eksik
- ❌ Hangi entity column olduğu belli değil

### ADIM 4: CLARIFICATION CHECK

**needs_clarification = TRUE olmalı eğer:**
- Entity sayısı < 2 VE query_type comparison/time_series_comparison ise
- Confidence < 0.70
- Entity column tahmin edilemiyor
- Context'te entity yok ama "bunu" gibi referans var

---

## OUTPUT FORMAT

Sadece şu JSON'ı döndür (başka hiçbir şey yazma):

```json
{{
    "entities": ["ENTITY1", "ENTITY2"],
    "entity_column": "ProductName",
    "entity_source": "mixed",
    "confidence": 0.90,
    "needs_clarification": false,
    "reasoning": "Context'ten 'KLASİK DÜRÜM' + query'den 'CAJUN DÜRÜM' çıkarıldı"
}}
```

**entity_column seçenekleri:**
- ProductName (ürün adı)
- CategoryName (kategori)
- BranchName (şube)
- CityName (şehir)
- CustomerName (müşteri)

**entity_source seçenekleri:**
- "query": Sadece sorgudan
- "context": Sadece context'ten
- "mixed": Her ikisinden de

---

⚠️ KRİTİK: Comparison query için MUTLAKA 2+ entity gerekli!
⚠️ KRİTİK: Context'te entity VARSA, onları kullan!
⚠️ KRİTİK: Entity isimleri DATABASE formatında olmalı (büyük harf, Türkçe karakter)

ŞİMDİ JSON DÖNDÜR:
"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Parse JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        entities = data.get("entities", [])
        entity_column = data.get("entity_column", "CategoryName")
        confidence = float(data.get("confidence", 0.5))
        needs_clarification = data.get("needs_clarification", False)

        # Validation
        if query_type in ["comparison", "time_series_comparison"]:
            if len(entities) < 2:
                logger.warning(f"[ENTITY_EXTRACT] Comparison query but only {len(entities)} entities")
                needs_clarification = True

        logger.info(f"[ENTITY_EXTRACT] Extracted: entities={entities}, column={entity_column}, "
                   f"source={data.get('entity_source')}, confidence={confidence:.2f}")

        return {
            "entities": entities,
            "entity_column": entity_column,
            "entity_source": data.get("entity_source", "query"),
            "confidence": confidence,
            "needs_clarification": needs_clarification,
            "reasoning": data.get("reasoning", "")
        }

    except Exception as e:
        logger.error(f"[ENTITY_EXTRACT] Error: {e}")
        return {
            "entities": [],
            "entity_column": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "reasoning": f"Error during extraction: {str(e)}"
        }


async def _extract_query_entities(
    user_query: str,
    query_type: str,
    llm: BaseChatModel,
    retry_count: int = 0,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Extract entities from user query based on query_type.

    CRITICAL: 100% LLM-DRIVEN NLP!
    - No regex patterns
    - No keyword matching
    - Pure LLM understanding with structured output

    LLM-driven extraction for:
    - metric (ciro, satış, miktar, etc.)
    - limit (10, 5, top-3, etc.)
    - entities (İstanbul, Ankara, Ürün A, etc.)
    - time period (son 6 ay, bu yıl, etc.)
    - aggregation (toplam, ortalama, sayı, etc.)

    Args:
        user_query: User's natural language query
        query_type: Detected query type
        llm: Language model for extraction
        retry_count: Current retry attempt
        max_retries: Maximum retry attempts for JSON parsing

    Returns:
        Extracted entities dict
    """
    pattern = get_pattern(query_type)

    if not pattern:
        logger.warning(f"[ENTITY_EXTRACTION] No pattern for query_type: {query_type}")
        return {}

    required_fields = pattern.get("required_fields", [])
    optional_fields = pattern.get("optional_fields", [])
    example_queries = pattern.get("example_queries", [])

    # Enhanced prompt with few-shot learning
    prompt = f"""Sen bir doğal dil işleme uzmanısın. Türkçe sorgudan entity'leri çıkar.

**SORGU:** "{user_query}"
**QUERY TYPE:** {query_type}
**DESCRIPTION:** {pattern.get('description', '')}

---

## ÇIKARILACAK FİELD'LAR

### REQUIRED (Mutlaka olmalı):
{chr(10).join(f'- {field}' for field in required_fields)}

### OPTIONAL (Varsa ekle):
{chr(10).join(f'- {field}' for field in optional_fields)}

---

## FİELD AÇIKLAMALARI

- **metric**: Ölçülecek metrik (ciro, satış, miktar, müşteri sayısı, gelir, hasılat)
- **limit**: Top-N için sayı (10, 5, 3, etc.) - "en çok 10", "top 5", "ilk 3" gibi ifadelerden
- **entity**: Ana varlık tipi (ürün, şube, müşteri, kategori, çalışan, bölge)
- **entities**: Karşılaştırılan entity listesi (["İstanbul", "Ankara"], ["Ürün A", "Ürün B"])
- **entity_column**: Database kolon tahmini (city, product, branch, category)
- **date_column**: Tarih kolonu tahmini (order_date, created_at, document_date)
- **period**: SQL INTERVAL format (6 MONTH, 30 DAY, 1 YEAR)
- **granularity**: Zaman detayı (DAY, MONTH, YEAR, HOUR)
- **aggregation**: SQL fonksiyon (SUM, AVG, COUNT, MIN, MAX)
- **order_direction**: Sıralama yönü (DESC, ASC) - "en çok" → DESC, "en az" → ASC
- **grouping_columns**: GROUP BY için kolonlar
- **distribution_column**: Dağılım analizi için kolon
- **filters**: Ek WHERE koşulları

---

## FEW-SHOT EXAMPLES (Benzer Sorgular)

**Örnek 1:**
Sorgu: "En çok satan 10 ürünü göster"
Output: {{"metric": "satış", "limit": 10, "entity": "ürün", "aggregation": "SUM", "order_direction": "DESC"}}

**Örnek 2:**
Sorgu: "İstanbul vs Ankara satışlarını karşılaştır"
Output: {{"entities": ["İstanbul", "Ankara"], "entity_column": "city", "metric": "satış", "aggregation": "SUM"}}

**Örnek 3:**
Sorgu: "Son 6 aydaki aylık satış trendi"
Output: {{"period": "6 MONTH", "granularity": "MONTH", "metric": "satış", "date_column": "order_date", "aggregation": "SUM"}}

**Örnek 4:**
Sorgu: "Toplam ciro nedir?"
Output: {{"metric": "ciro", "aggregation": "SUM"}}

**Örnek 5:**
Sorgu: "En az ciro yapan 5 şubeyi göster"
Output: {{"metric": "ciro", "limit": 5, "entity": "şube", "aggregation": "SUM", "order_direction": "ASC"}}

**Örnek 6:**
Sorgu: "Bu yıl ürün A ve B'nin haftalık satışları"
Output: {{"period": "1 YEAR", "granularity": "WEEK", "entities": ["ürün A", "ürün B"], "entity_column": "product", "metric": "satış"}}

---

## QUERY TYPE SPECIFIC EXAMPLES

Query Type: {query_type}
İlgili örnek sorgular:
{chr(10).join(f'- "{q}"' for q in example_queries)}

---

## KRİTİK KURALLAR

1. **SADECE JSON DÖNDÜR** - Açıklama yazma, direkt JSON yaz
2. **TÜM REQUIRED FIELD'LARI DOLDUR** - Boş bırakma, tahminde bulun
3. **SAYILARI INTEGER YAP** - "10" değil, 10
4. **LİSTELERİ ARRAY YAP** - "İstanbul, Ankara" değil, ["İstanbul", "Ankara"]
5. **SQL FORMAT KULLAN** - Period için "6 ay" değil "6 MONTH"
6. **KOLON ADLARINI İNGİLİZCE YAZ** - "şehir" değil "city"

---

## OUTPUT FORMAT

Sadece aşağıdaki JSON formatında döndür (başka hiçbir şey yazma):

```json
{{
  "metric": "...",
  "limit": 10,
  ...
}}
```

ŞİMDİ YUKARIDAK SORGU İÇİN JSON DÖNDÜR:
"""

    try:
        # LLM call with structured output
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Extract JSON (robust parsing)
        json_content = content
        if "```json" in content:
            json_content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_content = content.split("```")[1].split("```")[0].strip()
        elif "{" in content and "}" in content:
            # Extract first JSON object
            start = content.index("{")
            end = content.rindex("}") + 1
            json_content = content[start:end]

        entities = json.loads(json_content)

        # Validation: Check required fields
        missing_fields = [f for f in required_fields if f not in entities or entities[f] is None]

        if missing_fields:
            logger.warning(f"[ENTITY_EXTRACTION] Missing required fields: {missing_fields}")

            # Fill with smart defaults
            for field in missing_fields:
                entities[field] = _get_default_value_for_field(field, user_query, query_type)

            logger.info(f"[ENTITY_EXTRACTION] Filled missing fields with defaults")

        logger.info(f"[ENTITY_EXTRACTION] ✓ {query_type}: {entities}")

        return entities

    except json.JSONDecodeError as e:
        logger.error(f"[ENTITY_EXTRACTION] JSON parse error (attempt {retry_count + 1}/{max_retries}): {e}")
        logger.error(f"[ENTITY_EXTRACTION] Content: {content[:300]}")

        # Retry with stronger prompt
        if retry_count < max_retries:
            logger.info(f"[ENTITY_EXTRACTION] Retrying with enhanced prompt...")
            return await _extract_query_entities(user_query, query_type, llm, retry_count + 1, max_retries)

        # Final fallback: Minimal rule-based (emergency only)
        logger.error(f"[ENTITY_EXTRACTION] Max retries reached, using emergency fallback")
        return _emergency_entity_extraction(user_query, query_type)

    except Exception as e:
        logger.error(f"[ENTITY_EXTRACTION] Unexpected error: {e}", exc_info=True)

        # Retry once
        if retry_count < 1:
            return await _extract_query_entities(user_query, query_type, llm, retry_count + 1, max_retries)

        # Emergency fallback
        return _emergency_entity_extraction(user_query, query_type)


def _get_default_value_for_field(field: str, user_query: str, query_type: str) -> Any:
    """
    Get smart default value for missing field.

    Args:
        field: Missing field name
        user_query: User query for context
        query_type: Query type

    Returns:
        Default value for field
    """
    query_lower = user_query.lower()

    # Smart defaults based on field type
    if field == "limit":
        return 10  # Default top-N

    elif field == "aggregation":
        if any(kw in query_lower for kw in ["toplam", "toplamı", "ciro"]):
            return "SUM"
        elif any(kw in query_lower for kw in ["ortalama"]):
            return "AVG"
        elif any(kw in query_lower for kw in ["kaç", "sayı", "adet"]):
            return "COUNT"
        else:
            return "SUM"  # Most common

    elif field == "order_direction":
        if any(kw in query_lower for kw in ["en az", "en düşük"]):
            return "ASC"
        else:
            return "DESC"  # Most common for rankings

    elif field == "granularity":
        if "günlük" in query_lower or "gün" in query_lower:
            return "DAY"
        elif "aylık" in query_lower or "ay" in query_lower:
            return "MONTH"
        elif "yıllık" in query_lower or "yıl" in query_lower:
            return "YEAR"
        else:
            return "DAY"  # Default

    elif field == "date_column":
        return "order_date"  # Most common

    elif field == "entity_column":
        if "şube" in query_lower or "branch" in query_lower:
            return "branch"
        elif "ürün" in query_lower or "product" in query_lower:
            return "product"
        elif "müşteri" in query_lower or "customer" in query_lower:
            return "customer"
        elif "kategori" in query_lower or "category" in query_lower:
            return "category"
        else:
            return "entity"  # Generic

    elif field == "period":
        # Try to extract from query
        if "son" in query_lower and "ay" in query_lower:
            import re
            match = re.search(r'son (\d+) ay', query_lower)
            if match:
                return f"{match.group(1)} MONTH"
        return "1 MONTH"  # Default

    elif field == "metric":
        if "ciro" in query_lower or "gelir" in query_lower:
            return "ciro"
        elif "satış" in query_lower or "satan" in query_lower:
            return "satış"
        elif "müşteri" in query_lower:
            return "müşteri"
        else:
            return "metrik"  # Generic

    elif field == "entity":
        if "ürün" in query_lower:
            return "ürün"
        elif "şube" in query_lower:
            return "şube"
        elif "müşteri" in query_lower:
            return "müşteri"
        else:
            return "entity"  # Generic

    # Default fallback
    return None


def _emergency_entity_extraction(user_query: str, query_type: str) -> Dict[str, Any]:
    """
    EMERGENCY ONLY: Minimal entity extraction when LLM completely fails.

    This should RARELY be called - only when LLM has critical errors.
    Uses minimal heuristics, not production-quality.

    Args:
        user_query: User query
        query_type: Query type

    Returns:
        Minimal extracted entities (best effort)
    """
    logger.warning(f"[EMERGENCY_EXTRACTION] Using emergency fallback for: {user_query}")

    entities = {}
    query_lower = user_query.lower()

    # Extract basic entities based on query_type
    pattern = get_pattern(query_type)
    required_fields = pattern.get("required_fields", []) if pattern else []

    # Fill all required fields with defaults
    for field in required_fields:
        default_value = _get_default_value_for_field(field, user_query, query_type)
        if default_value is not None:
            entities[field] = default_value

    logger.warning(f"[EMERGENCY_EXTRACTION] Extracted (minimal): {entities}")

    return entities


def _rule_based_entity_extraction(user_query: str, query_type: str) -> Dict[str, Any]:
    """
    DEPRECATED: Use _emergency_entity_extraction instead.

    Kept for backward compatibility only.
    """
    logger.warning("[ENTITY_EXTRACTION] DEPRECATED: _rule_based_entity_extraction called")
    return _emergency_entity_extraction(user_query, query_type)


# =============================================================================
# QUERY TYPE CONTEXT BUILDER NODE
# =============================================================================

async def build_query_type_context_node(
    state: ReportState,
    llm: Optional[BaseChatModel] = None
) -> Dict[str, Any]:
    """
    Build SQL context hints based on query_type.

    This node runs AFTER classify_intent and BEFORE extract_query.

    Flow:
        classify_intent (query_type detected)
            ↓
        build_query_type_context (SQL hints created) ← YOU ARE HERE
            ↓
        extract_query
            ↓
        sql_architect (uses SQL hints)

    Input from state:
        - query_type: Detected query type
        - user_query: User's natural language query

    Output to state:
        - sql_context_hints: Context for SQL generation
          {
              "query_pattern": "ranking",
              "pattern_description": "Top-N sıralama",
              "sql_hints": ["ORDER BY DESC", "LIMIT N"],
              "required_fields": ["metric", "limit", "entity"],
              "extracted_entities": {...},
              "example_sql": "SELECT ... ORDER BY ... LIMIT ...",
              "formatted_prompt": "..."  # Ready for LLM
          }

    Args:
        state: ReportState
        llm: Optional LLM for entity extraction (if None, uses rule-based fallback)

    Returns:
        State update with sql_context_hints
    """
    query_type = state.get("query_type")
    user_query = state.get("user_query")

    # Early exit if no query_type
    if not query_type:
        logger.info("[QUERY_TYPE_CONTEXT] No query_type, skipping context building")
        return {}

    # Early exit if no user_query
    if not user_query:
        logger.warning("[QUERY_TYPE_CONTEXT] No user_query found")
        return {}

    logger.info(f"[QUERY_TYPE_CONTEXT] Building context for query_type='{query_type}'")

    # Get pattern for this query_type
    pattern = get_pattern(query_type)

    if not pattern:
        logger.warning(f"[QUERY_TYPE_CONTEXT] Unknown query_type: {query_type}")
        return {}

    # Extract entities from user query
    if llm:
        try:
            extracted_entities = await _extract_query_entities(user_query, query_type, llm)
        except Exception as e:
            logger.error(f"[QUERY_TYPE_CONTEXT] Entity extraction failed: {e}")
            extracted_entities = _rule_based_entity_extraction(user_query, query_type)
    else:
        # No LLM, use rule-based extraction
        extracted_entities = _rule_based_entity_extraction(user_query, query_type)

    # Build context hints
    context_hints = {
        "query_pattern": query_type,
        "pattern_description": pattern["description"],
        "sql_requirements": pattern["sql_requirements"],
        "sql_hints": pattern["sql_hints"],
        "required_fields": pattern["required_fields"],
        "optional_fields": pattern.get("optional_fields", []),
        "extracted_entities": extracted_entities,
        "example_sql": pattern["example_sql"].strip(),
        "example_queries": pattern.get("example_queries", []),
        "validation_rules": pattern.get("validation_rules", {})
    }

    # Format as LLM-ready prompt
    context_hints["formatted_prompt"] = format_pattern_for_prompt(query_type, extracted_entities)

    logger.info(f"[QUERY_TYPE_CONTEXT] Context built successfully:")
    logger.info(f"  Pattern: {query_type}")
    logger.info(f"  Entities: {extracted_entities}")
    logger.info(f"  SQL hints: {len(context_hints['sql_hints'])} hints")

    return {
        "sql_context_hints": context_hints
    }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_build_query_type_context_node(llm: Optional[BaseChatModel] = None):
    """
    Factory to create build_query_type_context_node with LLM.

    Args:
        llm: Optional LLM for entity extraction

    Returns:
        Node function
    """
    async def node_func(state: ReportState) -> Dict[str, Any]:
        return await build_query_type_context_node(state, llm=llm)

    return node_func


__all__ = [
    "build_query_type_context_node",
    "create_build_query_type_context_node"
]
