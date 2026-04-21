"""Pytest configuration for unit tests - patches chromadb import issues."""
import sys
from unittest.mock import MagicMock

# Mock chromadb and its problematic dependencies to avoid import errors
sys.modules["chromadb"] = MagicMock()
sys.modules["chromadb.auth"] = MagicMock()
sys.modules["chromadb.auth.token_authn"] = MagicMock()
sys.modules["chromadb.telemetry"] = MagicMock()
sys.modules["chromadb.telemetry.opentelemetry"] = MagicMock()
