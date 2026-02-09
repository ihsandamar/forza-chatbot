"""
Business Rules Vector Store - Setup Script
===========================================

Bu script vector store'u initialize eder ve business_rules.json'daki
tüm kuralları indexler. Sadece ilk kurulumda veya business_rules.json
güncellendiğinde çalıştırılmalıdır.

Kullanım:
    python setup_business_rules_vectorstore.py
"""

import sys
import logging
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.graphs.generic_text2sql.business_rules_vector_store import BusinessRulesVectorStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """
    Initialize vector store and index all business rules.
    """
    print("=" * 70)
    print("Business Rules Vector Store - Setup")
    print("=" * 70)
    print()

    # Get paths
    current_dir = Path(__file__).parent
    rules_file = current_dir / "business_rules.json"
    persist_dir = current_dir / "chroma_db"

    # Check if business_rules.json exists
    if not rules_file.exists():
        print("[ERROR] business_rules.json bulunamadi!")
        print(f"   Beklenen konum: {rules_file}")
        print()
        print("Lutfen once business_rules.json dosyasini olusturun.")
        sys.exit(1)

    print(f"[OK] Business rules dosyasi: {rules_file}")
    print(f"[OK] Persist dizini: {persist_dir}")
    print()

    # Initialize vector store
    try:
        print("[*] Vector store initialize ediliyor...")
        store = BusinessRulesVectorStore(
            rules_file_path=str(rules_file),
            persist_directory=str(persist_dir),
            similarity_threshold=0.7  # Production threshold
        )
        print("[OK] Vector store basariyla olusturuldu")
        print()

    except Exception as e:
        print(f"[ERROR] Vector store olusturma hatasi: {e}")
        sys.exit(1)

    # Rebuild index
    try:
        print("[*] Index olusturuluyor (bu biraz zaman alabilir)...")
        print()
        store.rebuild_index()
        print()
        print("[OK] Index basariyla olusturuldu!")
        print()

    except Exception as e:
        print(f"[ERROR] Index olusturma hatasi: {e}")
        sys.exit(1)

    # Verify with test query
    try:
        print("[*] Test sorgusu calistiriliyor...")
        test_query = "Premium musterilerin geliri"

        result = store.get_relevant_rules_for_query(
            user_query=test_query,
            n_results=3,
            use_hybrid=True
        )

        print(f"   Query: '{test_query}'")
        print(f"   Bulunan kurallar: {result['total_count']}")
        print(f"   - Default: {result['default_count']}")
        print(f"   - Semantic: {result['semantic_count']}")
        print()

        if result['rules']:
            print("   Ilk 3 kural:")
            for rule in result['rules'][:3]:
                print(f"     - [{rule['rule_id']}] "
                      f"(similarity: {rule['similarity']:.3f}) "
                      f"{'[DEFAULT]' if rule['is_default'] else ''}")
            print()

        print("[OK] Test basarili!")
        print()

    except Exception as e:
        print(f"[WARNING] Test hatasi (index yine de olusturuldu): {e}")
        print()

    # Summary
    print("=" * 70)
    print("[OK] SETUP TAMAMLANDI!")
    print("=" * 70)
    print()
    print("Vector store hazir. Artik generic_text2sql graph'i kullanabilirsiniz.")
    print()
    print("[*] Ipuclari:")
    print("   - business_rules.json guncellerseniz bu scripti tekrar calistirin")
    print("   - Index dosyalari surada saklanir:", persist_dir)
    print("   - Index'i silmek icin su klasoru silin:", persist_dir)
    print()


if __name__ == "__main__":
    main()
