"""
HITL Tools for Report Agent

Human-in-the-Loop araçları.
interrupt_before pattern ile kullanıcı etkileşimi sağlar.

Usage:
    - ask_user_clarification: Kullanıcıya soru sor
    - Interrupt node'u: Graph'ı durdur, kullanıcı yanıtı bekle
"""

import logging
from typing import List, Optional, Dict, Any
from langchain_core.tools import tool

from .state import PendingQuestion, ReportState

logger = logging.getLogger(__name__)


# =============================================================================
# HITL TOOLS
# =============================================================================

@tool
def ask_user_clarification(
    question: str,
    options: List[str],
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Kullanıcıya açıklama sorusu sor.

    Bu tool çağrıldığında graph interrupt olur ve
    kullanıcı yanıtı beklenir.

    Args:
        question: Sorulacak soru
        options: Seçenekler listesi
        context: Ek bağlam bilgisi

    Returns:
        PendingQuestion formatında dict
    """
    logger.info(f"HITL: Asking user - {question}")
    logger.debug(f"Options: {options}")

    return {
        "question": question,
        "options": options,
        "context": context
    }


# =============================================================================
# HITL NODE FUNCTIONS
# =============================================================================

def should_interrupt(state: ReportState) -> bool:
    """
    Interrupt gerekip gerekmediğini kontrol et.

    interrupt_before conditional olarak kullanılır.

    Args:
        state: Current report state

    Returns:
        True if should interrupt for user input
    """
    # Zaten kullanıcı input bekliyorsak interrupt etme (resume durumu)
    if state.get("user_clarification"):
        return False

    # Pending question varsa interrupt et
    if state.get("pending_question"):
        return True

    # waiting_for_user_input flag'i set edilmişse interrupt et
    if state.get("waiting_for_user_input", False):
        return True

    return False


def create_clarification_request(
    question: str,
    options: List[str],
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Clarification request oluştur.

    Bu fonksiyon node içinde çağrılır ve
    state'e pending_question ekler.

    Args:
        question: Soru
        options: Seçenekler
        context: Bağlam

    Returns:
        State update dict
    """
    pending_question = PendingQuestion(
        question=question,
        options=options,
        context=context
    )

    return {
        "pending_question": pending_question,
        "waiting_for_user_input": True
    }


def process_user_response(state: ReportState) -> Dict[str, Any]:
    """
    Kullanıcı yanıtını işle.

    Resume sonrası kullanıcı yanıtı state'de user_clarification
    olarak gelir. Bu fonksiyon yanıtı işler ve state'i temizler.

    Args:
        state: Current state with user_clarification

    Returns:
        State update dict
    """
    user_response = state.get("user_clarification")
    pending_question = state.get("pending_question")

    if not user_response:
        logger.warning("No user clarification in state")
        return {}

    logger.info(f"Processing user response: {user_response}")

    # Pending question'ı temizle
    return {
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None  # İşlendi, temizle
    }


# =============================================================================
# HITL QUESTION TEMPLATES
# =============================================================================

class HITLQuestions:
    """Önceden tanımlı HITL soru şablonları."""

    @staticmethod
    def table_ambiguity(tables: List[str]) -> Dict[str, Any]:
        """
        Tablo belirsizliği sorusu.

        Args:
            tables: Olası tablo isimleri

        Returns:
            Clarification request
        """
        return create_clarification_request(
            question="Hangi tabloyu kullanmak istiyorsunuz?",
            options=tables + ["Hepsini birleştir"],
            context="Birden fazla uygun tablo bulundu."
        )

    @staticmethod
    def filter_value_ambiguity(
        column: str,
        possible_values: List[str]
    ) -> Dict[str, Any]:
        """
        Filtre değeri belirsizliği sorusu.

        Args:
            column: Kolon adı
            possible_values: Olası değerler

        Returns:
            Clarification request
        """
        return create_clarification_request(
            question=f"'{column}' için hangi değeri kullanmak istiyorsunuz?",
            options=possible_values[:5],  # Max 5 seçenek
            context=f"'{column}' kolonu için birden fazla eşleşme bulundu."
        )

    @staticmethod
    def modification_type_unclear(
        current_context_summary: str
    ) -> Dict[str, Any]:
        """
        Modifikasyon tipi belirsiz.

        Args:
            current_context_summary: Mevcut context özeti

        Returns:
            Clarification request
        """
        return create_clarification_request(
            question="Mevcut sorguyu nasıl değiştirmek istiyorsunuz?",
            options=[
                "Filtre ekle",
                "Filtre çıkar",
                "Gruplama değiştir",
                "Sıralama değiştir",
                "Yeni sorgu başlat"
            ],
            context=f"Mevcut sorgu: {current_context_summary}"
        )

    @staticmethod
    def empty_result_recovery(
        previous_sql: str
    ) -> Dict[str, Any]:
        """
        Boş sonuç durumunda recovery sorusu.

        Args:
            previous_sql: Önceki SQL

        Returns:
            Clarification request
        """
        return create_clarification_request(
            question="Bu filtreyle veri bulunamadı. Ne yapmak istersiniz?",
            options=[
                "Önceki sorguya geri dön",
                "Filtreleri genişlet",
                "Yeni sorgu başlat"
            ],
            context="Son sorgu boş sonuç döndürdü."
        )

    @staticmethod
    def date_range_ambiguity() -> Dict[str, Any]:
        """Tarih aralığı belirsizliği."""
        return create_clarification_request(
            question="Hangi tarih aralığını kullanmak istiyorsunuz?",
            options=[
                "Son 7 gün",
                "Son 30 gün",
                "Bu ay",
                "Bu yıl",
                "Tüm zamanlar"
            ],
            context="Tarih filtresi belirlenmedi."
        )


# =============================================================================
# INTERRUPT UTILITIES
# =============================================================================

def format_interrupt_message(pending_question: PendingQuestion) -> str:
    """
    Kullanıcıya gösterilecek interrupt mesajını formatla.

    Args:
        pending_question: Bekleyen soru

    Returns:
        Formatlanmış mesaj
    """
    message_parts = [
        "❓ " + pending_question["question"],
        "",
        "Seçenekler:"
    ]

    for i, option in enumerate(pending_question["options"], 1):
        message_parts.append(f"  {i}. {option}")

    if pending_question.get("context"):
        message_parts.extend(["", f"ℹ️ {pending_question['context']}"])

    return "\n".join(message_parts)
