from typing import Any, Dict

from pydantic import BaseModel, Field


class ReportAgentConfiguration(BaseModel):
    """
    LangGraph Studio'dan runtime'da configure edilebilen alanlar.

    StateGraph(config_schema=ReportAgentConfiguration) ile kayıt edilir;
    Studio UI'da "Configurable" panelinde görünür.
    """

    table_name: str = Field(
        default="MasterReportDocumentTable",
        description="Sorgunun uygulanacağı tablo adı",
    )

    query: str = Field(
        default="""
        -- MasterReport Query Merged

    SELECT  
        D.Id AS DocumentId,
        D.BranchId,
        D.BusinessId,
        D.DocumentTypeId,
        D.DocumentKindId,
        D.CashierId,
        D.UserId,
        D.Status AS DocumentStatus,
        D.Date,
        D.SpecialCode1 COLLATE SQL_Latin1_General_CP1_CI_AS AS TableNo,
        D.CustomerId,
        D.CustomerName COLLATE SQL_Latin1_General_CP1_CI_AS AS CustomerName,
        D.SpecialCode3 COLLATE SQL_Latin1_General_CP1_CI_AS AS TableCustomerNumber,
        0 AS IsTableActive, 

		--DocumentDetails
		DD.Id AS DocumentDetailId,
        DD.ProductId,
        DD.WaybillId,
        DD.BillId,
        DD.VoucherId,
        ISNULL(DD.Quantity, 0) AS Quantity,
        ISNULL(DD.RowAmount, 0) AS RowAmount,
        ISNULL(DD.DiscountAmountTotal, 0) AS DiscountAmountTotal, 
        DD.IsTreatWasteCancel, 
        DD.ProductUnitId, 
        DD.UpdatedAt, 
        DD.UpdatedUserId, 
        DATEPART(DW, DD.Maturity) AS DayOfWeek, 
        DATEPART(HOUR, DD.Maturity) AS Hour, 
        DD.PurchasePriceWithTax,
		DD.Description1,
		DD.ParentId AS ParentId,
		DD.ChoiceId AS ChoiceId,

		--DocumentTypes
		DT.Name AS DocumentTypeName,
		DT.IsReturn AS DocumentTypeIsReturn
	INTO #Documents
    FROM 
        Documents D WITH (NOLOCK)
		LEFT JOIN 
			DocumentDetails DD WITH (NOLOCK) ON 
				CASE 
					WHEN ISNULL(DD.WaybillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000' 
						 AND ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
					THEN ISNULL(DD.VoucherId, '00000000-0000-0000-0000-000000000000') 
					WHEN ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000' 
					THEN ISNULL(DD.WaybillId, '00000000-0000-0000-0000-000000000000') 
					ELSE ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') 
				END = D.Id
		LEFT JOIN
			DocumentTypes DT WITH (NOLOCK) ON D.DocumentTypeId = DT.Id 
    WHERE 
        D.Status = 1
		AND DD.Status = 1
		AND DT.Status = 1
		AND DT.JoinType IN (1, 2, 3)
		
		
		
	
		

    SELECT  
        D.Id AS DocumentId,
        D.BranchId,
        D.BusinessId,
        D.DocumentTypeId,
        D.DocumentKindId,
        D.CashierId,
        D.UserId,
        D.Status AS DocumentStatus,
        D.Date,
        D.SpecialCode1 COLLATE SQL_Latin1_General_CP1_CI_AS AS TableNo,
        D.CustomerId,
        D.CustomerName COLLATE SQL_Latin1_General_CP1_CI_AS AS CustomerName,
        D.SpecialCode3 COLLATE SQL_Latin1_General_CP1_CI_AS AS TableCustomerNumber,
        D.IsTableActive, 

		--TempDocumentDetails
		DD.Id AS DocumentDetailId,
        DD.ProductId,
        DD.WaybillId,
        DD.BillId,
        DD.VoucherId,
        ISNULL(DD.Quantity, 0) AS Quantity,
        ISNULL(DD.RowAmount, 0) AS RowAmount,
        ISNULL(DD.DiscountAmountTotal, 0) AS DiscountAmountTotal, 
        DD.IsTreatWasteCancel, 
        DD.ProductUnitId, 
        DD.UpdatedAt, 
        DD.UpdatedUserId, 
        DATEPART(DW, DD.Maturity) AS DayOfWeek, 
        DATEPART(HOUR, DD.Maturity) AS Hour, 
        DD.PurchasePriceWithTax,
		DD.Description1,
		DD.ParentId AS ParentId,
		DD.ChoiceId AS ChoiceId,

		--DocumentTypes
        CAST(NULL AS NVARCHAR(100)) AS DocumentTypeName,
        CAST(NULL AS BIT) AS DocumentTypeIsReturn
	INTO #TempDocuments
    FROM 
        TempDocuments D WITH (NOLOCK)
	LEFT JOIN 
		TempDocumentDetails DD WITH (NOLOCK) ON 
			CASE 
				WHEN ISNULL(WaybillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000' 
					 AND ISNULL(BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
				THEN ISNULL(VoucherId, '00000000-0000-0000-0000-000000000000') 
				WHEN ISNULL(BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000' 
				THEN ISNULL(WaybillId, '00000000-0000-0000-0000-000000000000') 
				ELSE ISNULL(BillId, '00000000-0000-0000-0000-000000000000') 
			END = D.Id
    WHERE 1=1
		
		
		
		
	SELECT * INTO #UnionDocuments FROM (
		SELECT * FROM #Documents
		UNION ALL
		SELECT * FROM #TempDocuments
	) AS CombinedData;



		

    SELECT  
        Id, 
        CONCAT(FirstName, ' ', LastName) AS FirstLastName 
	INTO #Users
    FROM 
        Users WITH (NOLOCK)
    WHERE 1=1 
		AND Status = 1
		
		

		
		
    SELECT  
        P.Id AS ProductId, 
        P.Name AS ProductName, 
        C.Id AS CategoryId, 
        C.Name AS CategoryName 
	INTO #ProductCategory
    FROM 
        Products P WITH (NOLOCK)
    LEFT JOIN 
        ProductCategories PC WITH (NOLOCK) ON P.Id = PC.ProductId
    LEFT JOIN 
        Categories C WITH (NOLOCK) ON PC.CategoryId = C.Id
    WHERE 
        1 = 1 
        AND PC.Status = 1 
        AND P.Status = 1
		AND C.Status = 1
        
        
SELECT 
    CASE 
        WHEN child.MainId IS NULL OR child.MainId = '00000000-0000-0000-0000-000000000000' 
        THEN child.Id 
        ELSE parent.Id 
    END AS MainChoiceId,
    CASE 
        WHEN child.MainId IS NULL OR child.MainId = '00000000-0000-0000-0000-000000000000' 
        THEN child.Name 
        ELSE parent.Name 
    END AS MainChoiceName,
    child.Id AS ChoiceId,
    child.Name AS ChoiceName
INTO #TempProductChoices
FROM ProductChoices child
LEFT JOIN ProductChoices parent ON child.MainId = parent.Id AND parent.Status = 1
WHERE child.Status = 1
        

SELECT 
    -- Ortak Alanlar
    D.DocumentId,
    D.BranchId,
    D.BusinessId,
    BS.Name AS BusinessName,
    D.DocumentTypeId,
    D.DocumentKindId,
    D.CashierId,
    D.UserId AS DeliveryUserId,
    D.DocumentStatus,
    D.Date AS DocumentDate,
    D.DocumentDetailId,
    PC.ProductId,
    D.Quantity,
    D.RowAmount,
    D.DiscountAmountTotal,
    B.Name AS BranchName,
    PC.ProductName AS ProductName,
    PC.CategoryId,
    PC.CategoryName AS CategoryName,
    DK.Name AS DocumentKindName,
    D.DocumentTypeName,
    D.DocumentTypeIsReturn,
    PU.UnitId AS ProductUnitId,
    UN.Name AS ProductUnitName,
    CS.Name AS CashierName,
    0 AS IsTableActive,
    D.TableNo,
    D.CustomerId,
    D.CustomerName,
    IB.GroupName AS BranchGroupName,
    IB.BusinessType AS BusinessType,
    CTY.Name AS BranchCityName,
    TWN.Name AS BranchTownName,
    D.IsTreatWasteCancel AS DocumentDetailIsTreatWasteCancel,
    D.DayOfWeek,
    D.Hour,
    D.TableCustomerNumber,
    D.UpdatedAt AS DocumentDetailUpdatedAt,
    D.UpdatedUserId AS DocumentDetailUpdatedUserId,
    DDUpdetedUser.FirstLastName AS DocumentDetailUpdatedUserFirstLastName,
    D.PurchasePriceWithTax,
	D.Description1 AS DocumentDetailDescription1,

	D.ParentId AS MenuId,
	D.ChoiceId AS ChoiceId, 
	PCH.ChoiceName AS ChoiceName,
	PCH.MainChoiceId,
	PCH.MainChoiceName,
    U.FirstLastName AS DeliveryUserName

INTO MasterReportDocumentTable
FROM 
    #UnionDocuments D

LEFT JOIN 
    Branches B WITH (NOLOCK) ON D.BranchId = B.Id AND B.Status = 1
LEFT JOIN 
    #ProductCategory PC ON D.ProductId = PC.ProductId
LEFT JOIN 
    DocumentKinds DK WITH (NOLOCK) ON D.DocumentKindId = DK.Id AND DK.Status = 1
LEFT JOIN 
    #Users U ON D.UserId = U.Id

LEFT JOIN 
    ProductUnits PU WITH (NOLOCK) ON D.ProductUnitId = PU.Id AND PU.Status = 1
LEFT JOIN 
    Units UN WITH (NOLOCK) ON PU.UnitId = UN.Id AND UN.Status = 1
LEFT JOIN 
    Cashiers CS WITH (NOLOCK) ON D.CashierId = CS.Id AND CS.Status = 1
LEFT JOIN 
    IntegrationBranches IB WITH (NOLOCK) ON B.Id = IB.DefaultBranchId AND IB.Status = 1
LEFT JOIN 
    Cities CTY WITH (NOLOCK) ON B.CityId = CTY.Id AND CTY.Status = 1
LEFT JOIN 
    Towns TWN WITH (NOLOCK) ON B.TownId = TWN.Id AND TWN.Status = 1
LEFT JOIN 
    #Users DDUpdetedUser ON D.UpdatedUserId = DDUpdetedUser.Id
LEFT JOIN 
    Businesses BS WITH (NOLOCK) ON D.BusinessId = BS.Id AND BS.Status = 1
LEFT JOIN
	#TempProductChoices PCH WITH (NOLOCK) ON D.ChoiceId = PCH.ChoiceId 
WHERE 1=1 


 
    
DROP TABLE #Documents
DROP TABLE #TempDocuments
DROP TABLE #UnionDocuments

DROP TABLE #ProductCategory
DROP TABLE #Users
DROP TABLE #TempProductChoices
        """,
        description="Tabloyu oluşturan SQL scripti (GO ile ayrılmış batch'ler desteklenir)",
    )

    column_metadata: Dict[str, Any] = Field(
        default = {
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
    "TableNo": "Masa numarası"
},
        description="Kolon metaverileri — {kolon_adı: açıklama} formatında",
    )

    business_rules_path: str = Field(
        default="./src/graphs/report_agent/data/business_rules.json",
        description="Business rules JSON dosya yolu. LangGraph Studio'dan runtime'da override edilebilir.",
    )
