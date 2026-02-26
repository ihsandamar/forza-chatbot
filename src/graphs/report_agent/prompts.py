from typing import Literal, Optional

from pydantic import BaseModel, field_validator


# =============================================================================
# PYDANTIC MODELS — Structured LLM Output
# =============================================================================

class IntentClassificationResult(BaseModel):
    """Intent + query type — tek LLM çağrısı ile sınıflandırma."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False           # Kullanıcı açıkça grafik/chart istedi mi?
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
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
  → use_result_type="new_query": Sonuçtaki bir entity için tamamen yeni sorgu oluştur
  → use_result_type="revisualize": Aynı veriyi farklı chart/format ile göster
  → use_result_type="compute": Sonuçlardaki sayısal kolonlar üzerinde matematiksel işlem yap (SQL gerekmez)
    compute_operation="sum"   → "toplamı", "topla", "toplam ne kadar"
    compute_operation="avg"   → "ortalaması", "ortalama al", "ortalama nedir"
    compute_operation="count" → "kaç tane", "kaç satır", "sayısı"
    compute_operation="min"   → "en düşük", "minimum", "en az"
    compute_operation="max"   → "en yüksek", "maksimum", "en fazla"
  → use_result_type="modify_context": Sonuçtaki entity'yi kullanarak mevcut SQL'i değiştir
    (ör: "bu ürün için şehirlere göre kır" → entity + active_sql'e GROUP BY/filtre ekle)
    DIKKAT: "new_query"dan farkı — entity zaten belli, sadece aktif sorgu değiştirilecek

**query_type:**
- SINGLE: Tek bir metrik veya toplam (ör: "toplam ciro nedir?", "kaç adisyon açıldı?")
- LISTING: Belirli bir boyut filtrelenip başka bir boyutun detayı listeleniyor
  (ör: "dürümler kategorisindeki ürünler", "Ankara şubesindeki satışlar", "paket servisteki kategoriler")
  → Bir boyut değer filtresi, diğer boyut GROUP BY
- RANKING: Sıralama / top-N / en fazla / en az
- COMPARISON: İki veya daha fazla grubun karşılaştırması
- TIME_SERIES_COMPARISON: SADECE dönemler ARASI karşılaştırma (periyodik kırılım veya iki dönem farkı)
  ✅ "bu yılı geçen yılla karşılaştır" → TIME_SERIES_COMPARISON
  ✅ "aylık satış trendi göster" → TIME_SERIES_COMPARISON (çok ay kırılımı)
  ✅ "her ay ne kadar satıldı" → TIME_SERIES_COMPARISON (periyodik kırılım)
  ❌ "son 1 yılda carilere göre ciro" → LISTING (tek dönem filtresi + boyut kırılımı)
  ❌ "geçen ay şubelere göre satışlar" → LISTING (tek dönem filtresi + boyut kırılımı)
  ❌ "bu yılın en çok satan ürünleri" → RANKING
  Kural: "son X [dönem]de [boyut]a göre" kalıbı = tarih filtresi + boyut GROUP BY = LISTING
         (sıralama/top-N istiyorsa RANKING, tarih+boyut kırılımı istiyorsa LISTING)
         Sorgu aylık/yıllık KIRILIM istiyorsa (GROUP BY YEAR + MONTH) = TIME_SERIES_COMPARISON

**wants_visualization:**
- True: Kullanıcı açıkça grafik/görsel talep ediyor
  → "grafik", "chart", "çizgi grafik", "bar", "pasta", "görselleştir", "diyagram", "şekil olarak göster" gibi ifadeler içeriyorsa
  → use_result_type="revisualize" ise HER ZAMAN True
  → Hem sorgu hem grafik istiyorsa (ör: "satışları bar chart olarak göster") True
- False: Sadece veri/tablo istiyor, grafik talep etmiyor (DEFAULT)
  → "şube satışları nedir?", "top 10 ürün" gibi salt veri sorguları → False

**confidence:** 0.0-1.0 güven skoru.
- 0.90+: Kesin
- 0.70-0.90: Makul tahmin
- 0.70 altı: Belirsiz → kullanıcıya sor

⚠️ ALAN KISITLAMASI: `use_result_type` ve `compute_operation` alanları YALNIZCA intent_type="USE_RESULT" olduğunda doldurulur. MODIFY_QUERY veya NEW_QUERY için bu alanlar boş (null) bırakılır.
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
⚠️ KESİNLİKLE: Mevcut SQL'i YENIDEN YAZMA. Sadece istenen kısmı değiştir. SELECT kolonları, FROM, tüm WHERE koşulları (değiştirilecek olanlar hariç), GROUP BY ve ORDER BY AYNEN korunur.

- Sadece istenilen değişikliği yap, SQL'in geri kalanını koru
- Tarih aralığı değişikliği: SADECE DATEADD/BETWEEN ifadesini güncelle — diğer WHERE koşulları, SELECT, GROUP BY, ORDER BY dokunulmaz
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
