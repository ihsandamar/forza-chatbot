from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class InsightDebugInfo(TypedDict, total=False):
    """Insight engine'in her çalışmasının tam kaydı — LangSmith/debug tracer'da görülebilir."""

    # SQL izleri
    active_sql: str                        # orijinal sorgu SQL'i
    comparison_sql: Optional[str]          # karşılaştırma dönemi SQL'i (varsa)

    # Ham veri özeti
    total_rows: int                        # current_df satır sayısı
    total_value: float                     # toplam metrik (DB'den veya df.sum())
    period_days: int                       # analiz edilen gün sayısı
    period_label: str                      # "2024-01-01 – 2024-03-23"
    daily_avg: float                       # günlük ortalama metrik
    data_granularity: str                  # "günlük" / "haftalık" / "aylık" / "bilinmiyor"

    # Gruplama bağlamı
    dimension_columns: list                # ["ProductName", "DocumentDate"]
    metric_columns: list                   # ["RowAmount"]
    groupby_fields: list                   # date dışı boyut sütunları
    segment_col: Optional[str]             # ana segment sütunu
    segment_count: int                     # kaç farklı segment var
    top_segment: Optional[str]             # en yüksek paylı segment
    top_segment_share_pct: float           # en yüksek segmentin pay yüzdesi

    # Matematiksel hesaplama sonuçları
    analyzer_breakdown: dict               # {"TrendAnalyzer": 3, "AnomalyDetector": 2, ...}
    all_findings_count: int                # tüm bulgular (ranking öncesi)
    ranked_findings_count: int             # ranker sonrası kalan
    significance_distribution: dict       # {"🔴": 3, "🟡": 5, "🟢": 2}

    # LLM'e giden prompt
    llm_prompt: str                        # gönderilen prompt metni
    llm_prompt_chars: int                  # karakter sayısı


class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]         # NEW_QUERY | MODIFY_QUERY | USE_RESULT | VAGUE_QUERY
    query_type: Optional[str]          # SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    wants_visualization: Optional[bool]  # Kullanıcı açıkça grafik istedi mi? MODIFY_QUERY'de visualization_explicitly_set=False ise önceki turdan inherit edilir
    requested_chart_type: Optional[str]  # "heatmap", "sunburst" etc. — intent LLM'den gelir
    chart_x_hint: Optional[str]          # x-axis kolon ipucu — kullanıcı açıkça belirtirse dolar
    use_result_type: Optional[str]     # "new_query" | "revisualize" | "compute" | "modify_context"
    compute_operation: Optional[str]   # "sum" | "avg" | "count" | "min" | "max" (compute için)

    # Conversation Context (MODIFY ve USE_RESULT için)
    active_sql: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    active_filters: Optional[List[Dict[str, Any]]]  # Son SQL'in WHERE filtreleri [{field, value}]; classify_intent: NEW_QUERY'de None, diğerlerinde korunur; modify_sql günceller; sql_executor query_schema boşsa preserve eder
    accumulated_entities: Optional[List[Dict[str, Any]]]  # cross-turn {column, value} listesi; intent'ten bağımsız korunur (max 100, sütun başına max 10)

    # Text2SQL I/O (subgraph shared fields)
    sql_queries: Optional[List[str]]
    pre_built_sql: Optional[str]        # modify_sql çıktısı — sql_generator bunu görünce yeniden üretmez
    time_granularity: Optional[str]      # text2sql → viz subgraph (hour_of_day, day_of_week, etc.)
    comparison_dimension: Optional[str]   # text2sql → viz subgraph (DB column: "CategoryName", "ProductName" etc.)
    modification_hints: Optional[List[Dict[str, Any]]]  # modify_sql → value_resolver (MODIFY_QUERY value resolution)
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    candidate_filter_terms: Optional[List[Dict[str, Any]]]  # term_resolver → term_validator (term_id + metadata)
    validated_term_filters: Optional[List[Dict[str, Any]]]  # term_validator → sql_generator (onaylanan filtreler)

    # NLU Pipeline (semantic approach)
    semantic_intent: Optional[Dict]      # SemanticIntent.model_dump() — semantic_extractor output
    term_resolution: Optional[Dict]      # {raw_text → TermMatch dict} — term_resolver output
    time_breakdown: Optional[bool]       # intent_resolver time_breakdown flag

    # Visualization
    viz_request: Optional[str]           # "pasta grafik" gibi görselleştirme tarzı (sadece revisualize'da)
    visualization_output: Optional[Dict[str, Any]]

    # Clarification (VAGUE_QUERY loop protection)
    _clarification_count: Optional[int]  # report_chat geçiş sayısı, max 2
    _skip_vague_check: Optional[bool]    # True = max clarification aşıldı, VAGUE_QUERY → NEW_QUERY zorla

    # Insight Engine
    comparison_sql: Optional[str]           # Mode B: kullanıcının verdiği karşılaştırma SQL'i
    insight_findings: Optional[List[Dict[str, Any]]]  # Ranker çıktısı — ranked top-N (debug)
    insight_raw_findings: Optional[List[Dict[str, Any]]]  # Tüm findings ranking öncesi (debug)
    insight_summary: Optional[Dict[str, Any]]  # Özet istatistikler: total, days, avg, segment (debug)
    insight_debug: Optional[InsightDebugInfo]  # Tam debug kaydı: SQL + veri + matematik + LLM prompt
    insight_output: Optional[str]           # LLM Interpreter çıktısı
    user_role: Optional[str]                # branch_manager | general_manager | operations

    # Response
    final_response: Optional[str]

    # HITL subgraph clarification pipeline
    text2sql_clarification: Optional[dict]
    # Payload: {"type","question","options","source"}
    # text2sql node set eder → hitl_check okur → None'a resetler

    text2sql_answers: Optional[list]
    # Birikimli cevaplar: [{"source": str, "answer": str}, ...]
    # hitl_check append eder → text2sql node'ları okur
    # classify_intent her turda None'a resetler

    _hitl_answered: bool
    # True → hitl_check'ten sonra text2sql tekrar çalıştır
    # False → normal visualization/build_response akışı


def create_initial_state() -> ReportState:
    return ReportState(
        messages=[],
        user_query="",
        session_id=None,
        intent_type=None,
        query_type=None,
        intent_confidence=None,
        wants_visualization=None,
        requested_chart_type=None,
        chart_x_hint=None,
        use_result_type=None,
        compute_operation=None,
        active_sql=None,
        active_results=None,
        active_filters=None,
        accumulated_entities=None,
        sql_queries=None,
        pre_built_sql=None,
        time_granularity=None,
        comparison_dimension=None,
        modification_hints=None,
        results=None,
        error=None,
        candidate_filter_terms=None,
        validated_term_filters=None,
        semantic_intent=None,
        term_resolution=None,
        time_breakdown=None,
        viz_request=None,
        visualization_output=None,
        _clarification_count=0,
        _skip_vague_check=False,
        comparison_sql=None,
        insight_findings=None,
        insight_raw_findings=None,
        insight_summary=None,
        insight_debug=None,
        insight_output=None,
        user_role=None,
        final_response=None,
        text2sql_clarification=None,
        text2sql_answers=None,
        _hitl_answered=False,
    )
