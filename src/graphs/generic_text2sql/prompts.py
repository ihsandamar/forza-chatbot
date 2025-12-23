from langchain_core.prompts import ChatPromptTemplate


# Generic Intent Parser - No business logic, just structure and dates
INTENT_PARSER_PROMPT_TEXT = """Sen bir doğal dil analiz uzmanısın. Kullanıcının sorusunu DİKKATLİCE analiz edip genel bir yapıya çevir.

## BUGÜNÜN TARİHİ
Bugün: {today_date}
Şu an: {current_datetime}
Yıl: {current_year}
Ay: {current_month}

## KULLANICI SORUSU
{user_query}

## GÖREV
Kullanıcının sorusunu DİKKATLE analiz et:
1. Sorudaki TÜM koşulları ve filtreleri belirle
2. "en çok", "en az", "ilk", "son" gibi sıralama ifadelerini tespit et
3. Her bir bağımlı adımı AYRI AYRI belirle
4. Tarih ifadelerini çözümle
5. "aylar bazında", "günlük", "yıllık" gibi grouping ifadelerini tespit et

## ÖNEMLİ: KARMAŞIK SORGULAR İÇİN
- Her "en çok/en az" ifadesi genellikle AYRI bir adımdır
- Örnek: "en çok satan kategorideki en az satan ürün" → 2 adım:
  1. En çok satan kategoriyi bul
  2. O kategorideki en az satan ürünü bul

## ÇIKTI FORMATI (Sadece JSON)

### Basit Sorgu:
{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "Bugün belirli şubenin toplam satışları",
      "filters": [
        {{"field_hint": "tarih", "operator": "=", "value_hint": "{today_date}"}},
        {{"field_hint": "şube", "operator": "=", "value_hint": "tunalı"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "tutar", "alias": "TotalAmount"}}
      ],
      "group_by": [],
      "order_by": null,
      "limit": null,
      "depends_on": null
    }}
  ],
  "final_output": "Şubenin bugünkü toplam satış tutarı"
}}

### Çok Adımlı Bağımlı Sorgu:
{{
  "complexity": "compound",
  "steps": [
    {{
      "step_number": 1,
      "description": "Belirli tarihteki en çok satan kategoriyi bul",
      "filters": [
        {{"field_hint": "tarih", "operator": "=", "value_hint": "2025-11-06"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "miktar", "alias": "TotalQty"}}
      ],
      "group_by": ["kategori"],
      "order_by": {{"field_hint": "TotalQty", "direction": "DESC"}},
      "limit": 1,
      "depends_on": null
    }},
    {{
      "step_number": 2,
      "description": "O kategorideki tüm tarihlerde en az adet satan ürünü bul",
      "filters": [
        {{"field_hint": "kategori", "operator": "=", "value_hint": "step_1.kategori"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "miktar", "alias": "TotalQty"}}
      ],
      "group_by": ["ürün"],
      "order_by": {{"field_hint": "TotalQty", "direction": "ASC"}},
      "limit": 1,
      "depends_on": 1
    }},
    {{
      "step_number": 3,
      "description": "O ürünün son 5 yıl içindeki cirosunu aylar bazında şubeler için göster",
      "filters": [
        {{"field_hint": "ürün", "operator": "=", "value_hint": "step_2.ürün"}},
        {{"field_hint": "tarih", "operator": ">=", "value_hint": "DATEADD(YEAR, -5, '{today_date}')"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "tutar", "alias": "Revenue"}}
      ],
      "group_by": ["şube", "yıl", "ay"],
      "order_by": null,
      "limit": null,
      "depends_on": 2
    }}
  ],
  "final_output": "En çok satan kategorideki en az satan ürünün son 5 yıldaki aylık şube performansı"
}}

## KURALLAR

### Tarih Çözümleme:
- "bugün" → value_hint: "{today_date}"
- "dün" → value_hint: "DATEADD(DAY, -1, '{today_date}')"
- "son 7 gün" → value_hint: "DATEADD(DAY, -7, '{today_date}')", operator: ">="
- "bu ay" → value_hint: "{current_year}-{current_month}"
- "son 5 yıl" → value_hint: "DATEADD(YEAR, -5, '{today_date}')", operator: ">="
- "6 kasım" → value_hint: "{current_year}-11-06" (current year if not specified)

### Sıralama Kuralları:
- "en çok" → ORDER BY DESC + LIMIT 1
- "en az" → ORDER BY ASC + LIMIT 1
- "ilk" → ORDER BY ASC + LIMIT N
- "son" → ORDER BY DESC + LIMIT N

### Gruplama Kuralları:
- "aylar bazında" → group_by: ["yıl", "ay"]
- "günlük" → group_by: ["tarih"]
- "yıllık" → group_by: ["yıl"]
- "şubeler için" → group_by'e "şube" ekle
- "ürünler için" → group_by'e "ürün" ekle

### Genel Kurallar:
- field_hint: Genel alan adı kullan (tarih, şube, ürün, kategori, tutar, miktar, yıl, ay, gün vb.)
- value_hint: Kullanıcının verdiği değeri olduğu gibi yaz
- Bağımlı adımlar: "step_X.alanAdı" formatı kullan
- Her "en çok/en az" ifadesi için AYRI adım oluştur
- Emin olmadığın değerleri "?" ile işaretle
"""

INTENT_PARSER_PROMPT = ChatPromptTemplate.from_template(INTENT_PARSER_PROMPT_TEXT)


# Business Logic Matcher - Maps generic intent to specific DB schema
INTENT_MATCHER_PROMPT_TEXT = """Sen bir veritabanı şema uzmanısın. Generic intent yapısını gerçek tablo kolonlarına eşleştir.

## TABLO BİLGİSİ
Tablo adı: SalesDetailView

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

## GENERIC INTENT
{parsed_intent}

## GÖREV
Generic field_hint'leri gerçek kolon adlarına eşleştir.

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

## ÇIKTI FORMATI
Aynı JSON yapısını döndür, sadece field_hint değerlerini güncelle:

{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "Bugün TUNALI şubesinin toplam satışları",
      "filters": [
        {{"field_hint": "DocumentDate", "operator": "=", "value_hint": "2024-12-19"}},
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
  "final_output": "TUNALI şubesinin bugünkü toplam satış tutarı"
}}

NOT:
- Sadece JSON döndür, başka bir şey yazma
- value_hint değerlerini AYNEN KORU (kullanıcının girdiği değerler önemli)
- Sadece field_hint değerlerini güncelle
"""

INTENT_MATCHER_PROMPT = ChatPromptTemplate.from_template(INTENT_MATCHER_PROMPT_TEXT)


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
1. Her adım için ayrı SQL oluştur (çok adımlıysa CTE kullan)
2. depends_on varsa önceki adımın sonucunu kullan
3. field_hint: Zaten gerçek kolon adı
4. MSSQL syntax: TOP, DATEADD, CAST vb.
5. Tarih filtreleri: CAST(DocumentDate AS DATE)
6. **CTE içinde ORDER BY KULLANMA** (sadece TOP ile birlikte)
   - ORDER BY'ı final SELECT'te kullan
7. limit varsa TOP kullan
8. Sadece SQL sorgusu döndür (markdown yok)

## ÖRNEK 1 - resolved_value kullanımı:
Input:
{{
  "steps": [
    {{
      "filters": [
        {{"field_hint": "BranchName", "value_hint": "tunalı", "resolved_value": "TUNALI MERKEZ"}},
        {{"field_hint": "DocumentDate", "value_hint": "2024-12-23"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalAmount"}}
      ]
    }}
  ]
}}

Output (DİKKAT: resolved_value kullanıldı!):
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
