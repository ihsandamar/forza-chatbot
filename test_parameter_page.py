"""
Test parametreli sayfa için vector store
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from embedding.pipeline import VectorStorePipeline

def main():
    # Load existing vector store
    pipeline = VectorStorePipeline(config_path="config/config.yaml")
    vector_store = pipeline.load_existing(collection_name="forza_web_pages")

    # Test with parametreli sayfa
    test_queries = [
        "Cari detayını göster",
        "Müşteri detay sayfası",
        "Stok detayını aç"
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)

        results = vector_store.similarity_search(query, k=3)

        for i, doc in enumerate(results, 1):
            print(f"\n{i}. {doc.metadata.get('title', 'N/A')}")
            print(f"   URL: {doc.metadata.get('url', 'N/A')}")
            print(f"   Has Parameters: {doc.metadata.get('has_parameters', False)}")
            print(f"   Parameter Count: {doc.metadata.get('parameter_count', 0)}")

            # Check url_parameters
            url_params = doc.metadata.get('url_parameters', '')
            if url_params:
                print(f"   URL Parameters: {url_params[:100]}...")
            else:
                print(f"   URL Parameters: None")

if __name__ == "__main__":
    main()
