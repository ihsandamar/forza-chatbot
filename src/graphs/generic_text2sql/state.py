from typing import TypedDict, List, Optional, Literal


class Filter(TypedDict, total=False):
    """Filter definition for SQL query"""
    field_hint: str
    operator: Literal["=", ">", "<", ">=", "<=", "!=", "LIKE", "IN", "BETWEEN", "IS", "IS NOT"]
    value_hint: str
    resolved_value: Optional[str]  # Değer resolver tarafından bulunan gerçek değer
    resolution_confidence: Optional[float]  # Çözümleme güven skoru (0-100)
    logical_operator: Optional[Literal["AND", "OR"]]  # Mantıksal operatör (default: AND)


class Aggregation(TypedDict, total=False):
    """Aggregation definition for SQL query"""
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    field_hint: str
    alias: str


class OrderBy(TypedDict, total=False):
    """Order by definition for SQL query"""
    field_hint: str
    direction: Literal["ASC", "DESC"]


class QueryStep(TypedDict, total=False):
    """Individual query step definition"""
    step_number: int
    description: str
    select: Optional[List[str]]  # Kullanıcının görmek istediği alanlar (opsiyonel)
    filters: List[Filter]
    aggregations: List[Aggregation]
    group_by: List[str]
    order_by: Optional[OrderBy]
    limit: Optional[int]
    depends_on: Optional[int]


class ParsedIntent(TypedDict, total=False):
    """Parsed user intent structure"""
    complexity: Literal["simple", "compound", "comparative"]
    steps: List[QueryStep]
    final_output: str


class ResolutionMetadata(TypedDict, total=False):
    """Metadata about value resolution process"""
    total_values: int  # Toplam çözümlenmesi gereken değer sayısı
    resolved_values: int  # Başarıyla çözümlenen değer sayısı
    unresolved_values: List[str]  # Çözümlenemeyen değerler
    avg_confidence: Optional[float]  # Ortalama güven skoru


class GenericText2SQLState(TypedDict):
    """State for generic text2sql graph"""
    user_query: str
    parsed_intent: Optional[ParsedIntent]
    enriched_metadata: Optional[dict]  # Column-specific metadata (token optimization)
    resolved_steps: Optional[List[QueryStep]]
    resolution_metadata: Optional[ResolutionMetadata]
    sql_queries: Optional[List[str]]
    results: Optional[List[dict]]
    final_response: Optional[str]
    error: Optional[str]

    # Optimization fields
    schema_metadata: Optional[dict]  # Runtime-discovered schema metadata
    business_rules: Optional[dict]  # Loaded business rules from JSON
    retry_count: Optional[int]  # Self-healing retry counter
    sql_error_history: Optional[List[dict]]  # History of SQL errors for self-correction