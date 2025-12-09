"""
Test base_url replacement
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from embedding.pipeline import VectorStorePipeline

def main():
    # Load existing vector store
    pipeline = VectorStorePipeline(config_path="config/config.yaml")
    vector_store = pipeline.load_existing(collection_name="forza_web_pages")

    # Test with pages that have {base_url} placeholder
    print("="*60)
    print("Testing base_url replacement")
    print("="*60)

    results = vector_store.similarity_search("toplu düzenleme", k=5)

    print(f"\nFound {len(results)} results:\n")

    for i, doc in enumerate(results, 1):
        title = doc.metadata.get('title', 'N/A')
        url = doc.metadata.get('url', 'N/A')
        has_base_url = '{base_url}' in url.lower() or '{baseurl}' in url.lower()

        print(f"{i}. {title}")
        print(f"   URL: {url}")
        print(f"   Has base_url placeholder: {has_base_url}")

        if has_base_url:
            print(f"   [!] NEEDS REPLACEMENT!")
        else:
            print(f"   [OK]")

        print()

if __name__ == "__main__":
    main()
