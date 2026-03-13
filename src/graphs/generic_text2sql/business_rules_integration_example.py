"""
Business Rules Vector Store - Integration Example
==================================================

Generic Text-to-SQL graph'a vector store'u entegre etme örneği.
"""

from business_rules_vector_store import BusinessRulesVectorStore
from pathlib import Path
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class Text2SQLWithBusinessRules:
    """
    Text-to-SQL sistemine business rules entegrasyonu
    """

    def __init__(self, rules_file: str = "business_rules.json"):
        """
        Args:
            rules_file: Business rules JSON dosyası
        """
        rules_path = Path(__file__).parent / rules_file

        # Vector store'u initialize et
        self.vector_store = BusinessRulesVectorStore(
            rules_file_path=str(rules_path),
            similarity_threshold=0.6  # Production için optimize edilebilir
        )

        # İlk kurulumda index oluştur
        self._ensure_index_exists()

    def _ensure_index_exists(self):
        """
        Index yoksa oluştur, varsa kullan
        """
        try:
            # Collections var mı kontrol et
            collections = self.vector_store.client.list_collections()
            collection_names = [c.name for c in collections]

            if "business_rules" not in collection_names:
                logger.info("Index bulunamadı, oluşturuluyor...")
                self.vector_store.rebuild_index()
            else:
                logger.info("✅ Index mevcut, yükleniyor...")
                self.vector_store.rules_collection = self.vector_store.client.get_collection(
                    "business_rules",
                    embedding_function=self.vector_store.embedding_function
                )
                self.vector_store.default_rules_collection = self.vector_store.client.get_collection(
                    "default_business_rules",
                    embedding_function=self.vector_store.embedding_function
                )
        except Exception as e:
            logger.error(f"Index kontrolünde hata: {e}")
            logger.info("Index yeniden oluşturuluyor...")
            self.vector_store.rebuild_index()

    def enrich_prompt_with_business_rules(
        self,
        user_query: str,
        detected_tables: List[str] = None,
        max_rules: int = 5
    ) -> str:
        """
        Kullanıcı sorusuna göre alakalı business rules'ları bulup
        LLM prompt'una eklenecek context oluştur

        Args:
            user_query: Kullanıcının sorusu
            detected_tables: Schema'dan tespit edilen tablolar
            max_rules: Maksimum kaç kural eklenecek

        Returns:
            LLM'e verilecek business rules context
        """
        # Alakalı kuralları bul
        result = self.vector_store.get_relevant_rules_for_query(
            user_query=user_query,
            detected_tables=detected_tables,
            n_results=max_rules,
            use_hybrid=True
        )

        # Context oluştur
        context_parts = []

        # 1. Default rules (her zaman uygulanır)
        default_rules = [r for r in result['rules'] if r['is_default']]
        if default_rules:
            context_parts.append("## Default Business Rules (Always Apply):\n")
            for rule in default_rules:
                desc = rule['metadata']['description']
                context_parts.append(f"- {desc}")

        # 2. Query-specific rules
        semantic_rules = [r for r in result['rules'] if not r['is_default']]
        if semantic_rules:
            context_parts.append("\n## Relevant Business Rules for This Query:\n")
            for rule in semantic_rules[:max_rules]:
                desc = rule['metadata']['description']
                similarity = rule['similarity']
                context_parts.append(f"- {desc} (relevance: {similarity:.2f})")

        # 3. Merged SQL components (LLM'in kullanması için)
        if result['merged_sql']:
            context_parts.append("\n## SQL Components to Include:\n")

            for component, value in result['merged_sql'].items():
                if value:
                    context_parts.append(f"**{component.upper()}**: {value}")

        context = "\n".join(context_parts)
        return context

    def generate_sql_with_rules(
        self,
        user_query: str,
        schema: str,
        detected_tables: List[str] = None,
        llm_function=None
    ) -> Dict[str, Any]:
        """
        Business rules ile birlikte SQL generate et

        Args:
            user_query: Kullanıcı sorusu
            schema: Database schema
            detected_tables: Tespit edilen tablolar
            llm_function: SQL generate edecek LLM fonksiyonu

        Returns:
            {
                'sql': str,
                'applied_rules': List[Dict],
                'merged_sql': Dict,
                'business_context': str
            }
        """
        # Business rules context oluştur
        business_context = self.enrich_prompt_with_business_rules(
            user_query=user_query,
            detected_tables=detected_tables,
            max_rules=5
        )

        # Alakalı kuralları al
        rules_result = self.vector_store.get_relevant_rules_for_query(
            user_query=user_query,
            detected_tables=detected_tables,
            n_results=5
        )

        # LLM prompt oluştur
        full_prompt = f"""
You are a SQL expert. Generate a SQL query based on the user question, database schema, and business rules.

**User Question**: {user_query}

**Database Schema**:
{schema}

**Business Rules Context**:
{business_context}

**IMPORTANT**:
- Follow ALL business rules mentioned above
- Merge the SQL components provided into your final query
- Default rules MUST be applied to every query
- Use the exact filters, aggregations, and joins specified

Generate the SQL query:
"""

        # LLM'e gönder (eğer function verilmişse)
        generated_sql = None
        if llm_function:
            generated_sql = llm_function(full_prompt)

        return {
            'sql': generated_sql,
            'applied_rules': rules_result['rules'],
            'merged_sql': rules_result['merged_sql'],
            'business_context': business_context,
            'prompt': full_prompt
        }


def demo_integration():
    """
    Integration demo
    """
    print("=" * 70)
    print("Text-to-SQL with Business Rules - Integration Demo")
    print("=" * 70)

    # Initialize
    text2sql = Text2SQLWithBusinessRules()

    # Example schema
    schema = """
    Table: customers
    - id (INT, PRIMARY KEY)
    - name (VARCHAR)
    - tier (VARCHAR) -- Gold, Platinum, Bronze, Silver
    - customer_type (VARCHAR) -- B2B, B2C
    - is_internal (BOOLEAN)
    - created_at (TIMESTAMP)
    - last_order_date (DATE)

    Table: orders
    - order_id (INT, PRIMARY KEY)
    - customer_id (INT, FK -> customers.id)
    - amount (DECIMAL)
    - status (VARCHAR) -- completed, cancelled, refunded
    - order_type (VARCHAR) -- one-time, recurring
    - is_test (BOOLEAN)
    - order_date (TIMESTAMP)
    """

    # Test queries
    test_queries = [
        {
            'query': "Premium müşterilerin bu ayki toplam geliri nedir?",
            'tables': ['customers', 'orders']
        },
        {
            'query': "Aktif B2B müşterilerin ortalama sipariş değeri?",
            'tables': ['customers', 'orders']
        },
        {
            'query': "Son 30 günde kaç yeni müşteri kaydoldu?",
            'tables': ['customers']
        }
    ]

    for i, test in enumerate(test_queries, 1):
        print(f"\n{'=' * 70}")
        print(f"TEST {i}: {test['query']}")
        print('=' * 70)

        # Generate SQL with business rules
        result = text2sql.generate_sql_with_rules(
            user_query=test['query'],
            schema=schema,
            detected_tables=test['tables'],
            llm_function=None  # Demo'da LLM yok
        )

        print("\nApplied Rules:")
        for rule in result['applied_rules'][:5]:
            print(f"  - [{rule['rule_id']}] "
                  f"({rule['metadata']['description']}) "
                  f"[similarity: {rule['similarity']:.2f}]")

        print("\nMerged SQL Components:")
        for component, value in result['merged_sql'].items():
            if value:
                print(f"  {component}: {value}")

        print("\nBusiness Context (LLM'e gonderilecek):")
        print("-" * 70)
        print(result['business_context'])

    print("\n" + "=" * 70)
    print("[OK] Demo completed!")
    print("=" * 70)


if __name__ == "__main__":
    demo_integration()
