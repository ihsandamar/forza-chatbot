from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


# =============================================================================
# PYDANTIC MODELS — Structured LLM Output
# =============================================================================

class IntentClassificationResult(BaseModel):
    """Intent + query type — tek LLM çağrısı ile sınıflandırma."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
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


class ModificationHint(BaseModel):
    """modify_sql_node'un SQL'e gömdüğü bir filtre değerini tanımlar."""

    column: str          # DB kolon adı (örn: "CategoryName")
    embedded_value: str  # SQL'e yazılan birebir string (örn: "dürümler")


class SqlModificationResult(BaseModel):
    """MODIFY_QUERY — mevcut SQL üzerine delta uygular."""

    modified_sql: str
    explanation: str
    confidence: float       # 0.0-1.0: referans çözümleme ve değişiklik doğruluğuna güven
    modification_hints: List[ModificationHint] = []


class EntityExtractionResult(BaseModel):
    """USE_RESULT(A) — önceki result'tan entity çekip yeni sorgu seed'i oluşturur."""

    entity_name: str
    entity_type: str        # product | branch | customer | category | period
    new_query_seed: str     # Text2SQL subagent'a gönderilecek doğal dil sorgu


class QueryClarificationResult(BaseModel):
    """VAGUE_QUERY — belirsiz sorgu için kullanıcıya öneriler üretir."""

    message: str            # kullanıcıya gösterilecek açıklama mesajı
    suggestions: List[str]  # 3-4 spesifik sorgu önerisi


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
- VAGUE_QUERY: Sorgu çok genel/belirsiz — SQL'e çevrilemeyecek kadar spesifik değil
  → Dönem belirtmemiş, filtre/kırılım yok, ne istediği açık değil
  → Örnekler: "satış durumu nedir", "ciro", "durum ne", "satışlar nasıl"
  → DİKKAT: "toplam ciro nedir" VAGUE_QUERY DEĞİLDİR — net bir metrik istiyor (SINGLE)
  → DİKKAT: "son 1 aydaki satışlar" VAGUE_QUERY DEĞİLDİR — dönem + metrik belirli (NEW_QUERY)
  → SADECE gerçekten belirsiz, spesifik olmayan sorgularda VAGUE_QUERY seç
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
- COMPARISON: İki veya daha fazla grubun karşılaştırması — SADECE zaman granülaritesi (haftalık/aylık/günlük vb.) YOKSA
  ✅ "dürümler ve içecek kategorilerini karşılaştır" → COMPARISON (zaman kırılımı yok)
  ✅ "Ankara ve İstanbul şubelerini karşılaştır" → COMPARISON
  ❌ "dürümler ve içecek kategorilerini haftalık karşılaştır" → TIME_SERIES_COMPARISON (zaman granülaritesi var!)
- TIME_SERIES_COMPARISON: Dönemsel kırılım veya zaman granülaritesi olan karşılaştırma
  ✅ "bu yılı geçen yılla karşılaştır" → TIME_SERIES_COMPARISON
  ✅ "aylık satış trendi göster" → TIME_SERIES_COMPARISON (çok ay kırılımı)
  ✅ "her ay ne kadar satıldı" → TIME_SERIES_COMPARISON (periyodik kırılım)
  ✅ "dürümler ve hammade kategorilerini haftalık karşılaştır" → TIME_SERIES_COMPARISON (entity + haftalık = dönemsel kırılım!)
  ✅ "A ve B'yi aylık/günlük/saatlik/yıllık bazda karşılaştır" → TIME_SERIES_COMPARISON (entity + zaman granülaritesi)
  ❌ "son 1 yılda carilere göre ciro" → LISTING (tek dönem filtresi + boyut kırılımı)
  ❌ "geçen ay şubelere göre satışlar" → LISTING (tek dönem filtresi + boyut kırılımı)
  ❌ "bu yılın en çok satan ürünleri" → RANKING
  KURAL 1: Sorgu aylık/yıllık/haftalık/günlük/saatlik KIRILIM istiyorsa → TIME_SERIES_COMPARISON
  KURAL 2: "X ve Y'yi [periyot] bazda karşılaştır" kalıbı → zaman granülaritesi + entity = TIME_SERIES_COMPARISON
  KURAL 3: "son X [dönem]de [boyut]a göre" kalıbı = tarih filtresi + boyut GROUP BY = LISTING

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

## KONUŞMA GEÇMİŞİ
{conversation_context}

## MEVCUT SQL
{active_sql}

## AKTİF FİLTRELER
{active_filters}

## ÖNCEKİ SORGU SONUÇLARI (ilk 5 satır)
{active_results}

## KULLANICI İSTEĞİ
{modification_request}

## KOLON BİLGİLERİ
{column_metadata}

## KURALLAR
⚠️ KESİNLİKLE: Mümkün olduğunca mevcut SQL'in yapısını koru. Kullanıcı sadece filtre/tarih/limit değişikliği istiyorsa SELECT, GROUP BY, ORDER BY'a dokunma. Ancak kullanıcı farklı bir gruplama, farklı kolonlar veya farklı bir analiz perspektifi istiyorsa (ör: "haftanın gününe göre", "aylık kırılımda") yapısal değişiklik yapabilirsin — bu durumda WHERE koşullarını mümkün olduğunca koru.

- Kullanıcının isteğini TAMAMEN karşıla — birden fazla değişiklik isteniyorsa HEPSİNİ uygula
- Değişiklik gerektirmeyen kısımları koru (ör: sadece tarih değişiyorsa GROUP BY'a dokunma)
- Yeni filtre: WHERE clause'a ekle (varsa AND ile bağla)
- Limit değişikliği: sadece TOP N değerini güncelle
- Sıralama değişikliği: sadece ORDER BY clause'u güncelle
- Geçerli T-SQL (SQL Server) üret, syntax hatası olmasın
- explanation alanında ne değiştirdiğini kısaca açıkla

⚠️ TARİH KARŞILAŞTIRMA: DocumentDate datetime kolonudur (saat bilgisi içerir).
Belirli bir güne filtre koyarken ASLA `[DocumentDate] = '2026-02-15'` yazma — eşleşmez!
HER ZAMAN `CAST([DocumentDate] AS DATE) = '2026-02-15'` kullan.
Tarih aralığı için: `CAST([DocumentDate] AS DATE) BETWEEN '...' AND '...'` kullan.

⚠️ LIKE KULLANIMI: "İçeren", "geçen", "başlayan", "biten" gibi kısmi arama ifadelerinde LIKE operatörü kullanırken HER ZAMAN wildcard (%) kullan:
- "isminde X geçen" / "X içeren" → [ProductName] LIKE '%X%'
- ASLA [ProductName] LIKE 'X' yazma — bu sadece TAM EŞLEŞMEyi bulur, kısmi eşleşme YAPMAZ!
- Doğru: AND [ProductName] LIKE '%LATTE%'   (LATTE içeren tüm ürünler)
- Yanlış: AND [ProductName] LIKE 'LATTE'     (sadece tam olarak "LATTE" olanlar)

⚠️ SONUÇ REFERANSI: Kullanıcı "bu ürün", "o şube", "bu gün" gibi önceki sonuca veya konuşmaya referans veriyorsa:
1. KONUŞMA GEÇMİŞİ bölümündeki mesajlardan referansın ne olduğunu belirle (ör: "bu ürün" → AI yanıtında bahsedilen ürün adı)
2. ÖNCEKİ SORGU SONUÇLARI bölümündeki gerçek değerleri kullanarak SQL'e doğru filtre ekle
3. Sonuçlarda bir tarih değeri varsa ve kullanıcı "bu gün" diyorsa → o tarihi yaz, bugünün tarihini DEĞİL

⚠️ YAPISAL DEĞİŞİKLİK: Kullanıcı sorgunun yapısını değiştirmek istiyorsa (farklı GROUP BY, farklı SELECT kolonları, farklı aggregation),
SELECT/GROUP BY/ORDER BY'ı kullanıcının isteğine göre yeniden yaz. WHERE koşullarını mümkün olduğunca koru.

## CONFIDENCE
confidence alanına 0.0–1.0 arası bir değer ver:
- 1.0: İstek açık, referanslar net, değişiklik kesin doğru
- 0.7-0.9: İstek anlaşılıyor ama küçük belirsizlikler var (ör: "bu" neyi kastettiği %90 belli)
- 0.5-0.7: Referans belirsiz — "bu ürün" deniyor ama konuşmada birden fazla entity geçiyor
- <0.5: Ne istendiği veya referans çözülemedi

## MODIFICATION_HINTS
Kullanıcının yazdığı ve SQL'e literal olarak gömdüğün her STRING FİLTRE DEĞERİ için bir hint ver:
- column: hangi DB kolonunu kullandığın (örn: "CategoryName")
- embedded_value: SQL'e yazdığın BİREBİR string — büyük/küçük harf dahil (örn: "dürümler")

ÖNEMLİ KURALLAR:
- Sadece kullanıcı inputundan gelen STRING değerleri için hint ver
- Tarih ifadeleri (DATEADD, BETWEEN, '2024-01-01'), sayısal değerler (TOP 10) için hint VERME
- Kolon adları için hint VERME — sadece WHERE koşulundaki değerler
- Zaten çözülmüş değerler (active_filters içindeki resolved değerler) için hint VERME
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


QUERY_CLARIFICATION_PROMPT = """Kullanıcının sorgusu çok genel/belirsiz. Sorguyu netleştirmek için öneriler üret.

## KULLANICI SORGUSU
{user_query}

## MEVCUT VERİ KOLONLARI
{column_metadata}

## GÖREV
Kullanıcının ne istemiş olabileceğini tahmin et ve 3-4 SPESİFİK sorgu önerisi üret.

KURALLAR:
- Her öneri doğrudan SQL'e çevrilebilecek kadar spesifik olmalı
- Öneriler kullanıcının orijinal sorgusundaki konuyla ilgili olmalı
- Dönem, kırılım ve metrik içermeli (ör: "Son 1 ayın kategorilere göre satış cirosu")
- message alanında kullanıcıya kısa ve samimi bir açıklama yaz
- suggestions listesine 3-4 öneri koy
"""


class ComputeToolSelection(BaseModel):
    """LLM compute tool seçimi — hangi işlem, hangi kolon, hangi kolonlar gösterilsin."""

    tool: Literal["find_max", "find_min", "sum_column", "avg_column", "count_rows"]
    target_column: str                # işlem yapılacak sayısal kolon (e.g., "ToplamCiro")
    display_columns: List[str]        # sonuçta gösterilecek kolonlar (e.g., ["ProductName", "ToplamCiro"])


COMPUTE_TOOL_PROMPT = """Kullanıcı önceki sorgu sonuçları üzerinde bir hesaplama istiyor.

## MEVCUT SONUÇLAR (ilk 5 satır)
{active_results}

## KOLON BİLGİSİ
Sayısal kolonlar: {numeric_columns}
Metin kolonları: {text_columns}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının isteğine göre doğru tool'u seç:
- find_max: "en çok", "en yüksek", "en fazla", "maksimum", "birinci" → ilgili satırı bul
- find_min: "en az", "en düşük", "minimum", "sonuncu" → ilgili satırı bul
- sum_column: "topla", "toplam", "toplam ne kadar" → kolondaki tüm değerleri topla
- avg_column: "ortalama", "ortalama nedir" → kolondaki değerlerin ortalaması
- count_rows: "kaç tane", "kaç satır", "sayısı" → satır sayısı

## KURALLAR
- target_column: İşlem yapılacak sayısal kolon adını AYNEN yaz (büyük/küçük harf dahil)
- display_columns: Kullanıcının görmek isteyeceği kolonları seç
  → find_max/find_min: İlişkili metin kolonu + hedef sayısal kolon (ör: ["ProductName", "ToplamCiro"])
  → sum_column/avg_column: Sadece hedef kolon (ör: ["ToplamCiro"])
  → count_rows: Boş liste []
- Birden fazla sayısal kolon varsa, kullanıcının bahsettiği kolonu seç (ciro=amount, adet=quantity)
"""
