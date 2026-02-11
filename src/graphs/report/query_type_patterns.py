"""
Query Type SQL Patterns

Her query type için SQL generation pattern'leri ve hint'leri.
Bu pattern'ler sql_architect ve sql_query_builder node'larında kullanılır.
"""

from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# QUERY TYPE SQL PATTERNS
# =============================================================================

QUERY_TYPE_SQL_PATTERNS = {
    "ranking": {
        "description": "Top-N sıralama (en yüksek/düşük değerler)",
        "sql_requirements": [
            "ORDER BY {metric} DESC/ASC kullanılmalı",
            "LIMIT {n} eklenmelidir",
            "GROUP BY {entity} ZORUNLU - aggregation varsa gruplama yapılacak entity group_by'da olmalı!"
        ],
        "sql_hints": [
            "En çok/az/yüksek/düşük ifadeleri ORDER BY gerektirir",
            "Top-N için LIMIT {n} zorunlu",
            "Metric: SUM, COUNT, AVG gibi aggregate fonksiyonlar olabilir",
            "KRİTİK: Aggregation kullanıyorsan entity kolonunu (ürün, şube, kategori) MUTLAKA group_by'a ekle!"
        ],
        "required_fields": ["metric", "limit", "entity"],
        "optional_fields": ["filters", "group_by"],
        "example_queries": [
            "En çok satan 10 ürün",
            "En az ciro yapan 5 şube",
            "En yüksek maaşlı 3 çalışan"
        ],
        "example_sql": """
SELECT
    product_name,
    SUM(amount) as total_sales
FROM Sales
GROUP BY product_name
ORDER BY total_sales DESC
LIMIT 10
        """,
        "validation_rules": {
            "must_have_order_by": True,
            "must_have_limit": True,
            "order_direction_matches_intent": True  # "en çok" → DESC, "en az" → ASC
        }
    },

    "comparison": {
        "description": "İki veya daha fazla entity'nin karşılaştırması",
        "sql_requirements": [
            "WHERE {entity_column} IN ({entities}) kullanılmalı",
            "GROUP BY {entity_column} eklenmelidir - ZORUNLU!",
            "Her entity için ayrı metrik hesaplanmalı"
        ],
        "sql_hints": [
            "X vs Y, A ile B gibi ifadeler comparison gerektirir",
            "Karşılaştırılan entity'ler WHERE IN ile filtrelenir",
            "Sonuç her entity için ayrı satır içermelidir",
            "KRİTİK: Entity kolonu (şehir, ürün, etc.) MUTLAKA group_by'da olmalı!"
        ],
        "required_fields": ["entities", "entity_column", "metric"],
        "optional_fields": ["filters", "time_range"],
        "example_queries": [
            "İstanbul vs Ankara satışları",
            "Ürün A ile Ürün B karşılaştırması",
            "Bu yıl ile geçen yıl satış karşılaştırması"
        ],
        "example_sql": """
SELECT
    city,
    SUM(amount) as total_sales
FROM Sales
WHERE city IN ('Istanbul', 'Ankara')
GROUP BY city
        """,
        "validation_rules": {
            "must_have_where_in": True,
            "must_have_group_by": True,
            "min_entities": 2
        }
    },

    "time_series": {
        "description": "Zaman bazlı trend analizi",
        "sql_requirements": [
            "WHERE {date_column} >= DATE_SUB(NOW(), INTERVAL {period}) kullanılmalı",
            "GROUP BY {time_granularity} eklenmelidir (DATE, MONTH, YEAR) - ZORUNLU!",
            "ORDER BY {date_column} ASC ile sıralanmalı"
        ],
        "sql_hints": [
            "Son X gün/ay/yıl ifadeleri time_series gerektirir",
            "Tarih bazlı gruplama yapılmalı",
            "Zaman sıralı veri için ORDER BY tarih kolonuna göre",
            "KRİTİK: Zaman granularity (gün, ay, yıl) MUTLAKA group_by'da olmalı!"
        ],
        "required_fields": ["date_column", "period", "granularity"],
        "optional_fields": ["metric", "filters"],
        "example_queries": [
            "Son 6 aydaki satışlar",
            "Bu yılki aylık ciro",
            "Son 30 günün günlük trendi"
        ],
        "example_sql": """
SELECT
    DATE(order_date) as day,
    SUM(amount) as daily_sales
FROM Sales
WHERE order_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)
GROUP BY DATE(order_date)
ORDER BY day ASC
        """,
        "validation_rules": {
            "must_have_date_filter": True,
            "must_have_group_by_date": True,
            "must_have_order_by_date": True
        }
    },

    "time_series_comparison": {
        "description": "Çoklu entity'lerin zaman serisi karşılaştırması",
        "sql_requirements": [
            "WHERE {date_column} >= ... AND {entity_column} IN ({entities})",
            "GROUP BY {time_granularity}, {entity_column} - ZORUNLU! (2 kolon birden)",
            "ORDER BY {date_column}, {entity_column}"
        ],
        "sql_hints": [
            "X ve Y'nin son N gündeki trendi = time_series + comparison",
            "İki boyutta gruplama: zaman + entity",
            "Her entity için ayrı zaman serisi",
            "KRİTİK: Hem zaman (gün/ay) hem de entity (ürün/şube) MUTLAKA group_by'da olmalı!"
        ],
        "required_fields": ["date_column", "period", "entities", "entity_column"],
        "optional_fields": ["metric", "granularity"],
        "example_queries": [
            "Ürün A ve B'nin son 3 aydaki satış trendi",
            "İstanbul ve Ankara'nın aylık ciro karşılaştırması"
        ],
        "example_sql": """
SELECT
    DATE(order_date) as day,
    product,
    SUM(amount) as sales
FROM Sales
WHERE order_date >= DATE_SUB(NOW(), INTERVAL 3 MONTH)
  AND product IN ('Product A', 'Product B')
GROUP BY DATE(order_date), product
ORDER BY day, product
        """,
        "validation_rules": {
            "must_have_date_filter": True,
            "must_have_entity_filter": True,
            "must_have_double_group_by": True
        }
    },

    "single_value": {
        "description": "Tek bir metrik değeri (toplam, ortalama, sayı)",
        "sql_requirements": [
            "SELECT {aggregation}({metric}) as result",
            "GROUP BY kullanılMAMALI (tek değer döner)",
            "Filtreler WHERE ile uygulanabilir"
        ],
        "sql_hints": [
            "Toplam/ortalama/sayı ifadeleri single value gerektirir",
            "Sonuç tek satır, tek kolon",
            "Aggregate fonksiyon: SUM, AVG, COUNT, MIN, MAX"
        ],
        "required_fields": ["metric", "aggregation"],
        "optional_fields": ["filters"],
        "example_queries": [
            "Toplam ciro nedir?",
            "Ortalama sipariş tutarı",
            "Kaç müşterimiz var?"
        ],
        "example_sql": """
SELECT
    SUM(amount) as total_revenue
FROM Sales
        """,
        "validation_rules": {
            "must_have_aggregation": True,
            "must_not_have_group_by": True,
            "single_column_result": True
        }
    },

    "aggregation": {
        "description": "Gruplama ve toplama (kategori bazlı metrikler)",
        "sql_requirements": [
            "GROUP BY {grouping_columns} - ZORUNLU!",
            "Aggregate fonksiyonlar: SUM, AVG, COUNT, MIN, MAX",
            "ORDER BY metrik (opsiyonel ama önerilen)"
        ],
        "sql_hints": [
            "Kategorilere/gruplara göre metrik ifadeleri aggregation gerektirir",
            "Her grup için ayrı satır döner",
            "Sonuç sıralanabilir (genellikle metriğe göre DESC)",
            "KRİTİK: Gruplama kolonları (kategori, şube, etc.) MUTLAKA group_by'da olmalı!"
        ],
        "required_fields": ["grouping_columns", "metric"],
        "optional_fields": ["filters", "order_by"],
        "example_queries": [
            "Kategorilere göre satış toplamı",
            "Şubelere göre ortalama ciro",
            "Ürün gruplarına göre müşteri sayısı"
        ],
        "example_sql": """
SELECT
    category,
    SUM(amount) as total_sales
FROM Sales
GROUP BY category
ORDER BY total_sales DESC
        """,
        "validation_rules": {
            "must_have_group_by": True,
            "must_have_aggregation": True
        }
    },

    "distribution": {
        "description": "Değer dağılımı (frekans, oran)",
        "sql_requirements": [
            "GROUP BY {distribution_column} - ZORUNLU!",
            "COUNT(*) veya SUM({metric})",
            "ORDER BY count/percentage DESC (genellikle)"
        ],
        "sql_hints": [
            "Dağılım/oran/yüzde ifadeleri distribution gerektirir",
            "Her kategori için frekans/miktar hesaplanır",
            "Pie chart için idealdir",
            "KRİTİK: Dağılım kolonu (kategori, şube, etc.) MUTLAKA group_by'da olmalı!"
        ],
        "required_fields": ["distribution_column"],
        "optional_fields": ["metric", "filters"],
        "example_queries": [
            "Satışların şubelere göre dağılımı",
            "Ürün kategorilerinin oranı",
            "Müşteri sayısının bölgelere göre dağılımı"
        ],
        "example_sql": """
SELECT
    status,
    COUNT(*) as count,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER() as percentage
FROM Orders
GROUP BY status
ORDER BY count DESC
        """,
        "validation_rules": {
            "must_have_group_by": True,
            "should_have_count_or_sum": True
        }
    },

    "trend": {
        "description": "Trend analizi (artış/azalış, değişim yüzdesi)",
        "sql_requirements": [
            "İki zaman dilimi karşılaştırması (önceki vs şimdiki)",
            "LAG/LEAD window functions veya self-join",
            "Değişim yüzdesi hesaplama"
        ],
        "sql_hints": [
            "Trend/artış/azalış/değişim ifadeleri trend analizi gerektirir",
            "Önceki dönem ile karşılaştırma yapılır",
            "Yüzde değişim = ((yeni - eski) / eski) * 100"
        ],
        "required_fields": ["date_column", "metric"],
        "optional_fields": ["period", "comparison_type"],
        "example_queries": [
            "Satışlar artıyor mu?",
            "Geçen aya göre değişim",
            "Yıllık büyüme trendi"
        ],
        "example_sql": """
SELECT
    month,
    sales,
    LAG(sales) OVER (ORDER BY month) as prev_month_sales,
    ((sales - LAG(sales) OVER (ORDER BY month)) / LAG(sales) OVER (ORDER BY month)) * 100 as growth_rate
FROM Monthly_Sales
ORDER BY month
        """,
        "validation_rules": {
            "should_have_window_function_or_join": True,
            "should_calculate_change": True
        }
    }
}


# =============================================================================
# PATTERN HELPERS
# =============================================================================

def get_pattern(query_type: str) -> Dict[str, Any]:
    """
    Get SQL pattern for query_type.

    Args:
        query_type: Query type identifier

    Returns:
        Pattern dict or empty dict if not found
    """
    pattern = QUERY_TYPE_SQL_PATTERNS.get(query_type)

    if not pattern:
        logger.warning(f"[PATTERNS] Unknown query_type: {query_type}")
        return {}

    return pattern


def get_sql_hints(query_type: str) -> List[str]:
    """
    Get SQL hints for query_type.

    Args:
        query_type: Query type identifier

    Returns:
        List of SQL hints
    """
    pattern = get_pattern(query_type)
    return pattern.get("sql_hints", [])


def get_validation_rules(query_type: str) -> Dict[str, Any]:
    """
    Get validation rules for query_type.

    Args:
        query_type: Query type identifier

    Returns:
        Validation rules dict
    """
    pattern = get_pattern(query_type)
    return pattern.get("validation_rules", {})


def format_pattern_for_prompt(query_type: str, extracted_entities: Dict[str, Any]) -> str:
    """
    Format pattern as LLM prompt context.

    Args:
        query_type: Query type identifier
        extracted_entities: Extracted entities from user query

    Returns:
        Formatted string for LLM prompt
    """
    pattern = get_pattern(query_type)

    if not pattern:
        return ""

    # Build formatted prompt
    prompt_parts = [
        f"QUERY TYPE: {query_type.upper()}",
        f"DESCRIPTION: {pattern['description']}",
        "",
        "SQL REQUIREMENTS (CRITICAL - MUST FOLLOW):"
    ]

    for i, req in enumerate(pattern['sql_requirements'], 1):
        prompt_parts.append(f"  {i}. {req}")

    prompt_parts.append("")
    prompt_parts.append("SQL HINTS:")

    for hint in pattern['sql_hints']:
        prompt_parts.append(f"  • {hint}")

    prompt_parts.append("")
    prompt_parts.append("EXAMPLE SQL:")
    prompt_parts.append(pattern['example_sql'].strip())

    if extracted_entities:
        prompt_parts.append("")
        prompt_parts.append("EXTRACTED ENTITIES:")
        for key, value in extracted_entities.items():
            prompt_parts.append(f"  • {key}: {value}")

    return "\n".join(prompt_parts)


# =============================================================================
# PATTERN MATCHING
# =============================================================================

def validate_sql_matches_pattern(
    sql: str,
    query_type: str,
    strict: bool = False
) -> Dict[str, Any]:
    """
    Validate if SQL matches expected query_type pattern.

    Args:
        sql: Generated SQL query
        query_type: Expected query type
        strict: If True, validation failures are errors (not warnings)

    Returns:
        {
            "valid": bool,
            "warnings": List[str],
            "errors": List[str],
            "suggestions": List[str]
        }
    """
    validation = {
        "valid": True,
        "warnings": [],
        "errors": [],
        "suggestions": []
    }

    rules = get_validation_rules(query_type)

    if not rules:
        return validation

    sql_upper = sql.upper()

    # Ranking validations
    if query_type == "ranking":
        if rules.get("must_have_order_by") and "ORDER BY" not in sql_upper:
            msg = "ORDER BY clause missing for ranking query"
            if strict:
                validation["errors"].append(msg)
                validation["valid"] = False
            else:
                validation["warnings"].append(msg)
            validation["suggestions"].append("Add ORDER BY {metric} DESC for top-N ranking")

        if rules.get("must_have_limit") and "LIMIT" not in sql_upper:
            msg = "LIMIT clause missing for top-N ranking"
            if strict:
                validation["errors"].append(msg)
                validation["valid"] = False
            else:
                validation["warnings"].append(msg)
            validation["suggestions"].append("Add LIMIT N to restrict result count")

    # Comparison validations
    elif query_type == "comparison":
        if rules.get("must_have_where_in") and " IN " not in sql_upper:
            msg = "WHERE IN clause missing for comparison"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Add WHERE {column} IN ({values}) to filter entities")

        if rules.get("must_have_group_by") and "GROUP BY" not in sql_upper:
            msg = "GROUP BY missing for comparison"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Add GROUP BY to separate each entity")

    # Time series validations
    elif query_type == "time_series":
        has_date_filter = any(kw in sql_upper for kw in ["DATE", "TIMESTAMP", "INTERVAL", ">=", "BETWEEN"])

        if rules.get("must_have_date_filter") and not has_date_filter:
            msg = "Date/time filtering may be missing for time series"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Add WHERE date >= DATE_SUB(NOW(), INTERVAL {period})")

        if rules.get("must_have_group_by_date") and "GROUP BY" not in sql_upper:
            msg = "GROUP BY date missing for time series"
            validation["warnings"].append(msg)

        if rules.get("must_have_order_by_date") and "ORDER BY" not in sql_upper:
            msg = "ORDER BY date missing for time series trend"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Add ORDER BY {date_column} ASC for chronological order")

    # Single value validations
    elif query_type == "single_value":
        has_aggregation = any(agg in sql_upper for agg in ["SUM(", "AVG(", "COUNT(", "MIN(", "MAX("])

        if rules.get("must_have_aggregation") and not has_aggregation:
            msg = "Aggregation function missing for single value query"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Use SUM/AVG/COUNT/MIN/MAX for single value result")

        if rules.get("must_not_have_group_by") and "GROUP BY" in sql_upper:
            msg = "GROUP BY found but single value query should return single row"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Remove GROUP BY for single aggregate value")

    # Aggregation validations
    elif query_type == "aggregation":
        if rules.get("must_have_group_by") and "GROUP BY" not in sql_upper:
            msg = "GROUP BY missing for aggregation query"
            validation["warnings"].append(msg)
            validation["suggestions"].append("Add GROUP BY {columns} to group results")

        has_aggregation = any(agg in sql_upper for agg in ["SUM(", "AVG(", "COUNT(", "MIN(", "MAX("])
        if rules.get("must_have_aggregation") and not has_aggregation:
            msg = "Aggregation function missing"
            validation["warnings"].append(msg)

    # Time series comparison validations
    elif query_type == "time_series_comparison":
        if rules.get("must_have_date_filter"):
            has_date_filter = any(kw in sql_upper for kw in ["DATE", "TIMESTAMP", "INTERVAL"])
            if not has_date_filter:
                validation["warnings"].append("Date filtering may be missing")

        if rules.get("must_have_entity_filter") and " IN " not in sql_upper:
            validation["warnings"].append("Entity filtering (IN clause) may be missing")

        if rules.get("must_have_double_group_by"):
            group_by_count = sql_upper.count("GROUP BY")
            if group_by_count == 0:
                validation["warnings"].append("GROUP BY missing for time series comparison")
            elif "," not in sql.split("GROUP BY")[1].split("ORDER BY")[0] if "ORDER BY" in sql else sql.split("GROUP BY")[1]:
                validation["warnings"].append("GROUP BY should include both date and entity columns")

    logger.info(f"[VALIDATION] {query_type}: valid={validation['valid']}, "
               f"warnings={len(validation['warnings'])}, errors={len(validation['errors'])}")

    return validation


__all__ = [
    "QUERY_TYPE_SQL_PATTERNS",
    "get_pattern",
    "get_sql_hints",
    "get_validation_rules",
    "format_pattern_for_prompt",
    "validate_sql_matches_pattern"
]
