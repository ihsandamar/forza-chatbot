"""
Test yumurta search - debug similarity search quality
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from embedding.pipeline import VectorStorePipeline

def main():
    # Load existing vector store
    pipeline = VectorStorePipeline(config_path="config/config.yaml")
    vector_store = pipeline.load_existing(collection_name="forza_web_pages")

    print("="*60)
    print("Testing: 'yumurta detayını getir'")
    print("="*60)
    print()

    query = "yumurta detayını getir"

    # Get similarity search with scores
    results = vector_store.similarity_search_with_score(query, k=10)

    print(f"Found {len(results)} results:\n")

    for i, (doc, distance) in enumerate(results, 1):
        title = doc.metadata.get('title', 'N/A')
        category = doc.metadata.get('category', 'N/A')
        url = doc.metadata.get('url', 'N/A')
        has_params = doc.metadata.get('has_parameters', False)

        # Convert distance to similarity score
        similarity = 1.0 / (1.0 + distance)

        print(f"{i}. [{similarity:.3f}] {title}")
        print(f"   Category: {category}")
        print(f"   URL: {url[:80]}...")
        print(f"   Has Parameters: {has_params}")
        print(f"   Distance: {distance:.3f}")
        print()

    # Check if best match is correct
    best_doc, best_distance = results[0]
    best_title = best_doc.metadata.get('title', 'N/A')
    best_category = best_doc.metadata.get('category', 'N/A')

    print("="*60)
    print("ANALYSIS")
    print("="*60)
    print(f"Best Match: {best_title}")
    print(f"Category: {best_category}")
    print()

    if "cari" in best_title.lower() or "customer" in best_title.lower():
        print("ERROR: Matched to CARI (customer) page!")
        print("Expected: URUN/STOK (product/item) page")
        print()

        # Find stok pages
        stok_pages = [(doc, dist) for doc, dist in results
                      if "stok" in doc.metadata.get('title', '').lower()
                      or "ürün" in doc.metadata.get('title', '').lower()]

        if stok_pages:
            print(f"Found {len(stok_pages)} STOK pages in results:")
            for doc, dist in stok_pages[:3]:
                similarity = 1.0 / (1.0 + dist)
                print(f"  - [{similarity:.3f}] {doc.metadata.get('title')}")
        else:
            print("WARNING: No STOK pages found in top 10 results!")
    else:
        print("OK: Matched correctly")

if __name__ == "__main__":
    main()
