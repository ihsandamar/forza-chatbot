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
    
    def __init__(self, db_connection_string: str):
        # MSSQL+pyodbc DSN'yi pyodbc connection string'e çevir
        self.db_conn = self._parse_mssql_dsn(db_connection_string)
        self.executor = ThreadPoolExecutor(max_workers=5)

        # Kolon konfigürasyonu
        self.column_config = {
            # Tam cache (az değer, sık kullanım)
            "BusinessName": {"strategy": "full_cache", "max": 50, "ttl": 1440},
            "BusinessType": {"strategy": "full_cache", "max": 20, "ttl": 1440},
            "BranchName": {"strategy": "full_cache", "max": 500, "ttl": 60},
            "BranchGroupName": {"strategy": "full_cache", "max": 100, "ttl": 1440},
            "BranchCityName": {"strategy": "full_cache", "max": 81, "ttl": 1440},
            "BranchTownName": {"strategy": "full_cache", "max": 1000, "ttl": 1440},
            "CategoryName": {"strategy": "full_cache", "max": 100, "ttl": 60},
            "DocumentTypeName": {"strategy": "full_cache", "max": 20, "ttl": 1440},
            "DocumentKindName": {"strategy": "full_cache", "max": 20, "ttl": 1440},
            "ProductUnitName": {"strategy": "full_cache", "max": 50, "ttl": 1440},
            "CashierName": {"strategy": "full_cache", "max": 200, "ttl": 120},
            "TableNo": {"strategy": "full_cache", "max": 200, "ttl": 120},
            "ChoiceName": {"strategy": "full_cache", "max": 100, "ttl": 1440},
            "MainChoiceName": {"strategy": "full_cache", "max": 50, "ttl": 1440},
            "ProductName": {"strategy": "full_cache", "max": 200, "ttl": 1440},
            "CustomerName": {"strategy": "full_cache", "max": 200, "ttl": 1440},

            # DB arama (çok değer)
            # "ProductName": {"strategy": "db_search", "max": 10},
            # "CustomerName": {"strategy": "db_search", "max": 10},
        }
        
        # Cache storage
        self.cache: Dict[str, Dict] = {}

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
        """Uygulama başlangıcında cache'i doldur"""
        logger.info("ValueResolver baslatiliyor...")

        for column, config in self.column_config.items():
            if config["strategy"] == "full_cache":
                await self._load_to_cache(column)

        logger.info("ValueResolver hazir!")
    
    async def _load_to_cache(self, column: str):
        """Bir kolonun değerlerini cache'e yükle"""
        config = self.column_config[column]

        query = f"""
            SELECT DISTINCT TOP {config['max']} {column}
            FROM MasterReportDocumentTable
            WHERE {column} IS NOT NULL
        """

        loop = asyncio.get_event_loop()
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
            conn = pyodbc.connect(self.db_conn)
            cursor = conn.cursor()
            cursor.execute(query)
            rows = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return rows
        except pyodbc.OperationalError as e:
            # Connection/network errors
            error_msg = str(e)
            if '08001' in error_msg or 'timeout' in error_msg.lower() or 'connection' in error_msg.lower():
                logger.error(f"[DB CONNECTION ERROR] SQL Server baglantisi yapilamiyor ({column})")
                logger.error(f"  Hata: Named Pipes/Network hatasi")
                logger.error(f"  Connection string: {self.db_conn[:60]}...")
                logger.error(f"  Cozum onerileri:")
                logger.error(f"    1. SQL Server calistigindan emin olun")
                logger.error(f"    2. config.yaml dosyasindaki connection string'i kontrol edin")
                logger.error(f"    3. SQL Server remote connections kabul ediyor olsun")
                logger.error(f"    4. Firewall ayarlarini kontrol edin (port 1433)")
                logger.error(f"    5. Network connectivity test edin: ping/telnet server_ip 1433")
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
        config = self.column_config.get(column)
        
        if not config:
            return None
        
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
            FROM MasterReportDocumentTable
            WHERE {column} LIKE '%{search_term}%'
        """

        loop = asyncio.get_event_loop()
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


# ============================================
# KULLANIM ÖRNEĞİ
# ============================================

async def main():
    # Servis oluştur
    resolver = ValueResolverService("mssql+pyodbc://sa:Vega1234@DESKTOP-TIEAGO8/harbi?driver=ODBC+Driver+17+for+SQL+Server")
    
    # Başlangıçta cache'i doldur
    await resolver.initialize()
    
    # Test
    tests = [
        ("dürüm", "CategoryName"),
        ("durumler", "CategoryName"),
        ("DÜRÜMLER", "CategoryName"),
        ("TUNALI", "BranchName"),
        ("tnali", "BranchName"),
        ("ankara", "BranchCityName"),
        ("klasik dürüm", "ProductName"),  # DB'den arayacak
        ("tavuk döner", "ProductName"),   # DB'den arayacak
    ]
    
    print("\n=== Test Sonuçları ===\n")
    for user_input, column in tests:
        result = await resolver.resolve(user_input, column)
        if result:
            print(f"'{user_input}' ({column})")
            print(f"  → '{result['resolved']}' (güven: {result['confidence']}%)")
        else:
            print(f"'{user_input}' ({column}) → BULUNAMADI")
        print()