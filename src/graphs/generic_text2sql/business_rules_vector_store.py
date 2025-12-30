"""
Business Rules Vector Store
============================

Text-to-SQL sistemleri için iş kurallarını semantic olarak arayan ve
en alakalı kuralları bulan vector store sınıfı.

Özellikler:
- Sadece description + modules embed edilir (SQL değil)
- SQL bileşenleri metadata'da saklanır
- Default kurallar ayrı collection'da
- Hybrid search (semantic + keyword)
- SQL merge mantığı
- Similarity threshold (>0.7)
- Table-aware filtering
"""

import json
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class BusinessRulesVectorStore:
    """
    İş kurallarını vector store'da tutan ve semantic search yapan sınıf.
    """

    def __init__(
        self,
        rules_file_path: str,
        persist_directory: str = "./chroma_db",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        similarity_threshold: float = 0.7
    ):
        """
        Args:
            rules_file_path: business_rules.json dosya yolu
            persist_directory: ChromaDB persist klasörü
            embedding_model: Kullanılacak embedding modeli
            similarity_threshold: Minimum benzerlik skoru (0-1)
        """
        self.rules_file_path = Path(rules_file_path)
        self.similarity_threshold = similarity_threshold

        # ChromaDB setup
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))

        # Embedding function
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )

        # Collections
        self.rules_collection = None
        self.default_rules_collection = None

        # Rules data
        self.rules_data = self._load_rules()

    def _load_rules(self) -> Dict[str, Any]:
        """business_rules.json dosyasını yükle"""
        with open(self.rules_file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _prepare_embedding_text(self, rule: Dict[str, Any]) -> str:
        """
        Embed edilecek text'i hazırla

        🔴 KRITIK: Sadece description + modules embed edilir, SQL değil!
        """
        description = rule['description']
        modules = ", ".join(rule['modules'])

        # Semantic meaning için text
        embedding_text = f"{description}. Anahtar kelimeler: {modules}"
        return embedding_text

    def _prepare_metadata(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """
        🔴 KRITIK: SQL bileşenlerini metadata olarak sakla
        """
        # SQL components'i flat metadata'ya çevir
        metadata = {
            "rule_id": rule['id'],
            "description": rule['description'],
            "modules": json.dumps(rule['modules'], ensure_ascii=False),
            "related_tables": json.dumps(rule['related_tables'], ensure_ascii=False),
            "is_default": str(rule['is_default']),  # ChromaDB string olarak ister

            # SQL components (metadata olarak)
            "sql_aggregation": rule['sql'].get('aggregation') or "",
            "sql_filter": rule['sql'].get('filter') or "",
            "sql_group_by": rule['sql'].get('group_by') or "",
            "sql_select": rule['sql'].get('select') or "",
            "sql_join": rule['sql'].get('join') or "",
            "sql_having": rule['sql'].get('having') or "",
        }

        return metadata

    def initialize_collections(self, force_recreate: bool = False):
        """
        Vector store collections'ları oluştur

        🟡 ÖNEMLI: Default kuralları ayrı collection'da tut
        """
        logger.info("Initializing ChromaDB collections...")

        # Eğer var olan collections'ı sil (force recreate)
        if force_recreate:
            try:
                self.client.delete_collection("business_rules")
                self.client.delete_collection("default_business_rules")
            except:
                pass

        # 1. Normal rules collection
        self.rules_collection = self.client.get_or_create_collection(
            name="business_rules",
            embedding_function=self.embedding_function,
            metadata={"description": "Business logic rules for Text-to-SQL"}
        )

        # 2. Default rules collection (her sorguya eklenir)
        self.default_rules_collection = self.client.get_or_create_collection(
            name="default_business_rules",
            embedding_function=self.embedding_function,
            metadata={"description": "Default rules applied to all queries"}
        )

        logger.info(f"✅ Collections created successfully")

    def index_rules(self):
        """
        business_rules.json'daki tüm kuralları index'e

        🔴 KRITIK: Description + modules embed et, SQL metadata'da
        """
        rules = self.rules_data['business_logic_rules']

        normal_rules = []
        default_rules = []

        for rule in rules:
            embedding_text = self._prepare_embedding_text(rule)
            metadata = self._prepare_metadata(rule)

            rule_data = {
                'id': rule['id'],
                'text': embedding_text,
                'metadata': metadata
            }

            if rule['is_default']:
                default_rules.append(rule_data)
            else:
                normal_rules.append(rule_data)

        # Index normal rules
        if normal_rules:
            self.rules_collection.add(
                ids=[r['id'] for r in normal_rules],
                documents=[r['text'] for r in normal_rules],
                metadatas=[r['metadata'] for r in normal_rules]
            )
            logger.info(f"✅ Indexed {len(normal_rules)} normal rules")

        # Index default rules
        if default_rules:
            self.default_rules_collection.add(
                ids=[r['id'] for r in default_rules],
                documents=[r['text'] for r in default_rules],
                metadatas=[r['metadata'] for r in default_rules]
            )
            logger.info(f"✅ Indexed {len(default_rules)} default rules")

    def search_rules(
        self,
        query: str,
        n_results: int = 5,
        include_defaults: bool = True,
        table_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        🟡 ÖNEMLI: Hybrid search - semantic + keyword

        Args:
            query: Kullanıcı sorusu
            n_results: Kaç kural döndürülecek
            include_defaults: Default kuralları da dahil et mi?
            table_filter: Belirli tablolara filtrele (table-aware)

        Returns:
            Alakalı kuralların listesi
        """
        results = []

        # 1. Default rules'ı al (her zaman)
        if include_defaults:
            default_results = self.default_rules_collection.query(
                query_texts=[query],
                n_results=100  # Hepsini al
            )

            for i, rule_id in enumerate(default_results['ids'][0]):
                metadata = default_results['metadatas'][0][i]
                distance = default_results['distances'][0][i]

                # Distance to similarity (1 - normalized distance)
                similarity = 1 - distance

                results.append({
                    'rule_id': rule_id,
                    'similarity': similarity,
                    'metadata': metadata,
                    'is_default': True
                })

        # 2. Semantic search - normal rules
        where_filter = None

        # 🢧 Table-aware filtering
        if table_filter:
            # ChromaDB'de array containment için workaround
            # related_tables JSON string içinde arama yapalım
            pass  # Aşağıda manuel filtreleyeceğiz

        search_results = self.rules_collection.query(
            query_texts=[query],
            n_results=n_results * 2,  # Daha fazla al, sonra filtrele
            where=where_filter
        )

        for i, rule_id in enumerate(search_results['ids'][0]):
            metadata = search_results['metadatas'][0][i]
            distance = search_results['distances'][0][i]

            # Distance to similarity
            similarity = 1 - distance

            # 🟡 ÖNEMLI: Similarity threshold uygula
            if similarity < self.similarity_threshold:
                continue

            # 🢧 Table-aware filtering (manual)
            if table_filter:
                related_tables = json.loads(metadata['related_tables'])
                # "*" means all tables
                if "*" not in related_tables:
                    # Check if any table matches
                    if not any(table in related_tables for table in table_filter):
                        continue

            results.append({
                'rule_id': rule_id,
                'similarity': similarity,
                'metadata': metadata,
                'is_default': False
            })

        # Similarity'ye göre sırala ve limit uygula
        results = sorted(results, key=lambda x: x['similarity'], reverse=True)

        # Default olmayan kuralları limit'le
        non_default = [r for r in results if not r['is_default']][:n_results]
        defaults = [r for r in results if r['is_default']]

        return defaults + non_default

    def keyword_search(
        self,
        keywords: List[str],
        n_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        🟡 ÖNEMLI: Keyword-based search (hybrid search için)

        Args:
            keywords: Aranacak anahtar kelimeler
            n_results: Kaç sonuç döndürülecek
        """
        results = []

        # Her keyword için ara
        for keyword in keywords:
            search_results = self.rules_collection.get(
                where_document={"$contains": keyword.lower()}
            )

            for i, rule_id in enumerate(search_results['ids']):
                metadata = search_results['metadatas'][i]

                results.append({
                    'rule_id': rule_id,
                    'similarity': 0.9,  # Keyword match yüksek skor
                    'metadata': metadata,
                    'is_default': False,
                    'match_type': 'keyword'
                })

        # Deduplicate
        seen = set()
        unique_results = []
        for r in results:
            if r['rule_id'] not in seen:
                seen.add(r['rule_id'])
                unique_results.append(r)

        return unique_results[:n_results]

    def merge_sql_components(
        self,
        rules: List[Dict[str, Any]],
        date_column: str = "created_at",
        amount_column: str = "amount"
    ) -> Dict[str, str]:
        """
        🔴 KRITIK: Birden fazla kuraldan gelen SQL bileşenlerini birleştir

        Args:
            rules: search_rules() veya keyword_search() sonuçları
            date_column: Placeholder {date_column} için değer
            amount_column: Placeholder {amount_column} için değer

        Returns:
            Merged SQL components
        """
        merged = {
            'aggregation': [],
            'filter': [],
            'group_by': [],
            'select': [],
            'join': [],
            'having': []
        }

        seen_components = {
            'filter': set(),
            'join': set(),
            'group_by': set(),
            'select': set()
        }

        for rule in rules:
            metadata = rule['metadata']

            # Her SQL component'i ekle
            for component in ['aggregation', 'filter', 'group_by', 'select', 'join', 'having']:
                value = metadata.get(f'sql_{component}', '').strip()

                if not value:
                    continue

                # Placeholder replacement
                value = value.replace('{date_column}', date_column)
                value = value.replace('{amount_column}', amount_column)

                # Duplicate kontrolü (bazı componentler için)
                if component in seen_components:
                    if value in seen_components[component]:
                        continue
                    seen_components[component].add(value)

                merged[component].append(value)

        # Birleştir
        final_sql = {}

        # Aggregation: ilkini al (genelde tek olur)
        if merged['aggregation']:
            final_sql['aggregation'] = merged['aggregation'][0]

        # Filter: AND ile birleştir
        if merged['filter']:
            final_sql['filter'] = " AND ".join([f"({f})" for f in merged['filter']])

        # Group by: virgülle birleştir
        if merged['group_by']:
            final_sql['group_by'] = ", ".join(merged['group_by'])

        # Select: virgülle birleştir
        if merged['select']:
            final_sql['select'] = ", ".join(merged['select'])

        # Join: hepsini ekle
        if merged['join']:
            final_sql['join'] = " ".join(merged['join'])

        # Having: AND ile birleştir
        if merged['having']:
            final_sql['having'] = " AND ".join([f"({h})" for h in merged['having']])

        return final_sql

    def get_relevant_rules_for_query(
        self,
        user_query: str,
        detected_tables: Optional[List[str]] = None,
        n_results: int = 5,
        use_hybrid: bool = True
    ) -> Dict[str, Any]:
        """
        Kullanıcı sorusu için en alakalı kuralları bul ve SQL'leri birleştir

        Args:
            user_query: Kullanıcının Text-to-SQL sorusu
            detected_tables: Tespit edilen tablo isimleri
            n_results: Kaç kural döndürülecek
            use_hybrid: Hybrid search kullan mı?

        Returns:
            {
                'rules': List[Dict],  # Bulunan kurallar
                'merged_sql': Dict,   # Birleştirilmiş SQL bileşenleri
                'default_count': int,
                'semantic_count': int
            }
        """
        # 1. Semantic search
        semantic_results = self.search_rules(
            query=user_query,
            n_results=n_results,
            include_defaults=True,
            table_filter=detected_tables
        )

        # 2. Keyword search (hybrid için)
        keyword_results = []
        if use_hybrid:
            # User query'den keywords çıkar (basit tokenization)
            keywords = user_query.lower().split()
            keywords = [k for k in keywords if len(k) > 3]  # 3 harften uzun

            if keywords:
                keyword_results = self.keyword_search(keywords, n_results=3)

        # 3. Combine & deduplicate
        all_results = semantic_results + keyword_results
        seen_ids = set()
        unique_results = []

        for r in all_results:
            if r['rule_id'] not in seen_ids:
                seen_ids.add(r['rule_id'])
                unique_results.append(r)

        # 4. SQL'leri merge et
        merged_sql = self.merge_sql_components(unique_results)

        # 5. Stats
        default_count = sum(1 for r in unique_results if r['is_default'])
        semantic_count = len(unique_results) - default_count

        return {
            'rules': unique_results,
            'merged_sql': merged_sql,
            'default_count': default_count,
            'semantic_count': semantic_count,
            'total_count': len(unique_results)
        }

    def rebuild_index(self):
        """
        Index'i sıfırdan oluştur
        """
        logger.info("Rebuilding index from scratch...")
        self.initialize_collections(force_recreate=True)
        self.index_rules()
        logger.info("✅ Index rebuild completed")


def main():
    """
    Test & Demo
    """
    import sys
    from pathlib import Path

    # business_rules.json path
    rules_file = Path(__file__).parent / "business_rules.json"

    if not rules_file.exists():
        print(f"❌ business_rules.json bulunamadı: {rules_file}")
        sys.exit(1)

    print("=" * 60)
    print("Business Rules Vector Store - Test")
    print("=" * 60)

    # Initialize
    store = BusinessRulesVectorStore(
        rules_file_path=str(rules_file),
        similarity_threshold=0.5  # Demo için düşük threshold
    )

    # Rebuild index
    print("\n📦 Building index...")
    store.rebuild_index()

    # Test queries
    test_queries = [
        "Premium müşterilerin bu ayki cirosu nedir?",
        "Aktif kullanıcıların sayısı kaç?",
        "Son 30 günde kaç sipariş verildi?",
        "Geçen ayki ARR neydi?",
        "B2B müşterilerin ortalama sipariş değeri nedir?"
    ]

    print("\n" + "=" * 60)
    print("TEST QUERIES")
    print("=" * 60)

    for query in test_queries:
        print(f"\n🔍 Query: {query}")
        print("-" * 60)

        result = store.get_relevant_rules_for_query(
            user_query=query,
            n_results=3,
            use_hybrid=True
        )

        print(f"📊 Stats:")
        print(f"   - Default rules: {result['default_count']}")
        print(f"   - Semantic rules: {result['semantic_count']}")
        print(f"   - Total rules: {result['total_count']}")

        print(f"\n📋 Found Rules:")
        for rule in result['rules'][:5]:  # İlk 5'i göster
            print(f"   - [{rule['rule_id']}] "
                  f"(similarity: {rule['similarity']:.3f}) "
                  f"{'[DEFAULT]' if rule['is_default'] else ''}")

        print(f"\n🔧 Merged SQL:")
        for component, value in result['merged_sql'].items():
            if value:
                print(f"   {component}: {value}")

    print("\n" + "=" * 60)
    print("✅ Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
