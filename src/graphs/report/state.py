"""
Report Graph State Definition

Stateful Report Agent - HITL destekli, context-aware rapor üretim sistemi.

State Hierarchy:
- ReportState: Temel state (backward compatible)
- ActiveQueryContext: Mevcut sorgu bağlamı
- QueryCheckpoint: Undo/redo için sorgu versiyonları
"""

from typing import TypedDict, List, Optional, Dict, Any, Annotated
from datetime import datetime
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# =============================================================================
# ACTIVE QUERY CONTEXT - Mevcut SQL sorgusu ve bağlamı
# =============================================================================

class ActiveQueryContext(TypedDict):
    """
    Mevcut SQL sorgusu ve bağlamını saklar.

    Delta-SQL güncellemeleri için temel context bilgisi sağlar.
    """
    # Tablo bilgisi
    current_table: str                      # "SatisVerileri", "MusteriVerileri"

    # SQL bilgisi
    current_sql: str                        # Aktif SQL string
    applied_filters: List[Dict[str, Any]]   # [{"column": "sehir", "value": "Istanbul", "operator": "="}]
    grouping_columns: List[str]             # GROUP BY kolonları
    order_by_columns: List[str]             # ORDER BY kolonları

    # Sonuç bilgisi
    result_sample: Optional[List[Dict]]     # İlk 5 satır örneği
    result_row_count: int                   # Toplam satır sayısı

    # Meta bilgi
    last_execution_time: str                # ISO timestamp
    confidence_score: float                 # 0.0-1.0 güven skoru


# =============================================================================
# QUERY CHECKPOINT - Undo/Redo desteği için versiyon takibi
# =============================================================================

class QueryCheckpoint(TypedDict):
    """
    Sorgu versiyonlarını saklar (Undo/Redo capability).

    Her başarılı SQL execute'dan sonra checkpoint oluşturulur.
    """
    version: int                            # Versiyon numarası (1, 2, 3...)
    timestamp: str                          # ISO timestamp
    active_context: ActiveQueryContext      # O andaki context snapshot
    user_message: str                       # Kullanıcının mesajı


# =============================================================================
# PENDING QUESTION - HITL için bekleyen sorular
# =============================================================================

class PendingQuestion(TypedDict):
    """HITL için kullanıcıya sorulacak soru."""
    question: str                           # "Hangi tablo? Bireysel mi Kurumsal mı?"
    options: List[str]                      # ["Bireysel", "Kurumsal", "Ikisini Birlestir"]
    context: Optional[str]                  # Ek bağlam bilgisi


# =============================================================================
# REDUCER FUNCTIONS - State güncellemeleri için
# =============================================================================

def append_with_limit(existing: List, new: Any, limit: int = 10) -> List:
    """
    Listeye eleman ekle, maksimum limit'i aşma.

    Args:
        existing: Mevcut liste
        new: Eklenecek eleman(lar)
        limit: Maksimum eleman sayısı

    Returns:
        Güncellenmiş liste (son 'limit' eleman)
    """
    if new is None:
        return existing

    if isinstance(new, list):
        combined = existing + new
    else:
        combined = existing + [new]

    return combined[-limit:]


def checkpoint_reducer(existing: List[QueryCheckpoint], new: Any) -> List[QueryCheckpoint]:
    """
    Query checkpoint reducer - son 10 checkpoint'i tutar.

    Args:
        existing: Mevcut checkpoint listesi
        new: Yeni checkpoint(ler)

    Returns:
        Güncellenmiş liste (son 10 checkpoint)
    """
    return append_with_limit(existing, new, limit=10)


# =============================================================================
# REPORT STATE - Ana state tanımı
# =============================================================================

class ReportState(TypedDict):
    """
    Stateful Report Agent için ana state.

    LangGraph messages pattern kullanır.
    HITL ve context management destekler.
    """

    # -------------------------------------------------------------------------
    # Core: Mesajlar (LangGraph standard)
    # -------------------------------------------------------------------------
    messages: Annotated[List[BaseMessage], add_messages]

    # -------------------------------------------------------------------------
    # Context: Aktif sorgu bağlamı
    # -------------------------------------------------------------------------
    active_query_context: Optional[ActiveQueryContext]

    # -------------------------------------------------------------------------
    # History: Sorgu geçmişi (Undo/Redo)
    # -------------------------------------------------------------------------
    query_history: Annotated[List[QueryCheckpoint], checkpoint_reducer]

    # -------------------------------------------------------------------------
    # HITL: Human-in-the-Loop desteği
    # -------------------------------------------------------------------------
    pending_question: Optional[PendingQuestion]     # Bekleyen soru
    waiting_for_user_input: bool                    # True ise interrupt
    user_clarification: Optional[str]               # Kullanıcının cevabı

    # -------------------------------------------------------------------------
    # Processing: İşlem çıktıları
    # -------------------------------------------------------------------------
    text2sql_output: Optional[Dict[str, Any]]
    visualization_output: Optional[Dict[str, Any]]

    # -------------------------------------------------------------------------
    # Error: Hata takibi
    # -------------------------------------------------------------------------
    error: Optional[str]
    no_records_message: Optional[str]

    # -------------------------------------------------------------------------
    # Internal: Intent classification results (runtime fields)
    # -------------------------------------------------------------------------
    _intent_type: Optional[str]                     # IntentType enum value
    _confidence: Optional[float]                    # 0.0-1.0
    _extracted_entities: Optional[Dict[str, Any]]   # Extracted entities from intent
    _modification_action: Optional[str]             # "add", "remove", "expand", etc.
    _selected_table: Optional[str]                  # User-selected table from HITL
    _selected_filter_value: Optional[str]           # User-selected filter value from HITL
    _selected_column: Optional[str]                 # User-selected column from metadata ambiguity
    _selected_value: Optional[str]                  # User-selected value from metadata ambiguity
    _clarification_type: Optional[str]              # "column", "value", "table", etc.
    _user_preference: Optional[str]                 # User preference (date range, location, category)
    _preference_type: Optional[str]                 # "date_range", "location", "category", "general"
    _use_exact_input: Optional[bool]                # True if user rejected "did you mean" suggestion
    _viz_decision: Optional[Dict[str, Any]]         # Visualization decision (from report graph, not viz graph)


# =============================================================================
# FACTORY FUNCTIONS - State oluşturma yardımcıları
# =============================================================================

def create_empty_context() -> ActiveQueryContext:
    """Boş ActiveQueryContext oluşturur."""
    return ActiveQueryContext(
        current_table="",
        current_sql="",
        applied_filters=[],
        grouping_columns=[],
        order_by_columns=[],
        result_sample=None,
        result_row_count=0,
        last_execution_time=datetime.now().isoformat(),
        confidence_score=0.0
    )


def create_checkpoint(
    context: ActiveQueryContext,
    user_message: str,
    version: int
) -> QueryCheckpoint:
    """
    Yeni checkpoint oluşturur.

    Args:
        context: Mevcut query context
        user_message: Kullanıcının mesajı
        version: Versiyon numarası

    Returns:
        QueryCheckpoint instance
    """
    return QueryCheckpoint(
        version=version,
        timestamp=datetime.now().isoformat(),
        active_context=context,
        user_message=user_message
    )


def create_initial_state() -> ReportState:
    """
    Boş initial state oluşturur.

    Returns:
        ReportState instance with defaults
    """
    return ReportState(
        messages=[],
        active_query_context=None,
        query_history=[],
        pending_question=None,
        waiting_for_user_input=False,
        user_clarification=None,
        text2sql_output=None,
        visualization_output=None,
        error=None,
        no_records_message=None
    )
