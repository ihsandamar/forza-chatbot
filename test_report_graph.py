"""
Test Report Graph

Simple test script to invoke the report graph with a user message.
"""

import asyncio
from langchain_core.messages import HumanMessage
from src.graphs.graph_entrypoints import report_graph


async def test_report():
    """Async test function"""
    # Initialize report graph
    print("🔧 Initializing report graph...")
    graph = report_graph()
    print("✅ Report graph initialized\n")

    # Create test input
    test_query = "son 1 senedeki şubelerin satış performansını saat detayında çizgi grafiğini gösterir misin?"
    initial_state = {
        "messages": [HumanMessage(content=test_query)],
        "text2sql_output": None,
        "visualization_output": None,
        "error": None
    }

    print(f"📝 Test Query: {test_query}\n")
    print("🚀 Invoking report graph...\n")

    # Async invoke graph
    try:
        result = await graph.ainvoke(initial_state)

        print("=" * 60)
        print("✅ REPORT GRAPH RESULT")
        print("=" * 60)

        # Show messages
        print("\n📨 Messages:")
        for i, msg in enumerate(result.get("messages", [])):
            msg_type = "User" if msg.__class__.__name__ == "HumanMessage" else "AI"
            print(f"\n[{i+1}] {msg_type}: {msg.content[:200]}")

        # Show text2sql output summary
        text2sql_out = result.get("text2sql_output")
        if text2sql_out:
            print("\n\n📊 Text2SQL Output:")
            print(f"  - Query: {text2sql_out.get('user_query', 'N/A')}")
            print(f"  - SQL Generated: {len(text2sql_out.get('sql_queries', [])) > 0}")
            print(f"  - Results: {len(text2sql_out.get('results', [])) if text2sql_out.get('results') else 0} rows")
            print(f"  - Error: {text2sql_out.get('error', 'None')}")

        # Show visualization output summary
        viz_out = result.get("visualization_output")
        if viz_out:
            print("\n\n📈 Visualization Output:")
            viz_final = viz_out.get("visualization_output", {})
            print(f"  - Output Type: {viz_final.get('output_type', 'N/A')}")
            print(f"  - Needs Graph: {viz_final.get('needs_graph', False)}")
            print(f"  - Summary: {viz_final.get('summary', 'N/A')}")
            print(f"  - Data Points: {len(viz_final.get('data', [])) if viz_final.get('data') else 0}")
            print(f"  - Error: {viz_out.get('error', 'None')}")

            # Show Plotly output
            plotly_code = viz_out.get("plotly_code")
            plotly_figure = viz_out.get("plotly_figure")

            print("\n\n🎨 Plotly Output:")
            if plotly_code:
                print(f"  - Plotly Code: ✅ Generated ({len(plotly_code)} chars)")
                print(f"\n--- Plotly Code ---")
                print(plotly_code)
                print(f"--- End Code ---\n")
            else:
                print(f"  - Plotly Code: ❌ Not generated")

            if plotly_figure:
                print(f"  - Plotly Figure: ✅ Created")
                print(f"  - Figure Type: {type(plotly_figure)}")
                if isinstance(plotly_figure, dict):
                    print(f"  - Figure Keys: {list(plotly_figure.keys())}")
                    print(f"  - Has data: {'data' in plotly_figure}")
                    print(f"  - Has layout: {'layout' in plotly_figure}")

                    # Save to HTML file
                    try:
                        import plotly.graph_objects as go
                        import json

                        # Recreate figure from JSON
                        fig = go.Figure(plotly_figure)

                        # Save to HTML
                        html_file = "plotly_output.html"
                        fig.write_html(html_file)
                        print(f"\n  ✅ Plotly chart saved to: {html_file}")
                        print(f"  📂 Open this file in your browser to see the chart!")

                    except Exception as e:
                        print(f"\n  ⚠️ Could not save HTML: {e}")
            else:
                print(f"  - Plotly Figure: ❌ Not created")

            # Show HTML snippet
            plotly_html_snippet = viz_out.get("plotly_html_snippet")
            if plotly_html_snippet:
                print(f"\n  - HTML Snippet: ✅ Generated ({len(plotly_html_snippet)} chars)")
                print(f"  - Snippet preview (first 200 chars):")
                print(f"    {plotly_html_snippet[:200]}...")

                # Save snippet to file for testing
                snippet_file = "plotly_snippet.html"
                with open(snippet_file, 'w', encoding='utf-8') as f:
                    # Wrap snippet in minimal HTML for testing
                    f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Plotly Chart Snippet</title>
</head>
<body>
    <h1>Embedded Plotly Chart</h1>
    {plotly_html_snippet}
</body>
</html>""")
                print(f"\n  ✅ HTML snippet saved to: {snippet_file}")
                print(f"  📂 This is the embeddable snippet for frontend!")
            else:
                print(f"\n  - HTML Snippet: ❌ Not generated")

        # Show error if any
        error = result.get("error")
        if error:
            print(f"\n\n❌ Error: {error}")

            print("\n" + "=" * 60)
            print("\n✅ Test completed successfully!")

    except Exception as e:
        print(f"\n❌ Error invoking report graph: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Run async test
    asyncio.run(test_report())
