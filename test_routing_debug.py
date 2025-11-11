"""
Test script for routing graph - simple document retrieval.
"""

import logging
from langchain_core.messages import HumanMessage

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

from src.models.models import LLM
from src.graphs.routing.graph import RoutingGraph

# Create graph
print("[TEST] Creating RoutingGraph...")
llm = LLM()
routing_graph = RoutingGraph(llm)
compiled_graph = routing_graph.build_graph()

print("\n" + "="*70)
print("TEST: Document Retrieval")
print("="*70)

# Test with LangGraph compatible messages
state = {
    "messages": [HumanMessage(content="master reports")]
}

print(f"[TEST] Input: messages list with HumanMessage('master reports')")

try:
    # Invoke with config for checkpointer
    result = compiled_graph.invoke(state, config={"configurable": {"thread_id": "test-1"}})
    related_pages = result.get('related_pages', [])

    print(f"\n[TEST] Found {len(related_pages)} documents")

    if related_pages:
        print("\nRetrieved documents:")
        for i, (doc, score) in enumerate(related_pages):
            title = doc.metadata.get("title", "Unknown") if doc.metadata else "Unknown"
            print(f"  {i+1}. {title} (score: {score:.2f})")
    else:
        print("[TEST] No documents found!")

except Exception as e:
    print(f"[TEST] ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
