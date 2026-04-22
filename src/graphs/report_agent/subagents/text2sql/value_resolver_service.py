from rapidfuzz import process, fuzz
import pyodbc
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, List
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import asyncio
import unicodedata
import logging

logger = logging.getLogger(__name__)

class ValueResolverService:
    """
    Kullanıcı inputlarını veritabanı değerlerine çeviren servis
    """

    def __init__(self, db_connection_string: str, table_name: str = "MasterReportDocumentTable"):
        # MSSQL+pyodbc DSN'yi pyodbc connection string'e çevir
        self.db_conn = self._parse_mssql_dsn(db_connection_string)
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.table_name = table_name

        logger.info(f"ValueResolverService initialized with table: {table_name}")

        # Kolon konfigürasyonu - dinamik olarak tabloya göre oluşturulacak
        self.column_config = {}

        # Cache storage
        self.cache: Dict[str, Dict] = {}

        # Semantic column name mapping (Turkish/natural language → DB column)
        self.column_semantic_map: Dict[str, str] = {}
        self.column_reverse_map: Dict[str, List[str]] = {}  # DB column → semantic aliases

        self._init_column_semantic_mapping()

    def _parse_mssql_dsn(self, dsn: str) -> str:
        """mssql+pyodbc DSN'yi pyodbc connection string'e çevir"""
        # mssql+pyodbc://user:pass@host:port/database?driver=DRIVER
        from urllib.parse import urlparse, parse_qs

        if dsn.startswith("mssql+pyodbc://"):
            parsed = urlparse(dsn)
            query_params = parse_qs(parsed.query)
            driver = query_params.get("driver", ["ODBC Driver 17 for SQL Server"])[0]

            # Build server string with port if specified
            server = parsed.hostname
            if parsed.port:
                server = f"{server},{parsed.port}"

            conn_str = (
                f"Driver={{{driver}}};"
                f"Server={server};"
                f"Database={parsed.path.lstrip('/')};"
                f"UID={parsed.username};"
                f"PWD={parsed.password};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=yes;"
                f"Connection Timeout=30"
            )
            return conn_str
        return dsn

    def _discover_table_schema(self) -> List[str]:
        """
        Tablodaki string kolonları otomatik keşfet.

        Returns:
            List of column names that are string types (varchar, nvarchar, char, nchar, text)
        """
        try:
            conn = pyodbc.connect(self.db_conn, timeout=30)
            conn.timeout = 30
            cursor = conn.cursor()

            # Get table schema from INFORMATION_SCHEMA
            query = """
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = ?
                AND DATA_TYPE IN ('varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext')
                ORDER BY ORDINAL_POSITION
            """

            cursor.execute(query, (self.table_name,))
            columns = [row[0] for row in cursor.fetchall()]

            cursor.close()
            conn.close()

            logger.info(f"Discovered {len(columns)} string columns in {self.table_name}: {', '.join(columns)}")
            return columns

        except Exception as e:
            logger.error(f"Error discovering table schema: {e}")
            return []

    def _determine_cache_strategy(self, column: str) -> Dict:
        """
        Kolonun distinct value sayısına göre otomatik cache stratejisi belirle.

        Args:
            column: Column name

        Returns:
            Dict with strategy config (strategy, max, ttl)
        """
        try:
            conn = pyodbc.connect(self.db_conn, timeout=10)
            conn.timeout = 20
            cursor = conn.cursor()
            cursor.execute("SET LOCK_TIMEOUT 3000")  # fail fast if table is locked (3s)

            # Count distinct values - Escape table name for SQL Server
            query = f"SELECT COUNT(DISTINCT {column}) FROM [{self.table_name}] WHERE {column} IS NOT NULL"
            cursor.execute(query)
            distinct_count = cursor.fetchone()[0]

            cursor.close()
            conn.close()

            # Determine strategy based on distinct count
            if distinct_count <= 20:
                # Very few values - full cache with long TTL
                config = {"strategy": "full_cache", "max": distinct_count + 10, "ttl": 1440}  # 24 hours
            elif distinct_count <= 100:
                # Moderate values - full cache with medium TTL
                config = {"strategy": "full_cache", "max": distinct_count + 20, "ttl": 240}  # 4 hours
            elif distinct_count <= 500:
                # Many values - full cache with short TTL
                config = {"strategy": "full_cache", "max": 500, "ttl": 60}  # 1 hour
            elif distinct_count <= 1000:
                # Very many values - partial cache
                config = {"strategy": "full_cache", "max": 1000, "ttl": 30}  # 30 minutes
            else:
                # Too many values - use DB search only (no initial cache)
                config = {"strategy": "db_search", "max": 20, "ttl": 15}  # 15 minutes

            logger.info(f"Column '{column}': {distinct_count} distinct values → strategy={config['strategy']}, max={config['max']}")
            return config

        except Exception as e:
            logger.error(f"Error determining cache strategy for {column}: {e}")
            # Fallback to safe defaults
            return {"strategy": "db_search", "max": 20, "ttl": 15}

    def _normalize_turkish(self, text: str) -> str:
        """Türkçe karakterleri normalize et ve küçük harfe çevir"""
        # Türkçe karakter eşleştirmeleri
        turkish_map = {
            'ı': 'i', 'İ': 'i', 'I': 'i',
            'ğ': 'g', 'Ğ': 'g',
            'ü': 'u', 'Ü': 'u',
            'ş': 's', 'Ş': 's',
            'ö': 'o', 'Ö': 'o',
            'ç': 'c', 'Ç': 'c',
        }

        # Küçük harfe çevir
        text = text.lower()

        # Türkçe karakterleri değiştir
        for tr_char, en_char in turkish_map.items():
            text = text.replace(tr_char, en_char)

        return text

    async def initialize(self):
        """
        Uygulama başlangıcında tabloyu keşfet ve cache'i doldur.

        Adımlar:
        1. Tablo şemasını keşfet (string kolonlar)
        2. Her kolon için cache stratejisi belirle
        3. full_cache stratejisi olan kolonları cache'e yükle
        4. Semantik kolon mapping'ini hazırla
        """
        logger.info(f"ValueResolver baslatiliyor (table: {self.table_name})...")

        # 1. Tablodaki string kolonları keşfet
        columns = self._discover_table_schema()

        if not columns:
            logger.warning(f"No string columns found in table {self.table_name}")
            logger.info("ValueResolver initialized with empty config")
            return

        # 2. Her kolon için otomatik cache stratejisi belirle
        logger.info(f"Determining cache strategies for {len(columns)} columns...")
        for column in columns:
            self.column_config[column] = self._determine_cache_strategy(column)

        # 3. full_cache stratejisi olan kolonları cache'e yükle
        cache_count = 0
        for column, config in self.column_config.items():
            if config["strategy"] == "full_cache":
                await self._load_to_cache(column)
                cache_count += 1

        logger.info(f"ValueResolver hazir! ({cache_count}/{len(columns)} columns cached)")
    
    async def _load_to_cache(self, column: str):
        """Bir kolonun değerlerini cache'e yükle"""
        config = self.column_config[column]

        query = f"""
            SELECT DISTINCT TOP {config['max']} {column}
            FROM [{self.table_name}]
            WHERE {column} IS NOT NULL
        """

        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(self.executor, self._fetch_from_db, query, column)

        values = {row for row in rows if row}

        self.cache[column] = {
            "values": values,
            "fetched_at": datetime.now(),
            "ttl": config["ttl"]
        }

        logger.info(f"  OK {column}: {len(values)} deger cache'lendi")

    def _fetch_from_db(self, query: str, column: str) -> list:
        """Veritabanından veri çek (synchronous) with error handling"""
        try:
            conn = pyodbc.connect(self.db_conn, timeout=10)
            conn.timeout = 20
            cursor = conn.cursor()
            cursor.execute("SET LOCK_TIMEOUT 3000")  # fail fast if table is locked (3s)
            cursor.execute(query)
            rows = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return rows
        except pyodbc.OperationalError as e:
            error_msg = str(e)
            if 'HYT00' in error_msg or ('timeout' in error_msg.lower() and '08001' not in error_msg):
                logger.warning(f"[VALUE_RESOLVER] Query timeout for column '{column}' — table may be large or still loading")
            elif '08001' in error_msg or 'connection' in error_msg.lower():
                logger.error(f"[DB CONNECTION ERROR] SQL Server baglantisi yapilamiyor ({column})")
                logger.error(f"  Connection string: {self.db_conn[:60]}...")
            else:
                logger.error(f"DB operational error for {column}: {e}")
            return []
        except Exception as e:
            logger.error(f"DB error for {column}: {e}")
            return []
    
    async def resolve(self, user_input: str, column: str, threshold: int = 75) -> Optional[Dict]:
        """
        Ana metod: Kullanıcı inputunu veritabanı değerine çevir

        Returns:
            {
                "original": "kullanıcının yazdığı",
                "resolved": "DB'deki değer",
                "confidence": 85,
                "column": "CategoryName"
            }
        """
        # Eğer kolon henüz keşfedilmemişse, otomatik olarak strateji belirle
        if column not in self.column_config:
            logger.info(f"Column '{column}' not in config, auto-discovering strategy...")
            loop = asyncio.get_running_loop()
            self.column_config[column] = await loop.run_in_executor(
                self.executor, self._determine_cache_strategy, column
            )

            # Eğer full_cache stratejisi seçildiyse, hemen cache'e yükle
            if self.column_config[column]["strategy"] == "full_cache":
                await self._load_to_cache(column)

        config = self.column_config[column]

        if config["strategy"] == "full_cache":
            return await self._resolve_from_cache(user_input, column, threshold)

        elif config["strategy"] == "db_search":
            return await self._resolve_from_db(user_input, column, threshold)
        
        return None
    
    async def _resolve_from_cache(self, user_input: str, column: str, threshold: int) -> Optional[Dict]:
        """Cache'den fuzzy match ile çöz - Türkçe karakter desteği ve exact match priority ile"""

        # Cache'i kontrol et, gerekirse yenile
        await self._ensure_cache_fresh(column)

        cached = self.cache.get(column, {})
        values = list(cached.get("values", []))

        if not values:
            return None

        # Türkçe normalize edilmiş input
        normalized_input = self._normalize_turkish(user_input)

        # Her değer için normalize edilmiş versiyonları oluştur
        normalized_choices = {self._normalize_turkish(val): val for val in values}
        normalized_list = list(normalized_choices.keys())

        # 1. EXACT MATCH kontrolü (öncelikli!)
        for normalized_val, original_val in normalized_choices.items():
            if normalized_input == normalized_val:
                return {
                    "original": user_input,
                    "resolved": original_val,
                    "confidence": 100,
                    "column": column
                }

        # 2. Kelime sayısını hesapla (penalty için)
        input_word_count = len(normalized_input.split())

        # 3. Birden fazla scorer ile fuzzy match (öncelik sırası önemli!)
        scorers = [
            (fuzz.ratio, 1.0),              # Tam eşleşme (en yüksek öncelik)
            (fuzz.token_sort_ratio, 0.95),  # Kelime sırası önemsiz
            (fuzz.token_set_ratio, 0.90),   # Kısmi eşleşme
            (fuzz.partial_ratio, 0.80),     # Substring match (en düşük öncelik)
        ]

        best_result = None
        best_weighted_score = 0

        for scorer, weight in scorers:
            result = process.extractOne(
                normalized_input,
                normalized_list,
                scorer=scorer,
                score_cutoff=max(threshold - 15, 60)
            )

            if result:
                normalized_match = result[0]
                score = result[1]

                # Kelime sayısı farkını penalize et
                match_word_count = len(normalized_match.split())
                word_count_diff = abs(input_word_count - match_word_count)

                # Kelime sayısı farkı 2'den fazlaysa penalty uygula
                if word_count_diff > 2:
                    score *= 0.85
                elif word_count_diff > 1:
                    score *= 0.92
                elif word_count_diff > 0:
                    score *= 0.97

                # Weighted score hesapla
                weighted_score = score * weight

                if weighted_score > best_weighted_score:
                    best_weighted_score = weighted_score
                    original_value = normalized_choices[normalized_match]
                    best_result = (original_value, int(score))

        if best_result:
            return {
                "original": user_input,
                "resolved": best_result[0],
                "confidence": best_result[1],
                "column": column
            }

        return None
    
    async def _resolve_from_db(self, user_input: str, column: str, threshold: int) -> Optional[Dict]:
        """DB'de LIKE ile arayıp fuzzy match ile seç - Türkçe karakter desteği ve exact match priority ile"""

        config = self.column_config[column]
        search_term = user_input.replace("'", "''")  # SQL injection koruması

        query = f"""
            SELECT DISTINCT TOP {config['max']} {column}
            FROM [{self.table_name}]
            WHERE {column} LIKE '%{search_term}%'
        """

        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(self.executor, self._fetch_from_db, query, column)

        if not rows:
            return None

        candidates = [row for row in rows if row]

        if len(candidates) == 1:
            return {
                "original": user_input,
                "resolved": candidates[0],
                "confidence": 100,
                "column": column
            }

        # Birden fazla sonuç: Türkçe normalize ederek fuzzy match
        normalized_input = self._normalize_turkish(user_input)
        normalized_choices = {self._normalize_turkish(val): val for val in candidates}
        normalized_list = list(normalized_choices.keys())

        # 1. EXACT MATCH kontrolü
        for normalized_val, original_val in normalized_choices.items():
            if normalized_input == normalized_val:
                return {
                    "original": user_input,
                    "resolved": original_val,
                    "confidence": 100,
                    "column": column
                }

        # 2. Kelime sayısı hesapla
        input_word_count = len(normalized_input.split())

        # 3. Weighted fuzzy match
        scorers = [
            (fuzz.ratio, 1.0),
            (fuzz.token_sort_ratio, 0.95),
            (fuzz.token_set_ratio, 0.90),
            (fuzz.partial_ratio, 0.80),
        ]

        best_result = None
        best_weighted_score = 0

        for scorer, weight in scorers:
            result = process.extractOne(
                normalized_input,
                normalized_list,
                scorer=scorer,
                score_cutoff=max(threshold - 15, 60)
            )

            if result:
                normalized_match = result[0]
                score = result[1]

                # Kelime sayısı penalty
                match_word_count = len(normalized_match.split())
                word_count_diff = abs(input_word_count - match_word_count)

                if word_count_diff > 2:
                    score *= 0.85
                elif word_count_diff > 1:
                    score *= 0.92
                elif word_count_diff > 0:
                    score *= 0.97

                weighted_score = score * weight

                if weighted_score > best_weighted_score:
                    best_weighted_score = weighted_score
                    original_value = normalized_choices[normalized_match]
                    best_result = (original_value, int(score))

        if best_result:
            return {
                "original": user_input,
                "resolved": best_result[0],
                "confidence": best_result[1],
                "column": column
            }

        return None
    
    async def _ensure_cache_fresh(self, column: str):
        """Cache'in güncel olduğundan emin ol"""
        cached = self.cache.get(column)

        if not cached:
            await self._load_to_cache(column)
            return

        ttl = timedelta(minutes=cached["ttl"])
        if datetime.now() - cached["fetched_at"] > ttl:
            await self._load_to_cache(column)

    def _init_column_semantic_mapping(self):
        """
        Initialize semantic column name mapping.
        Maps Turkish/natural language column names to actual database columns.

        This prevents errors like "Invalid column name 'RowAmount'" by ensuring
        semantic column names (e.g., "Tutar", "SatisTutari") are resolved to
        actual DB columns (e.g., "RowAmount").
        """
        # Semantic mapping: natural language → DB column name
        semantic_aliases = {
            # Tutar/Amount related
            "tutar": "RowAmount",
            "satistutar": "RowAmount",
            "satistutari": "RowAmount",
            "satis_tutar": "RowAmount",
            "amount": "RowAmount",
            "rowamount": "RowAmount",
            "toplam": "RowAmount",
            "toplamtutar": "RowAmount",
            "totalamount": "RowAmount",
            "revenue": "RowAmount",

            # Miktar/Quantity related
            "miktar": "Quantity",
            "adet": "Quantity",
            "quantity": "Quantity",
            "qty": "Quantity",

            # Tarih/Date related
            "tarih": "DocumentDate",
            "tarihsaat": "DocumentDate",
            "date": "DocumentDate",
            "datetime": "DocumentDate",
            "documentdate": "DocumentDate",

            # Şube/Branch related
            "sube": "BranchName",
            "subeadi": "BranchName",
            "sube_adi": "BranchName",
            "branch": "BranchName",
            "branchname": "BranchName",

            # Ürün/Product related
            "urun": "ProductName",
            "urunadi": "ProductName",
            "urun_adi": "ProductName",
            "product": "ProductName",
            "productname": "ProductName",

            # Kategori/Category related
            "kategori": "CategoryName",
            "kategoriadi": "CategoryName",
            "kategori_adi": "CategoryName",
            "category": "CategoryName",
            "categoryname": "CategoryName",

            # Şehir/City related
            "sehir": "BranchCityName",
            "sehiradi": "BranchCityName",
            "sehir_adi": "BranchCityName",
            "city": "BranchCityName",
            "cityname": "BranchCityName",
            "branchcity": "BranchCityName",
            "branchcityname": "BranchCityName",

            # Müşteri/Customer related
            "musteri": "CustomerName",
            "musteriadi": "CustomerName",
            "musteri_adi": "CustomerName",
            "customer": "CustomerName",
            "customername": "CustomerName",

            # Kasiyer/Cashier related
            "kasiyer": "CashierName",
            "cashier": "CashierName",
            "cashiername": "CashierName",

            # İndirim/Discount related
            "indirim": "DiscountAmountTotal",
            "indirimimtutar": "DiscountAmountTotal",
            "discount": "DiscountAmountTotal",
            "discountamounttotal": "DiscountAmountTotal",
        }

        # Normalize keys (lowercase, remove underscores/spaces)
        for alias, db_column in semantic_aliases.items():
            normalized_alias = self._normalize_turkish(alias.replace("_", "").replace(" ", ""))
            self.column_semantic_map[normalized_alias] = db_column

            # Reverse mapping
            if db_column not in self.column_reverse_map:
                self.column_reverse_map[db_column] = []
            self.column_reverse_map[db_column].append(alias)

        logger.info(f"[VALUE_RESOLVER] Semantic column mapping initialized: {len(self.column_semantic_map)} aliases")

    def resolve_column_name(self, semantic_name: str) -> Optional[str]:
        """Delegate to ColumnResolver — single source of truth for column normalization."""
        from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
        if not hasattr(self, "_column_resolver"):
            db_cols = list(self.column_config.keys()) if self.column_config else []
            self._column_resolver = ColumnResolver(db_columns=db_cols)
        return self._column_resolver.resolve(semantic_name)

    def get_column_aliases(self, db_column: str) -> List[str]:
        """
        Get all semantic aliases for a database column.

        Args:
            db_column: Database column name

        Returns:
            List of semantic aliases
        """
        return self.column_reverse_map.get(db_column, [])
