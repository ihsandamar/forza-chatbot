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
    """
    description:        str
    select_columns:     List[str]            # Aggregation yoksa gösterilecek kolonlar (boş olabilir)
    filters:            List[SchemaFilter]
    aggregations:       List[SchemaAggregation]
    group_by:           List[str]            # Gerçek kolon adları veya SQL expression
    order_by_column:    Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit:              Optional[int] = None
    applied_rule_ids:   List[str] = []       # Business rule ID'leri — Python SQL'e ekler


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

## UYGULANACAK İŞ KURALLARI (ChromaDB'den seçilmiş)
{business_rules_context}

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

### KURAL 2 — Tarih Filtreleri (resolve_date TOOL ZORUNLU)
Sorguda tarih ifadesi varsa ("son 3 ay", "bu yıl", "ocak 2024" gibi):
  1. resolve_date("ifade") tool'unu çağır
  2. Tool "{col}" placeholder'lı SQL döner — {col} yerine column_metadata'dan doğru tarih kolonu adını yaz
  3. OP:>= ile başlıyorsa → operator: ">=", value: DATEADD(...) kısmı
     OP:BETWEEN ile başlıyorsa → operator: "BETWEEN", value: tarih aralığı
     OP:= ile başlıyorsa → operator: "=", value: tarih
     Düz expression ise (YEAR(...)) → value alanına direkt yaz, date_descriptor kullanma

Tarih filtresinde date_descriptor KULLANMA — tool sonucunu kullan.

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
Örnek: "en çok satan 10 ürün" → aggregations=[SUM(Quantity)], group_by=["ProductName"],
       order_by_column="TotalQty", order_by_direction="DESC", limit=10

### KURAL 5 — Periyodik Gruplama
"günlük satışlar"  → group_by: ["CAST(TarihKolonu AS DATE)"]
"aylık satışlar"   → group_by: ["YEAR(TarihKolonu)", "MONTH(TarihKolonu)"]
"yıllık satışlar"  → group_by: ["YEAR(TarihKolonu)"]
"saatlik dağılım"  → group_by: ["CAST(TarihKolonu AS DATE)", "HourKolonu"]
Tarih kolonu adını column_metadata'dan al.

### KURAL 6 — Business Rules Seçimi (KRİTİK)
"UYGULANACAK İŞ KURALLARI" bölümünde kurallar [id] formatında listelenmiştir.

Uygulama adımları:
  1. [VARSAYILAN — HER ZAMAN UYGULA] etiketli rule ID'lerini applied_rule_ids'e MUTLAKA ekle
  2. Diğer rule'ların Açıklama'sını kullanıcı sorgusuyla karşılaştır
  3. Sorguyla örtüşen her rule'un ID'sini applied_rule_ids'e ekle
  4. SQL bileşenlerini (WHERE, SUM, GROUP BY) KENDİN YAZMA — Python uygular

Örnekler:
  Sorgu: "ödemesi alınan masaların cirosu" →
    applied_rule_ids: ["iade_dusulmus", "kapali_masa_filtre"]

  Sorgu: "toplam satış tutarı" →
    applied_rule_ids: ["iade_dusulmus"]

  Sorgu: "açık masalardaki normal satışlar" →
    applied_rule_ids: ["iade_dusulmus", "acik_masa_filtre", "sadece_normal_satis"]

### KURAL 7 — Hata Düzeltme
ÖNCEKİ SQL HATASI varsa:
  - Hata mesajını analiz et
  - Yanlış kolon adı → column_metadata'dan doğrusunu bul
  - GROUP BY hatası → Kural 3'ü uygula
  - Syntax hatası → ilgili field'ı düzelt
"""
