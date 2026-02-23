from typing import Literal, Optional

from pydantic import BaseModel, field_validator


# =============================================================================
# PYDANTIC MODELS — Structured LLM Output
# =============================================================================

class IntentClassificationResult(BaseModel):
    """Intent + query type — tek LLM çağrısı ile sınıflandırma."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT"]
    query_type: Literal["SINGLE", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    use_result_type: Optional[Literal["new_query", "revisualize"]] = None
    modification_action: Optional[str] = None   # "add_filter" | "remove_filter" | "change_limit" | "change_order"
    modification_target: Optional[str] = None   # "şehir", "tarih", "limit"
    modification_value: Optional[str] = None    # "Ankara", "2024-01", "50"

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class SqlModificationResult(BaseModel):
    """MODIFY_QUERY — mevcut SQL üzerine delta uygular."""

    modified_sql: str
    explanation: str


class EntityExtractionResult(BaseModel):
    """USE_RESULT(A) — önceki result'tan entity çekip yeni sorgu seed'i oluşturur."""

    entity_name: str
    entity_type: str        # product | branch | customer | category | period
    new_query_seed: str     # Text2SQL subagent'a gönderilecek doğal dil sorgu


# =============================================================================
# PROMPTS
# =============================================================================

INTENT_CLASSIFIER_PROMPT = """Sen bir rapor asistanısın. Kullanıcının mesajını analiz edip intent'ini belirle.

## KONUŞMA GEÇMİŞİ
{conversation_history}

## KULLANICI MESAJI
{user_query}

## MEVCUT SORGU DURUMU
- Aktif SQL var mı: {has_active_sql}
- Son sonuç satır sayısı: {result_count}

## KURALLAR

**intent_type:**
- NEW_QUERY: Kullanıcı tamamen yeni bir sorgu istiyor, önceki bağlamla ilgisi yok
- MODIFY_QUERY: Önceki sorguyu değiştirmek istiyor (filtre ekle/çıkar, sırala, limitı değiştir)
  → Aktif SQL olmadan ASLA MODIFY_QUERY seçme
- USE_RESULT: Önceki SONUÇLARI kullanmak istiyor
  → use_result_type="new_query": Sonuçtaki bir entity için yeni sorgu oluştur
  → use_result_type="revisualize": Aynı veriyi farklı chart/format ile göster

**query_type:**
- SINGLE: Tek bir metrik veya liste sorgusu
- RANKING: Sıralama / top-N / en fazla / en az
- COMPARISON: İki veya daha fazla grubun karşılaştırması
- TIME_SERIES_COMPARISON: Dönemler arası karşılaştırma (ay/yıl/çeyrek)

**confidence:** 0.0-1.0 güven skoru.
- 0.90+: Kesin
- 0.70-0.90: Makul tahmin
- 0.70 altı: Belirsiz → kullanıcıya sor
"""

SQL_MODIFIER_PROMPT = """Mevcut SQL sorgusunu kullanıcının isteğine göre değiştir.

## MEVCUT SQL
{active_sql}

## AKTİF FİLTRELER
{active_filters}

## KULLANICI İSTEĞİ
{modification_request}

## KOLON BİLGİLERİ
{column_metadata}

## KURALLAR
- Sadece istenilen değişikliği yap, SQL'in geri kalanını koru
- Yeni filtre: WHERE clause'a ekle (varsa AND ile bağla)
- Limit değişikliği: sadece TOP N değerini güncelle
- Sıralama değişikliği: sadece ORDER BY clause'u güncelle
- Geçerli T-SQL (SQL Server) üret, syntax hatası olmasın
- explanation alanında ne değiştirdiğini kısaca açıkla
"""

ENTITY_EXTRACTOR_PROMPT = """Kullanıcı önceki sorgu sonuçlarından bir entity seçmek istiyor.

## ÖNCEKİ SONUÇLAR (ilk 5 satır)
{active_results}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının hangi entity'yi seçtiğini belirle ve yeni bir sorgu için seed oluştur.

- entity_name: Seçilen değerin tam adı (ör: "iPhone 15 Pro", "Ankara Şubesi", "2024-Q1")
- entity_type: product | branch | customer | category | period
- new_query_seed: Bu entity için doğal dil sorgu cümlesi (Text2SQL'e gönderilecek)
  Örnek: "iPhone 15 Pro'nun aylık satış detayları nedir?"
"""
