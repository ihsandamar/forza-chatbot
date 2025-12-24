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


SQL_QUERY_BUILDER_PROMPT_TEXT = """Sen bir MSSQL sorgu oluşturma uzmanısın.

## TABLO BİLGİSİ
Tablo: MasterReportDocumentTable

## KULLANILAN KOLONLAR VE DETAYLARI
{enriched_metadata}

## RESOLVED STEPS
{resolved_steps}

## GÖREV
Yukarıdaki adımları MSSQL sorgusuna çevir.

## ÖNEMLİ: DEĞER KULLANIMI
Her filter için değer seçimi SIRASI:
1. **resolved_value** VARSA → ONU KULLAN (kesinlikle öncelikli!)
2. resolved_value YOKSA → value_hint kullan
3. value_hint'te "step_X.AlanAdı" varsa → önceki CTE'den al
4. value_hint'te DATEADD varsa → direkt SQL'e kopyala

**NOT**: resolved_value zaten veritabanından çözülmüş gerçek değerdir, MUTLAKA kullanılmalıdır!

## KURALLAR

1. **SELECT Clause**:
   - Eğer "select" alanı varsa ve boş değilse: SELECT ile belirtilen kolonları kullan
   - Eğer "select" null/boş ve aggregation varsa: Aggregation sonuçlarını + group_by alanlarını kullan
   - Eğer ikisi de yoksa: SELECT * kullan

2. **WHERE Clause (Filtreler)**:
   - Her filter'ı WHERE clause'a ekle
   - **logical_operator** alanına dikkat et:
     * Eğer filter'da "logical_operator": "OR" varsa → önceki filter ile OR ile bağla
     * Eğer logical_operator yoksa veya "AND" ise → önceki filter ile AND ile bağla
   - Örnek:
     * Filter 1: şehir = "istanbul", logical_operator: "OR"
     * Filter 2: şehir = "ankara"
     * WHERE: şehir = 'İSTANBUL' OR şehir = 'ANKARA'

3. **CTE ve Bağımlılıklar**:
   - Her adım için ayrı SQL oluştur (çok adımlıysa CTE kullan)
   - depends_on varsa önceki adımın sonucunu kullan
   - field_hint: Zaten gerçek kolon adı

4. **MSSQL Syntax**:
   - TOP kullan (limit için)
   - DATEADD, CAST kullan
   - Tarih filtreleri: CAST(DocumentDate AS DATE)
   - **CTE içinde ORDER BY KULLANMA** (sadece TOP ile birlikte)
   - ORDER BY'ı final SELECT'te kullan

5. **Sadece SQL sorgusu döndür** (markdown yok)

## ÖRNEK 1 - SELECT alanı ile basit liste:
Input:
{{
  "steps": [
    {{
      "select": ["ProductName", "RowAmount"],
      "filters": [
        {{"field_hint": "BranchName", "value_hint": "tunalı", "resolved_value": "TUNALI MERKEZ"}}
      ],
      "aggregations": [],
      "group_by": []
    }}
  ]
}}

Output:
```sql
SELECT ProductName, RowAmount
FROM MasterReportDocumentTable
WHERE BranchName = 'TUNALI MERKEZ'
```

## ÖRNEK 2 - Mantıksal Operatörler (OR):
Input:
{{
  "steps": [
    {{
      "select": ["BranchCityName", "RowAmount"],
      "filters": [
        {{"field_hint": "BranchCityName", "value_hint": "istanbul", "resolved_value": "İSTANBUL", "logical_operator": "OR"}},
        {{"field_hint": "BranchCityName", "value_hint": "ankara", "resolved_value": "ANKARA"}}
      ],
      "aggregations": [],
      "group_by": []
    }}
  ]
}}

Output:
```sql
SELECT BranchCityName, RowAmount
FROM MasterReportDocumentTable
WHERE BranchCityName = 'İSTANBUL' OR BranchCityName = 'ANKARA'
```

## ÖRNEK 3 - Aggregation (SELECT null):
Input:
{{
  "steps": [
    {{
      "select": null,
      "filters": [
        {{"field_hint": "BranchName", "value_hint": "tunalı", "resolved_value": "TUNALI MERKEZ"}},
        {{"field_hint": "DocumentDate", "value_hint": "2024-12-23"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalAmount"}}
      ],
      "group_by": []
    }}
  ]
}}

Output:
```sql
SELECT SUM(RowAmount) AS TotalAmount
FROM MasterReportDocumentTable
WHERE BranchName = 'TUNALI MERKEZ'
  AND CAST(DocumentDate AS DATE) = '2024-12-23'
```

## ÖRNEK 2 - Bağımlı Adımlar:
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
  GROUP BY CategoryName
  ORDER BY TotalQty DESC
)
SELECT TOP 10 ProductName, SUM(RowAmount) AS Revenue, SUM(Quantity) AS TotalQty
FROM MasterReportDocumentTable
WHERE CategoryName = (SELECT CategoryName FROM step_1)
GROUP BY ProductName
ORDER BY Revenue DESC
```

## ÖRNEK 3 - Tarih ve resolved_value birlikte:
Input:
{{
  "steps": [
    {{
      "filters": [
        {{"field_hint": "BranchCityName", "value_hint": "istanbul", "resolved_value": "İSTANBUL"}},
        {{"field_hint": "DocumentDate", "operator": ">=", "value_hint": "DATEADD(DAY, -7, '2024-12-23')"}}
      ],
      "aggregations": [
        {{"function": "COUNT", "field_hint": "*", "alias": "TotalOrders"}},
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalRevenue"}}
      ]
    }}
  ]
}}

Output:
```sql
SELECT COUNT(*) AS TotalOrders, SUM(RowAmount) AS TotalRevenue
FROM MasterReportDocumentTable
WHERE BranchCityName = 'İSTANBUL'
  AND CAST(DocumentDate AS DATE) >= DATEADD(DAY, -7, '2024-12-23')
```

Şimdi SQL oluştur (sadece sorgu):
"""

SQL_QUERY_BUILDER_PROMPT = ChatPromptTemplate.from_template(SQL_QUERY_BUILDER_PROMPT_TEXT)
