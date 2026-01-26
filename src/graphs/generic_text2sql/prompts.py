from langchain_core.prompts import ChatPromptTemplate


# Generic Intent Parser - No business logic, just structure
INTENT_PARSER_PROMPT_TEXT = """Sen bir doğal dil analiz uzmanısın. Kullanıcının sorusunu parse edip yapılandırılmış bir formata çevir.

## KULLANICI SORUSU
{user_query}

## GÖREV
Kullanıcının sorusunu analiz edip aşağıdaki yapıya göre parse et:
1. Kullanıcının hangi bilgileri görmek istediğini belirle (select)
2. Hangi koşulları uygulamak istediğini tespit et (filters)
3. Hesaplama yapmak istiyorsa belirle (aggregations)
4. Gruplamalar varsa tespit et (group_by)
5. Sıralama istiyorsa belirle (order_by)
6. Bağımlı adımları ayır (depends_on)

## JSON ÇIKTI YAPISI

### Alan Açıklamaları:
- **select**: Kullanıcının görmek istediği alanlar. Örnek: ["ürün", "tutar", "miktar"]
  * Aggregation kullanıldığında genelde boş olur (aggregation sonuçları döner)
  * Liste sorguları için kullanıcının görmek istediği kolonlar

- **filters**: Sorgu koşulları. Her filter:
  * field_hint: Hangi alan (tarih, şube, ürün, kategori, tutar, miktar, vb.)
  * operator: Karşılaştırma operatörü (=, >, <, >=, <=, !=, LIKE, IN, IS, IS NOT)
  * value_hint: Kullanıcının verdiği değer (aynen koru)
  * logical_operator: Filtreler arası bağlantı ("AND" veya "OR", default: "AND")

- **aggregations**: Hesaplamalar. Her aggregation:
  * function: SUM, COUNT, AVG, MAX, MIN
  * field_hint: Hangi alan üzerinde
  * alias: Sonuç kolonu adı

- **group_by**: Gruplama alanları. Örnek: ["kategori"], ["şube", "yıl", "ay"]

- **order_by**: Sıralama. Örnek: {{"field_hint": "tutar", "direction": "DESC"}}

- **limit**: Sonuç sayısı kısıtlaması. Örnek: 1, 10, 100

- **depends_on**: Bağımlı adımlar için önceki adım numarası

- **complexity**: "simple" (tek adım) veya "compound" (çok adımlı)

## ÖRNEKLER

### Örnek 1 - Basit Liste (Select ile):
Soru: "Tunalı şubesinin ürünlerini göster"
{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "Tunalı şubesinin ürün listesi",
      "select": ["ürün"],
      "filters": [
        {{"field_hint": "şube", "operator": "=", "value_hint": "tunalı"}}
      ],
      "aggregations": [],
      "group_by": ["ürün"],
      "order_by": null,
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "Tunalı şubesinin ürünleri"
}}

### Örnek 2 - Aggregation ile:
Soru: "Hangi ürün ne kadar satıldı?"
{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "Ürünlerin toplam satış miktarları",
      "select": null,
      "filters": [],
      "aggregations": [
        {{"function": "SUM", "field_hint": "miktar", "alias": "ToplamMiktar"}}
      ],
      "group_by": ["ürün"],
      "order_by": null,
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "Her ürünün toplam satış miktarı"
}}

### Örnek 3 - Mantıksal Filtreler (OR):
Soru: "İstanbul veya Ankara'daki satışlar"
{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "İstanbul veya Ankara satışları",
      "select": ["şehir", "tutar"],
      "filters": [
        {{"field_hint": "şehir", "operator": "=", "value_hint": "istanbul", "logical_operator": "OR"}},
        {{"field_hint": "şehir", "operator": "=", "value_hint": "ankara"}}
      ],
      "aggregations": [],
      "group_by": [],
      "order_by": null,
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "İstanbul veya Ankara'daki satışlar"
}}

### Örnek 4 - Bağımlı Adımlar + Tarih (Doğal Dil):
Soru: "6 kasımda en çok satan kategorideki, tüm tarihlerde en az satan ürünün son 5 yıldaki aylık performansı"
{{
  "complexity": "compound",
  "steps": [
    {{
      "step_number": 1,
      "description": "6 kasımda en çok satan kategori",
      "select": null,
      "filters": [
        {{"field_hint": "tarih", "operator": "=", "value_hint": "6 kasım"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "miktar", "alias": "ToplamMiktar"}}
      ],
      "group_by": ["kategori"],
      "order_by": {{"field_hint": "ToplamMiktar", "direction": "DESC"}},
      "limit": 1,
      "depends_on": null
    }},
    {{
      "step_number": 2,
      "description": "O kategorideki tüm tarihlerde en az satan ürün",
      "select": null,
      "filters": [
        {{"field_hint": "kategori", "operator": "=", "value_hint": "step_1.kategori"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "miktar", "alias": "ToplamMiktar"}}
      ],
      "group_by": ["ürün"],
      "order_by": {{"field_hint": "ToplamMiktar", "direction": "ASC"}},
      "limit": 1,
      "depends_on": 1
    }},
    {{
      "step_number": 3,
      "description": "O ürünün son 5 yıldaki aylık performansı",
      "select": null,
      "filters": [
        {{"field_hint": "ürün", "operator": "=", "value_hint": "step_2.ürün"}},
        {{"field_hint": "tarih", "operator": ">=", "value_hint": "son 5 yıl"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "tutar", "alias": "Ciro"}}
      ],
      "group_by": ["yıl", "ay"],
      "order_by": null,
      "limit": null,
      "depends_on": 2
    }}
  ],
  "final_output": "6 kasımda en çok satan kategorideki en az satan ürünün son 5 yıldaki aylık cirosu"
}}

NOT: Dikkat et - "6 kasım" ve "son 5 yıl" doğal dil olarak kaldı, tarih çözümlemesi yapılmadı!

## ÖNEMLİ KURALLAR

1. **Select Kullanımı**:
   - Aggregation YOKSA ve kullanıcı belirli alanlar görmek istiyorsa select kullan
   - Aggregation VARSA genelde select null olur
   - "göster", "listele", "hangileri" gibi ifadelerde select kullan

2. **Mantıksal Operatörler**:
   - Default davranış: AND (belirtilmediğinde)
   - "veya", "ya da" → OR kullan
   - "ve", "hem", "aynı zamanda" → AND kullan
   - logical_operator sadece iki filter arasındaki bağlantı için kullanılır

3. **Bağımlı Adımlar**:
   - "en çok/en az" her kullanımda genelde yeni adım
   - Önceki adımdan değer almak için: "step_X.alanAdı"
   - depends_on ile bağımlılığı belirt

4. **Field Hint İsimleri** (Genel adlar, veritabanı bağımsız):
   - tarih, şube, ürün, kategori, tutar, miktar, müşteri, kasiyer
   - yıl, ay, gün, saat, şehir, ilçe
   - işlem_tipi, masa_durumu, menü_id, adisyon_id

5. **Value Hint**:
   - Kullanıcının verdiği değeri AYNEN yaz, ÇÖZÜMLEME YAPMA!
   - Emin olmadığın değerleri "?" ile işaretle
   - **ÇOK ÖNEMLİ - TARİH İFADELERİ**: Tarih ifadelerini doğal dil olarak AYNEN kullanıcının söylediği gibi yaz
     * "bugün" → value_hint: "bugün"
     * "6 kasım" → value_hint: "6 kasım"
     * "son 7 gün" → value_hint: "son 7 gün"
     * TARİH ÇÖZÜMLEMESÎ YAPMA! (Bu sonraki adımda yapılacak)

6. **Özel Durumlar** (Kritik!):
   - "ikram" → filter ekle: {{"field_hint": "işlem_tipi", "operator": "=", "value_hint": "1"}}
   - "zayi" veya "fire" → filter ekle: {{"field_hint": "işlem_tipi", "operator": "=", "value_hint": "2"}}
   - "iptal" → filter ekle: {{"field_hint": "işlem_tipi", "operator": "=", "value_hint": "3"}}
   - "açık masa" → filter ekle: {{"field_hint": "masa_durumu", "operator": "=", "value_hint": "1"}}
   - "kapalı masa" → filter ekle: {{"field_hint": "masa_durumu", "operator": "=", "value_hint": "0"}}

Sadece JSON döndür, başka açıklama yapma.
"""

INTENT_PARSER_PROMPT = ChatPromptTemplate.from_template(INTENT_PARSER_PROMPT_TEXT)


# Business Logic Matcher - Maps generic intent to specific DB schema
INTENT_MATCHER_PROMPT_TEXT = """Sen bir veritabanı şema uzmanısın. Generic intent yapısını gerçek tablo kolonlarına eşleştir ve tarih ifadelerini çözümle.

## BUGÜNÜN TARİHİ
Bugün: {today_date}
Şu an: {current_datetime}
Yıl: {current_year}
Ay: {current_month}

## TABLO BİLGİSİ
Tablo adı: MasterReportDocumentTable

Kolonlar:
- DocumentId: Adisyon ID (guid)
- DocumentDate: Satış tarihi (datetime)
- ProductName: Ürün adı (text)
- CategoryName: Kategori adı (text)
- Quantity: Satış miktarı (numeric)
- RowAmount: Satış tutarı (numeric)
- BranchName: Şube adı (text)
- DayOfWeek: Haftanın günü (1=Pazartesi, 7=Pazar)
- Hour: Saat (0-23)
- CustomerName: Müşteri adı (text)
- CashierName: Kasiyer adı (text)
- BranchCityName: Şehir (text)
- TableNo: Masa Numarası/Adı (text)

## GENERIC INTENT
{parsed_intent}

## GÖREV
1. Generic field_hint'leri gerçek kolon adlarına eşleştir
2. Tarih ifadelerini (value_hint) SQL tarih fonksiyonlarına çevir

## EŞLEŞTİRME KURALLARI
- "tarih" → "DocumentDate"
- "şube" → "BranchName"
- "ürün" → "ProductName"
- "kategori" → "CategoryName"
- "tutar" → "RowAmount"
- "miktar" → "Quantity"
- "müşteri" → "CustomerName"
- "kasiyer" → "CashierName"
- "şehir" → "BranchCityName"
- "gün" → "DayOfWeek"
- "saat" → "Hour"
- "yıl" → "YEAR(DocumentDate)" (calculated field)
- "ay" → "MONTH(DocumentDate)" (calculated field)
- "işlem_tipi" → "DocumentDetailIsTreatWasteCancel"
- "masa_durumu" → "IsTableActive"
- "menü_id" → "MenuId"
- "adisyon_id" → "DocumentId"

## TARİH ÇÖZÜMLEMESİ (value_hint dönüşümleri)
Doğal dil tarih ifadelerini SQL formatına çevir:

### Mutlak Tarihler:
- "bugün" → "{today_date}"
- "dün" → "DATEADD(DAY, -1, '{today_date}')"
- "yarın" → "DATEADD(DAY, 1, '{today_date}')"

### Göreceli Tarihler:
- "son 7 gün", "son 7 günde" → "DATEADD(DAY, -7, '{today_date}')" (operator: ">=")
- "son 30 gün" → "DATEADD(DAY, -30, '{today_date}')" (operator: ">=")
- "son 5 yıl", "son 5 yılda" → "DATEADD(YEAR, -5, '{today_date}')" (operator: ">=")
- "son 3 ay" → "DATEADD(MONTH, -3, '{today_date}')" (operator: ">=")

### Periyot Tarihleri:
- "bu ay" → "{current_year}-{current_month}" (LIKE kullan: "{current_year}-{current_month}-%")
- "bu yıl" → "{current_year}" (LIKE kullan: "{current_year}-%")
- "geçen ay" → "DATEADD(MONTH, -1, '{today_date}')"

### Spesifik Tarihler (Gün-Ay formatı):
- "6 kasım", "kasım 6", "6 kas" → "{current_year}-11-06"
- "15 ocak" → "{current_year}-01-15"
- "3 mart" → "{current_year}-03-03"
- **NOT**: Yıl belirtilmemişse current_year kullan!
- **NOT**: Ay isimlerini sayıya çevir (ocak=01, şubat=02, mart=03, nisan=04, mayıs=05, haziran=06, temmuz=07, ağustos=08, eylül=09, ekim=10, kasım=11, aralık=12)

### Tam Tarihler:
- "2023-11-06" → Olduğu gibi bırak
- "6.11.2023" → "2023-11-06" formatına çevir

ÖNEMLİ: Tarih alanı (DocumentDate) için value_hint'i bu kurallara göre dönüştür!

## ÇIKTI FORMATI
Aynı JSON yapısını döndür, field_hint ve tarih value_hint değerlerini güncelle:

### Örnek - Tarih Çözümleme:
Input (INTENT_PARSER'dan gelen):
{{
  "complexity": "simple",
  "steps": [
    {{
      "filters": [
        {{"field_hint": "tarih", "operator": "=", "value_hint": "6 kasım"}},
        {{"field_hint": "şube", "operator": "=", "value_hint": "tunalı"}}
      ]
    }}
  ]
}}

Output (TARİH ÇÖZÜMLEME YAPILMIŞ):
{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "6 kasımda TUNALI şubesinin satışları",
      "select": null,
      "filters": [
        {{"field_hint": "DocumentDate", "operator": "=", "value_hint": "{current_year}-11-06"}},
        {{"field_hint": "BranchName", "operator": "=", "value_hint": "tunalı"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalAmount"}}
      ],
      "group_by": [],
      "order_by": null,
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "TUNALI şubesinin 6 kasımdaki toplam satış tutarı"
}}

Dikkat: "6 kasım" → "{current_year}-11-06" olarak çözümlendi!

NOT:
- Sadece JSON döndür, başka bir şey yazma
- Tarih olmayan value_hint değerlerini AYNEN KORU
- Tarih ifadeleri için yukarıdaki kuralları uygula
- field_hint'leri eşleştir
- select, logical_operator gibi yeni alanları AYNEN KORU
"""

INTENT_MATCHER_PROMPT = ChatPromptTemplate.from_template(INTENT_MATCHER_PROMPT_TEXT)


# Detaylı kolon metadata - Sadece gerekli olanlar kullanılacak (token tasarrufu)
COLUMN_METADATA_DETAILED = {
    # Tarih/Zaman
    "DocumentDate": "Satış tarihi (datetime)",
    "DayOfWeek": "Gün (1=Pazartesi...7=Pazar)",
    "Hour": "Saat (0-23)",
    "YEAR(DocumentDate)": "Yıl (calculated field)",
    "MONTH(DocumentDate)": "Ay (calculated field)",

    # Adisyon
    "DocumentId": "Adisyon ID (guid). ÖNEMLİ: Adisyon toplam tutarı hesaplanırken GROUP BY DocumentId kullan!",
    "IsTableActive": "Masa durumu. 1: Açık masalar (ödemesi alınmamış, hala masada), 0: Kapalı masalar (ödemesi alınan)",

    # Ürün
    "ProductName": "Ürün adı",
    "CategoryName": "Kategori adı",
    "MenuId": "Menü ürünü ID. NULL veya Empty Guid ise ana ürün, değer varsa menü içi seçenek (yan ürün)",

    # Satış
    "Quantity": "Satış miktarı (adet)",
    "RowAmount": "Satış tutarı (TL)",
    "DiscountAmountTotal": "İndirim tutarı (TL)",
    "DocumentDetailIsTreatWasteCancel": "İşlem tipi. Null: Default Normal satış, 1: İkram, 2: Zayi (fire), 3: İptal",

    # Lokasyon
    "BranchName": "Şube adı",
    "BranchCityName": "Şehir",
    "BranchTownName": "İlçe",

    # Satış Tipi
    "DocumentTypeName": "İşlem tipi (Stok Çıkış, Fatura, vb.)",
    "DocumentKindName": "Satış kanalı (Paket Servis, Masa, vb.)",
    "DocumentTypeIsReturn": "İade mi? (0: Normal, 1: İade)",

    # Personel
    "CashierName": "Kasiyer adı",
    "DeliveryUserName": "Kurye adı",

    # Müşteri
    "CustomerName": "Müşteri adı",
    "TableNo": "Masa numarası",
}

# Kısa metadata (backward compatibility)
COLUMN_METADATA_SHORT = """
## Kolonlar

### Tarih/Zaman
- DocumentDate: Satış tarihi
- DayOfWeek: Gün (1=Pzt...7=Paz)
- Hour: Saat (0-23)

### Ürün
- ProductName: Ürün adı
- CategoryName: Kategori adı

### Satış
- Quantity: Adet
- RowAmount: Tutar (TL)
- DiscountAmountTotal: İndirim (TL)

### Lokasyon
- BranchName: Şube
- BranchCityName: Şehir
- BranchTownName: İlçe

### Satış Tipi
- DocumentTypeName: İşlem tipi (Stok Çıkış, Fatura)
- DocumentKindName: Kanal (Paket Servis, Masa)
- DocumentTypeIsReturn: İade mi (0/1)

### Personel
- CashierName: Kasiyer
- DeliveryUserName: Kurye

### Müşteri
- CustomerName: Müşteri adı
- TableNo: Masa no
"""


SQL_QUERY_BUILDER_PROMPT_TEXT = """Sen bir MSSQL sorgu oluşturma uzmanısın. Yukarıdaki adımları MSSQL sorgusuna çevir.

Tablo: {table_name}

## KULLANILAN KOLONLAR
{enriched_metadata}

## İŞ KURALLARI (BUSINESS RULES)
{business_rules_context}

## RESOLVED STEPS
{resolved_steps}

## KRİTİK KURALLAR

**1. Değer Kullanımı**:
- resolved_value varsa → MUTLAKA onu kullan (veritabanından çözülmüş)
- Yoksa value_hint kullan
- "step_X.Alan" → önceki CTE'den al
- DATEADD → direkt SQL'e kopyala

**2. SELECT Clause**:
- **ÇOK ÖNEMLİ**: GROUP BY'daki TÜM alanlar SELECT'te olmalı (grafik için zorunlu!)
- Aggregation varsa: Aggregation + group_by alanları
- Aggregation yoksa: "select" alanındaki kolonlar veya SELECT *

**3. WHERE Clause**:
- logical_operator = "OR" → önceki filter ile OR
- logical_operator yok/AND → AND ile bağla

**3.5. ÇOK ÖNEMLİ - ÇOKLU ADIM SORGULARI (depends_on var)**:
- Group By'da kullanılan TÜMALANLAR için WHERE'ye IS NOT NULL ekle!
- Örnek: GROUP BY CategoryName → WHERE'ye `AND CategoryName IS NOT NULL`
- Örnek: GROUP BY CAST(DocumentDate AS DATE) → WHERE'ye `AND CAST(DocumentDate AS DATE) IS NOT NULL`
- Örnek: SUM(Amount) agregasyonu → WHERE'ye `AND Amount IS NOT NULL`
- Bu, sonraki CTE step'lerinde NULL referans sorunlarını önler!

**4. ORDER BY (Zaman Serisi için KRİTİK!)**:
- GROUP BY'da zaman ifadesi varsa → ORDER BY'a MUTLAKA ekle!
- Örnek: `GROUP BY YEAR(DocumentDate), MONTH(DocumentDate)` → `ORDER BY YEAR(DocumentDate), MONTH(DocumentDate)`
- Örnek: `GROUP BY CAST(DocumentDate AS DATE)` → `ORDER BY CAST(DocumentDate AS DATE)`

**5. MSSQL Syntax**:
- Limit → TOP kullan
- Tarih filtre → CAST(DocumentDate AS DATE)
- CTE'de ORDER BY sadece TOP ile
- Çok adım → CTE kullan

**Çıktı**: Sadece SQL sorgusu (markdown yok)

## ÖRNEK 1 - CTE + Bağımlı Adımlar:
Input:
{{
  "steps": [
    {{
      "step_number": 1,
      "filters": [],
      "aggregations": [{{"function": "SUM", "field_hint": "Quantity", "alias": "TotalQty"}}],
      "group_by": ["CategoryName"],
      "order_by": {{"field_hint": "TotalQty", "direction": "DESC"}},
      "limit": 1
    }},
    {{
      "step_number": 2,
      "filters": [{{"field_hint": "CategoryName", "value_hint": "step_1.CategoryName"}}],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "Revenue"}},
        {{"function": "SUM", "field_hint": "Quantity", "alias": "TotalQty"}}
      ],
      "group_by": ["ProductName"],
      "order_by": {{"field_hint": "Revenue", "direction": "DESC"}},
      "limit": 10,
      "depends_on": 1
    }}
  ]
}}

Output:
```sql
WITH step_1 AS (
  SELECT TOP 1 CategoryName, SUM(Quantity) AS TotalQty
  FROM MasterReportDocumentTable
  WHERE CategoryName IS NOT NULL
  GROUP BY CategoryName
  ORDER BY TotalQty DESC
)
SELECT TOP 10 ProductName, SUM(RowAmount) AS Revenue, SUM(Quantity) AS TotalQty
FROM MasterReportDocumentTable
WHERE CategoryName = (SELECT CategoryName FROM step_1)
  AND ProductName IS NOT NULL
GROUP BY ProductName
ORDER BY Revenue DESC
```

## ÖRNEK 2 - Zaman Serisi (GROUP BY → SELECT + ORDER BY):
Input:
{{
  "steps": [
    {{
      "filters": [
        {{"field_hint": "CategoryName", "value_hint": "DURUMLER", "resolved_value": "DURUMLER"}},
        {{"field_hint": "DocumentDate", "operator": ">=", "value_hint": "DATEADD(YEAR, -1, '2025-12-29')"}}
      ],
      "aggregations": [
        {{"function": "AVG", "field_hint": "RowAmount", "alias": "AverageDailyAmount"}}
      ],
      "group_by": ["CAST(DocumentDate AS DATE)"]
    }}
  ]
}}

Output (NOT: GROUP BY alanı → SELECT + ORDER BY):
```sql
SELECT AVG(RowAmount) AS AverageDailyAmount, CAST(DocumentDate AS DATE) AS Date
FROM MasterReportDocumentTable
WHERE CategoryName = 'DURUMLER'
  AND CAST(DocumentDate AS DATE) >= DATEADD(YEAR, -1, '2025-12-29')
GROUP BY CAST(DocumentDate AS DATE)
ORDER BY CAST(DocumentDate AS DATE) ASC
```

Şimdi SQL oluştur (sadece sorgu):
"""

SQL_QUERY_BUILDER_PROMPT = ChatPromptTemplate.from_template(SQL_QUERY_BUILDER_PROMPT_TEXT)


# ============================================================================
# OPTIMIZED: SQL ARCHITECT PROMPT (Collapsed Architecture)
# ============================================================================
# Combines intent_parser + intent_matching into a single LLM call
# Uses Chain of Thought (CoT) for better reasoning
# Injects business rules and schema metadata dynamically
# ============================================================================

SQL_ARCHITECT_PROMPT_TEXT = """Sen bir ERP veritabanı mimarı ve doğal dil işleme uzmanısın.

Kullanıcının sorusunu analiz edip, veritabanı sorgulama için yapılandırılmış bir intent oluştur.

## BİLGİLENDİRME

### BUGÜNÜN TARİHİ
Bugün: {today_date}
Şu an: {current_datetime}
Yıl: {current_year}
Ay: {current_month}

### VERİTABANI ŞEMASI
Tablo: {table_name}

Mevcut Kolonlar:
{schema_metadata}

### İŞ KURALLARI (DEĞİŞTİRİLEMEZ KANUNLAR)
{business_rules}

## KULLANICI SORUSU
{user_query}

## GÖREV

**ADIM 1: SORGUYU ANLA (Chain of Thought - Düşünce Zinciri)**

Önce kullanıcının sorusunu analiz et ve düşünce sürecini yaz:

1. Kullanıcı hangi bilgileri görmek istiyor?
2. Hangi filtreleme koşulları var?
3. Hesaplama/toplama var mı?
4. Gruplama gerekiyor mu?
5. Bu sorgu için hangi İŞ KURALLARI geçerli? (ÇOK ÖNEMLİ!)
6. Tarih ifadeleri var mı? Bunları nasıl çözeceğim?

**ADIM 2: YAPIYA DÖNÜŞTÜR**

Analiz sonucunda aşağıdaki JSON yapısını oluştur:

{{
  "complexity": "simple" | "compound",
  "thinking": "Düşünce süreci (1-2 cümle özet)",
  "applied_business_rules": ["rule_id_1", "rule_id_2"],  // Uygulanan iş kuralı ID'leri
  "steps": [
    {{
      "step_number": 1,
      "description": "Bu adımın açıklaması",
      "select": ["KolonAdı1", "KolonAdı2"] | null,
      "filters": [
        {{
          "field_hint": "GerçekKolonAdı",  // VERİTABANI KOLONUNA EŞLEŞTİRİLMİŞ
          "operator": "=",
          "value_hint": "kullanıcının değeri VEYA çözümlenmiş tarih",
          "logical_operator": "AND" | "OR"
        }}
      ],
      "aggregations": [
        {{
          "function": "SUM" | "COUNT" | "AVG" | "MAX" | "MIN",
          "field_hint": "GerçekKolonAdı",
          "alias": "SonuçKolonAdı"
        }}
      ],
      "group_by": ["KolonAdı1"],
      "order_by": {{"field_hint": "KolonAdı", "direction": "DESC"}},
      "limit": 1,
      "depends_on": null
    }}
  ],
  "final_output": "Sonucun açıklaması"
}}

## KRİTİK KURALLAR

### 1. KOLON EŞLEŞTİRMESİ (ŞEMA MAPPING)

field_hint değerlerinde GERÇEK KOLON ADLARINI kullan:
- "tarih" → "DocumentDate"
- "şube" → "BranchName"
- "ürün" → "ProductName"
- "kategori" → "CategoryName"
- "tutar" → "RowAmount"
- "miktar" → "Quantity"
- "müşteri" → "CustomerName"
- "kasiyer" → "CashierName"
- "şehir" → "BranchCityName"
- "ilçe" → "BranchTownName"
- "gün" → "DayOfWeek"
- "saat" → "Hour"
- "yıl" → "YEAR(DocumentDate)"  # Calculated field
- "ay" → "MONTH(DocumentDate)"   # Calculated field
- "masa" → "TableNo"
- "adisyon" → "DocumentId"

### 2. TARİH ÇÖZÜMLEMESİ (ÇOK ÖNEMLİ!)

Kullanıcının verdiği tarih ifadelerini SQL formatına çevir:

**Mutlak Tarihler:**
- "bugün" → "{today_date}"
- "dün" → "DATEADD(DAY, -1, '{today_date}')"
- "yarın" → "DATEADD(DAY, 1, '{today_date}')"

**Göreceli Tarihler:**
- "son 7 gün" → "DATEADD(DAY, -7, '{today_date}')" (operator: ">=")
- "son 30 gün" → "DATEADD(DAY, -30, '{today_date}')" (operator: ">=")
- "son 5 yıl" → "DATEADD(YEAR, -5, '{today_date}')" (operator: ">=")
- "son 3 ay" → "DATEADD(MONTH, -3, '{today_date}')" (operator: ">=")

**Periyot Tarihleri:**
- "bu ay" → "{current_year}-{current_month}" (LIKE kullan: "{current_year}-{current_month}-%")
- "bu yıl" → "{current_year}" (LIKE kullan: "{current_year}-%")

**Spesifik Tarihler:**
- "6 kasım" → "{current_year}-11-06"
- "15 ocak" → "{current_year}-01-15"
- **NOT**: Ay isimlerini sayıya çevir (ocak=01, şubat=02, mart=03, nisan=04, mayıs=05, haziran=06, temmuz=07, ağustos=08, eylül=09, ekim=10, kasım=11, aralık=12)

### 3. İŞ KURALLARI UYGULAMASI (ZORUNLUDİR!)

Yukarıda verilen İŞ KURALLARI'nı (business_rules) OKU ve UYGULA:

**Örnek: Ciro Hesaplama**
- Kullanıcı "ciro", "gelir", "hasılat" diyorsa:
  - İptal filtresi ekle: {{"field_hint": "DocumentDetailIsTreatWasteCancel", "operator": "IS NULL"}}
  - İade filtresi ekle: {{"field_hint": "DocumentTypeIsReturn", "operator": "=", "value_hint": "0"}}

**Örnek: Açık Masa**
- Kullanıcı "açık masa" diyorsa:
  - {{"field_hint": "IsTableActive", "operator": "=", "value_hint": "1"}}

**Örnek: İkram**
- Kullanıcı "ikram" diyorsa:
  - {{"field_hint": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value_hint": "1"}}

**Örnek: Adisyon Tutarı**
- Kullanıcı "adisyon tutarı", "masa tutarı" diyorsa:
  - GROUP BY DocumentId kullan!

### 4. SELECT VE AGGREGATION KULLANIMI

- **Aggregation YOKSA**: select alanını kullan (kullanıcının görmek istediği kolonlar)
- **Aggregation VARSA**: select genelde null olur (aggregation sonuçları döner)

**KRİTİK KURAL - PERİYODİK GRUPLAMA (MUTLAKA UYGULA!):**

Kullanıcı periyodik ifade kullanırsa + aggregation varsa → MUTLAKA group_by ekle!

**Periyodik İfadeler ve Karşılıkları:**
- "günlük", "her gün", "gün gün", "günlere göre", "gün bazında"
  → group_by: ["CAST(DocumentDate AS DATE)"]

- "aylık", "her ay", "ay ay", "aylara göre", "ay bazında", "aylar bazında"
  → group_by: ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]
  * NOT: Birden fazla yıl olabilir, hem yıl hem ay gerekli

- "yıllık", "her yıl", "yıl yıl", "yıllara göre", "yıl bazında"
  → group_by: ["YEAR(DocumentDate)"]

- "saatlik", "her saat", "saat saat", "saatlere göre", "saat bazında"
  → group_by: ["CAST(DocumentDate AS DATE)", "Hour"]

**ÖRNEK - YANLIŞ VE DOĞRU:**

❌ YANLIŞ: "günlük ortalama" → aggregation: AVG, group_by: [] (TOPLAM DÖNER!)
✅ DOĞRU: "günlük ortalama" → aggregation: AVG, group_by: ["CAST(DocumentDate AS DATE)"] (HER GÜN AYRI!)

❌ YANLIŞ: "aylık satışlar" → aggregation: SUM, group_by: [] (TOPLAM DÖNER!)
✅ DOĞRU: "aylık satışlar" → aggregation: SUM, group_by: ["YEAR(DocumentDate)", "MONTH(DocumentDate)"] (HER AY AYRI!)

### 5. MANTIKSAL OPERATÖRLER

- "veya", "ya da" → logical_operator: "OR"
- "ve", "hem" → logical_operator: "AND"
- Default: "AND"

### 6. BAĞIMLI ADIMLAR

- "en çok", "en az" gibi sorgulamalar genelde yeni adım gerektirir
- Önceki adımdan değer almak için: "step_X.KolonAdı"
- depends_on ile bağımlılığı belirt

## ÇIKTI FORMATI

**ÇOK ÖNEMLİ**: Sadece JSON döndür, başka bir şey yazma!

Çıktı JSON olmalı ve yukarıdaki yapıya uymalıdır.

## ÖRNEKLER

### Örnek 1: Basit Ciro Sorgusu

Kullanıcı: "Tunalı şubesinin bugünkü cirosu ne kadar?"

Düşünce Zinciri:
1. Kullanıcı "ciro" istiyor → SUM(RowAmount) aggregation
2. "Tunalı" şubesi → BranchName filtresi
3. "bugünkü" → DocumentDate = bugün
4. Ciro hesaplama → İş kuralı: İptal/iade hariç!

Çıktı:
{{
  "complexity": "simple",
  "thinking": "Ciro hesaplama için iptal ve iade işlemleri hariç tutulmalı, Tunalı şubesi ve bugün filtresi uygulanmalı",
  "applied_business_rules": ["revenue_calculation"],
  "steps": [
    {{
      "step_number": 1,
      "description": "Tunalı şubesinin bugünkü cirosu (iptal/iade hariç)",
      "select": null,
      "filters": [
        {{"field_hint": "BranchName", "operator": "=", "value_hint": "tunalı"}},
        {{"field_hint": "DocumentDate", "operator": "=", "value_hint": "{today_date}"}},
        {{"field_hint": "DocumentDetailIsTreatWasteCancel", "operator": "IS NULL"}},
        {{"field_hint": "DocumentTypeIsReturn", "operator": "=", "value_hint": "0"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalRevenue"}}
      ],
      "group_by": [],
      "order_by": null,
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "Tunalı şubesinin bugünkü toplam cirosu (iptal/iade hariç)"
}}

### Örnek 2: Günlük Ortalama (PERİYODİK GRUPLAMA)

Kullanıcı: "Son bir senede dürümler kategorisindeki günlük tutar ortalaması"

Düşünce Zinciri:
1. "günlük" kelimesi var → PERİYODİK GRUPLAMA gerekli!
2. "ortalama" → AVG(RowAmount) aggregation
3. "dürümler kategorisi" → CategoryName filtresi
4. "son bir senede" → DocumentDate >= DATEADD(YEAR, -1, bugün)
5. **KRİTİK**: "günlük" + aggregation → MUTLAKA group_by: ["CAST(DocumentDate AS DATE)"]

Çıktı:
{{
  "complexity": "simple",
  "thinking": "Günlük periyodik ifade kullanıldı, aggregation var, bu yüzden MUTLAKA günlük gruplama gerekli. Aksi halde TOPLAM ortalama döner (HATA!)",
  "applied_business_rules": [],
  "steps": [
    {{
      "step_number": 1,
      "description": "Dürümler kategorisinin günlük tutar ortalaması (son 1 yıl)",
      "select": null,
      "filters": [
        {{"field_hint": "CategoryName", "operator": "=", "value_hint": "dürümler"}},
        {{"field_hint": "DocumentDate", "operator": ">=", "value_hint": "DATEADD(YEAR, -1, '{today_date}')"}}
      ],
      "aggregations": [
        {{"function": "AVG", "field_hint": "RowAmount", "alias": "DailyAverage"}}
      ],
      "group_by": ["CAST(DocumentDate AS DATE)"],
      "order_by": {{"field_hint": "CAST(DocumentDate AS DATE)", "direction": "ASC"}},
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "Dürümler kategorisinin her gün için ortalama tutar (365 satır beklenir)"
}}

### Örnek 3: Bağımlı Adımlar + Tarih

Kullanıcı: "6 kasımda en çok satan kategorideki, son 5 yıldaki en az satan ürünün aylık performansı"

Düşünce Zinciri:
1. "6 kasım" → 2025-11-06 (current_year kullan)
2. "en çok satan kategori" → Adım 1: TOP 1 kategori
3. "o kategorideki en az satan ürün" → Adım 2: depends_on: 1
4. "son 5 yıl" → DATEADD(YEAR, -5, ...)
5. "aylık performans" → GROUP BY YEAR, MONTH

Çıktı:
{{
  "complexity": "compound",
  "thinking": "Üç adımlı bağımlı sorgu: 1) 6 kasımda en çok satan kategori, 2) O kategoride tüm zamanlarda en az satan ürün, 3) O ürünün son 5 yıldaki aylık satışları",
  "applied_business_rules": [],
  "steps": [
    {{
      "step_number": 1,
      "description": "6 kasımda en çok satan kategori",
      "select": null,
      "filters": [
        {{"field_hint": "DocumentDate", "operator": "=", "value_hint": "{current_year}-11-06"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "Quantity", "alias": "TotalQty"}}
      ],
      "group_by": ["CategoryName"],
      "order_by": {{"field_hint": "TotalQty", "direction": "DESC"}},
      "limit": 1,
      "depends_on": null
    }},
    {{
      "step_number": 2,
      "description": "O kategorideki tüm tarihlerde en az satan ürün",
      "select": null,
      "filters": [
        {{"field_hint": "CategoryName", "operator": "=", "value_hint": "step_1.CategoryName"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "Quantity", "alias": "TotalQty"}}
      ],
      "group_by": ["ProductName"],
      "order_by": {{"field_hint": "TotalQty", "direction": "ASC"}},
      "limit": 1,
      "depends_on": 1
    }},
    {{
      "step_number": 3,
      "description": "O ürünün son 5 yıldaki aylık satışları",
      "select": null,
      "filters": [
        {{"field_hint": "ProductName", "operator": "=", "value_hint": "step_2.ProductName"}},
        {{"field_hint": "DocumentDate", "operator": ">=", "value_hint": "DATEADD(YEAR, -5, '{today_date}')"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "MonthlyRevenue"}},
        {{"function": "SUM", "field_hint": "Quantity", "alias": "MonthlyQty"}}
      ],
      "group_by": ["YEAR(DocumentDate)", "MONTH(DocumentDate)"],
      "order_by": {{"field_hint": "YEAR(DocumentDate), MONTH(DocumentDate)", "direction": "ASC"}},
      "limit": null,
      "depends_on": 2
    }}
  ],
  "final_output": "6 kasımda en çok satan kategorideki en az satan ürünün son 5 yıldaki aylık performansı"
}}

## SON HATIRLATMA

1. **Field hint'ler gerçek kolon adları olmalı** (DocumentDate, BranchName, vb.)
2. **Tarih ifadelerini çözümle** (SQL formatına çevir)
3. **İş kurallarını uygula** (mandatory_filters)
4. **applied_business_rules alanını doldur**
5. **Sadece JSON döndür** (açıklama yazma)

Şimdi kullanıcının sorusunu analiz et ve JSON çıktısı oluştur:
"""

SQL_ARCHITECT_PROMPT = ChatPromptTemplate.from_template(SQL_ARCHITECT_PROMPT_TEXT)
