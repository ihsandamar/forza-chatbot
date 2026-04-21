"""Pytest configuration for tests/ — patches chromadb and OpenTelemetry import issues.

chromadb's optional OpenTelemetry exporter pulls in
opentelemetry-exporter-otlp-proto-grpc which has a broken import
(_create_exp_backoff_generator) in the installed version.  Injecting
MagicMock stubs for chromadb and its sub-packages before any test
module tries to import them prevents that import chain from ever
being executed.
"""
import sys
from unittest.mock import MagicMock

# Patch chromadb and its problematic sub-packages before any test imports them.
# These stubs are also added by tests/unit/conftest.py for that sub-directory;
# injecting them here ensures the root-level test files (e.g. test_connection_pool.py)
# get the same treatment.
_CHROMADB_MOCKS = [
    "chromadb",
    "chromadb.auth",
    "chromadb.auth.token_authn",
    "chromadb.telemetry",
    "chromadb.telemetry.opentelemetry",
    "chromadb.utils",
    "chromadb.utils.embedding_functions",
]

for _mod in _CHROMADB_MOCKS:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
