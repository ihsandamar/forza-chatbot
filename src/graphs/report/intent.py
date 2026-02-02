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
- clarification_options: Varsa seçenekler listesi
- extracted_entities: Mesajdan çıkarılan bilgiler (filtreler, değerler vs.)
- modification_details: Eğer modify_* intent ise, ne tür değişiklik yapılacak

Niyet Türleri:
- new_query: Yeni bir rapor/sorgu isteği ("Satış raporu getir", "Müşterileri listele")
- modify_filter: Filtre ekleme/çıkarma ("Sadece İstanbul", "2024 yılı için", "Bunu da ekle")
- modify_aggregation: Gruplama değişikliği ("Aylık göster", "Şehir bazlı")
- modify_columns: Kolon değişikliği ("Buna müşteri adı da ekle")
- modify_order: Sıralama değişikliği ("Büyükten küçüğe sırala")
- visualize: Görselleştirme değişikliği ("Bar chart yap", "Pasta grafik göster")
- rollback: Geri alma ("Önceki hali", "Geri al")
- clarify: Detay isteme ("Daha detaylı", "Açıkla")
- unknown: Belirsiz/anlaşılamayan

## CONTEXT BİLGİSİ (Mevcut Sorgu Durumu)
{context_info}

## MODİFİKASYON TESPİTİ İÇİN KURALLAR

⚠️ ÖNEMLİ: Eğer aktif sorgu bağlamı VARSA, kullanıcı büyük ihtimalle MEVCUT sorguyu değiştirmek istiyor!

### Context-Referencing İfadeler (Önceki sonuca atıf):
Kullanıcı aşağıdaki ifadelerden BİRİNİ bile kullanıyorsa → %90 ihtimalle modify_filter:
- "burdaki", "buradaki", "bunun", "bunların", "şunun", "şunların"
- "bu kategorinin", "bu ürünlerin", "bu şubenin", "bu sonuçların"
- "peki", "peki bunun", "onun", "onların"
- "gösterdiğin", "verdiğin", "getirdiğin"
- "yukarıdaki", "önceki", "az önceki"

Bu ifadeler ÖNCEKI SONUCU REFERANS ALIYOR demektir!
→ intent = modify_filter
→ extracted_entities = {{"filter_action": "expand", "uses_context_reference": true}}
→ confidence = 0.9+

### Filtre Modifikasyonu (modify_filter):
Aktif context VARSA ve kullanıcı aşağıdakileri söylüyorsa:
- "Sadece X olsun", "Sadece X için" → filter_action: "add"
- "X ekle", "Buna X de ekle" → filter_action: "add"
- "X hariç", "X olmadan", "X çıkar" → filter_action: "remove"
- "Son X gün/ay/yıl" → filter_action: "add"

### Gruplama Değişikliği (modify_aggregation):
Aktif context VARSA:
- "X bazlı göster", "X bazında"
- "Aylık/günlük/yıllık göster"
- "Kategorilere göre"

### Sıralama Değişikliği (modify_order):
- "Büyükten küçüğe", "En çoktan en aza"
- "Alfabetik sırala", "Ters sırala"

### Kolon Ekleme (modify_columns):
- "X kolonunu da ekle"
- "Bunda X de göster"

### YENİ SORGU (new_query):
Sadece aktif context YOKSA veya kullanıcı açıkça yeni bir konu başlatıyorsa:
- "X raporu getir", "Y listele" (tamamen farklı konu)
- "Yeni rapor", "Başka bir şey"

## KARAR MATRİSİ

| Durum | Aktif Context? | Kullanıcı İfadesi | Intent |
|-------|---------------|-------------------|--------|
| Yeni rapor | Yok | "Satış raporu getir" | new_query |
| Yeni rapor | Var | "Müşteri listesini göster" (farklı konu) | new_query |
| Modifikasyon | Var | "Sadece İstanbul" | modify_filter |
| Modifikasyon | Var | "Aylık göster" | modify_aggregation |
| Modifikasyon | Yok | "Sadece İstanbul" | new_query (context yok!) |

## EXTRACTED_ENTITIES FORMATI (modify_filter için)

Eğer intent modify_filter ise, extracted_entities şöyle olmalı:
{{
  "filter_action": "add" | "remove" | "replace",
  "filter_column": "Tespit edilen kolon (örn: BranchCityName)",
  "filter_value": "Tespit edilen değer (örn: İstanbul)",
  "filter_operator": "=" | "!=" | ">" | "<" | "LIKE"
}}

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
            return """Aktif Sorgu Bağlamı: YOK (yeni oturum)

NOT: Aktif context olmadığında, kullanıcı "sadece X" veya "X ekle" dese bile
bu yeni bir sorgu olarak değerlendirilmelidir (modify değil)."""

        # Filtreleri okunabilir formata çevir
        filters = context.get('applied_filters', [])
        filter_text = ""
        if filters:
            filter_lines = []
            for f in filters:
                col = f.get('column', '')
                op = f.get('operator', '=')
                val = f.get('value', '')
                filter_lines.append(f"  • {col} {op} '{val}'")
            filter_text = "\n".join(filter_lines)
        else:
            filter_text = "  (Filtre yok)"

        # Gruplama
        grouping = context.get('grouping_columns', [])
        grouping_text = ", ".join(grouping) if grouping else "(Gruplama yok)"

        # Result sample
        result_sample = context.get('result_sample', [])
        sample_text = ""
        if result_sample:
            sample_lines = []
            for row in result_sample[:3]:
                sample_lines.append(f"  {row}")
            sample_text = "\n".join(sample_lines)
        else:
            sample_text = "  (Örnek sonuç yok)"

        return f"""🔵 Aktif Sorgu Bağlamı: VAR ✓

Mevcut Tablo: {context.get('current_table', 'Bilinmiyor')}

Mevcut SQL (kısaltılmış):
```sql
{context.get('current_sql', 'Yok')[:400]}
```

Uygulanan Filtreler:
{filter_text}

Gruplama: {grouping_text}

Son Sonuç: {context.get('result_row_count', 0)} satır (son {context.get('last_execution_time', 'bilinmeyen zaman')})

Örnek Sonuç Verisi (ilk 3 satır):
{sample_text}

⚠️ KRİTİK: Aktif context VAR - kullanıcı büyük ihtimalle MEVCUT sorguyu değiştirmek istiyor!

CONTEXT-AWARE İNTENT TESPİTİ:
1. Kullanıcı "burdaki", "bunun", "peki", "gösterdiğin" gibi REFERANS ifadeleri kullanıyorsa
   → %95 ihtimalle modify_filter (filter_action: expand, uses_context_reference: true)
   → confidence = 0.9+

2. Kullanıcı "sadece X", "X ekle", "X için" diyorsa
   → %90 ihtimalle modify_filter (filter_action: add)
   → confidence = 0.85+

3. Kullanıcı "aylık göster", "bazlı göster" diyorsa
   → %85 ihtimalle modify_aggregation
   → confidence = 0.8+

4. Kullanıcı tamamen FARKLI bir konu açıyorsa (örn: "Müşteri listesi" ama önceki sorgu satış ile ilgiliyse)
   → new_query
   → confidence = 0.7+

DEFAULT: Context varken belirsiz ifadeler → modify_filter olarak yorumla (conservative approach)"""

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
    Context-aware: Aktif context varken modification intent'lerini
    daha yüksek öncelikle tespit eder.
    """

    # Keyword patterns - öncelik sırasına göre
    PATTERNS = {
        IntentType.ROLLBACK: [
            "geri", "önceki", "iptal", "undo", "vazgeç", "geri al"
        ],
        IntentType.MODIFY_FILTER: [
            "sadece", "için", "filtrele", "hariç", "dahil",
            "olan", "olmayan", "arasında", "büyük", "küçük",
            "ekle", "çıkar", "kaldır", "bunu da"
        ],
        IntentType.MODIFY_AGGREGATION: [
            "bazlı", "bazında", "grupla", "aylık göster", "günlük göster",
            "yıllık göster", "haftalık göster", "gruplama"
        ],
        IntentType.MODIFY_ORDER: [
            "sırala", "büyükten küçüğe", "küçükten büyüğe",
            "en çoktan", "en azdan", "alfabetik"
        ],
        IntentType.VISUALIZE: [
            "grafik", "chart", "bar", "pasta", "line", "çizgi",
            "görselleştir"
        ],
        IntentType.CLARIFY: [
            "detay", "açıkla", "ne demek", "nasıl"
        ],
        IntentType.NEW_QUERY: [
            "rapor", "listele", "göster", "getir", "bul", "ara",
            "kaç tane", "ne kadar", "toplam"
        ]
    }

    # Context varken modification'ı tetikleyen ifadeler
    MODIFICATION_TRIGGERS = [
        "sadece", "için", "ekle", "çıkar", "hariç", "dahil",
        "bunu da", "şunu da", "de ekle", "da ekle",
        "olsun", "olmasın", "filtrele",
        "bazlı", "bazında", "göre göster"
    ]

    # Context-referencing ifadeler (önceki sorguya atıfta bulunan)
    CONTEXT_REFERENCE_TRIGGERS = [
        "burdaki", "buradaki", "bu kategorideki", "bu şubedeki",
        "bunun", "bunların", "şunun", "şunların",
        "bu ürünlerin", "bu kategorinin", "bu şubenin",
        "aynı", "aynısı", "aynısının", "aynı şekilde",
        "peki", "peki bu", "peki bunun", "onun", "onların",
        "yukarıdaki", "önceki sorgu", "az önce",
        "bunlar", "şunlar", "onlar", "bunlarda", "şunlarda",
        "bu sonuçların", "bu verilerin", "bu kayıtların",
        "gösterdiğin", "verdiğin", "getirdiğin",
        "az önceki", "önceki", "geçen sorgu"
    ]

    def classify(
        self,
        user_message: str,
        has_active_context: bool = False
    ) -> IntentClassification:
        """
        Basit kural tabanlı sınıflandırma.

        Context-aware: Aktif context varsa, modification ifadelerini
        daha yüksek öncelikle tespit eder.

        Args:
            user_message: Kullanıcı mesajı
            has_active_context: Aktif context var mı?

        Returns:
            IntentClassification
        """
        message_lower = user_message.lower()
        scores: Dict[IntentType, int] = {}
        extracted_entities: Dict[str, Any] = {}

        # Önce context-reference trigger'larını kontrol et (context varsa)
        # "burdaki ürünler", "bu kategorinin" gibi ifadeler
        if has_active_context:
            context_ref_score = sum(1 for t in self.CONTEXT_REFERENCE_TRIGGERS if t in message_lower)
            if context_ref_score > 0:
                # Context'e atıf var - bu bir detaylandırma/expansion sorgusu
                # Örn: "burdaki ürünlerin satış oranlarını ver"
                logger.info(f"[INTENT] Context reference detected: score={context_ref_score}")

                # Bu tür sorgular genelde NEW_QUERY gibi davranır ama context'i kullanır
                # MODIFY_FILTER olarak işaretleyip context injection yapalım
                scores[IntentType.MODIFY_FILTER] = context_ref_score + 3  # Yüksek öncelik

                extracted_entities["filter_action"] = "expand"  # Genişletme/detaylandırma
                extracted_entities["uses_context_reference"] = True

        # Sonra modification trigger'larını kontrol et (context varsa)
        if has_active_context:
            modification_score = sum(1 for t in self.MODIFICATION_TRIGGERS if t in message_lower)
            if modification_score > 0:
                # Modification tipi tespit et
                if any(t in message_lower for t in ["bazlı", "bazında", "göre göster", "aylık", "günlük"]):
                    scores[IntentType.MODIFY_AGGREGATION] = modification_score + 2
                elif any(t in message_lower for t in ["sırala", "büyükten", "küçükten"]):
                    scores[IntentType.MODIFY_ORDER] = modification_score + 2
                else:
                    # Eğer zaten context reference ile MODIFY_FILTER varsa, score'u artır
                    if IntentType.MODIFY_FILTER in scores:
                        scores[IntentType.MODIFY_FILTER] += modification_score
                    else:
                        scores[IntentType.MODIFY_FILTER] = modification_score + 2

                    # Filter entity extraction (basit)
                    extracted_entities["filter_action"] = extracted_entities.get("filter_action", "add")
                    if any(t in message_lower for t in ["hariç", "çıkar", "kaldır", "olmadan"]):
                        extracted_entities["filter_action"] = "remove"

                    # Değer tespiti (basit pattern matching)
                    # "sadece X" veya "X için" patternleri
                    import re
                    sadece_match = re.search(r"sadece\s+(\w+)", message_lower)
                    icin_match = re.search(r"(\w+)\s+için", message_lower)

                    if sadece_match:
                        extracted_entities["filter_value"] = sadece_match.group(1)
                    elif icin_match:
                        extracted_entities["filter_value"] = icin_match.group(1)

        # Öncelikli kontrol: "Grafiğe dönüştür" pattern'i (text2sql atlanacak)
        visualize_convert_keywords = [
            "grafiğe dönüştür", "grafik yap", "grafik göster", "chart yap",
            "çubuk grafik yap", "pasta grafik yap", "çizgi grafik yap",
            "bunu grafiğe", "bunu çubuk", "bunu pasta", "bunu çizgi"
        ]

        if has_active_context and any(kw in message_lower for kw in visualize_convert_keywords):
            # Context var + "grafiğe dönüştür" = VISUALIZE intent
            logger.info("[INTENT] Visualize convert detected (skip text2sql, go direct to viz)")
            return IntentClassification(
                intent_type=IntentType.VISUALIZE,
                confidence=0.95,
                requires_clarification=False,
                clarification_question=None,
                clarification_options=None,
                extracted_entities={"convert_to_chart": True}
            )

        # Pattern matching (normal flow)
        for intent_type, patterns in self.PATTERNS.items():
            score = sum(1 for p in patterns if p in message_lower)
            if score > 0:
                # Var olan score'a ekle (override etme)
                if intent_type in scores:
                    scores[intent_type] += score
                else:
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

        # Confidence hesapla
        # Context varken modification intent'leri daha güvenilir
        if has_active_context and best_intent in {IntentType.MODIFY_FILTER, IntentType.MODIFY_AGGREGATION, IntentType.MODIFY_ORDER}:
            confidence = min(max_score * 0.35, 0.95)  # Daha yüksek confidence
        else:
            confidence = min(max_score * 0.3, 0.9)

        # Modification intent ama context yoksa - NEW_QUERY'ye çevir
        modification_intents = {
            IntentType.MODIFY_FILTER,
            IntentType.MODIFY_AGGREGATION,
            IntentType.MODIFY_ORDER,
            IntentType.ROLLBACK
        }
        if best_intent in modification_intents and not has_active_context:
            # Context yoksa modification yapamazsın
            # NEW_QUERY'ye düşür veya clarification iste
            if IntentType.NEW_QUERY in scores:
                best_intent = IntentType.NEW_QUERY
                confidence = 0.6
            else:
                # Clarification iste
                return IntentClassification(
                    intent_type=IntentType.UNKNOWN,
                    confidence=0.3,
                    requires_clarification=True,
                    clarification_question="Henüz aktif bir sorgu yok. Yeni bir rapor oluşturmak ister misiniz?",
                    clarification_options=["Evet, yeni rapor oluştur", "Hayır"],
                    extracted_entities=extracted_entities
                )

        return IntentClassification(
            intent_type=best_intent,
            confidence=confidence,
            requires_clarification=confidence < 0.6,
            clarification_question=None,
            clarification_options=None,
            extracted_entities=extracted_entities
        )
