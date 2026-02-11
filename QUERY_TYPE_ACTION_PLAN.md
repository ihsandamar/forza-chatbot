# Query Type Action Implementation Plan

## 🎯 Problem

`query_type` doğru tespit ediliyor ama **sonucunda hiçbir aksiyon alınmıyor**:
- ❌ SQL generation'da kullanılmıyor
- ❌ Visualization decision'da kullanılmıyor
- ❌ İlgili SQL pattern'leri uygulanmıyor

**Örnek Sorunlar:**
- "En çok satan 10 ürün" → `ranking` tespit ediliyor ama `ORDER BY + LIMIT 10` eklenmeden SQL oluşturuluyor
- "İstanbul vs Ankara satışları" → `comparison` tespit ediliyor ama grouped comparison SQL'i yazılmıyor
- "Son 6 aydaki satışlar" → `time_series` tespit ediliyor ama tarih filtresi otomatik eklenmiyor

---

## 🏗️ Architecture Overview

```
USER QUERY
    ↓
classify_intent (query_type tespit edildi ✓)
    ↓
extract_query
    ↓
[NEW] query_type_context_builder ← query_type'a göre SQL hints oluştur
    ↓
sql_architect ← query_type context ile çalış
    ↓
[ENHANCED] sql_query_builder ← query_type pattern'leri uygula
    ↓
sql_executor
    ↓
[ENHANCED] decide_visualization ← query_type'a göre chart seç
    ↓
visualization
```

---

## 📋 Implementation Phases

### **Phase 1: SQL Generation Enhancement** (2-3 saat)

#### 1.1. Query Type SQL Patterns

Her `query_type` için SQL pattern tanımları:

```python
QUERY_TYPE_SQL_PATTERNS = {
    "ranking": {
        "description": "Top-N sıralama",
        "sql_hints": [
            "ORDER BY {metric} DESC",
            "LIMIT {n}",
            "En yüksek/düşük değerleri getir"
        ],
        "required_fields": ["metric", "limit"],
        "example": "SELECT * FROM Sales ORDER BY amount DESC LIMIT 10"
    },

    "comparison": {
        "description": "İki veya daha fazla entity karşılaştırması",
        "sql_hints": [
            "WHERE {entity_column} IN ({entities})",
            "GROUP BY {entity_column}",
            "Belirtilen entity'ler için ayrı metrikler"
        ],
        "required_fields": ["entities", "entity_column"],
        "example": "SELECT city, SUM(amount) FROM Sales WHERE city IN ('Istanbul', 'Ankara') GROUP BY city"
    },

    "time_series": {
        "description": "Zaman bazlı trend analizi",
        "sql_hints": [
            "WHERE {date_column} >= DATE_SUB(NOW(), INTERVAL {period})",
            "GROUP BY {time_granularity}",
            "ORDER BY {date_column} ASC"
        ],
        "required_fields": ["date_column", "period", "granularity"],
        "example": "SELECT DATE(date) as day, SUM(amount) FROM Sales WHERE date >= DATE_SUB(NOW(), INTERVAL 6 MONTH) GROUP BY DATE(date) ORDER BY day"
    },

    "time_series_comparison": {
        "description": "Çoklu entity'lerin zaman serisi karşılaştırması",
        "sql_hints": [
            "WHERE {date_column} >= ... AND {entity_column} IN ({entities})",
            "GROUP BY {time_granularity}, {entity_column}",
            "ORDER BY {date_column}, {entity_column}"
        ],
        "required_fields": ["date_column", "period", "entities", "entity_column"],
        "example": "SELECT DATE(date) as day, product, SUM(amount) FROM Sales WHERE date >= ... AND product IN ('X', 'Y') GROUP BY day, product ORDER BY day"
    },

    "single_value": {
        "description": "Tek bir metrik değeri",
        "sql_hints": [
            "SELECT {aggregation}({metric}) as result",
            "WHERE koşulları varsa ekle",
            "GROUP BY kullanma (tek değer)"
        ],
        "required_fields": ["metric", "aggregation"],
        "example": "SELECT SUM(amount) as total_revenue FROM Sales"
    },

    "aggregation": {
        "description": "Gruplama ve toplama",
        "sql_hints": [
            "GROUP BY {grouping_columns}",
            "Aggregation fonksiyonları: SUM, AVG, COUNT, MIN, MAX",
            "ORDER BY metrik (isteğe bağlı)"
        ],
        "required_fields": ["grouping_columns"],
        "example": "SELECT category, SUM(amount) FROM Sales GROUP BY category"
    },

    "distribution": {
        "description": "Değer dağılımı",
        "sql_hints": [
            "GROUP BY {distribution_column}",
            "COUNT(*) veya SUM({metric})",
            "ORDER BY count DESC (genellikle)"
        ],
        "required_fields": ["distribution_column"],
        "example": "SELECT status, COUNT(*) as count FROM Orders GROUP BY status"
    },

    "trend": {
        "description": "Trend analizi (artış/azalış)",
        "sql_hints": [
            "İki zaman dilimi karşılaştırması",
            "LAG/LEAD window functions",
            "Yüzde değişim hesaplama"
        ],
        "required_fields": ["date_column", "metric"],
        "example": "SELECT month, amount, LAG(amount) OVER (ORDER BY month) as prev_month FROM Monthly_Sales"
    }
}
```

#### 1.2. Query Type Context Builder Node

**Yeni Node:** `build_query_type_context_node`

```python
async def build_query_type_context_node(state: ReportState) -> Dict[str, Any]:
    """
    Build SQL context hints based on query_type.

    Input: query_type, user_query, reference_context
    Output: sql_context_hints (LLM'e gönderilecek)

    Example:
        query_type = "ranking"
        user_query = "En çok satan 10 ürün"

        Output:
        {
            "sql_context_hints": {
                "query_pattern": "ranking",
                "instructions": [
                    "ORDER BY {metric} DESC kullan",
                    "LIMIT 10 ekle",
                    "En yüksek değerleri getir"
                ],
                "expected_fields": {
                    "metric": "satış miktarı/ciro",
                    "limit": 10,
                    "entity": "ürün"
                }
            }
        }
    """
    query_type = state.get("query_type")
    user_query = state.get("user_query")

    if not query_type:
        return {}  # No hints, standard SQL generation

    # Get pattern for this query_type
    pattern = QUERY_TYPE_SQL_PATTERNS.get(query_type)

    if not pattern:
        logger.warning(f"Unknown query_type: {query_type}")
        return {}

    # Extract entities from user query using LLM
    entities = await _extract_query_entities(user_query, query_type)

    # Build context hints
    context_hints = {
        "query_pattern": query_type,
        "pattern_description": pattern["description"],
        "sql_hints": pattern["sql_hints"],
        "required_fields": pattern["required_fields"],
        "extracted_entities": entities,
        "example_sql": pattern["example"]
    }

    logger.info(f"[QUERY_TYPE_CONTEXT] Built hints for {query_type}: {context_hints}")

    return {
        "sql_context_hints": context_hints
    }
```

#### 1.3. SQL Architect Enhancement

**Modify:** `sql_architect` prompt'una query_type context ekle

```python
# sql_architect_node içinde

sql_context_hints = state.get("sql_context_hints", {})

if sql_context_hints:
    query_pattern = sql_context_hints.get("query_pattern")
    sql_hints = sql_context_hints.get("sql_hints", [])

    # Add to prompt
    enhanced_prompt = f"""
User Query: {user_query}

QUERY TYPE: {query_pattern}
PATTERN DESCRIPTION: {sql_context_hints.get('pattern_description')}

SQL HINTS (CRITICAL - Follow these patterns):
{chr(10).join(f'- {hint}' for hint in sql_hints)}

EXAMPLE SQL:
{sql_context_hints.get('example_sql')}

EXTRACTED ENTITIES:
{json.dumps(sql_context_hints.get('extracted_entities', {}), indent=2)}

Build SQL query following the {query_pattern} pattern.
"""
```

#### 1.4. SQL Query Builder Validation

**Enhance:** `sql_query_builder_node` - query_type pattern'i doğrula

```python
async def validate_sql_pattern(sql: str, query_type: str, hints: dict) -> dict:
    """
    Validate if generated SQL matches expected query_type pattern.

    Returns:
        {
            "valid": bool,
            "warnings": List[str],
            "suggestions": List[str]
        }
    """
    validation = {"valid": True, "warnings": [], "suggestions": []}

    if query_type == "ranking":
        if "ORDER BY" not in sql.upper():
            validation["warnings"].append("ORDER BY missing for ranking query")
            validation["suggestions"].append("Add ORDER BY {metric} DESC")

        if "LIMIT" not in sql.upper():
            validation["warnings"].append("LIMIT missing for top-N ranking")
            validation["suggestions"].append("Add LIMIT clause")

    elif query_type == "comparison":
        if "GROUP BY" not in sql.upper():
            validation["warnings"].append("GROUP BY missing for comparison")

        entities = hints.get("extracted_entities", {}).get("entities", [])
        if len(entities) < 2:
            validation["warnings"].append("Comparison requires at least 2 entities")

    elif query_type == "time_series":
        if "ORDER BY" not in sql.upper():
            validation["warnings"].append("ORDER BY date missing for time series")

        # Check for date filtering
        date_keywords = ["DATE", "TIMESTAMP", "INTERVAL", ">=", "BETWEEN"]
        if not any(kw in sql.upper() for kw in date_keywords):
            validation["warnings"].append("Time filtering may be missing")

    return validation
```

---

### **Phase 2: Visualization Decision Enhancement** (1-2 saat)

#### 2.1. Query Type Visualization Mapping

```python
QUERY_TYPE_VIZ_MAPPING = {
    "ranking": {
        "primary_chart": "bar_horizontal",
        "alternatives": ["bar_vertical", "table"],
        "reasoning": "Horizontal bar chart best for rankings (easy to read labels)",
        "chart_config": {
            "sort_by": "value",
            "order": "desc",
            "show_values": True
        }
    },

    "comparison": {
        "primary_chart": "bar_grouped",
        "alternatives": ["line_multi", "table"],
        "reasoning": "Grouped bars for side-by-side comparison",
        "chart_config": {
            "group_by": "entity",
            "show_legend": True
        }
    },

    "time_series": {
        "primary_chart": "line",
        "alternatives": ["area", "bar_vertical"],
        "reasoning": "Line chart shows temporal trends clearly",
        "chart_config": {
            "x_axis": "date",
            "y_axis": "metric",
            "show_points": False,
            "smooth": True
        }
    },

    "time_series_comparison": {
        "primary_chart": "line_multi",
        "alternatives": ["area_stacked", "bar_grouped"],
        "reasoning": "Multiple lines for comparing trends across entities",
        "chart_config": {
            "x_axis": "date",
            "y_axis": "metric",
            "group_by": "entity",
            "show_legend": True
        }
    },

    "single_value": {
        "primary_chart": "metric_card",
        "alternatives": ["gauge", "table"],
        "reasoning": "Single number display (KPI card)",
        "chart_config": {
            "format": "number",
            "show_trend": False
        }
    },

    "aggregation": {
        "primary_chart": "bar_vertical",
        "alternatives": ["table", "pie"],
        "reasoning": "Bar chart for category comparisons",
        "chart_config": {
            "sort_by": "value",
            "order": "desc"
        }
    },

    "distribution": {
        "primary_chart": "pie",
        "alternatives": ["bar_vertical", "donut"],
        "reasoning": "Pie chart shows proportions clearly",
        "chart_config": {
            "show_percentage": True,
            "show_legend": True
        }
    },

    "trend": {
        "primary_chart": "line",
        "alternatives": ["area", "bar_vertical"],
        "reasoning": "Line chart with trend indicators",
        "chart_config": {
            "show_trend_line": True,
            "show_change_percentage": True
        }
    }
}
```

#### 2.2. Enhanced Visualization Decision Node

```python
async def decide_visualization_enhanced_node(state: ReportState) -> Dict[str, Any]:
    """
    Decide visualization based on query_type.

    Priority:
    1. query_type mapping (if available)
    2. Data shape analysis (fallback)
    3. User preference (if specified)
    """
    query_type = state.get("query_type")
    results = state.get("text2sql_output", {}).get("results", [])

    # Default decision
    viz_decision = {
        "needs_graph": True,
        "chart_type": "bar",
        "reasoning": "Default visualization"
    }

    # Phase 1: query_type based decision (PRIORITY)
    if query_type and query_type in QUERY_TYPE_VIZ_MAPPING:
        viz_config = QUERY_TYPE_VIZ_MAPPING[query_type]

        viz_decision = {
            "needs_graph": True,
            "chart_type": viz_config["primary_chart"],
            "alternatives": viz_config["alternatives"],
            "reasoning": f"Query type '{query_type}': {viz_config['reasoning']}",
            "chart_config": viz_config["chart_config"],
            "query_type_driven": True
        }

        logger.info(f"[VIZ_DECISION] Query type based: {query_type} → {viz_decision['chart_type']}")

    # Phase 2: Data shape analysis (fallback if query_type not available)
    elif results:
        viz_decision = _analyze_data_shape_for_viz(results)
        viz_decision["query_type_driven"] = False

    # Phase 3: Special cases
    if len(results) == 1 and len(results[0]) == 1:
        # Single value result
        viz_decision["chart_type"] = "metric_card"
        viz_decision["needs_graph"] = False

    return {
        "_viz_decision": viz_decision
    }
```

---

### **Phase 3: Integration & Testing** (1-2 saat)

#### 3.1. Graph Wiring

**graph.py updates:**

```python
# After classify_intent, before extract_query
if enable_query_type_action:
    graph.add_node("build_query_type_context", build_query_type_context_node)
    graph.add_edge("classify_intent", "build_query_type_context")
    graph.add_edge("build_query_type_context", "extract_query")
else:
    graph.add_edge("classify_intent", "extract_query")
```

#### 3.2. Feature Flag

```yaml
# config.yaml
report:
  query_type_action:
    enabled: true
    use_sql_patterns: true
    use_viz_mapping: true
    strict_validation: false  # True = reject SQL if pattern mismatch
```

#### 3.3. Test Cases

```python
TEST_CASES = [
    {
        "query": "En çok satan 10 ürünü göster",
        "expected_query_type": "ranking",
        "expected_sql_contains": ["ORDER BY", "LIMIT 10"],
        "expected_chart": "bar_horizontal"
    },

    {
        "query": "İstanbul vs Ankara satışlarını karşılaştır",
        "expected_query_type": "comparison",
        "expected_sql_contains": ["GROUP BY", "IN ('Istanbul', 'Ankara')"],
        "expected_chart": "bar_grouped"
    },

    {
        "query": "Son 6 aydaki satış trendi",
        "expected_query_type": "time_series",
        "expected_sql_contains": ["INTERVAL 6 MONTH", "ORDER BY"],
        "expected_chart": "line"
    },

    {
        "query": "Toplam ciro nedir?",
        "expected_query_type": "single_value",
        "expected_sql_contains": ["SUM"],
        "expected_chart": "metric_card"
    }
]
```

---

## 🚀 Implementation Order

### **Week 1: SQL Enhancement**

**Day 1-2: Core Infrastructure**
- [ ] `QUERY_TYPE_SQL_PATTERNS` tanımları
- [ ] `build_query_type_context_node` implementasyonu
- [ ] `_extract_query_entities` helper (LLM based)

**Day 3-4: SQL Architect Integration**
- [ ] SQL architect prompt enhancement
- [ ] SQL query builder validation
- [ ] Pattern matching logic

**Day 5: Testing**
- [ ] Unit tests for each query_type
- [ ] Integration tests
- [ ] Edge case handling

### **Week 2: Visualization & Polish**

**Day 1-2: Visualization** ✅ COMPLETED
- [x] `QUERY_TYPE_VIZ_MAPPING` tanımları ✅
- [x] `decide_visualization_enhanced_node` ✅
- [x] Chart config generation ✅
- [x] Turkish suffix handling (pasta grafik/grafiği) ✅
- [x] Comprehensive test suite (7 tests, 100% pass) ✅

**Day 3-4: Integration** ✅ COMPLETED
- [x] Graph wiring ✅ (Already done in Phase 1)
- [x] Feature flags ✅ (via build_report_graph parameters)
- [x] Config management ✅ (via function parameters)

**Day 5: End-to-End Testing** ✅ COMPLETED
- [x] Full workflow tests ✅ (4/4 integration tests passed)
- [x] Phase 1 + Phase 2 consistency check ✅ (100%)
- [x] All 8 query types validated ✅
- [x] Documentation ✅

---

## 📊 Success Metrics

### **Functional Metrics:**
- ✅ SQL pattern matching accuracy: >90%
- ✅ Visualization selection accuracy: >85%
- ✅ Query type → Action mapping: 100% coverage

### **Quality Metrics:**
- ✅ User query → Correct SQL pattern: <5% failure rate
- ✅ Automatic ORDER BY/LIMIT injection: 100% for ranking
- ✅ Correct chart type selection: >80% user satisfaction

---

## 🔧 Technical Debt & Future Improvements

### **Known Limitations:**
1. Entity extraction relies on LLM (can fail)
2. Pattern matching is strict (may need fuzzy matching)
3. No learning from user corrections yet

### **Future Enhancements:**
1. **Adaptive Patterns**: Learn from user corrections
2. **Custom Patterns**: User-defined query_type patterns
3. **Multi-language Support**: Pattern localization
4. **Smart Defaults**: Auto-detect period for time_series (e.g., "son ay" → 1 month)

---

## 📝 Example Flow (End-to-End)

### **Input:** "En çok ciro yapan 5 şubeyi göster"

```
1. classify_intent
   → query_type: "ranking"
   → confidence: 0.95

2. build_query_type_context
   → pattern: "ranking"
   → hints: ["ORDER BY DESC", "LIMIT 5"]
   → entities: {"metric": "ciro", "limit": 5, "entity": "şube"}

3. sql_architect
   → Prompt: "Build ranking query with ORDER BY and LIMIT 5"
   → Intent: "Get top 5 branches by revenue"

4. sql_query_builder
   → SQL: "SELECT branch, SUM(revenue) as total FROM Sales GROUP BY branch ORDER BY total DESC LIMIT 5"
   → Validation: ✓ Has ORDER BY ✓ Has LIMIT 5

5. sql_executor
   → Results: [{branch: "A", total: 100000}, ...]

6. decide_visualization_enhanced
   → query_type: "ranking" → chart: "bar_horizontal"
   → config: {sort_by: "value", show_values: true}

7. visualization
   → Renders horizontal bar chart with top 5 branches

8. build_response
   → "En çok ciro yapan 5 şube (grafik ile birlikte)"
```

---

## 🎯 Critical Success Factors

1. **LLM Prompt Quality**: SQL hints must be clear and actionable
2. **Entity Extraction Accuracy**: Must correctly identify metrics, limits, entities
3. **Fallback Handling**: Graceful degradation if query_type is None
4. **User Feedback Loop**: Log mismatches for continuous improvement

---

## ⚠️ Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM ignores hints | High | Strict validation + retry with stronger prompt |
| Wrong entity extraction | Medium | Fuzzy matching + user confirmation |
| Performance overhead | Low | Cache pattern configs, async processing |
| Pattern conflicts | Medium | Priority order: user_preference > query_type > data_shape |

---

## 📚 Documentation Needed

1. **Developer Guide**: How to add new query_type patterns
2. **User Guide**: How system interprets different query types
3. **API Reference**: `sql_context_hints` structure
4. **Migration Guide**: Backward compatibility notes

---

**Status:** Ready for implementation ✅
**Estimated Effort:** 2 weeks (1 dev)
**Priority:** HIGH - Core functionality gap
