"""
Test script for json_to_model conversion
"""

from embedding.utils import EmbeddingUtils

def main():
    # Load forza.json
    json_data = EmbeddingUtils.get_json_data("data/forza.json")

    print(f"Loaded JSON: {json_data['name']} v{json_data['version']}")
    print(f"Total pages in JSON: {json_data['total_pages']}\n")

    # Convert to model
    catalog = EmbeddingUtils.json_to_model(json_data)

    print(f"Catalog Model:")
    print(f"  Name: {catalog['name']}")
    print(f"  Version: {catalog['version']}")
    print(f"  Total pages: {len(catalog['pages'])}\n")

    # Test first page
    if catalog['pages']:
        page = catalog['pages'][0]
        print(f"First Page:")
        print(f"  Title: {page['metadata']['title']}")
        print(f"  URL: {page['metadata']['url']}")
        print(f"  Category: {page['metadata']['category']}")
        print(f"  Keywords: {len(page['keywords'])} keywords")
        print(f"  User expressions: {len(page['user_expression'])} expressions")
        print(f"  Parameters: {len(page['metadata']['parameters'])} parameters")
        print(f"  Content length: {len(page['content'])} chars\n")

    # Test page with parameters
    pages_with_params = [p for p in catalog['pages'] if p['metadata']['parameters']]
    if pages_with_params:
        page_with_params = pages_with_params[0]
        print(f"Page with Parameters:")
        print(f"  Title: {page_with_params['metadata']['title']}")
        print(f"  URL: {page_with_params['metadata']['url']}")
        print(f"  Parameters:")
        for param in page_with_params['metadata']['parameters']:
            print(f"    - {param['name']}: {param['type']} (required: {param['required']})")
            print(f"      Description: {param['description']}")
            print(f"      Endpoint: {param['endpoint']}\n")

    print("✓ Conversion successful!")

if __name__ == "__main__":
    main()
