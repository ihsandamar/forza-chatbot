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

### KURAL 1 — Kolon Adları
SADECE yukarıdaki KOLON BİLGİLERİ'ndeki gerçek DB adlarını kullan.
Kullanıcı "şube" derse → kolon açıklamalarına bak, doğru DB kolon adını yaz.
Hiçbir zaman "tarih", "şube", "tutar" gibi Türkçe field_hint yazma — gerçek DB adını yaz.

### KURAL 2 — Tarih Filtreleri (DateDescriptor ZORUNLU)
Tarih olan filtreler için value/value_hint DEĞİL, date_descriptor doldur.

Örnekler:
  "son 3 ay"      → {{"type":"relative","unit":"month","amount":-3}},   operator: ">="
  "son 7 gün"     → {{"type":"relative","unit":"day","amount":-7}},     operator: ">="
  "son 1 yıl"     → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "bu yıl"        → {{"type":"current_period","period":"year"}}
  "bu ay"         → {{"type":"current_period","period":"month"}}
  "bugün"         → {{"type":"current_period","period":"day"}}
  "bu çeyrek"     → {{"type":"current_period","period":"quarter"}}
  "15 ocak"       → {{"type":"exact","value":"{current_year}-01-15"}},  operator: "="
  "ocak 2024"     → iki filter: >= {{"type":"exact","value":"2024-01-01"}}
                              ve <= {{"type":"exact","value":"2024-01-31"}}

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
Örnek: "en çok satan 10 ürün" → aggregations=[SUM(Quantity)], group_by=["ProductName"],
       order_by_column="TotalQty", order_by_direction="DESC", limit=10

### KURAL 5 — Periyodik Gruplama
"günlük satışlar"  → group_by: ["CAST(TarihKolonu AS DATE)"]
"aylık satışlar"   → group_by: ["YEAR(TarihKolonu)", "MONTH(TarihKolonu)"]
"yıllık satışlar"  → group_by: ["YEAR(TarihKolonu)"]
"saatlik dağılım"  → group_by: ["CAST(TarihKolonu AS DATE)", "HourKolonu"]
Tarih kolonu adını column_metadata'dan al.

### KURAL 6 — Business Rules
KURALLAR bölümündeki her kural için ID listesini applied_rule_ids'e yaz.
SQL bileşenlerini (WHERE koşulu, SUM ifadesi) KENDİN YAZMA — Python uygular.
Sadece hangi rule'un uygulanacağını belirt.

### KURAL 7 — Hata Düzeltme
ÖNCEKİ SQL HATASI varsa:
  - Hata mesajını analiz et
  - Yanlış kolon adı → column_metadata'dan doğrusunu bul
  - GROUP BY hatası → Kural 3'ü uygula
  - Syntax hatası → ilgili field'ı düzelt
"""
