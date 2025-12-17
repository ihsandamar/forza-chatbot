"""
Test routing graph with category extraction and alternative fallback
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from langchain_core.messages import HumanMessage
from src.graphs.routing.graph import RoutingGraph
from src.models.llm import LLM
from src.services.config_loader import ConfigLoader

def main():
    """Test routing graph with belediye carisi query"""

    print("="*60)
    print("Testing Routing Graph with Category Extraction")
    print("="*60)
    print()

    # Load config and create graph
    config = ConfigLoader.load_config("config/config.yaml")
    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
        base_url=getattr(config.llm, 'base_url', None)
    )
    graph = RoutingGraph(llm)

    # Test query
    query = "belediye carisinin detayını getir"
    print(f"Query: '{query}'")
    print()

    # Create state
    initial_state = {
        "messages": [HumanMessage(content=query)]
    }

    # Run graph
    print("Running graph...")
    print("-" * 60)

    try:
        result = graph.invoke(initial_state)

        # Print results
        print("\n" + "="*60)
        print("RESULTS")
        print("="*60)

        # Extracted category
        extracted_category = result.get("extracted_category")
        print(f"Extracted Category: {extracted_category}")
        print()

        # Navigation output
        nav_output = result.get("navigation_output")
        if nav_output:
            print(f"Page Title: {nav_output.get('page_title', 'N/A')}")
            print(f"URL: {nav_output.get('url', 'N/A')}")
            print(f"Category: {nav_output.get('category', 'N/A')}")
            print(f"Requires Parameters: {nav_output.get('requires_parameters', False)}")
            print(f"Confidence: {nav_output.get('confidence', 0.0)}")
            print()
            print(f"Suggestion: {nav_output.get('suggestion_text', 'N/A')}")
        else:
            print("No navigation output found")

        # Check for unfilled parameters
        has_unfilled = result.get("has_unfilled_parameters", False)
        unfilled_params = result.get("unfilled_parameters", [])

        if has_unfilled:
            print()
            print("WARNING: URL has unfilled parameters:", unfilled_params)
        else:
            print()
            print("SUCCESS: URL is complete with no unfilled parameters")

        # Alternative page info
        tried_pages = result.get("tried_page_ids", set())
        if tried_pages:
            print(f"\nTried {len(tried_pages)} alternative pages")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
