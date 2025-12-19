from langchain_core.prompts import ChatPromptTemplate


INTENT_PARSER_PROMPT_TEXT = """Sen bir SQL sorgu analiz uzmanısın. Kullanıcının doğal dildeki sorusunu analiz et.

## BUGÜNÜN TARİHİ
Bugün: {today_date}
Şu an: {current_datetime}
Yıl: {current_year}
Ay: {current_month}

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

## KULLANICI SORUSU
{user_query}

## TALİMATLAR
1. Soruyu analiz et ve kaç adım gerektiğini belirle
2. Her adımı ayrı ayrı tanımla
3. Adımlar arası bağımlılıkları belirt
4. Tarih ifadelerini gerçek tarihlere çevir (aşağıdaki kurallara göre)

## ÇIKTI FORMATI (Sadece JSON, başka bir şey yazma)

### Basit Sorgu Örneği:
{{
  "complexity": "simple",
  "steps": [
    {{
      "step_number": 1,
      "description": "Bugün TUNALI şubesinin toplam satışları",
      "filters": [
        {{"field_hint": "DocumentDate", "operator": "=", "value_hint": "{today_date}"}},
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

### Bağımlı Adımlar Örneği:
{{
  "complexity": "compound",
  "steps": [
    {{
      "step_number": 1,
      "description": "En çok satan kategoriyi bul",
      "filters": [],
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
      "description": "O kategorideki ürünlerin satışlarını getir",
      "filters": [
        {{"field_hint": "CategoryName", "operator": "=", "value_hint": "step_1.CategoryName"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "Revenue"}}
      ],
      "group_by": ["ProductName"],
      "order_by": {{"field_hint": "Revenue", "direction": "DESC"}},
      "limit": 10,
      "depends_on": 1
    }}
  ],
  "final_output": "En çok satan kategorideki ürünlerin satış tutarları"
}}

NOT: value_hint içinde DATEADD kullanırken tırnak işaretlerine DİKKAT et!
Doğru: "value_hint": "DATEADD(DAY, -1, '{today_date}')"
Yanlış: "value_hint": DATEADD(...) (tırnak yok)

## ÖNEMLİ KURALLAR

### Tarih Çözümleme:
BUGÜNÜN TARİHİ: {today_date} (Örnek: 2024-12-19)
Tarih ifadelerini value_hint'e şu şekilde yaz:
- "bugün" sözcüğü → value_hint: "{today_date}" (Bugünün tarihini kullan)
- "dün" sözcüğü → value_hint: "DATEADD(DAY, -1, '{today_date}')"
- "son 7 gün" → value_hint: "DATEADD(DAY, -7, '{today_date}')", operator: ">="
- "bu ay" → value_hint: "{current_year}-" ile başlayan format
- "son 5 yıl" → value_hint: "DATEADD(YEAR, -5, '{today_date}')", operator: ">="
- Genel kural: Tarih ifadelerini DATEADD fonksiyonu veya ISO tarih formatında yaz

### Diğer Kurallar:
- "en çok satan" → SUM(Quantity) veya COUNT(*) ile GROUP BY + ORDER BY DESC + LIMIT 1
- "hangi günlerde" → DayOfWeek ile GROUP BY
- **ÖNEMLİ**: Bir adımın sonucu başka adımda kullanılıyorsa:
  * depends_on: önceki adımın numarasını belirt
  * value_hint: "step_X.AlanAdı" formatında yaz (örn: "step_1.CategoryName", "step_2.ProductName")
  * Bu sayede SQL builder önceki adımdan değeri alabilir
- Emin olmadığın değerleri "?" ile işaretle
- Kullanıcının verdiği ürün/şube/kategori adları için sözel hint bırak (örn: "tunalı", "dürüm")
  * Bunlar value resolver tarafından gerçek değerlere çevrilecek
"""

INTENT_PARSER_PROMPT = ChatPromptTemplate.from_template(INTENT_PARSER_PROMPT_TEXT)


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

## Kolonlar
{column_metadata}

## GÖREV
Aşağıdaki adımları MSSQL sorgusuna çevir.

## RESOLVED STEPS
{resolved_steps}

## KURALLAR
1. Her adım için ayrı bir SQL sorgusu oluştur (CTE kullan)
2. depends_on varsa, önceki adımın sonucunu kullan
3. resolved_value varsa, onu kullan (value_hint değil!)
4. value_hint'te "step_X.AlanAdı" formatı varsa, önceki CTE'den değeri al
   Örnek: step_1.CategoryName → WHERE CategoryName = (SELECT CategoryName FROM step_1)
5. value_hint'te DATEADD varsa, direkt SQL'e kopyala
6. MSSQL syntax kullan (TOP, DATEADD, DATEDIFF vb.)
7. Tarih filtreleri için CAST kullan: CAST(DocumentDate AS DATE)
8. **ÖNEMLİ**: CTE (WITH) içinde ORDER BY kullanma!
   - MSSQL'de CTE içinde ORDER BY sadece TOP ile kullanılabilir
   - ORDER BY'ı final SELECT'te kullan
   - YANLIŞ: WITH step_1 AS (SELECT ... ORDER BY ...)
   - DOĞRU: WITH step_1 AS (SELECT ...) SELECT * FROM step_1 ORDER BY ...
9. limit varsa TOP kullan: SELECT TOP 10 ...
10. Sadece SELECT sorguları oluştur
11. Çıktı: Sadece SQL sorgusu, başka bir şey yazma

## ÖRNEK 1 - Basit Sorgu:
Input:
{{
  "steps": [
    {{
      "step_number": 1,
      "filters": [
        {{"field_hint": "BranchName", "resolved_value": "TUNALI"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalAmount"}}
      ]
    }}
  ]
}}

Output:
```sql
SELECT SUM(RowAmount) AS TotalAmount
FROM MasterReportDocumentTable
WHERE BranchName = 'TUNALI'
```

## ÖRNEK 2 - Bağımlı Adımlar (step referansı):
Input:
{{
  "steps": [
    {{
      "step_number": 1,
      "aggregations": [
        {{"function": "SUM", "field_hint": "Quantity", "alias": "TotalQty"}}
      ],
      "group_by": ["CategoryName"],
      "order_by": {{"field_hint": "TotalQty", "direction": "DESC"}},
      "limit": 1
    }},
    {{
      "step_number": 2,
      "filters": [
        {{"field_hint": "CategoryName", "value_hint": "step_1.CategoryName"}}
      ],
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "Revenue"}}
      ],
      "depends_on": 1
    }}
  ]
}}

Output (DİKKAT: CTE içinde ORDER BY YOK, TOP kullanıldı):
```sql
WITH step_1 AS (
  SELECT TOP 1 CategoryName, SUM(Quantity) AS TotalQty
  FROM MasterReportDocumentTable
  GROUP BY CategoryName
  ORDER BY TotalQty DESC
)
SELECT SUM(RowAmount) AS Revenue
FROM MasterReportDocumentTable
WHERE CategoryName = (SELECT CategoryName FROM step_1)
```

## ÖRNEK 3 - CTE ile ORDER BY (DOĞRU kullanım):
Input:
{{
  "steps": [
    {{
      "step_number": 1,
      "aggregations": [
        {{"function": "SUM", "field_hint": "RowAmount", "alias": "TotalRevenue"}}
      ],
      "group_by": ["BranchName"],
      "order_by": {{"field_hint": "TotalRevenue", "direction": "DESC"}},
      "limit": null
    }}
  ]
}}

Output (ORDER BY final SELECT'te):
```sql
SELECT BranchName, SUM(RowAmount) AS TotalRevenue
FROM MasterReportDocumentTable
GROUP BY BranchName
ORDER BY TotalRevenue DESC
```

VEYA çok adımlı ise:
```sql
WITH step_1 AS (
  SELECT BranchName, SUM(RowAmount) AS TotalRevenue
  FROM MasterReportDocumentTable
  GROUP BY BranchName
  -- ORDER BY YOK!
)
SELECT *
FROM step_1
ORDER BY TotalRevenue DESC
```

Şimdi SQL oluştur (sadece sorgu, açıklama yok):
"""

SQL_QUERY_BUILDER_PROMPT = ChatPromptTemplate.from_template(SQL_QUERY_BUILDER_PROMPT_TEXT)
