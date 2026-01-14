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
    DT.Name AS DocumentTypeName,
    DT.IsReturn AS DocumentTypeIsReturn
INTO #Documents
FROM Documents D WITH (NOLOCK)
LEFT JOIN DocumentTypes DT WITH (NOLOCK) ON D.DocumentTypeId = DT.Id 
WHERE D.Status = 1
  AND DT.Status = 1
  AND DT.JoinType IN (1, 2, 3);


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
    CAST(NULL AS NVARCHAR(100)) AS DocumentTypeName,
    CAST(NULL AS BIT) AS DocumentTypeIsReturn
INTO #TempDocuments
FROM TempDocuments D WITH (NOLOCK);


-- Burada SELECT * yerine kolonları tek tek yaz
SELECT  
    DocumentId,
    BranchId,
    BusinessId,
    DocumentTypeId,
    DocumentKindId,
    CashierId,
    UserId,
    DocumentStatus,
    Date,
    TableNo,
    CustomerId,
    CustomerName,
    TableCustomerNumber,
    IsTableActive,
    DocumentTypeName,
    DocumentTypeIsReturn
INTO #UnionDocuments
FROM (
    SELECT  
        DocumentId,
        BranchId,
        BusinessId,
        DocumentTypeId,
        DocumentKindId,
        CashierId,
        UserId,
        DocumentStatus,
        Date,
        TableNo,
        CustomerId,
        CustomerName,
        TableCustomerNumber,
        IsTableActive,
        DocumentTypeName,
        DocumentTypeIsReturn
    FROM #Documents
    UNION ALL
    SELECT  
        DocumentId,
        BranchId,
        BusinessId,
        DocumentTypeId,
        DocumentKindId,
        CashierId,
        UserId,
        DocumentStatus,
        Date,
        TableNo,
        CustomerId,
        CustomerName,
        TableCustomerNumber,
        IsTableActive,
        DocumentTypeName,
        DocumentTypeIsReturn
    FROM #TempDocuments
) AS CombinedData;


    SELECT  
		--Payments
        P.Id AS PaymentId,
        P.DocumentId AS PaymentDocumentId,
        P.UserId AS PaymentUserId,
        P.CurrencyUnitId,
        P.Date AS PaymentDate,
		P.SpecialCode2 AS PaymentSpecialCode2,
		P.SpecialCode3 COLLATE SQL_Latin1_General_CP1_CI_AS AS PaymentSpecialCode3,
		P.SpecialCode4 COLLATE SQL_Latin1_General_CP1_CI_AS AS PaymentSpecialCode4,


		--PaymentDetails
		PD.Id AS PaymentDetailId, 
        PD.BankCardContractDetailId,
        PD.PaymentId AS PaymentDetailPaymentId, 
        PD.PaymentType AS PaymentTypeId, 
        ISNULL(PD.Amount, 0) AS PaymentAmount, 
        PD.PaymentTypeDescription,

		--PaymentTypes
		PT.Name AS PaymentTypeName
	INTO #Payments
    FROM 
        Payments P WITH (NOLOCK)
	LEFT JOIN 
		PaymentDetails PD WITH (NOLOCK) ON P.Id = PD.PaymentId
	LEFT JOIN 
		PaymentTypes PT WITH (NOLOCK) ON PD.PaymentType = PT.Id 
    WHERE 
        P.Status = 1
		AND PD.Status = 1
		
		

		

    SELECT  
        Id, 
        CONCAT(FirstName, ' ', LastName) AS FirstLastName 
	INTO #Users
    FROM 
        Users WITH (NOLOCK)
    WHERE 1=1 
		AND Status = 1
		
		


        
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
    B.Name AS BranchName,
    DK.Name AS DocumentKindName,
    D.DocumentTypeName,
    D.DocumentTypeIsReturn,
    CS.Name AS CashierName,
    0 AS IsTableActive,
    D.TableNo,
    D.CustomerId,
    D.CustomerName,
    IB.GroupName AS BranchGroupName,
    IB.BusinessType AS BusinessType,
    CTY.Name AS BranchCityName,
    TWN.Name AS BranchTownName,
    D.TableCustomerNumber,

    -- MasterReportQuery'ye özel alanlar
    P.PaymentId,
    P.PaymentDocumentId,
    P.PaymentUserId,
    P.PaymentDate,
    P.PaymentDetailId,
    P.PaymentDetailPaymentId,
    P.PaymentAmount,
    P.PaymentTypeId,
    P.PaymentTypeName,
    P.PaymentTypeDescription,
    U.FirstLastName AS DeliveryUserName,
    CU.Name AS CurrencyUnitName,
    BCT.Id AS BankCardTypeId,
    BCT.BankCardName AS BankCardTypeName,
    PYUSER.FirstLastName AS PaymentUserName,
	P.PaymentSpecialCode2,
	P.PaymentSpecialCode3 AS PaymentPlatformName,
	P.PaymentSpecialCode4 AS PaymentCourierName
INTO MasterReportPaymentTable
FROM 
    #UnionDocuments D
LEFT JOIN 
    #Payments P ON D.DocumentId = P.PaymentDocumentId 
LEFT JOIN 
    Branches B WITH (NOLOCK) ON D.BranchId = B.Id AND B.Status = 1

LEFT JOIN 
    DocumentKinds DK WITH (NOLOCK) ON D.DocumentKindId = DK.Id AND DK.Status = 1
LEFT JOIN 
    #Users U ON D.UserId = U.Id
LEFT JOIN 
    CurrencyUnits CU WITH (NOLOCK) ON P.CurrencyUnitId = CU.Id AND CU.Status = 1
LEFT JOIN 
    BankCardContractDetails BCCD WITH (NOLOCK) ON P.BankCardContractDetailId = BCCD.Id AND BCCD.Status = 1
LEFT JOIN 
    BankCardTypes BCT WITH (NOLOCK) ON BCCD.BankCardTypeId = BCT.Id AND BCT.Status = 1
LEFT JOIN 
    #Users PYUSER ON P.PaymentUserId = PYUSER.Id

LEFT JOIN 
    Cashiers CS WITH (NOLOCK) ON D.CashierId = CS.Id AND CS.Status = 1
LEFT JOIN 
    IntegrationBranches IB WITH (NOLOCK) ON B.Id = IB.DefaultBranchId AND IB.Status = 1
LEFT JOIN 
    Cities CTY WITH (NOLOCK) ON B.CityId = CTY.Id AND CTY.Status = 1
LEFT JOIN 
    Towns TWN WITH (NOLOCK) ON B.TownId = TWN.Id AND TWN.Status = 1
LEFT JOIN 
    Businesses BS WITH (NOLOCK) ON D.BusinessId = BS.Id AND BS.Status = 1

WHERE 1=1 

 
    
DROP TABLE #Documents
DROP TABLE #TempDocuments
DROP TABLE #UnionDocuments
DROP TABLE #Payments
DROP TABLE #Users
DROP TABLE #TempProductChoices

