from rapidfuzz import process, fuzz
from sentence_transformers import SentenceTransformer
import pyodbc
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, List
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import asyncio
import unicodedata

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
        # mssql+pyodbc://user:pass@host/database?driver=DRIVER
        from urllib.parse import urlparse, parse_qs

        if dsn.startswith("mssql+pyodbc://"):
            parsed = urlparse(dsn)
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
        print("🚀 ValueResolver başlatılıyor...")
        
        for column, config in self.column_config.items():
            if config["strategy"] == "full_cache":
                await self._load_to_cache(column)
        
        print("✅ ValueResolver hazır!")
    
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

        print(f"  ✓ {column}: {len(values)} değer cache'lendi")

    def _fetch_from_db(self, query: str, column: str) -> list:
        """Veritabanından veri çek (synchronous)"""
        conn = pyodbc.connect(self.db_conn)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows
    
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
        """Cache'den fuzzy match ile çöz - Türkçe karakter desteği ile"""

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

        # Birden fazla scorer ile dene (en iyisini al)
        scorers = [
            fuzz.token_sort_ratio,  # Kelime sırası önemsiz
            fuzz.token_set_ratio,   # Kısmi eşleşme
            fuzz.partial_ratio,     # Substring match
            fuzz.ratio,             # Tam eşleşme
        ]

        best_result = None
        best_score = 0

        for scorer in scorers:
            result = process.extractOne(
                normalized_input,
                normalized_list,
                scorer=scorer,
                score_cutoff=max(threshold - 15, 60)  # Daha düşük threshold
            )

            if result and result[1] > best_score:
                best_score = result[1]
                # Normalize edilmiş değerden orijinal değeri bul
                original_value = normalized_choices[result[0]]
                best_result = (original_value, result[1])

        if best_result:
            return {
                "original": user_input,
                "resolved": best_result[0],
                "confidence": best_result[1],
                "column": column
            }

        return None
    
    async def _resolve_from_db(self, user_input: str, column: str, threshold: int) -> Optional[Dict]:
        """DB'de LIKE ile arayıp fuzzy match ile seç - Türkçe karakter desteği ile"""

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

        scorers = [fuzz.token_sort_ratio, fuzz.token_set_ratio, fuzz.partial_ratio, fuzz.ratio]

        best_result = None
        best_score = 0

        for scorer in scorers:
            result = process.extractOne(
                normalized_input,
                normalized_list,
                scorer=scorer,
                score_cutoff=max(threshold - 15, 60)
            )

            if result and result[1] > best_score:
                best_score = result[1]
                original_value = normalized_choices[result[0]]
                best_result = (original_value, result[1])

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