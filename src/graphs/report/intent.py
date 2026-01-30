"""
Intent Classifier for Report Agent

Kullanıcı mesajlarını analiz eder ve niyet tipini belirler.
Confidence score ile HITL kararı alınır.

Intent Types:
- NEW_QUERY: Yeni sorgu ("Satış raporu getir")
- MODIFY_FILTER: Filtre ekle/çıkar ("Sadece İstanbul olsun")
- MODIFY_AGGREGATION: Gruplama değiştir ("Aylık göster")
- ROLLBACK: Geri al ("Önceki hali göster")
- VISUALIZE: Görselleştirme değiştir ("Bar chart yap")
- CLARIFY: Detay iste ("Daha detaylı göster")
"""

import logging
from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from .state import ActiveQueryContext

logger = logging.getLogger(__name__)


# =============================================================================
# INTENT TYPES
# =============================================================================

class IntentType(str, Enum):
    """Kullanıcı niyet türleri."""

    # Yeni sorgu başlat
    NEW_QUERY = "new_query"

    # Mevcut sorguyu modifiye et
    MODIFY_FILTER = "modify_filter"         # Filtre ekle/çıkar
    MODIFY_AGGREGATION = "modify_aggregation"  # Gruplama değiştir
    MODIFY_COLUMNS = "modify_columns"       # Kolon ekle/çıkar
    MODIFY_ORDER = "modify_order"           # Sıralama değiştir

    # Görselleştirme
    VISUALIZE = "visualize"                 # Grafik tipi değiştir

    # Kontrol
    ROLLBACK = "rollback"                   # Önceki versiyona dön
    CLARIFY = "clarify"                     # Detay iste

    # Belirsiz
    UNKNOWN = "unknown"


# =============================================================================
# CLASSIFICATION RESULT
# =============================================================================

@dataclass
class IntentClassification:
    """Intent sınıflandırma sonucu."""

    intent_type: IntentType
    confidence: float                       # 0.0-1.0
    requires_clarification: bool            # True ise HITL gerekli
    clarification_question: Optional[str]   # Sorulacak soru
    clarification_options: Optional[List[str]]  # Seçenekler
    extracted_entities: Dict[str, Any]      # Çıkarılan entity'ler

    @property
    def is_modification(self) -> bool:
        """Mevcut sorguyu modifiye eden intent mi?"""
        return self.intent_type in {
            IntentType.MODIFY_FILTER,
            IntentType.MODIFY_AGGREGATION,
            IntentType.MODIFY_COLUMNS,
            IntentType.MODIFY_ORDER
        }

    @property
    def needs_active_context(self) -> bool:
        """Active context gerektirir mi?"""
        return self.is_modification or self.intent_type in {
            IntentType.ROLLBACK,
            IntentType.CLARIFY,
            IntentType.VISUALIZE
        }


# =============================================================================
# INTENT CLASSIFIER
# =============================================================================

# Prompt template for intent classification
INTENT_CLASSIFICATION_PROMPT = """Sen bir kullanıcı niyet analiz uzmanısın.

Kullanıcının mesajını analiz et ve aşağıdaki bilgileri JSON formatında döndür:
- intent_type: Niyet türü (aşağıdaki listeden)
- confidence: Güven skoru (0.0-1.0)
- requires_clarification: Belirsizlik var mı? (true/false)
- clarification_question: Varsa sorulacak soru
- extracted_entities: Mesajdan çıkarılan bilgiler

Niyet Türleri:
- new_query: Yeni bir rapor/sorgu isteği ("Satış raporu getir", "Müşterileri listele")
- modify_filter: Filtre ekleme/çıkarma ("Sadece İstanbul", "2024 yılı için")
- modify_aggregation: Gruplama değişikliği ("Aylık göster", "Şehir bazlı")
- modify_columns: Kolon değişikliği ("Buna müşteri adı da ekle")
- modify_order: Sıralama değişikliği ("Büyükten küçüğe sırala")
- visualize: Görselleştirme değişikliği ("Bar chart yap", "Pasta grafik göster")
- rollback: Geri alma ("Önceki hali", "Geri al")
- clarify: Detay isteme ("Daha detaylı", "Açıkla")
- unknown: Belirsiz/anlaşılamayan

{context_info}

Kullanıcı mesajı: {user_message}

Son mesaj geçmişi:
{message_history}

JSON formatında yanıt ver (sadece JSON, başka bir şey yazma):"""


class IntentClassifier:
    """
    LLM-based intent classifier.

    Kullanıcı mesajlarını analiz eder, niyet tipini ve confidence score'u belirler.
    """

    # Confidence threshold for HITL
    CONFIDENCE_THRESHOLD = 0.75

    def __init__(self, llm: BaseChatModel):
        """
        Initialize intent classifier.

        Args:
            llm: Chat model for classification
        """
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_template(INTENT_CLASSIFICATION_PROMPT)

    async def classify(
        self,
        user_message: str,
        messages: List[BaseMessage],
        active_context: Optional[ActiveQueryContext] = None
    ) -> IntentClassification:
        """
        Kullanıcı mesajını sınıflandır.

        Args:
            user_message: Kullanıcının son mesajı
            messages: Mesaj geçmişi
            active_context: Mevcut sorgu bağlamı (varsa)

        Returns:
            IntentClassification result
        """
        try:
            # Context info hazırla
            context_info = self._format_context_info(active_context)

            # Son 3 mesajı al
            message_history = self._format_message_history(messages, limit=3)

            # Prompt oluştur
            formatted_prompt = self.prompt.format(
                context_info=context_info,
                user_message=user_message,
                message_history=message_history
            )

            # LLM çağır
            response = await self.llm.ainvoke(formatted_prompt)
            result = self._parse_response(response.content)

            logger.info(f"Intent classified: {result.intent_type} (confidence: {result.confidence})")
            return result

        except Exception as e:
            logger.error(f"Intent classification error: {e}")
            # Fallback to unknown with low confidence
            return IntentClassification(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                requires_clarification=True,
                clarification_question="Ne yapmak istediğinizi anlayamadım. Lütfen daha açık belirtir misiniz?",
                clarification_options=["Yeni rapor oluştur", "Mevcut raporu değiştir", "Geri al"],
                extracted_entities={}
            )

    def _format_context_info(self, context: Optional[ActiveQueryContext]) -> str:
        """Active context bilgisini formatla."""
        if not context:
            return "Aktif sorgu bağlamı: YOK (yeni oturum)"

        return f"""Aktif Sorgu Bağlamı:
- Tablo: {context.get('current_table', 'Bilinmiyor')}
- SQL: {context.get('current_sql', 'Yok')[:200]}...
- Filtreler: {context.get('applied_filters', [])}
- Gruplama: {context.get('grouping_columns', [])}
- Sonuç sayısı: {context.get('result_row_count', 0)} satır"""

    def _format_message_history(self, messages: List[BaseMessage], limit: int = 3) -> str:
        """Son N mesajı formatla."""
        if not messages:
            return "Mesaj geçmişi yok"

        recent = messages[-limit:] if len(messages) > limit else messages
        history_lines = []

        for msg in recent:
            role = "Kullanıcı" if isinstance(msg, HumanMessage) else "Asistan"
            content = str(msg.content)[:100]
            history_lines.append(f"- {role}: {content}...")

        return "\n".join(history_lines)

    def _parse_response(self, response: str) -> IntentClassification:
        """LLM yanıtını parse et."""
        import json

        try:
            # JSON extract et
            response = response.strip()
            if response.startswith("```"):
                # Code block içindeyse çıkar
                lines = response.split("\n")
                json_lines = [l for l in lines if not l.startswith("```")]
                response = "\n".join(json_lines)

            data = json.loads(response)

            # Intent type parse et
            intent_str = data.get("intent_type", "unknown")
            try:
                intent_type = IntentType(intent_str)
            except ValueError:
                intent_type = IntentType.UNKNOWN

            confidence = float(data.get("confidence", 0.5))
            requires_clarification = data.get("requires_clarification", confidence < self.CONFIDENCE_THRESHOLD)

            return IntentClassification(
                intent_type=intent_type,
                confidence=confidence,
                requires_clarification=requires_clarification,
                clarification_question=data.get("clarification_question"),
                clarification_options=data.get("clarification_options"),
                extracted_entities=data.get("extracted_entities", {})
            )

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}. Response: {response[:200]}")
            return IntentClassification(
                intent_type=IntentType.UNKNOWN,
                confidence=0.3,
                requires_clarification=True,
                clarification_question="İsteğinizi tam anlayamadım. Daha açık belirtir misiniz?",
                clarification_options=None,
                extracted_entities={}
            )


# =============================================================================
# SIMPLE RULE-BASED CLASSIFIER (Fallback / Fast path)
# =============================================================================

class SimpleIntentClassifier:
    """
    Kural tabanlı basit intent classifier.

    LLM çağırmadan hızlı sınıflandırma yapar.
    Belirsiz durumlarda LLM classifier'a yönlendirir.
    """

    # Keyword patterns
    PATTERNS = {
        IntentType.NEW_QUERY: [
            "rapor", "listele", "göster", "getir", "bul", "ara",
            "kaç tane", "ne kadar", "toplam"
        ],
        IntentType.MODIFY_FILTER: [
            "sadece", "için", "filtrele", "hariç", "dahil",
            "olan", "olmayan", "arasında", "büyük", "küçük"
        ],
        IntentType.MODIFY_AGGREGATION: [
            "bazlı", "bazında", "grupla", "aylık", "günlük",
            "yıllık", "haftalık", "toplam", "ortalama"
        ],
        IntentType.VISUALIZE: [
            "grafik", "chart", "bar", "pasta", "line", "çizgi",
            "görselleştir", "tablo"
        ],
        IntentType.ROLLBACK: [
            "geri", "önceki", "iptal", "undo", "vazgeç"
        ],
        IntentType.CLARIFY: [
            "detay", "açıkla", "ne demek", "nasıl"
        ]
    }

    def classify(
        self,
        user_message: str,
        has_active_context: bool = False
    ) -> IntentClassification:
        """
        Basit kural tabanlı sınıflandırma.

        Args:
            user_message: Kullanıcı mesajı
            has_active_context: Aktif context var mı?

        Returns:
            IntentClassification (düşük confidence, LLM verification gerekebilir)
        """
        message_lower = user_message.lower()
        scores: Dict[IntentType, int] = {}

        # Pattern matching
        for intent_type, patterns in self.PATTERNS.items():
            score = sum(1 for p in patterns if p in message_lower)
            if score > 0:
                scores[intent_type] = score

        if not scores:
            return IntentClassification(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                requires_clarification=True,
                clarification_question=None,
                clarification_options=None,
                extracted_entities={}
            )

        # En yüksek skoru al
        best_intent = max(scores, key=scores.get)
        max_score = scores[best_intent]

        # Confidence hesapla (basit: max 3 pattern match = 0.9)
        confidence = min(max_score * 0.3, 0.9)

        # Modification intent ama context yoksa düşük confidence
        modification_intents = {
            IntentType.MODIFY_FILTER,
            IntentType.MODIFY_AGGREGATION,
            IntentType.ROLLBACK
        }
        if best_intent in modification_intents and not has_active_context:
            confidence *= 0.5  # Yarıya düşür

        return IntentClassification(
            intent_type=best_intent,
            confidence=confidence,
            requires_clarification=confidence < 0.6,
            clarification_question=None,
            clarification_options=None,
            extracted_entities={}
        )
