#!/usr/bin/env python
"""
Test script for async functionality
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.services.config_loader import ConfigLoader
from src.core.chatbot import Chatbot
from src.builders.chatbot_builder import ChatbotBuilder
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory
from src.adapters.default_state_adapter import DefaultStateAdapter


async def test_config_loader():
    """Test async config loading"""
    print("Testing ConfigLoader.load_config_async()...")
    try:
        config = await ConfigLoader.load_config_async()
        print("[PASS] Config loaded successfully")
        return config
    except Exception as e:
        print(f"[FAIL] Config loading failed: {e}")
        return None


async def test_chatbot_async_methods():
    """Test async chatbot methods"""
    print("\nTesting Chatbot async methods...")
    try:
        # Load config
        config = await ConfigLoader.load_config_async()

        # Create dependency factories
        dependency_factory = DependencyFactory()
        adapter_factory = AdapterFactory()

        # Build chatbot with factories
        llm_config = config.llm
        graph_type = config.chatbot.graph_type
        chatbot = (
            ChatbotBuilder(dependency_factory, adapter_factory)
            .with_model(llm_config.model, llm_config.temperature, llm_config.api_key)
            .with_graph(graph_type)
            .with_graph_config({"configurable": {"thread_id": config.chatbot.thread_id}})
            .build()
        )

        # Test send_async
        print("Testing send_async()...")
        state = {
            "messages": [
                {"role": "user", "content": "Hello, how are you?"}
            ]
        }

        response = await chatbot.send_async(state)
        print(f"[PASS] send_async() response length: {len(response)} chars")

        # Test send_structured_async
        print("Testing send_structured_async()...")
        structured_response = await chatbot.send_structured_async(state)
        print(f"[PASS] send_structured_async() response: {list(structured_response.keys())}")

        return True
    except Exception as e:
        print(f"[FAIL] Chatbot async test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_adapter_async():
    """Test adapter async methods"""
    print("\nTesting BaseStateAdapter async methods...")
    try:
        adapter = DefaultStateAdapter()

        messages = [{"role": "user", "content": "Test"}]

        # Test to_graph_state_async
        print("Testing to_graph_state_async()...")
        graph_state = await adapter.to_graph_state_async(messages)
        print(f"[PASS] to_graph_state_async() result: {graph_state}")

        # Test from_graph_state_async
        print("Testing from_graph_state_async()...")
        response = await adapter.from_graph_state_async(graph_state)
        print(f"[PASS] from_graph_state_async() result: {response}")

        return True
    except Exception as e:
        print(f"[FAIL] Adapter async test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all async tests"""
    print("=" * 50)
    print("Testing Async Functionality")
    print("=" * 50)

    # Test config loader
    config = await test_config_loader()

    # Test adapter
    adapter_ok = await test_adapter_async()

    # Test chatbot async methods
    chatbot_ok = await test_chatbot_async_methods()

    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    print(f"Config Loader: {'[PASS]' if config else '[FAIL]'}")
    print(f"Adapter Async: {'[PASS]' if adapter_ok else '[FAIL]'}")
    print(f"Chatbot Async: {'[PASS]' if chatbot_ok else '[FAIL]'}")

    if config and adapter_ok and chatbot_ok:
        print("\n[PASS] All tests passed!")
        return 0
    else:
        print("\n[FAIL] Some tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
