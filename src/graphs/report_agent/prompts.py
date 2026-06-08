from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator, model_validator


# =============================================================================
# PYDANTIC MODELS — Structured LLM Output
# =============================================================================

class IntentClassificationResult(BaseModel):
    """Intent + query type — tek LLM çağrısı ile sınıflandırma."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY", "INSIGHT_REQUEST"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap", "comparison", "turkey_map",
    ]] = None
    chart_x_hint: Optional[str] = None
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None
    time_breakdown: bool = False
    visualization_explicitly_set: bool = False  # kullanıcı grafik hakkında açıkça bir şey söyledi

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def clear_chart_hints_when_no_chart_type(self) -> "IntentClassificationResult":
        if self.chart_type is None:
            self.chart_x_hint = None
        return self


class ChartTypeResult(BaseModel):
    """Dedicated chart type detection — classify_intent ile paralel çalışır."""
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap",
    ]] = None


class ModificationHint(BaseModel):
    """modify_sql_node'un SQL'e gömdüğü bir filtre değerini tanımlar."""

    column: str          # DB kolon adı (örn: "CategoryName")
    embedded_value: str  # SQL'e yazılan birebir string (örn: "dürümler")


class FilterDelta(BaseModel):
    """Tek bir WHERE koşulu değişikliği."""

    column: str
    operator: Literal["=", "!=", "LIKE", "NOT LIKE", ">", "<", ">=", "<=", "BETWEEN"]
    value: str  # SQL-ready: "'Ankara'", "'%latte%'", "DATEADD(month,-1,GETDATE())"


class SqlDelta(BaseModel):
    """MODIFY_QUERY — LLM ne değişsin söyler, Python uygular."""

    add_filters:           List[FilterDelta] = []
    remove_filter_columns: List[str] = []
    change_limit:          Optional[int] = None
    change_orderby:        Optional[str] = None
    change_groupby:        Optional[str] = None
    change_select:         Optional[str] = None
    explanation:           str
    confidence:            float


class EntityExtractionResult(BaseModel):
    """USE_RESULT(A) — önceki result'tan entity çekip yeni sorgu seed'i oluşturur."""

    entity_names: List[str]   # Seçilen değerlerin tam adları — tekil için [tek_isim]
    entity_type: str           # product | branch | customer | category | period
    new_query_seed: str        # Text2SQL'e gönderilecek doğal dil sorgu cümlesi


class QueryClarificationResult(BaseModel):
    """VAGUE_QUERY — belirsiz sorgu için kullanıcıya öneriler üretir."""

    message: str            # kullanıcıya gösterilecek açıklama mesajı
    suggestions: List[str]  # 3-4 spesifik sorgu önerisi


# =============================================================================
# PROMPTS
# =============================================================================

CHART_TYPE_PROMPT = """Kullanıcı sorgusuna göre en uygun grafik tipini belirle.

Sorgu: {user_query}

## KURALLAR

Aşağıdaki öncelik sırasıyla karar ver:

1. Kullanıcı açıkça bir grafik tipi belirttiyse → o tipi döndür (typo toleranslı: "sunbrust"→sunburst, "hetmap"→heatmap)

2. Grafik tipi belirtilmemişse, sorgu yapısına göre:
   - Zaman + kategori/boyut karşılaştırması (hiyerarşik, çok boyutlu: "aylık kategoriler", "dönemsel kırılım") → sunburst
   - Hiyerarşik part-of-whole, zaman boyutu yok ("kategorilerin alt kırılımı", "grup içi dağılım") → treemap
   - Saf zaman serisi / trend (tek metrik: "aylık ciro", "günlük satış trendi") → line_chart
   - Kategoriler arası flat karşılaştırma ("en çok satan", "şubeleri karşılaştır") → bar_chart
   - Oran / pay / yüzdesel dağılım ("payı nedir", "yüzde dağılım") → pie_chart
   - İki boyutlu dağılım matrisi (entity × periyot: "saatlere göre günler") → heatmap
   - İki sayısal değişken korelasyonu ("X arttıkça Y") → scatter_chart

3. Grafik talebi belirsizse veya sadece veri/tablo isteniyorsa → null

Yalnızca chart_type alanını doldur. Açıklama yapma.
"""

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
  → MODIFY_QUERY SINIRI: Sadece filtre/sıralama/limit değişikliklerini kapsar.
    "Boyut pivot" (GROUP BY boyutunu tamamen değiştirme) MODIFY_QUERY DEĞİLDİR → NEW_QUERY seç.
    Boyut pivot örnekleri: "en çok sattığı gün hangisidir", "hangi ayda en fazla ciro var",
    "en yüksek satışın olduğu hafta", "hangi saatte en çok sipariş geliyor"
    Bu sorgularda "bu ürün/bu şube" gibi zamirler olsa bile → NEW_QUERY (bağlam K3 ile çözülür)
- VAGUE_QUERY: Sorgu çok genel/belirsiz — SQL'e çevrilemeyecek kadar spesifik değil
  → Dönem belirtmemiş, filtre/kırılım yok, ne istediği açık değil
  → Örnekler: "satış durumu nedir", "ciro", "durum ne", "satışlar nasıl"
  → DİKKAT: "toplam ciro nedir" VAGUE_QUERY DEĞİLDİR — net bir metrik istiyor (SINGLE)
  → DİKKAT: "son 1 aydaki satışlar" VAGUE_QUERY DEĞİLDİR — dönem + metrik belirli (NEW_QUERY)
  → NOT: VAGUE_QUERY seçersen sorgu clarifier tarafından daha net hale getirilecek.
    Emin değilsen VAGUE_QUERY seç — NEW_QUERY'ye zorlamaya çalışma.
- INSIGHT_REQUEST: Kullanıcı mevcut veriden içgörü, trend analizi, anomali veya aksiyon önerisi istiyor.
  Örnek: "nelere dikkat etmeliyim", "bu veriden ne çıkarabilirim", "hangi ürün/şube sorunlu", "insight ver", "analiz et"
  SADECE aktif sonuç varsa (has_active_sql=Evet) bu intent'i kullan.
  Aktif sonuç yoksa VAGUE_QUERY kullan.
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
- LISTING: Belirli bir boyut filtrelenip başka bir boyutun **sadece isimleri/öğeleri** listeleniyor — metrik/toplam hesaplanmıyor
  (ör: "dürümler kategorisindeki ürünler", "paket servisteki kategoriler", "Ankara'daki şubeler hangileri")
  → Bir boyut değer filtresi, diğer boyut GROUP BY, TOPLAM YOK — sadece eleman listesi
  ⚠️ "illere göre satış", "şubelere göre ciro" gibi metrik hesaplayan sorgular LISTING DEĞİL → RANKING
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
  ❌ "son 1 yılda carilere göre ciro" → RANKING (tarih filtresi + metrik toplam + boyut GROUP BY = sıralama)
  ❌ "geçen ay şubelere göre satışlar" → RANKING (tarih filtresi + metrik toplam + boyut GROUP BY = sıralama)
  ❌ "bu yılın en çok satan ürünleri" → RANKING
  KURAL 1: Sorgu aylık/yıllık/haftalık/günlük/saatlik KIRILIM istiyorsa → TIME_SERIES_COMPARISON
  KURAL 2: "X ve Y'yi [periyot] bazda karşılaştır" kalıbı → zaman granülaritesi + entity = TIME_SERIES_COMPARISON
  KURAL 3: "son X [dönem]de [boyut]a göre" kalıbı = tarih filtresi + boyut GROUP BY
    → Ciro/satış/tutar/adet gibi metrik hesaplanıyorsa → RANKING
    → Sadece isimleri listele ("hangi ürünler", "kimler") → LISTING

TIME_SERIES_COMPARISON ayrıca TOPLU DAĞILIM sorgularını da kapsar:
- "saate göre ciro dağılımı" → TIME_SERIES_COMPARISON (aggregate: hour_of_day)
- "haftanın günlerine göre satış" → TIME_SERIES_COMPARISON (aggregate: day_of_week)
- "ayın günlerine göre adet" → TIME_SERIES_COMPARISON (aggregate: day_of_month)

TIME_SERIES_COMPARISON ayrıca ZAMAN BOYUTU SUPERLATİF sorgularını kapsar (dimension pivot):
✅ "bu ürünün en çok sattığı gün hangisidir" → TIME_SERIES_COMPARISON (gün = zaman boyutu, GROUP BY gün)
✅ "hangi ayda en fazla ciro var" → TIME_SERIES_COMPARISON
✅ "en yüksek satışın olduğu hafta" → TIME_SERIES_COMPARISON
✅ "hangi saatte en çok sipariş geliyor" → TIME_SERIES_COMPARISON
KURAL: "X'in/hangi [GÜN/AY/HAFTA/SAAT] en çok/en az/en yüksek/en düşük" kalıbı = TIME_SERIES_COMPARISON
Bu sorgular MODIFY_QUERY DEĞİLDİR — GROUP BY boyutu tamamen değiştiğinden NEW_QUERY olarak işlenir.

⚠️ FARK: "günlük satışlar" = TIME_SERIES (trend), "haftanın günlerine göre" = TIME_SERIES (dağılım)
  İkisi de TIME_SERIES_COMPARISON. Ayrım text2sql katmanında time_granularity ile yapılır.

**wants_visualization:**
- True: Kullanıcı açıkça grafik/görsel talep ediyor
  → "grafik", "chart", "çizgi grafik", "bar", "pasta", "görselleştir", "diyagram", "şekil olarak göster", "heatmap", "ısı haritası", "sunburst", "treemap" gibi ifadeler içeriyorsa
  → use_result_type="revisualize" ise HER ZAMAN True
  → Hem sorgu hem grafik istiyorsa (ör: "satışları bar chart olarak göster") True
- False: Sadece veri/tablo istiyor, grafik talep etmiyor (DEFAULT)
  → "şube satışları nedir?", "top 10 ürün" gibi salt veri sorguları → False

**chart_type:** (SADECE wants_visualization=True olduğunda doldur, aksi halde null)
- Kullanıcı belirli bir grafik tipi belirtiyorsa tespit et:
  - "bar chart", "bar grafik", "çubuk grafik", "sütun grafik", "histogram" → "bar_chart"
  - "line chart", "çizgi grafik", "line grafik", "trend grafik" → "line_chart"
  - "pie chart", "pasta grafik", "pasta dilimi" → "pie_chart"
  - "scatter", "dağılım grafik" → "scatter_chart"
  - "heatmap", "ısı haritası" → "heatmap"
  - "sunburst", "sunbrust" (yazım hatası toleransı) → "sunburst"
  - "treemap", "tree map" → "treemap"
  - "karşılaştırma grafiği", "comparison chart" → "comparison"
- Kullanıcı grafik tipini belirtmiyorsa (sadece "grafik göster", "görselleştir") → null
- wants_visualization=False ise HER ZAMAN null

**chart_x_hint:** (SADECE chart_type dolu VE kullanıcı x-ekseninde hangi boyutu istediğini açıkça belirtiyorsa)
- Kullanıcı "X bazında", "X'e göre", "X kırılımında" gibi ifadelerle belirli bir boyut adı veriyorsa → o ismi yaz
- Belirtmiyorsa → null
- Örnekler:
  - "BranchName bazında bar chart yap" → "BranchName"
  - "kategorilere göre pasta grafik" → "CategoryName"
  - "ürün bazında çizgi grafik" → "ProductName"
  - "sadece bar chart yap" → null (kolon belirtilmemiş)
  - "satışları bar chart olarak göster" → null (boyut belirtilmemiş)

**visualization_explicitly_set:** (True/False)
- True: Kullanıcı bu mesajda grafik/görsel hakkında açıkça bir şey söyledi
  → "bar chart yap", "pasta grafik istiyorum", "grafiği kaldır", "tablo olarak göster",
     "görsel olarak göster", "grafik istemiyorum", "sadece sayıları göster"
- False (DEFAULT): Kullanıcı grafik/görsel hakkında hiçbir şey söylemedi
  → "Ankara'yı ekle", "limit'i 20 yap", "en çok satanları getir", "filtre ekle"
  → MODIFY_QUERY'nin büyük çoğunluğunda False olur — kullanıcı sadece veriyi değiştiriyor

**confidence:** 0.0-1.0 güven skoru.
- 0.90+: Kesin
- 0.70-0.90: Makul tahmin
- 0.70 altı: Belirsiz → kullanıcıya sor

⚠️ ALAN KISITLAMASI: `use_result_type` ve `compute_operation` alanları YALNIZCA intent_type="USE_RESULT" olduğunda doldurulur. MODIFY_QUERY veya NEW_QUERY için bu alanlar boş (null) bırakılır.

**time_breakdown:**
- True: Kullanıcı dönemsel kırılım istiyor — "aylık", "haftalık", "günlük", "yıllık" ifadeleri var
- False: Dönemsel kırılım YOK (salt zaman filtresi veya zaman yok)
"""

SQL_MODIFIER_PROMPT = """Kullanıcının isteğini anlayıp SADECE ne değişmesi gerektiğini SqlDelta formatında döndür.
SQL yazmana gerek yok — değişiklikleri struct olarak belirt, Python uygulayacak.

## MEVCUT SQL
{active_sql}

## AKTİF BAĞLAM
{query_context}

Aktif filtreler zaten SQL'de var — bunları add_filters'a EKLEME.
Sadece kullanıcının talep ettiği YENİ değişiklikleri yaz.

## KULLANICI İSTEĞİ
{modification_request}

## KOLON BİLGİLERİ
{column_metadata}

## KURALLAR

⚠️ add_filters: Kullanıcı yeni bir filtre ekliyorsa (ör: "Ankara şubesi için"):
  column = DB kolon adı ("BranchName"), operator = "=", value = SQL-ready string ("'Ankara'")

⚠️ remove_filter_columns: Kullanıcı mevcut filtreyi kaldırıyorsa sadece kolon adını listele.
  AKTİF BAĞLAM'da gösterilmeyen filtreleri kaldırma — onlar SQL'de zaten yok.

⚠️ change_select: SADECE yapısal değişiklikler için (farklı GROUP BY, zaman kırılımı).
  Örnek — "aylık kır": change_select="DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS Total"

⚠️ TARİH DEĞERİ: add_filters ile tarih eklerken SQL-ready date string kullan.
  CAST EKLEMENİ GEREKMEZ — Python otomatik ekler.
  Örnek: value="'2024-01-01'" veya value="DATEADD(month,-1,GETDATE())"

⚠️ LIKE: Kısmi arama için her zaman % wildcard kullan. Örnek: value="'%LATTE%'"

⚠️ SONUÇ REFERANSI: "bu ürün", "bu şube" → AKTİF BAĞLAM'daki gerçek değeri kullan.
  Bağlamda ProductName: ["Latte", "Espresso"] varsa "bu ürün" → value="'Latte'"

⚠️ change_groupby ile boyut değişikliği: Orijinal SQL'de YEAR/MONTH gibi zaman ifadeleri varsa
  BUNLARI KORU, sadece entity boyutunu değiştir. Çizgi grafik + orijinal SQL'de aylık GROUP BY varsa
  change_groupby ve change_select'e hem yeni boyutu hem zaman ifadesini yaz.
  Örnek: "şubelere göre kır" + GROUP BY'da ay ifadesi var →
    change_groupby="[BranchName], CONCAT(YEAR([DocumentDate]), '-', RIGHT('0' + CAST(MONTH([DocumentDate]) AS VARCHAR), 2))"
    change_select="[BranchName], CONCAT(YEAR([DocumentDate]), '-', RIGHT('0' + CAST(MONTH([DocumentDate]) AS VARCHAR), 2)) AS [Ay], SUM([RowAmount]) AS [ToplamCiro]"

## CONFIDENCE
- 1.0: İstek açık, referanslar net
- 0.7-0.9: Küçük belirsizlikler var
- 0.5-0.7: Referans belirsiz
- <0.5: Ne istendiği çözülemedi — interrupt tetiklenecek
"""

ENTITY_EXTRACTOR_PROMPT = """Kullanıcı önceki sorgu sonuçlarından bir veya daha fazla entity seçmek istiyor.

## ÖNCEKİ SONUÇLAR (ilk 5 satır)
{active_results}

## KONUŞMA BAĞLAMI (önceki turlardaki değerler dahil)
{accumulated_context}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının hangi entity'leri seçtiğini belirle ve yeni bir sorgu için seed oluştur.

Kullanıcı "bu 3 ürün", "bu şubeler", "bunların hepsi" gibi çoğul referans kullanıyorsa →
ÖNCEKİ SONUÇLAR ve KONUŞMA BAĞLAMI'ndaki TÜM ilgili değerleri entity_names listesine ekle.

- entity_names: Seçilen değerlerin tam adları listesi
  Tekil referans için tek elemanlı liste: ["Ankara Şubesi"]
  Çoğul referans için tüm seçilenleri listele: ["LATTE", "FINCAN CAY", "LAS VEGAS UC PEYNIRLI BAGEL"]
- entity_type: product | branch | customer | category | period
- new_query_seed: Bu entity'ler için doğal dil sorgu cümlesi (Text2SQL'e gönderilecek)
  Örnek: "LATTE, FINCAN CAY ve LAS VEGAS UC PEYNIRLI BAGEL ürünlerinin son 1 yıldaki günlük satış trendi çizgi grafik"
  ÖNEMLİ: Kullanıcının orijinal isteğindeki TÜM detayları (dönem, grafik tipi, kırılım) new_query_seed'e koru!

ÖNEMLİ: KONUŞMA BAĞLAMI'nda "Aktif filtreler" satırı varsa, coğrafi/kategorik filtreleri new_query_seed'e yansıt.
  BranchCityName='Kocaeli' → seed'e "Kocaeli'deki" ekle.
  CategoryName='Kahve' → seed'e "Kahve kategorisindeki" ekle.
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
