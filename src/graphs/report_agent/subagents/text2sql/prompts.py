from typing import List, Literal, Optional

from pydantic import BaseModel


# =============================================================================
# PYDANTIC MODELS — Structured LLM Output
# =============================================================================

class QueryFilter(BaseModel):
    field_hint: str
    operator: Literal[
        "=", ">", "<", ">=", "<=", "!=",
        "LIKE", "IN", "BETWEEN", "IS NULL", "IS NOT NULL"
    ]
    value_hint: str
    resolved_value: Optional[str] = None   # value_resolver tarafından doldurulur
    logical_operator: Literal["AND", "OR"] = "AND"


class QueryAggregation(BaseModel):
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    field_hint: str
    alias: str


class QueryPlan(BaseModel):
    """sql_planner node'unun structured output'u."""
    description: str
    select_columns: List[str]              # Aggregation yoksa gösterilecek kolonlar
    filters: List[QueryFilter]
    aggregations: List[QueryAggregation]
    group_by: List[str]
    order_by_field: Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit: Optional[int] = None


class GeneratedSQL(BaseModel):
    """sql_builder node'unun structured output'u."""
    sql: str
    explanation: str    # Kolon eşleştirme kararları — debug için


class FixedSQL(BaseModel):
    """sql_executor retry durumunda sql_builder'dan beklenen output."""
    sql: str
    fix_explanation: str


# =============================================================================
# PROMPTS
# =============================================================================

QUERY_PLANNER_PROMPT = """Sen bir SQL planlama uzmanısın. Kullanıcının sorusunu analiz et ve yapılandırılmış bir sorgu planı çıkar.

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## MEVCUT KOLON BİLGİLERİ (field_hint seçmek için kullan)
{column_metadata}

## CONVERSATION CONTEXT
{conversation_context}

## KURALLAR

### field_hint
- Kullanıcının kullandığı doğal dil ifadesini yaz ("şube", "tarih", "tutar")
- Kolon açıklamalarına bak, en yakın semantik eşleşmeyi seç

### value_hint
- Kullanıcının yazdığı değeri AYNEN koru (büyük/küçük harf, Türkçe karakter önemli değil)
- Tarih ifadelerini olduğu gibi bırak ("son 3 ay", "ocak 2024", "bu yıl")

### Sorgu tipine göre zorunlu alanlar
- RANKING: aggregation + order_by + limit (mutlaka)
- COMPARISON: filters veya group_by ile segmentleri ayır
- TIME_SERIES_COMPARISON: tarih kolonunu group_by'a ekle
- SINGLE: basit select veya tek aggregation

### select_columns
- Aggregation varsa genelde boş bırak (aggregation sonuçları yeterli)
- Aggregation yoksa kullanıcının görmek istediği alanları ekle
"""

SQL_BUILDER_PROMPT = """Sorgu planına göre geçerli T-SQL (Microsoft SQL Server) üret.

## TABLO ADI
{table_name}

## KOLON METADATA (gerçek kolon isimleri ve tipleri)
{column_metadata}

## SORGU PLANI
{query_plan}

## BUSINESS RULES SQL COMPONENTS
{business_rules_context}

## ÖNCEKI SQL HATASI (varsa — sadece bu kısmı düzelt)
{sql_error}

## KURALLAR

### Kolon eşleştirme
- field_hint → column_metadata'daki GERÇEK kolon adını bul
- resolved_value varsa → `WHERE KolonAdi = 'resolved_value'` (kesin eşleşme)
- resolved_value yoksa → `WHERE UPPER(KolonAdi) LIKE UPPER('%value_hint%')` (fuzzy)

### T-SQL kuralları
- TOP N kullan (LIMIT değil)
- Kolon adında boşluk varsa [köşeli parantez] kullan
- String karşılaştırmada UPPER() veya COLLATE Turkish_CI_AI kullan
- Tarih: YEAR(kolon), MONTH(kolon), DATEPART(quarter, kolon), CONVERT(date, kolon)
- NULL güvenliği: IS NULL / IS NOT NULL

### Business rules
- business_rules_context'teki SQL bileşenlerini uygula
- aggregation varsa SUM() içine ekle (ör: iade kuralı)
- filter varsa WHERE'e AND ile ekle

### GROUP BY
- Aggregation kullanan her SELECT'te tüm non-aggregate kolonları GROUP BY'a ekle
- Bu hatayı ASLA yapma: SELECT x, SUM(y) FROM t → GROUP BY olmadan

### Hata düzeltme
- sql_error varsa: hatayı analiz et, SADECE o kısmı düzelt, sorgunun amacını koru
"""
