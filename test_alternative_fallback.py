"""
Test alternative page fallback mechanism
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from embedding.pipeline import VectorStorePipeline

def main():
    """Test parametresiz fallback"""

    # Load existing vector store
    pipeline = VectorStorePipeline(config_path="config/config.yaml")
    vector_store = pipeline.load_existing(collection_name="forza_web_pages")

    print("="*60)
    print("Testing Alternative Fallback Mechanism")
    print("="*60)
    print()

    # Test query: Should find both parametreli and parametresiz pages
    query = "Cari listesi"
    print(f"Query: '{query}'")
    print()

    results = vector_store.similarity_search(query, k=10)

    print(f"Found {len(results)} results:\n")

    parametreli_pages = []
    parametresiz_pages = []

    for i, doc in enumerate(results, 1):
        title = doc.metadata.get('title', 'N/A')
        url = doc.metadata.get('url', 'N/A')
        has_params = doc.metadata.get('has_parameters', False)
        param_count = doc.metadata.get('parameter_count', 0)

        # Check if URL has placeholders
        has_placeholder = '{' in url and '}' in url
        # Exclude base_url placeholders
        import re
        placeholders = re.findall(r'\{(\w+)\}', url)
        base_url_names = ["baseUrl", "base_url", "BASE_URL", "BaseUrl", "BASEURL"]
        param_placeholders = [p for p in placeholders if p not in base_url_names]

        if has_params or param_placeholders:
            parametreli_pages.append((title, url, param_placeholders))
        else:
            parametresiz_pages.append((title, url))

        status = "[PARAMETRELI]" if (has_params or param_placeholders) else "[PARAMETRESIZ]"
        print(f"{i}. {status} {title}")
        print(f"   URL: {url}")
        if param_placeholders:
            print(f"   Unfilled: {param_placeholders}")
        print()

    print("="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Parametreli pages: {len(parametreli_pages)}")
    print(f"Parametresiz pages: {len(parametresiz_pages)}")
    print()

    if parametresiz_pages:
        print("Parametresiz Fallback Options:")
        for title, url in parametresiz_pages[:3]:
            print(f"  - {title}: {url}")
    else:
        print("WARNING: No parametresiz fallback available!")

if __name__ == "__main__":
    main()
