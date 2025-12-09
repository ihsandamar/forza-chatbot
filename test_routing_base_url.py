"""
Test routing with base_url replacement
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from langchain_core.documents import Document

# Simulate the update_url_with_parameters_node logic
def test_base_url_replacement():
    """Test all base_url variants"""

    # Test cases with different base_url formats
    test_cases = [
        ("{base_url}/apps/stock/multipleEditList", "base_url"),
        ("{baseUrl}/apps/customer/list", "baseUrl"),
        ("{BASE_URL}/apps/orders", "BASE_URL"),
        ("{BaseUrl}/dashboard", "BaseUrl"),
        ("{BASEURL}/settings", "BASEURL"),
    ]

    # Expected replacement value
    web_site_url = "https://test.vegaforza.com"

    print("="*60)
    print("Testing base_url replacement variants")
    print("="*60)
    print()

    for original_url, variant_name in test_cases:
        updated_url = original_url

        # Same logic as in update_url_with_parameters_node
        base_url_variants = [
            "{baseUrl}",
            "{base_url}",
            "{BASE_URL}",
            "{BaseUrl}",
            "{BASEURL}"
        ]

        for variant in base_url_variants:
            if variant in updated_url:
                updated_url = updated_url.replace(variant, web_site_url)
                break

        # Check result
        success = "{" not in updated_url and "}" not in updated_url
        status = "[OK]" if success else "[FAIL]"

        print(f"{status} Variant: {variant_name}")
        print(f"     Original: {original_url}")
        print(f"     Updated:  {updated_url}")
        print()

if __name__ == "__main__":
    test_base_url_replacement()
