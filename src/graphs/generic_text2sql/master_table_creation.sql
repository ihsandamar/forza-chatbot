-- MasterReport Query - Create Temp Table
-- This SQL creates MasterReportDocumentTable as a temp table for querying

-- Step 1: Create #Documents from Documents table
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
    DT.Name AS DocumentTypeName,
    DT.IsReturn AS DocumentTypeIsReturn
INTO #Documents
FROM
    Documents D WITH (NOLOCK)
LEFT JOIN
    DocumentDetails DD ON
        CASE
            WHEN ISNULL(DD.WaybillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
                 AND ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
            THEN ISNULL(DD.VoucherId, '00000000-0000-0000-0000-000000000000')
            WHEN ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
            THEN ISNULL(DD.WaybillId, '00000000-0000-0000-0000-000000000000')
            ELSE ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000')
        END = D.Id
LEFT JOIN
    DocumentTypes DT ON D.DocumentTypeId = DT.Id
WHERE
    D.Status = 1
    AND DD.Status = 1
    AND DT.Status = 1
    AND DT.JoinType IN (1, 2, 3);

-- Step 2: Create #TempDocuments from TempDocuments table
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
    CAST(NULL AS NVARCHAR(100)) AS DocumentTypeName,
    CAST(NULL AS BIT) AS DocumentTypeIsReturn
INTO #TempDocuments
FROM
    TempDocuments D WITH (NOLOCK)
LEFT JOIN
    TempDocumentDetails DD ON
        CASE
            WHEN ISNULL(DD.WaybillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
                 AND ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
            THEN ISNULL(DD.VoucherId, '00000000-0000-0000-0000-000000000000')
            WHEN ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000') = '00000000-0000-0000-0000-000000000000'
            THEN ISNULL(DD.WaybillId, '00000000-0000-0000-0000-000000000000')
            ELSE ISNULL(DD.BillId, '00000000-0000-0000-0000-000000000000')
        END = D.Id
WHERE 1=1;

-- Step 3: Union documents
SELECT * INTO #UnionDocuments FROM (
    SELECT * FROM #Documents
    UNION ALL
    SELECT * FROM #TempDocuments
) AS CombinedData;

-- Step 4: Create supporting temp tables
SELECT
    Id,
    CONCAT(FirstName, ' ', LastName) AS FirstLastName
INTO #Users
FROM
    Users WITH (NOLOCK)
WHERE
    Status = 1;

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
    PC.Status = 1
    AND P.Status = 1
    AND C.Status = 1;

-- Step 5: Create final MasterReportDocumentTable
SELECT
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
    U.FirstLastName AS DeliveryUserName
INTO MasterReportDocumentTable
FROM
    #UnionDocuments D
LEFT JOIN
    Branches B ON D.BranchId = B.Id AND B.Status = 1
LEFT JOIN
    #ProductCategory PC ON D.ProductId = PC.ProductId
LEFT JOIN
    DocumentKinds DK ON D.DocumentKindId = DK.Id AND DK.Status = 1
LEFT JOIN
    #Users U ON D.UserId = U.Id
LEFT JOIN
    ProductUnits PU ON D.ProductUnitId = PU.Id AND PU.Status = 1
LEFT JOIN
    Units UN ON PU.UnitId = UN.Id AND UN.Status = 1
LEFT JOIN
    Cashiers CS ON D.CashierId = CS.Id AND CS.Status = 1
LEFT JOIN
    IntegrationBranches IB ON B.Id = IB.DefaultBranchId AND IB.Status = 1
LEFT JOIN
    Cities CTY ON B.CityId = CTY.Id AND CTY.Status = 1
LEFT JOIN
    Towns TWN ON B.TownId = TWN.Id AND TWN.Status = 1
LEFT JOIN
    #Users DDUpdetedUser ON D.UpdatedUserId = DDUpdetedUser.Id
LEFT JOIN
    Businesses BS ON D.BusinessId = BS.Id AND BS.Status = 1
WHERE 1=1;

-- Cleanup temp tables (keep MasterReportDocumentTable)
DROP TABLE #Documents;
DROP TABLE #TempDocuments;
DROP TABLE #UnionDocuments;
DROP TABLE #ProductCategory;
DROP TABLE #Users;
