"""
Create Vector Store using OOP Pipeline

Simple usage example of the new OOP architecture.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from embedding.utils import EmbeddingUtils
from embedding.pipeline import VectorStorePipeline


def main():
    """Create vector store from forza.json using OOP pipeline"""

    print("=" * 60)
    print("FORZA CATALOG VECTOR STORE CREATION")
    print("=" * 60 + "\n")

    # Step 1: Load and convert JSON to Catalog model
    print("[SETUP] Loading forza.json...")
    json_data = EmbeddingUtils.get_json_data("data/forza.json")
    catalog = EmbeddingUtils.json_to_model(json_data)
    print(f"        Loaded catalog: {catalog['name']} v{catalog['version']}\n")

    # Step 2: Initialize and run pipeline
    pipeline = VectorStorePipeline(config_path="config/config.yaml")

    vector_store = pipeline.run(
        catalog=catalog,
        collection_name="forza_web_pages",
        verbose=True
    )

    # Step 3: Test with sample query
    print("[TEST] Testing vector store with sample query...")
    query = "Anasayfayı göster"
    results = vector_store.similarity_search(query, k=3)

    print(f"\n[RESULTS] Top 3 results for: '{query}'")
    for i, doc in enumerate(results, 1):
        print(f"\n{i}. {doc.metadata.get('title', 'N/A')}")
        print(f"   URL: {doc.metadata.get('url', 'N/A')}")
        print(f"   Category: {doc.metadata.get('category', 'N/A')}")
        print(f"   Keys available: {list(doc.metadata.keys())}")

    print("\n" + "=" * 60)
    print("SUCCESS: Vector store created and tested!")
    print("=" * 60)


if __name__ == "__main__":
    main()
