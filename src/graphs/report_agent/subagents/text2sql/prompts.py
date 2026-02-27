from typing import List, Literal, Optional

from pydantic import BaseModel


# =============================================================================
# PYDANTIC MODELS — business_rules_node LLM validation
# =============================================================================

class BusinessRulesValidationResult(BaseModel):
    """
    business_rules_node LLM validation için structured output.
    Vector store'dan gelen aday (non-default) kurallardan hangilerinin
    bu sorgu için gerçekten geçerli olduğuna karar verir.
    """
    applicable_rule_ids: List[str]
    """
    Kullanıcı sorgusuna açıkça uyan kural ID'leri.
    Emin olmadığın veya uymayan kuralları EKLEME.
    İki çelişen kural varsa (ör: kapali_masa + acik_masa) ve kullanıcı açıklamamışsa İKİSİ DE EKLEME.
    """
    reasoning: str
    """Kısa açıklama: hangi kuralları neden kabul/reddettim."""


class TermValidationResult(BaseModel):
    """
    term_validator_node LLM validation için structured output.
    TermVectorStore'dan gelen aday filter term'lerin hangilerinin
    kullanıcı tarafından gerçekten kastetildiğine karar verir.
    """
    approved_filter_ids: List[str]
    """
    Kullanıcının AÇIKÇA kastettiği filter term ID'leri.
    Emin olmadığın → EKLEME. False positive sonuçsuz sorgu demek.
    """
    reasoning: str
    """Kısa açıklama: hangi terimleri neden kabul/reddettim."""


# =============================================================================
# PYDANTIC MODELS — sql_architect node'unun structured output'u
# =============================================================================

class DateDescriptor(BaseModel):
    """
    LLM tarih niyetini yapısal olarak yazar; Python DATEADD/YEAR/CAST'e çevirir.

    Örnekler:
      "son 3 ay"  → type=relative, unit=month, amount=-3
      "bu yıl"    → type=current_period, period=year
      "15 ocak"   → type=exact, value="{current_year}-01-15"
    """
    type: Literal["exact", "relative", "current_period"]
    unit:   Optional[Literal["day", "month", "year", "quarter"]] = None
    amount: Optional[int] = None    # Geçmiş: negatif, gelecek: pozitif
    period: Optional[Literal["day", "month", "year", "quarter"]] = None
    value:  Optional[str] = None    # "YYYY-MM-DD" formatı (exact için)


class SchemaFilter(BaseModel):
    """Tek bir WHERE koşulu."""
    column:           str       # Gerçek DB kolon adı (column_metadata'dan)
    operator:         Literal[
        "=", ">", "<", ">=", "<=", "!=",
        "LIKE", "IS NULL", "IS NOT NULL", "BETWEEN",
        "IN", "NOT IN"
    ]
    value:            Optional[str] = None           # String/sayı değer (tekli)
    values:           Optional[List[str]] = None     # IN/NOT IN için değer listesi
    date_descriptor:  Optional[DateDescriptor] = None  # Tarih filtresi ise bunu doldur
    value_hint:       Optional[str] = None           # Orijinal kullanıcı değeri (fuzzy için)
    logical_operator: Literal["AND", "OR"] = "AND"
    # value_resolver tarafından doldurulur:
    resolved_value:        Optional[str] = None
    resolution_confidence: Optional[float] = None


class SchemaAggregation(BaseModel):
    """Tek bir aggregation ifadesi."""
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    column:   str    # Gerçek DB kolon adı
    alias:    str    # Sonuç kolon alias'ı (ör: "ToplamCiro")


class QuerySchema(BaseModel):
    """
    sql_architect node'unun structured output'u.
    Tüm alanlar gerçek DB kolon adları içerir — Python bu şemadan SQL üretir.
    Business rules Python tarafından otomatik uygulanır (LLM seçmez).
    """
    description:        str
    select_columns:     List[str]
    filters:            List[SchemaFilter]
    aggregations:       List[SchemaAggregation]
    group_by:             List[str]
    time_granularity:     Optional[Literal["hourly", "daily", "weekly", "monthly", "yearly"]] = None
    comparison_dimension: Optional[str] = None   # DB kolon adı: "ProductName", "BranchName" vb.
    order_by_column:      Optional[str] = None
    order_by_direction:   Literal["ASC", "DESC"] = "DESC"
    limit:                Optional[int] = None
    # applied_rule_ids KALDIRILDI — Python auto_rules'dan uygular


# =============================================================================
# TERM VALIDATOR PROMPT — Parallel LLM gate for filter term validation
# =============================================================================

TERM_VALIDATOR_PROMPT = """Sen bir filtre terimi doğrulayıcısısın. Kullanıcı sorgusunu analiz et ve ADAY FİLTRE TERİMLERİ'nden hangilerinin kullanıcı tarafından AÇIKÇA kastetildiğini belirle.

## KULLANICI SORUSU
{user_query}

## ADAY FİLTRE TERİMLERİ (TermVectorStore semantic eşleşmesi)
{candidate_filters}

---

## KARAR KRİTERLERİ

**Filtre ONAYLANIR eğer:**
- Kullanıcı o kavramı sorguda AÇIKÇA belirtmişse
- Örnek: "sadece iade satışları göster" → filter_return ONAY ✓
- Örnek: "ikram edilen ürünler ne kadar?" → filter_treat ONAY ✓
- Örnek: "iade hariç ciro" → filter_return ONAY ✓ (iade açıkça geçiyor)

**Filtre REDDEDİLİR eğer:**
- Kullanıcı o kavramı hiç belirtmemişse — yalnızca semantik benzerlik var
- Örnek: "ödemesi alınan masalarda ciro" → filter_return RED ✗ ("iade" kelimesi geçmiyor)
- Örnek: "hangi ürün en çok sattı" → filter_treat RED ✗ ("ikram" geçmiyor)
- Örnek: "son 1 yılda satışlar" → filter_return RED ✗ (genel satış sorusu)

approved_filter_ids'e sadece kullanıcının gerçekten kastettiği ID'leri yaz.
Emin olmadığında → listeye EKLEME (false positive sonuçsuz sorgu demek).
"""


# =============================================================================
# PROMPT
# =============================================================================

SQL_ARCHITECT_PROMPT = """Sen bir T-SQL sorgu mimarısın. Kullanıcı sorusunu analiz et ve yapılandırılmış bir sorgu şeması (QuerySchema) üret.

## SORGUDA TESPİT EDİLEN İŞ TERİMLERİ (Doğrudan Uygula)
{term_hints}

## BUGÜNÜN TARİHİ
- Tarih: {today_date}
- Yıl: {current_year}
- Ay: {current_month}
- Çeyrek: {current_quarter}

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## VERİTABANI KOLON BİLGİLERİ
{column_metadata}

## KONUŞMA BAĞLAMI
{conversation_context}

## ÖNCEKİ SQL HATASI (varsa — şemayı buna göre düzelt)
{sql_error}

---

## KURALLAR

### KURAL 0 — Terim Eşleştirmeleri (EN YÜKSEK ÖNCELİK)
term_hints iki bölümden oluşabilir:

**"PYTHON-YÖNETİMLİ FİLTRELER" bölümü (varsa):**
Bu kolonları filters'a ASLA EKLEME. Python garantili olarak WHERE'e eklenecek.
Sen tekrar eklersen çelişki yaratırsın.

**"KOLON İPUÇLARI" bölümü (varsa):**
Bu eşleştirmeleri MUTLAKA aggregations ve group_by kararlarında kullan.
"KULLANICI METRİK KOLON SEÇİMİ" varsa o kolon ZORUNLU OLARAK tüm aggregations'larda kullanılmalıdır.

### KURAL 1 — Kolon Adları + Boyut Eşleştirme
SADECE yukarıdaki KOLON BİLGİLERİ'ndeki gerçek DB adlarını kullan.

"...lere/e göre" boyut → DB kolon eşleştirme rehberi (group_by için):
  "carilere göre" / "müşterilere göre" / "cari bazında" → [CustomerName]
  "şubelere göre" / "şube bazında"                      → [BranchName]
  "şehirlere göre" / "il bazında"                       → [BranchCityName]
  "kategorilere göre" / "kategori bazında"               → [CategoryName]
  "ürünlere göre" / "ürün bazında"                       → [ProductName]
  "kasiyerlere göre" / "kasiyer bazında"                 → [CashierName]
  "masalara göre" / "masa bazında"                       → [TableNo]

⚠️ "cari" = müşteri = CustomerName. Asla BranchCityName veya BranchName seçme.
Kolon DEĞER yazarken asla Türkçe kullanma: value_hint/resolved_value alanlarda "tarih", "tutar" gibi Türkçe yazma — gerçek DB değerlerini yaz.

### KURAL 1.5 — DocumentId GROUP BY: SADECE Adisyon Bazı Listelemelerde
column_metadata'da DocumentId için "GROUP BY DocumentId kullan" notu görürsen:
  Bu not SADECE adisyon bazında kırılım listesi gerektiğinde geçerlidir.
  Toplam / özet metrik sorgularında group_by boş kalmalıdır.

YANLIŞ ❌ — grand total sorgusunda DocumentId GROUP BY:
  "Son 3 aydaki toplam ciro ne kadar?"
  → group_by: ["DocumentId"]   ← her adisyon için ayrı satır döner, yanlış!

DOĞRU ✅ — grand total → group_by boş:
  "Son 3 aydaki toplam ciro ne kadar?"
  → aggregations: [SUM(RowAmount) AS TotalCiro], group_by: [], select_columns: []

DOĞRU ✅ — adisyon listesi → group_by DocumentId:
  "Son 3 aydaki her adisyonun tutarı nedir?"
  → aggregations: [SUM(RowAmount) AS TotalCiro], group_by: ["DocumentId"]

Kural: kullanıcı gruplama boyutu belirtmediyse ve "toplam/özet" istiyorsa → group_by: []

### KURAL 2 — Tarih Filtreleri (DateDescriptor ZORUNLU)
Sorguda tarih ifadesi varsa ("son 3 ay", "bu yıl", "ocak 2024", "son 1 sene" gibi):
  date_descriptor alanını doldur — value alanını KULLANMA.

ÖNEMLİ: "sene" = "yıl" (Türkçe sinonim). İkisi de aynı DateDescriptor'ı üretir.

⚠️ date_descriptor SADECE gerçek tarih kolonu olan `DocumentDate`'e uygula.
   IsTableActive, Quantity, RowAmount gibi boolean/sayısal kolonlara date_descriptor ASLA koyma.
   Kullanıcı "son 1 yılda ödemesi alınan masalar" derse:
     - DocumentDate → date_descriptor (tarih filtresi) ✓
     - IsTableActive → value="0", operator="=" (boolean filtresi) ✓
     - IsTableActive → date_descriptor KULLANMA ✗

Örnekler:
  "son 3 ay"          → {{"type":"relative","unit":"month","amount":-3}},   operator: ">="
  "son 7 gün"         → {{"type":"relative","unit":"day","amount":-7}},     operator: ">="
  "son 1 yıl"         → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "son 1 sene"        → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "son 1 senede"      → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "son 2 yılda"       → {{"type":"relative","unit":"year","amount":-2}},    operator: ">="
  "bu yıl"            → {{"type":"current_period","period":"year"}},        operator: ">="
  "bu ay"             → {{"type":"current_period","period":"month"}},       operator: ">="
  "bugün"             → {{"type":"current_period","period":"day"}},         operator: ">="
  "bu çeyrek"         → {{"type":"current_period","period":"quarter"}},     operator: ">="
  "15 ocak"           → {{"type":"exact","value":"{current_year}-01-15"}},  operator: "="
  "ocak 2024"         → filter 1: {{"type":"exact","value":"2024-01-01"}}, operator: ">="
                      → filter 2: {{"type":"exact","value":"2024-01-31"}}, operator: "<=", logical_operator: "AND"

Tarih filtresi için value alanını KULLANMA — date_descriptor kullan.

### KURAL 3 — GROUP BY Zorunluluğu (KRİTİK)
Aggregation varsa:
  - select_columns: BOŞ bırak []
  - group_by: tüm non-aggregate kolonları ekle
  - aggregations: SUM/COUNT/AVG/MAX/MIN ile doldur

YANLIŞ ❌:
  select_columns=["ProductName"], aggregations=[SUM(Quantity)], group_by=[]

DOĞRU ✅:
  select_columns=[], aggregations=[SUM(Quantity) AS TotalQty], group_by=["ProductName"]

### KURAL 4 — RANKING Sorguları
"Top 10 / en çok / en az / sıralama" → limit + order_by_column + en az 1 aggregation ZORUNLU.

Limit değeri:
  - Soruda SAYI varsa → o sayıyı kullan: "en çok satan 10 ürün" → limit=10
  - Soruda SAYI YOK, TEKİL isim var → limit=1: "en çok satan ürün" → limit=1
  - "en çok ... kategorisi", "en az ... şube", "bir numaralı ürün" → limit=1
  - "top 5", "ilk 10", "en yüksek 3" → sayıyı kullan

Örnekler:
  "en çok satan 10 ürün"       → aggregations=[SUM(Quantity)], group_by=["ProductName"],
                                  order_by_column="TotalQty", order_by_direction="DESC", limit=10
  "en çok ciro yapan kategori" → aggregations=[SUM(RowAmount)], group_by=["CategoryName"],
                                  order_by_column="ToplamCiro", order_by_direction="DESC", limit=1
  "en az satan ürün"           → aggregations=[SUM(Quantity)], group_by=["ProductName"],
                                  order_by_column="TotalQty", order_by_direction="ASC", limit=1

### KURAL 4.5 — COMPARISON Sorguları (KRİTİK)
query_type = "COMPARISON" → Karşılaştırılan TÜM varlıklar dönmeli, limit ASLA 1 koyma.

**Temel karşılaştırma** — "A ve B'yi karşılaştır":
  - limit: ZORUNLU null/None — her varlık için 1 satır olmalı
  - WHERE: karşılaştırılan değerleri OR ile ekle (value_hint kullan)
  - GROUP BY: SADECE karşılaştırma boyutu (CategoryName, BranchName, vb.)
  - order_by_direction: DESC

DOĞRU ✅:
  "dürümler ve içecek kategorilerini karşılaştır"
  → filters: [{{column=CategoryName, value_hint="dürümler", logical_operator="AND"}},
               {{column=CategoryName, value_hint="içecek", logical_operator="OR"}}]
  → group_by: ["CategoryName"]
  → aggregations: [SUM(RowAmount) AS TotalSales]
  → limit: null, order_by_column: "TotalSales", order_by_direction: "DESC"

**Zaman bazlı karşılaştırma** — "A ve B'yi aylık/haftalık/yıllık karşılaştır":
  - GROUP BY: karşılaştırma boyutu + zaman boyutu (MUTLAKA İKİSİ BİRDEN!)
  - order_by_column: zaman kolonu (periyodik sıralama için — GROUP BY'da olmalı!)
  - Tarih filtresi belirtildiyse uygula; belirtilmediyse bu ayı (current_period=month) kullan
  - filters: karşılaştırılan değerler için OR kullan (AND değil — AND imkansız koşul üretir!)

DOĞRU ✅:
  "dürümler ve içecek kategorilerini aylık karşılaştır"
  → filters: [{{CategoryName="dürümler", OR}}, {{CategoryName="içecek"}}]
  → group_by: ["CategoryName", "YEAR(DocumentDate)", "MONTH(DocumentDate)"]
  → aggregations: [SUM(RowAmount) AS TotalSales]
  → limit: null, order_by_column: "YEAR(DocumentDate)", order_by_direction: "ASC"

DOĞRU ✅:
  "dürümler ve içecek kategorilerini haftalık karşılaştır"
  → filters: [{{CategoryName="dürümler", OR}}, {{CategoryName="içecek"}}]
  → group_by: ["CategoryName", "YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"]
  → aggregations: [SUM(RowAmount) AS TotalSales]
  → limit: null, order_by_column: "YEAR(DocumentDate)", order_by_direction: "ASC"

⚠️ KRİTİK HATA — ASLA YAPMA:
  "A ve B kategorisini karşılaştır"
  → filters: [{{CategoryName="A", AND}}, {{CategoryName="B", AND}}]  ← YANLIŞ! İmkansız koşul!
  DOĞRUSU: OR ile ekle VEYA operator="IN", values=["A", "B"] kullan

⚠️ limit=1 ASLA KOYMA — COMPARISON'da YASAK

### KURAL 4.8 — TIME_SERIES_COMPARISON: Semantik Alan Dolumu (KRİTİK)
query_type = "TIME_SERIES_COMPARISON" olduğunda MUTLAKA doldur:

**time_granularity** — Zaman granülaritesi (sadece bu değerlerden biri):
  "saatlik", "saat saat", "her saat"  → "hourly"
  "günlük", "her gün", "gün bazında" → "daily"
  "haftalık", "her hafta"             → "weekly"
  "aylık", "her ay", "ay bazında"    → "monthly"
  "yıllık", "her yıl", "yıl bazında" → "yearly"

**comparison_dimension** — Karşılaştırılan entity'nin DB kolon adı:
  "ürünleri", "ürünlere göre", "ürün bazında"         → "ProductName"
  "şubeleri", "şubelere göre", "şube bazında"          → "BranchName"
  "kategorileri", "kategorilere göre"                   → "CategoryName"
  "müşterileri", "carileri", "müşterilere göre"        → "CustomerName"
  "kasiyerleri", "kasiyerlere göre"                    → "CashierName"
  "şehirleri", "şehirlere göre", "şehir bazında"      → "BranchCityName"
  "kanalları", "kanallar bazında", "satış kanallarını" → "DocumentKindName"
  Eğer sadece zaman kırılımı istiyorsa (entity yok)   → null

**group_by** — Python bu alanları kullanarak inşa eder, SEN BOŞ BIRAKIP BIRAKMAMAN FARK ETMEZ.
  Ancak doldurursan Python ile çelişme: zaman ifadeleri Python ekler, ham DocumentDate KOYMA.

ÖRNEK ✅:
  "dürümler kategorisindeki ürünleri günlük ciro olarak karşılaştır"
  → time_granularity: "daily"
  → comparison_dimension: "ProductName"
  → filters: [CategoryName = "dürümler"]
  → group_by: []  veya ["ProductName", "CAST(DocumentDate AS DATE)"]

ÖRNEK ✅:
  "son 1 yılda aylık satış trendi"
  → time_granularity: "monthly"
  → comparison_dimension: null  (entity yok, sadece zaman kırılımı)
  → group_by: []  veya ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]

ÖRNEK ✅:
  "Ankara şubesindeki kategorileri haftalık karşılaştır"
  → time_granularity: "weekly"
  → comparison_dimension: "CategoryName"
  → filters: [BranchName = "Ankara"]

### KURAL 5 — Periyodik Gruplama
"günlük satışlar"   → group_by: ["CAST(DocumentDate AS DATE)"]
"haftalık satışlar" → group_by: ["YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"]  # İKİSİ BİRDEN!
"aylık satışlar"    → group_by: ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]
"yıllık satışlar"   → group_by: ["YEAR(DocumentDate)"]
"saatlik dağılım"   → group_by: ["CAST(DocumentDate AS DATE)", "Hour"]
Tarih kolonu adını column_metadata'dan al.
⚠️ order_by_column MUTLAKA group_by'da olan bir kolon olmalı — GROUP BY'da olmayan kolona ORDER BY KOYMAK YASAK!
⚠️ group_by'a ham DocumentDate (datetime) ASLA KOYMA — zaman granülaritesi varsa SADECE ifadeyi kullan:
   YANLIŞ ❌: group_by: ["CAST(DocumentDate AS DATE)", "DocumentDate"]  ← datetime çift sayar!
   DOĞRU ✅:  group_by: ["CAST(DocumentDate AS DATE)"]                  ← sadece DATE ifadesi

### KURAL 5.5 — Entity + Zaman Kombinasyonu (TIME_SERIES_COMPARISON ile entity kırılımı)
"X kategorisindeki/şubesindeki [entity]leri [periyot] bazında karşılaştır" kalıbı:
  - X → WHERE filtresi (value_hint kullan — filtre değeri, GROUP BY değil!)
  - [entity] → GROUP BY (karşılaştırma boyutu: ProductName, BranchName, vb.)
  - [periyot] → GROUP BY (zaman boyutu: CAST/YEAR+MONTH/vb.)
  - İKİSİ BİRDEN GROUP BY'da olmak ZORUNDA!

DOĞRU ✅:
  "dürümler kategorisindeki ürünleri günlük ciro olarak karşılaştır"
  → filters: [{{column=CategoryName, value_hint="dürümler"}}]
  → group_by: ["ProductName", "CAST(DocumentDate AS DATE)"]   ← entity + zaman
  → aggregations: [SUM(RowAmount) AS ToplamCiro]
  → order_by_column: "CAST(DocumentDate AS DATE)", order_by_direction: "ASC"

DOĞRU ✅:
  "Ankara şubesindeki kategorileri aylık karşılaştır"
  → filters: [{{column=BranchName, value_hint="Ankara"}}]
  → group_by: ["CategoryName", "YEAR(DocumentDate)", "MONTH(DocumentDate)"]
  → aggregations: [SUM(RowAmount) AS ToplamCiro]
  → order_by_column: "YEAR(DocumentDate)", order_by_direction: "ASC"

YANLIŞ ❌ — entity boyutunu unutma:
  "dürümler kategorisindeki ürünleri günlük karşılaştır"
  → group_by: ["CAST(DocumentDate AS DATE)"]   ← ProductName eksik!
  → group_by: ["CAST(DocumentDate AS DATE)", "DocumentDate"]  ← ham datetime çift sayar!

### KURAL 7 — LİSTELEME Sorguları (LISTING query_type) — KRİTİK
"[boyut_değeri] [boyut_adı]sindeki/ndaki [detay_boyutu]ların satışları/listesi" kalıbı:
  → [boyut_değeri] → WHERE filtresi (value_hint kullan — value_resolver çözecek)
  → [detay_boyutu] → GROUP BY

YANLIŞ ❌ — boyut değeri GROUP BY'a koyma:
  "dürümler kategorisindeki ürünlerin satışları"
  → group_by: ["CategoryName"]   ← YANLIŞ (CategoryName bir filtre değeri, gruplama boyutu değil)

DOĞRU ✅ — boyut değeri filtre, detay GROUP BY:
  "dürümler kategorisindeki ürünlerin satışları"
  → filters: column=CategoryName, operator="=", value_hint="dürümler"
  → group_by: ["ProductName"]
  → aggregations: [SUM(RowAmount) AS TotalSales]

Daha fazla örnek:
  "Ankara şubesindeki ürünlerin ciroları"
  → filters: column=BranchName, value_hint="Ankara"
  → group_by: ["ProductName"]

  "paket servisteki kategorilerin satış adetleri"
  → filters: column=DocumentKindName, value_hint="paket servis"
  → group_by: ["CategoryName"]

  "dürümler kategorisindeki ürünlerin bu yıl satışları"
  → filters: column=CategoryName, value_hint="dürümler"
           + column=DocumentDate, date_descriptor=current_period:year
  → group_by: ["ProductName"]

ÖNEMLİ: term_hints'te bir kolon için "group_by veya select kullan" yazıyorsa bile,
sorgudan o kolonun FİLTRE değeri olduğu anlaşılıyorsa filters'a koy, group_by'a KOYMA.

### KURAL 6 — Hata Düzeltme
ÖNCEKİ SQL HATASI varsa:
  - Hata mesajını analiz et
  - Yanlış kolon adı → column_metadata'dan doğrusunu bul
  - GROUP BY hatası → Kural 3'ü uygula
  - Syntax hatası → ilgili field'ı düzelt
"""


# =============================================================================
# SCHEMA VALIDATOR — Parallel second-opinion LLM
# =============================================================================

class SchemaValidationResult(BaseModel):
    """
    schema_validator node'unun structured output'u.

    sql_architect ile PARALLEL çalışır — architect çıktısını görmez.
    Sadece GROUP BY, filters, limit üzerine bağımsız karar verir.
    merge_schemas node'u iki LLM çıktısını birleştirir.
    """
    group_by: List[str] = []
    """Kullanıcının GERÇEKTEN gruplama istediği kolonlar.
    Yalnızca açıkça belirtilenleri ekle.
    Boş liste → 'architect'e bırak' anlamına gelir."""

    filters: List[SchemaFilter] = []
    """Kullanıcının belirttiği filtreler (tarihler dahil).
    Architect'in bulduklarını tekrarlamak sorun değil — merge dedup yapar."""

    limit: Optional[int] = None
    """Kaç sonuç isteniyor. None = architect'e bırak."""

    reasoning: str
    """Kısa açıklama: hangi kararları neden aldın."""


SCHEMA_VALIDATOR_PROMPT = """Sen bir T-SQL sorgu doğrulayıcısısın. Kullanıcı sorusunu analiz et ve SADECE şu üç boyutu belirle:
  1. GROUP BY — kullanıcı hangi kolonlara göre gruplamak istiyor?
  2. Filters — kullanıcının belirttiği WHERE filtreleri neler?
  3. Limit — kaç sonuç isteniyor?

## BUGÜNÜN TARİHİ
- Tarih: {today_date}
- Yıl: {current_year}, Ay: {current_month}, Çeyrek: {current_quarter}

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## VERİTABANI KOLON BİLGİLERİ
{column_metadata}

## TESPİT EDİLEN İŞ TERİMLERİ (term_resolver çıktısı)
{term_hints}

---

## KURAL 1 — GROUP BY DİSİPLİNİ (EN KRİTİK)
group_by listesine SADECE kullanıcının açıkça gruplama/listeleme istediği kolonları ekle.

YANLIŞ ❌ (kullanıcı sormadı):
  "kategorilere göre en çok ciro yapan kategori" → group_by: ["CategoryName", "TableNo", "BranchCityName"]

DOĞRU ✅ (sadece ne soruldu):
  "kategorilere göre en çok ciro yapan kategori" → group_by: ["CategoryName"]

"...lere/e göre" boyut → DB kolon eşleştirme (group_by için):
  "carilere göre" / "müşterilere göre" / "cari bazında" → [CustomerName]
  "şubelere göre" / "şube bazında"                      → [BranchName]
  "şehirlere göre" / "il bazında"                       → [BranchCityName]
  "kategorilere göre" / "kategori bazında"               → [CategoryName]
  "ürünlere göre" / "ürün bazında"                       → [ProductName]
  "kasiyerlere göre" / "kasiyer bazında"                 → [CashierName]
  "masalara göre" / "masa bazında"                       → [TableNo]

⚠️ "cari" = müşteri = CustomerName. Asla BranchCityName seçme.

## KURAL 1.5 — DocumentId GROUP BY YASAĞI (Toplam Metrik Sorgularda)
column_metadata'da "GROUP BY DocumentId kullan" notu olsa bile:
  Kullanıcı tek bir toplam/özet metrik istiyorsa → group_by: []  (DocumentId EKLEME)

YANLIŞ ❌:
  "Toplam ciro ne kadar?" / "Son 3 aydaki ciro" → group_by: ["DocumentId"]

DOĞRU ✅:
  "Toplam ciro ne kadar?" → group_by: []
  "Her adisyonun tutarı nedir?" → group_by: ["DocumentId"]

Filtre bağlamı vs. gruplama bağlamı:
  "masaların ödemesi alınan" → TableNo GROUP BY'a EKLEME (IsTableActive=0 filtresi)
  "masaya göre satışlar"    → TableNo GROUP BY'a EKLE ✓

Belirleyici kelimeler:
  "...e göre", "...lere göre", "...bazında", "...kırılımında" → GROUP BY
  "...nın/nin/ların/lerin X'i" → filtre, GROUP BY değil

## KURAL 6 — LİSTELEME: Boyut Değeri Filtre, Detay Boyutu GROUP BY
"[değer] [boyut]sindeki [detay]ların ..." kalıbında:
  → [değer] [boyut] = WHERE filtresi
  → [detay] = GROUP BY

YANLIŞ ❌:
  "dürümler kategorisindeki ürünlerin satışları"
  → group_by: ["CategoryName"]   ← CategoryName değer filtresidir, GROUP BY değil

DOĞRU ✅:
  "dürümler kategorisindeki ürünlerin satışları"
  → filters: column=CategoryName, value_hint="dürümler"  |  group_by: ["ProductName"]

  "Ankara şubesindeki kategorilerin satışları"
  → filters: column=BranchName, value_hint="Ankara"  |  group_by: ["CategoryName"]

term_hints'te "group_by veya select kullan" yazıyor olsa bile,
sorguda o kolona ait spesifik bir değer varsa ("dürümler", "Ankara" gibi) → filters'a koy.

## KURAL 2 — FİLTRELER (DateDescriptor ZORUNLU)
Tarih ifadelerinde DateDescriptor kullan, value alanını kullanma.

"sene" = "yıl" (sinonim).

⚠️ date_descriptor SADECE `DocumentDate` kolonuna uygula.
   IsTableActive boolean bir kolandır (0/1) — date_descriptor ASLA koyma.
   "son 1 yılda ödemesi alınan masalar" → DocumentDate'e date_descriptor, IsTableActive'e value="0" ✓

Örnekler:
  "son 1 yıl" / "son 1 sene" / "son 1 senede" → {{"type":"relative","unit":"year","amount":-1}}, operator: ">="
  "son 3 ay"   → {{"type":"relative","unit":"month","amount":-3}}, operator: ">="
  "bu yıl"     → {{"type":"current_period","period":"year"}},     operator: ">="
  "bu ay"      → {{"type":"current_period","period":"month"}},    operator: ">="

## KURAL 3 — LİMİT
  - Sorguda sayı varsa → o sayı: "top 10 ürün" → limit=10
  - TEKİL isim, sayı yok → limit=1: "en çok X yapan kategori" → limit=1
  - Belirsizse → limit=None (architect'e bırak)

## KURAL 3.5 — COMPARISON'da limit ASLA set etme
query_type = "COMPARISON" → limit: ZORUNLU None.
"A ve B'yi karşılaştır" → her iki varlık dönmeli, limit=1 birini gizler.
⚠️ COMPARISON sorgularında limit'i None bırak — istisnasız.

## KURAL 4 — IsTableActive
  "ödemesi alınan masalar", "kapalı masalar", "ödemesi alınan" → IsTableActive=0
  "açık masalar", "aktif masalar" → IsTableActive=1
  (Typo tolere et: "ödmesi alınan" da aynı anlama gelir)

## KURAL 5 — filters listesini SADE TUT
  - Sadece kullanıcının açıkça belirttiği filtreleri ekle
  - Gereksiz filtre EKLEME — merge_schemas dedup yapar, ama fazla filtre yanlış sonuç verir
  - term_hints'te "PYTHON-YÖNETİMLİ FİLTRELER" bölümünde listelenen kolonları filters'a EKLEME — KURAL 5.5'e bak

## KURAL 5.5 — Python-Managed Filtreler (KRİTİK)
term_hints'teki "PYTHON-YÖNETİMLİ FİLTRELER" bölümündeki kolonları
filters listene ASLA ekleme. Python zaten uygulayacak — sen ekleyince çelişki yaratır.

YANLIŞ ❌:
  term_hints: "PYTHON-YÖNETİMLİ FİLTRELER: DocumentTypeIsReturn = 1 (iade)"
  → filters: [{{column: DocumentTypeIsReturn, value: 1}}]   ← Python zaten ekliyor!

DOĞRU ✅:
  term_hints: "PYTHON-YÖNETİMLİ FİLTRELER: DocumentTypeIsReturn = 1 (iade)"
  → o kolonu filters listene EKLEME — Python hallediyor.
"""


# =============================================================================
# BUSINESS RULES VALIDATOR PROMPT
# =============================================================================

BUSINESS_RULES_VALIDATOR_PROMPT = """Kullanıcı sorgusunu analiz et. Aşağıdaki ADAY İŞ KURALLARI'ndan hangilerinin bu sorgu için GERÇEKTEN geçerli olduğuna karar ver.

## KULLANICI SORUSU
{user_query}

## ADAY İŞ KURALLARI (Bunlar vector search'ten geldi — hepsi uygulanmayabilir)
{candidate_rules}

---

## KARAR KRİTERLERİ

**Kural GEÇERLİDİR eğer:**
- Kullanıcı o kuralın konusunu (açık masa, kapalı masa, normal satış, ikram, vb.) AÇIKÇA belirtmişse
- Örnek: "kapalı masaların cirosu" → kapali_masa_filtre GEÇERLİ
- Örnek: "sadece normal satışlar" → sadece_normal_satis GEÇERLİ

**Kural GEÇERSİZDİR eğer:**
- Kullanıcı o kuralın konusundan HİÇ bahsetmemişse
- Örnek: "carilere göre ciro" → kullanıcı masa durumu belirtmedi → kapali_masa_filtre/acik_masa_filtre GEÇERSİZ

**ÇAKIŞMA KURALI (KRİTİK):**
- Aynı kolona çelişen iki kural (ör: IsTableActive=0 VE IsTableActive=1) ASLA ikisi birden uygulanmaz
- Kullanıcı hangisini istediğini açıkça belirtmemişse → İKİSİ DE applicable_rule_ids'e EKLEME

applicable_rule_ids'e sadece gerçekten geçerli olan kural ID'lerini yaz.
Emin olmadığında → listeye EKLEME (eksik kural, çelişen kuraldan iyidir).
"""
