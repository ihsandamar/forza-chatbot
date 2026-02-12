"""
HITL Question Builder - User-Friendly Question Generation

Transforms AmbiguityContext into clear, well-structured HITL questions
with proper formatting, explanations, and context summaries.

Features:
- Type-specific question templates
- Rich formatting (emojis, sections, numbering)
- Context-aware explanations
- Clear option presentation

Author: Enhanced HITL System v2.0
Date: 2026-02-05
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from .ambiguity_framework import (
    AmbiguityContext,
    AmbiguityType,
    format_filter_summary
)


# =============================================================================
# QUESTION TEMPLATE - Structured HITL question
# =============================================================================

@dataclass
class QuestionTemplate:
    """
    Structured HITL question for user.

    Attributes:
        title: Main question title
        explanation: Why we're asking this question
        context_summary: Current state summary (optional)
        options: List of options for user to choose from
        metadata: Additional metadata for processing response
    """

    title: str
    explanation: str
    context_summary: Optional[str] = None
    options: List[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Initialize default values."""
        if self.options is None:
            self.options = []
        if self.metadata is None:
            self.metadata = {}

    def format_for_user(self) -> str:
        """
        Format question for display to user.

        Returns:
            Formatted string with emojis, sections, and clear structure

        Example:
            ❓ Hangi kolonu kullanmak istersiniz?

            💡 Sorgunuzda 'kategori' kelimesi birden fazla kolona eşleşiyor.

            📌 Mevcut Durum: Ankara | Son 3 yıl | 125 satır

            Seçenekler:
              1. CategoryName
              2. SubCategoryName
        """
        lines = []

        # Title with emoji
        lines.append(f"❓ {self.title}")
        lines.append("")

        # Explanation with emoji
        lines.append(f"💡 {self.explanation}")
        lines.append("")

        # Context summary (if exists)
        if self.context_summary:
            lines.append(f"📌 Mevcut Durum: {self.context_summary}")
            lines.append("")

        # Options
        if self.options:
            lines.append("Seçenekler:")
            for i, option in enumerate(self.options, 1):
                lines.append(f"  {i}. {option}")

        return "\n".join(lines)

    def to_pending_question(self) -> Dict[str, Any]:
        """
        Convert to PendingQuestion format for state.

        Returns:
            Dict compatible with PendingQuestion TypedDict
        """
        return {
            "question": self.format_for_user(),
            "options": self.options,
            "context": self.context_summary
        }


# =============================================================================
# HITL QUESTION BUILDER - Main builder class
# =============================================================================

class HITLQuestionBuilder:
    """
    Builds user-friendly HITL questions from AmbiguityContext.

    Usage:
        builder = HITLQuestionBuilder()
        question = builder.build_question(ambiguity_context)
        print(question.format_for_user())
    """

    def build_question(self, ambiguity_ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build HITL question from ambiguity context.

        Args:
            ambiguity_ctx: Detected ambiguity context

        Returns:
            QuestionTemplate ready for display

        Raises:
            ValueError: If ambiguity type not recognized
        """
        # Route to type-specific builder
        builders = {
            AmbiguityType.CONTEXT: self._build_context_question,
            AmbiguityType.PROMPT_SCOPE: self._build_prompt_scope_question,
            AmbiguityType.INTENT: self._build_intent_question,
            AmbiguityType.QUERY_TYPE: self._build_query_type_question,
            AmbiguityType.COLUMN: self._build_column_question,
            AmbiguityType.VALUE: self._build_value_question,
        }

        builder_func = builders.get(ambiguity_ctx.ambiguity_type)
        if not builder_func:
            raise ValueError(f"Unknown ambiguity type: {ambiguity_ctx.ambiguity_type}")

        return builder_func(ambiguity_ctx)

    # =========================================================================
    # CONTEXT AMBIGUITY - Priority #1 (Most Critical)
    # =========================================================================

    def _build_context_question(self, ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build context ambiguity question - CRITICAL for user understanding.

        ⚠️ CLEAR & DIRECT: User must understand what they're choosing!

        Example:
            User: "Hangi kategoriden satış olmuş?"
            Context: Ankara + Son 3 yıl filters

            Question:
                ❓ Sen ne yapmak istiyorsun?

                💡 Şu anda 'Ankara, Son 3 yıl' filtreleriyle çalışıyorsun.
                    Yeni sorgun bu filtrelerle mi devam edecek, yoksa sıfırdan
                    yeni bir sorgu mu başlatacaksın?

                📌 Mevcut Filtreler: Ankara | Son 3 yıl | 125 satır

                Seçenekler:
                  1. Mevcut filtrelerle devam et (Ankara + Son 3 yıl için göster)
                  2. Yeni sorgu başlat (TÜM VERİLER için göster)

        Args:
            ctx: AmbiguityContext with type=CONTEXT

        Returns:
            QuestionTemplate for context ambiguity
        """
        metadata = ctx.metadata
        filters = metadata.get("applied_filters", [])
        new_dimension = metadata.get("new_dimension", "analiz")
        row_count = metadata.get("result_row_count", 0)

        # Format filter summary
        filter_summary = format_filter_summary(filters)

        # Build title - DIRECT & CLEAR
        title = "Sen ne yapmak istiyorsun?"

        # Build explanation - DETAILED
        explanation = (
            f"Şu anda '{filter_summary}' filtreleriyle çalışıyorsun.\n"
            f"    Yeni sorgun ('{new_dimension}') bu filtrelerle mi devam edecek,\n"
            f"    yoksa sıfırdan yeni bir sorgu mu başlatacaksın?"
        )

        # Build context summary
        context_summary = ctx.active_context_summary or f"{filter_summary} | {row_count} satır"

        # Build options - CRYSTAL CLEAR
        option_continue = (
            f"Mevcut filtrelerle devam et "
            f"({filter_summary} için {new_dimension} göster)"
        )

        option_new = (
            f"Yeni sorgu başlat "
            f"(TÜM VERİLER için {new_dimension} göster)"
        )

        options = [option_continue, option_new]

        return QuestionTemplate(
            title=title,
            explanation=explanation,
            context_summary=f"Mevcut Filtreler: {context_summary}",
            options=options,
            metadata={
                "ambiguity_type": AmbiguityType.CONTEXT,
                "filters": filters,
                "new_dimension": new_dimension,
                "critical": True  # Mark as critical question
            }
        )

    # =========================================================================
    # PROMPT SCOPE AMBIGUITY - Priority #2 (NEW FEATURE)
    # =========================================================================

    def _build_prompt_scope_question(self, ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build prompt scope ambiguity question.

        Example:
            User: "Satışlar"

            Question:
                ❓ Sorgunuz çok kısa, daha açık belirtir misiniz?

                💡 'Satışlar' - Bu sorgu için daha fazla bilgiye ihtiyacım var.

                Seçenekler:
                  1. Tüm satış kayıtlarını listele
                  2. Satış özet istatistikleri göster
                  3. Belirli bir kritere göre satışları filtrele
                  4. Gruplama ile satış analizi yap

        Args:
            ctx: AmbiguityContext with type=PROMPT_SCOPE

        Returns:
            QuestionTemplate for prompt scope ambiguity
        """
        query = ctx.user_query
        metadata = ctx.metadata
        word_count = metadata.get("word_count", 0)
        suggested = metadata.get("suggested_clarifications", [])

        # Build title
        title = "Sorgunuz çok kısa, daha açık belirtir misiniz?"

        # Build explanation
        explanation = (
            f"'{query}' - Bu sorgu için daha fazla bilgiye ihtiyacım var.\n"
            f"    Ne tür bir analiz ya da rapor istediğinizi belirtir misiniz?"
        )

        # Build options (use suggested or default)
        if suggested:
            options = suggested
        else:
            options = [
                f"Tüm {query} kayıtlarını listele",
                f"{query} özet istatistikleri göster",
                f"Belirli bir kritere göre {query} filtrele",
                f"Gruplama ile {query} analizi yap"
            ]

        return QuestionTemplate(
            title=title,
            explanation=explanation,
            context_summary=None,
            options=options,
            metadata={
                "ambiguity_type": AmbiguityType.PROMPT_SCOPE,
                "original_query": query,
                "word_count": word_count
            }
        )

    # =========================================================================
    # INTENT AMBIGUITY - Priority #3
    # =========================================================================

    def _build_intent_question(self, ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build intent ambiguity question.

        Example:
            User: "Bunu değiştir"

            Question:
                ❓ Ne yapmak istediğinizi tam anlayamadım

                💡 Sorgunuz birden fazla işlem türüne uyuyor.

                Seçenekler:
                  1. Mevcut raporu değiştir
                  2. Yeni bir sorgu oluştur
                  3. Filtre ekle/çıkar

        Args:
            ctx: AmbiguityContext with type=INTENT

        Returns:
            QuestionTemplate for intent ambiguity
        """
        query = ctx.user_query
        possible_intents = ctx.metadata.get("possible_intents", [])

        # Build title
        title = "Ne yapmak istediğinizi tam anlayamadım"

        # Build explanation
        explanation = f"'{query}' - Sorgunuz birden fazla işlem türüne uyuyor."

        # Build options from possible intents
        intent_labels = {
            "new_query": "Yeni bir sorgu oluştur",
            "modify_filter": "Mevcut filtreleri değiştir",
            "add_column": "Yeni kolon ekle",
            "remove_column": "Kolon çıkar",
            "change_aggregation": "Toplama/gruplama değiştir",
            "undo": "Önceki adıma geri dön"
        }

        options = []
        for intent in possible_intents:
            label = intent_labels.get(intent, intent)
            options.append(label)

        # Fallback if no intents provided
        if not options:
            options = [
                "Yeni bir sorgu oluştur",
                "Mevcut raporu değiştir",
                "Filtre ekle/çıkar"
            ]

        return QuestionTemplate(
            title=title,
            explanation=explanation,
            context_summary=ctx.active_context_summary,
            options=options,
            metadata={
                "ambiguity_type": AmbiguityType.INTENT,
                "possible_intents": possible_intents
            }
        )

    # =========================================================================
    # QUERY TYPE AMBIGUITY - Priority #3.5 (NEW!)
    # =========================================================================

    def _build_query_type_question(self, ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build query type ambiguity question.

        Example:
            User: "Toplam ciro"

            Question:
                ❓ Ne tür bir analiz yapmak istiyorsunuz?

                💡 Sorgunuz birden fazla analiz türüne uyuyor.

                Seçenekler:
                  1. Tek bir toplam değer göster (Örn: Toplam ciro: 1.250.000 TL)
                  2. Kategorilere göre grupla (Örn: Her kategori için toplam)
                  3. En yüksek/düşük değerleri sırala (Örn: En çok ciro yapan 10 ürün)

        Args:
            ctx: AmbiguityContext with type=QUERY_TYPE

        Returns:
            QuestionTemplate for query type ambiguity
        """
        query = ctx.user_query
        possible_types = ctx.metadata.get("possible_types", ctx.candidates)
        detected_type = ctx.metadata.get("detected_type")

        # Build title
        title = "Ne tür bir analiz yapmak istiyorsunuz?"

        # Build explanation
        if detected_type:
            explanation = (
                f"'{query}' sorgusu için '{self._get_query_type_label(detected_type)}' tespit ettim,\n"
                f"    ancak başka analiz türleri de mümkün. Hangisini tercih edersiniz?"
            )
        else:
            explanation = f"'{query}' - Sorgunuz birden fazla analiz türüne uyuyor."

        # Build options with descriptions
        options = []
        for qtype in possible_types:
            label = self._get_query_type_option_label(qtype, query)
            options.append(label)

        return QuestionTemplate(
            title=title,
            explanation=explanation,
            context_summary=ctx.active_context_summary,
            options=options,
            metadata={
                "ambiguity_type": AmbiguityType.QUERY_TYPE,
                "possible_types": possible_types,
                "detected_type": detected_type,
                "query_type_mapping": {opt: qtype for opt, qtype in zip(options, possible_types)}
            }
        )

    def _get_query_type_label(self, query_type: str) -> str:
        """Get Turkish label for query type."""
        labels = {
            "single_value": "Tek Değer",
            "ranking": "Sıralama (Top-N)",
            "comparison": "Karşılaştırma",
            "time_series": "Zaman Serisi",
            "time_series_comparison": "Zaman Serisi Karşılaştırma",
            "aggregation": "Gruplama",
            "distribution": "Dağılım",
            "trend": "Trend Analizi"
        }
        return labels.get(query_type, query_type)

    def _get_query_type_option_label(self, query_type: str, user_query: str) -> str:
        """
        Get user-friendly option label for query type.

        Args:
            query_type: Query type identifier
            user_query: User's original query for context

        Returns:
            User-friendly label with example
        """
        labels = {
            "single_value": "Tek bir toplam/ortalama değer göster (Örn: Toplam ciro: 1.250.000 TL)",
            "ranking": "En yüksek/düşük değerleri sırala (Örn: En çok ciro yapan 10 ürün)",
            "comparison": "İki veya daha fazla öğeyi karşılaştır (Örn: İstanbul vs Ankara)",
            "time_series": "Zaman içindeki değişimi göster (Örn: Son 6 aydaki aylık satışlar)",
            "time_series_comparison": "Birden fazla öğenin zaman içindeki karşılaştırması",
            "aggregation": "Kategorilere/gruplara göre topla (Örn: Her kategori için toplam)",
            "distribution": "Dağılım ve oranları göster (Örn: Satışların şubelere göre dağılımı)",
            "trend": "Artış/azalış trendini analiz et (Örn: Satışlar artıyor mu?)"
        }
        return labels.get(query_type, query_type)

    # =========================================================================
    # COLUMN AMBIGUITY - Priority #4
    # =========================================================================

    def _build_column_question(self, ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build column ambiguity question.

        Example:
            User: "Kategorilere göre göster"
            Matched: CategoryName, SubCategoryName

            Question:
                ❓ Hangi kolonu kullanmak istersiniz?

                💡 Sorgunuzda 'kategori' kelimesi birden fazla kolona eşleşiyor.

                Seçenekler:
                  1. CategoryName (Ana kategori)
                  2. SubCategoryName (Alt kategori)

        Args:
            ctx: AmbiguityContext with type=COLUMN

        Returns:
            QuestionTemplate for column ambiguity
        """
        query_term = ctx.metadata.get("query_term", "belirtilen terim")
        matched_columns = ctx.metadata.get("matched_columns", ctx.candidates)

        # Build title
        title = "Hangi kolonu kullanmak istersiniz?"

        # Build explanation
        explanation = (
            f"Sorgunuzda '{query_term}' kelimesi birden fazla kolona eşleşiyor."
        )

        # Build options
        options = matched_columns

        return QuestionTemplate(
            title=title,
            explanation=explanation,
            context_summary=ctx.active_context_summary,
            options=options,
            metadata={
                "ambiguity_type": AmbiguityType.COLUMN,
                "query_term": query_term,
                "matched_columns": matched_columns
            }
        )

    # =========================================================================
    # VALUE AMBIGUITY - Priority #5 (Lowest)
    # =========================================================================

    def _build_value_question(self, ctx: AmbiguityContext) -> QuestionTemplate:
        """
        Build value ambiguity question.

        Example:
            User: "İstanbul"
            Matched: İstanbul (şehir), İstanbul (müşteri adı)

            Question:
                ❓ Hangi değeri kullanmak istersiniz?

                💡 'İstanbul' için birden fazla eşleşme bulundu.

                Seçenekler:
                  1. İstanbul (BranchCityName - Şehir)
                  2. İstanbul Mağazası (BranchName - Şube)

        Args:
            ctx: AmbiguityContext with type=VALUE

        Returns:
            QuestionTemplate for value ambiguity
        """
        column = ctx.metadata.get("column", "")
        user_term = ctx.metadata.get("user_term", "belirtilen değer")
        matched_values = ctx.metadata.get("matched_values", ctx.candidates)

        # Build title
        title = "Hangi değeri kullanmak istersiniz?"

        # Build explanation
        explanation = f"'{user_term}' için birden fazla eşleşme bulundu."

        # Build options (with column context if available)
        options = []
        for value in matched_values:
            if column:
                options.append(f"{value} ({column})")
            else:
                options.append(str(value))

        return QuestionTemplate(
            title=title,
            explanation=explanation,
            context_summary=ctx.active_context_summary,
            options=options,
            metadata={
                "ambiguity_type": AmbiguityType.VALUE,
                "column": column,
                "user_term": user_term,
                "matched_values": matched_values
            }
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_simple_question(
    title: str,
    explanation: str,
    options: List[str],
    context_summary: Optional[str] = None
) -> QuestionTemplate:
    """
    Quick helper to create simple question templates.

    Args:
        title: Question title
        explanation: Explanation text
        options: List of options
        context_summary: Optional context summary

    Returns:
        QuestionTemplate
    """
    return QuestionTemplate(
        title=title,
        explanation=explanation,
        context_summary=context_summary,
        options=options
    )
