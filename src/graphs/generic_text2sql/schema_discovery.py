"""
Runtime Schema Discovery Service.

Dynamically extracts table schema and metadata from the database
instead of using hard-coded dictionaries.
"""

import logging
import pyodbc
from typing import Dict, List, Optional, Set
from functools import lru_cache
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ColumnMetadata:
    """Metadata for a single database column."""
    column_name: str
    data_type: str
    is_nullable: bool
    max_length: Optional[int]
    description: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            "name": self.column_name,
            "type": self.data_type,
            "nullable": self.is_nullable,
            "max_length": self.max_length,
            "description": self.description or f"{self.column_name} ({self.data_type})"
        }


class SchemaDiscoveryService:
    """
    Service for discovering database schema at runtime.

    Features:
    - Extracts column metadata from INFORMATION_SCHEMA
    - Caches schema information for performance
    - Provides semantic search for relevant columns
    - Supports column descriptions from extended properties
    """

    def __init__(self, db_connection_string: str, target_table: str = "MasterReportDocumentTable"):
        """
        Initialize SchemaDiscoveryService.

        Args:
            db_connection_string: Database connection string
            target_table: Table name to discover schema for
        """
        self.db_connection_string = db_connection_string
        self.target_table = target_table
        self._schema_cache: Optional[Dict[str, ColumnMetadata]] = None

    def _get_connection(self) -> pyodbc.Connection:
        """
        Get database connection.

        Returns:
            pyodbc.Connection instance
        """
        from urllib.parse import urlparse, parse_qs

        if self.db_connection_string.startswith("mssql+pyodbc://"):
            parsed = urlparse(self.db_connection_string)
            query_params = parse_qs(parsed.query)
            driver = query_params.get("driver", ["ODBC Driver 17 for SQL Server"])[0]

            conn_str = (
                f"Driver={{{driver}}};"
                f"Server={parsed.hostname};"
                f"Database={parsed.path.lstrip('/')};"
                f"UID={parsed.username};"
                f"PWD={parsed.password};"
                "Trusted_Connection=no;"
            )
        else:
            conn_str = self.db_connection_string

        return pyodbc.connect(conn_str)

    def discover_schema(self, force_refresh: bool = False) -> Dict[str, ColumnMetadata]:
        """
        Discover table schema from database.

        Args:
            force_refresh: Force refresh cached schema

        Returns:
            Dictionary mapping column_name -> ColumnMetadata
        """
        # Return cached schema if available
        if self._schema_cache is not None and not force_refresh:
            logger.debug(f"Using cached schema for {self.target_table}")
            return self._schema_cache

        logger.info(f"Discovering schema for table: {self.target_table}")

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Query INFORMATION_SCHEMA for column metadata
            query = """
            SELECT
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.CHARACTER_MAXIMUM_LENGTH,
                ep.value AS DESCRIPTION
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id = OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME)
                AND ep.minor_id = c.ORDINAL_POSITION
                AND ep.name = 'MS_Description'
            WHERE c.TABLE_NAME = ?
            ORDER BY c.ORDINAL_POSITION
            """

            cursor.execute(query, (self.target_table,))

            schema = {}
            for row in cursor.fetchall():
                column_name = row[0]
                data_type = row[1]
                is_nullable = row[2] == 'YES'
                max_length = row[3]
                description = row[4]

                metadata = ColumnMetadata(
                    column_name=column_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    max_length=max_length,
                    description=description
                )

                schema[column_name] = metadata

            cursor.close()
            conn.close()

            # Cache the schema
            self._schema_cache = schema

            logger.info(f"Schema discovered: {len(schema)} columns found")
            return schema

        except Exception as e:
            logger.error(f"Error discovering schema: {e}", exc_info=True)
            raise

    def get_column_metadata(self, column_name: str) -> Optional[ColumnMetadata]:
        """
        Get metadata for a specific column.

        Args:
            column_name: Name of the column

        Returns:
            ColumnMetadata or None if not found
        """
        schema = self.discover_schema()
        return schema.get(column_name)

    def get_relevant_columns(self, column_names: Set[str]) -> Dict[str, str]:
        """
        Get metadata for a subset of columns (pruning).

        Args:
            column_names: Set of column names to retrieve

        Returns:
            Dictionary mapping column_name -> description
        """
        schema = self.discover_schema()

        relevant_metadata = {}
        for col_name in column_names:
            if col_name in schema:
                metadata = schema[col_name]
                relevant_metadata[col_name] = metadata.description or metadata.to_dict()['description']
            else:
                logger.warning(f"Column '{col_name}' not found in schema")

        return relevant_metadata

    def get_all_columns(self) -> List[str]:
        """
        Get list of all column names.

        Returns:
            List of column names
        """
        schema = self.discover_schema()
        return list(schema.keys())

    def enrich_with_business_context(self, column_metadata: Dict[str, str]) -> Dict[str, str]:
        """
        Enrich auto-discovered metadata with business context.

        This method overlays business-specific descriptions on top of
        schema-discovered metadata to provide richer context to the LLM.

        Args:
            column_metadata: Base metadata from schema discovery

        Returns:
            Enriched metadata with business context
        """
        # Business context overlay (from original COLUMN_METADATA_DETAILED)
        business_context = {
            "DocumentDate": "Satış tarihi (datetime)",
            "DayOfWeek": "Gün (1=Pazartesi...7=Pazar)",
            "Hour": "Saat (0-23)",
            "DocumentId": "Adisyon ID (guid). ÖNEMLİ: Adisyon toplam tutarı hesaplanırken GROUP BY DocumentId kullan!",
            "IsTableActive": "Masa durumu. 1: Açık masalar (ödemesi alınmamış, hala masada), 0: Kapalı masalar (ödemesi alınan)",
            "ProductName": "Ürün adı",
            "CategoryName": "Kategori adı",
            "MenuId": "Menü ürünü ID. NULL veya Empty Guid ise ana ürün, değer varsa menü içi seçenek (yan ürün)",
            "Quantity": "Satış miktarı (adet)",
            "RowAmount": "Satış tutarı (TL)",
            "DiscountAmountTotal": "İndirim tutarı (TL)",
            "DocumentDetailIsTreatWasteCancel": "İşlem tipi. Null: Default Normal satış, 1: İkram, 2: Zayi (fire), 3: İptal",
            "BranchName": "Şube adı",
            "BranchCityName": "Şehir",
            "BranchTownName": "İlçe",
            "DocumentTypeName": "İşlem tipi (Stok Çıkış, Fatura, vb.)",
            "DocumentKindName": "Satış kanalı (Paket Servis, Masa, vb.)",
            "DocumentTypeIsReturn": "İade mi? (0: Normal, 1: İade)",
            "CashierName": "Kasiyer adı",
            "DeliveryUserName": "Kurye adı",
            "CustomerName": "Müşteri adı",
            "TableNo": "Masa numarası",
        }

        # Overlay business context on discovered metadata
        enriched = column_metadata.copy()
        for col_name, business_desc in business_context.items():
            if col_name in enriched:
                # Replace with richer business description
                enriched[col_name] = business_desc

        return enriched

    @lru_cache(maxsize=128)
    def semantic_search_columns(self, query_hint: str) -> List[str]:
        """
        Find columns matching a semantic query hint.

        Uses fuzzy matching to find relevant columns based on user's
        natural language field hints.

        Args:
            query_hint: User's field hint (e.g., "tarih", "şube", "ürün")

        Returns:
            List of matching column names
        """
        # Semantic mapping (from field hints to column names)
        semantic_map = {
            "tarih": ["DocumentDate"],
            "şube": ["BranchName"],
            "ürün": ["ProductName"],
            "kategori": ["CategoryName"],
            "tutar": ["RowAmount"],
            "miktar": ["Quantity"],
            "müşteri": ["CustomerName"],
            "kasiyer": ["CashierName"],
            "şehir": ["BranchCityName"],
            "ilçe": ["BranchTownName"],
            "gün": ["DayOfWeek"],
            "saat": ["Hour"],
            "yıl": ["DocumentDate"],  # Will be transformed to YEAR(DocumentDate)
            "ay": ["DocumentDate"],   # Will be transformed to MONTH(DocumentDate)
            "işlem_tipi": ["DocumentDetailIsTreatWasteCancel"],
            "masa_durumu": ["IsTableActive"],
            "menü_id": ["MenuId"],
            "adisyon_id": ["DocumentId"],
            "masa": ["TableNo"],
            "kurye": ["DeliveryUserName"],
        }

        query_hint_lower = query_hint.lower()
        matches = semantic_map.get(query_hint_lower, [])

        if not matches:
            logger.warning(f"No semantic match found for hint: {query_hint}")

        return matches


# Singleton instance
_schema_discovery_service: Optional[SchemaDiscoveryService] = None


async def get_schema_discovery_service(db_connection_string: str) -> SchemaDiscoveryService:
    """
    Get or create SchemaDiscoveryService singleton.

    Args:
        db_connection_string: Database connection string

    Returns:
        SchemaDiscoveryService instance
    """
    global _schema_discovery_service

    if _schema_discovery_service is None:
        logger.info("Initializing SchemaDiscoveryService...")
        _schema_discovery_service = SchemaDiscoveryService(db_connection_string)
        # Warm up cache
        _schema_discovery_service.discover_schema()
        logger.info("SchemaDiscoveryService initialized successfully")

    return _schema_discovery_service
