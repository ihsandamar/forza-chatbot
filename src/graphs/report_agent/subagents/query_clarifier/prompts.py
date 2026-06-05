from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


class ClarityIssue(BaseModel):
    type: Literal[
        "missing_date_filter",
        "ambiguous_metric",
        "missing_grouping",
        "ambiguous_filter_value",
        "large_result_warning",
    ]
    description: str
    severity: Literal["low", "medium", "high"]


class ClarityAnalysisResult(BaseModel):
    clarity_score: float
    issues: List[ClarityIssue]
    suggested_query: Optional[str] = None
    suggestion_message: Optional[str] = None
    can_suggest: bool

    @field_validator("clarity_score")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


CLARITY_ANALYZER_PROMPT = """Sen bir Türkçe ERP rapor sorgu analizcisisin.

Kullanıcının raporlama sorgusunu analiz et ve netlik skoru (0.0–1.0) hesapla.
Eksiklik/belirsizlik varsa tespit et ve optimize edilmiş bir versiyon öner.

BAĞLAM:
- Niyet tipi: {intent_type}
- Aktif SQL var mı: {has_active_sql}
- Aktif SQL özeti (MODIFY_QUERY için): {active_sql_summary}

KONTROL LİSTESİ:
□ Tarih/dönem filtresi belirtilmiş mi? (DocumentDate, bu ay, geçen hafta vb.)
□ Metrik/ölçüm net mi? (RowAmount=tutar, Quantity=adet, Count=kayıt sayısı)
□ Gruplama/boyut belirtilmiş mi? (BranchName, CategoryName, ProductName vb.)
□ Filtre değerleri spesifik mi? (belirsiz terimler yerine tam değerler)
□ Büyük veri riski var mı? (limit/sıralama gerekliyse belirtilmiş mi)

NETLIK SKORU REHBERİ:
- 0.85–1.0 → Net sorgu — tarih + metrik + gruplama hepsi açık → can_suggest: false
- 0.65–0.84 → Küçük eksiklik — genellikle yeterince net → can_suggest: false
- 0.40–0.64 → Birden fazla eksiklik → can_suggest: true, öneri üret
- <0.40     → Çok belirsiz (VAGUE_QUERY bu range'i zaten yakalar, beklenmez)

MEVCUT VERİTABANI KOLONLARI:
RowAmount, Quantity, DocumentDate, BranchName, ProductName,
CategoryName, BranchCityName, CustomerName

KULLANICI SORGUSU: {user_query}

Eğer öneri üretebiliyorsan (can_suggest=true):
- suggested_query: Türkçe, doğal dilde optimize edilmiş sorgu metni
- suggestion_message: Tam olarak şu formatta yaz (suggested_query içeriğini yerine koy): "Şunu mu sormak istediniz?\\n\\n📊 [suggested_query metni]\\n\\nEvet ise onaylayın, değilse 'hayır' yazın."

Eğer sorgu netsek veya öneri üretemiyorsan:
- can_suggest: false
- suggested_query: null
- suggestion_message: null"""


VAGUE_CLARITY_PROMPT = """Sen bir Türkçe ERP rapor yorumlayıcısısın.

Kullanıcının sorgusu çok genel — spesifik bir SQL sorgusuna doğrudan dönüştürülemez.
Bu sorguyu en makul ERP raporu yorumuyla somutlaştır.

ÖRNEKLER:
- "satışları göster" → "Bu ayki toplam RowAmount, CategoryName bazında gruplandırılmış, büyükten küçüğe"
- "ne sattık" → "Son 30 günde en çok satan ilk 10 ProductName (Quantity bazında)"
- "şubelerin durumu" → "Bu ay her BranchName için toplam RowAmount"
- "kategorilere bak" → "Bu ay CategoryName bazında toplam RowAmount, büyükten küçüğe"

MEVCUT VERİTABANI KOLONLARI:
RowAmount, Quantity, DocumentDate, BranchName, ProductName,
CategoryName, BranchCityName, CustomerName

KULLANICI SORGUSU: {user_query}

Her zaman döndür:
- clarity_score: 0.0
- can_suggest: true
- issues: en az bir ClarityIssue (genellikle missing_date_filter + missing_grouping)
- suggested_query: spesifik, doğal Türkçe
- suggestion_message: Tam olarak şu formatta yaz (suggested_query içeriğini yerine koy): "Şunu mu sormak istediniz?\\n\\n📊 [suggested_query metni]\\n\\nEvet ise onaylayın, değilse 'hayır' yazın." """
