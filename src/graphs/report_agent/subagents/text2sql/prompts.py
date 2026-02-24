from typing import List, Literal, Optional

from pydantic import BaseModel


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
        "LIKE", "IS NULL", "IS NOT NULL", "BETWEEN"
    ]
    value:            Optional[str] = None           # String/sayı değer
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
    group_by:           List[str]
    order_by_column:    Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit:              Optional[int] = None
    # applied_rule_ids KALDIRILDI — Python auto_rules'dan uygular


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
"SORGUDA TESPİT EDİLEN İŞ TERİMLERİ" bölümündeki eşleştirmeleri MUTLAKA uygula.
Bu bölümdeki filtreler ve kolon seçimleri kesindir — column_metadata'dan bağımsız olarak geçerlidir.

### KURAL 1 — Kolon Adları
SADECE yukarıdaki KOLON BİLGİLERİ'ndeki gerçek DB adlarını kullan.
Kullanıcı "şube" derse → kolon açıklamalarına bak, doğru DB kolon adını yaz.
Hiçbir zaman "tarih", "şube", "tutar" gibi Türkçe field_hint yazma — gerçek DB adını yaz.

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

### KURAL 5 — Periyodik Gruplama
"günlük satışlar"  → group_by: ["CAST(TarihKolonu AS DATE)"]
"aylık satışlar"   → group_by: ["YEAR(TarihKolonu)", "MONTH(TarihKolonu)"]
"yıllık satışlar"  → group_by: ["YEAR(TarihKolonu)"]
"saatlik dağılım"  → group_by: ["CAST(TarihKolonu AS DATE)", "HourKolonu"]
Tarih kolonu adını column_metadata'dan al.

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

## KURAL 4 — IsTableActive
  "ödemesi alınan masalar", "kapalı masalar", "ödemesi alınan" → IsTableActive=0
  "açık masalar", "aktif masalar" → IsTableActive=1
  (Typo tolere et: "ödmesi alınan" da aynı anlama gelir)

## KURAL 5 — filters listesini SADE TUT
  - Sadece kullanıcının açıkça belirttiği filtreleri ekle
  - Gereksiz filtre EKLEME — merge_schemas dedup yapar, ama fazla filtre yanlış sonuç verir
  - IsTableActive, DocumentDetailIsTreatWasteCancel gibi filtreler term_hints'te "Python tarafından uygulanmaktadır" yazıyorsa filters'a EKLEME
"""
