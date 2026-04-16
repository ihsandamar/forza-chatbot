# Dead Code Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove ~25 dead files / ~3,000+ lines of code that are never reached from any live request path, leaving only code that is actually used.

**Architecture:** Two-phase approach on `refactor/cleanup-and-consolidation`. Phase 1 is pure `git rm` — no other file is touched. Phase 2 is surgical edits to live files. Each commit is self-contained and leaves the codebase in a working state.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, pytest

---

## File Map

### Phase 1 — Files deleted (git rm only)

| File | Why dead |
|------|----------|
| `src/core/session_manager.py` | ChatService uses `self.sessions: dict`; zero external callsites |
| `src/core/conversation.py` | ConversationManager wraps a list that's never read |
| `src/core/assistant_manager.py` | `_config_history` never read; zero external callsites |
| `src/models/erp_langgraph_models.py` | 468 lines, never imported; hardcoded data for a different domain |
| `src/models/models.py` | State TypedDict with GIB/restaurant ERP fields; no active graph uses it |
| `src/models/standard_types.py` | StandardResponse/Action etc; live path uses Pydantic ChatMessageResponse |
| `src/core/states/base_state.py` | StateRegistry / decorator registration; zero external callsites |
| `src/core/states/state_adapter.py` | Parallel state framework; zero callsites |
| `src/core/states/state_registry.py` | Same |
| `src/core/states/transformers.py` | Async transform; zero callsites |
| `src/core/messages/extractors.py` | MessageExtractor; zero callsites |
| `src/core/messages/validators.py` | MessageValidator; zero callsites |
| `src/builders/chatbot_builder.py` | ChatbotBuilder; not called from any entry point after launch-layer refactor |
| `src/builders/dependency_factory.py` | Zero callsites |
| `src/builders/adapter_factory.py` | `register_adapter()` has zero callsites |
| `src/adapters/base_state_adapter.py` | Replaced by inline logic in chatbot.py |
| `src/adapters/default_state_adapter.py` | Same |
| `src/adapters/vegaforza_state_adapter.py` | Same |
| `src/graphs/base_graph.py` (root) | 42-line stub; active graphs import enhanced version at `src/graphs/base/base_graph.py` |
| `src/graphs/base/graph_config.py` | `from_yaml` / `from_yaml_relative` — no YAML files exist in repo |
| `src/graphs/base/graph_types.py` | GraphOutput / GraphState TypedDicts; active graph states use their own `state.py` files |
| `src/interfaces/flask_interface.py` | 14-line Flask app; project uses FastAPI |
| `src/services/container.py` | ServiceContainer has zero callsites |
| `src/api/models.py` (root file) | Duplicate of `src/api/models/` package; routes use the package, not this file |

### Phase 1 — Files modified (cleanup only)

| File | Change |
|------|--------|
| `src/core/__init__.py` | Remove SessionManager / ConversationManager / AssistantManager imports and `__all__` entries |
| `src/adapters/__init__.py` | Remove all adapter re-exports (will be blank after deletions) |

### Phase 2 — Files modified (live code)

| File | Change |
|------|--------|
| `src/api/routes/metrics.py` | Delete two permanently-broken endpoints (lines 65–146) |
| `src/core/exceptions/chatbot_exception.py` | Delete 23 never-raised exception classes |
| `src/graphs/routing/exceptions.py` | Delete entire file (10 classes, never caught by routing nodes) |
| `src/core/chatbot.py` | Fix stale import; rename `_from_graph_state` → `extract_response` |
| `src/api/services/chat_service.py` | Delete 4 async alias methods; update `_from_graph_state` call |
| `src/interfaces/cli_interface.py` | Update 3 call sites to use canonical method names |
| `src/interfaces/gradio_interface.py` | Update 4 call sites to use canonical method names |

---

## Task 1: Delete core manager files

**Files:**
- Delete: `src/core/session_manager.py`
- Delete: `src/core/conversation.py`
- Delete: `src/core/assistant_manager.py`
- Modify: `src/core/__init__.py`

- [ ] **Step 1: Confirm zero external callsites**

```bash
grep -r "SessionManager\|ConversationManager\|AssistantManager" src/ --include="*.py" -l
```

Expected output: only `src/core/__init__.py` and the three files themselves. If any other file shows up, stop and investigate.

- [ ] **Step 2: Delete the three files**

```bash
git rm src/core/session_manager.py src/core/conversation.py src/core/assistant_manager.py
```

- [ ] **Step 3: Update `src/core/__init__.py`**

Current content (lines 19-21 and their `__all__` entries):
```python
from src.core.session_manager import SessionManager
from src.core.conversation import ConversationManager
from src.core.assistant_manager import AssistantManager
```
and in `__all__`:
```python
    # Managers
    "SessionManager",
    "ConversationManager",
    "AssistantManager",
```

Replace entire file with:
```python
"""
Core module - Domain models and business logic.

Exports:
- Models: Session, Conversation, Message, etc.
- Config: ChatbotConfig, AssistantConfig
- Chatbot: Core chatbot class
"""

from src.core.models import (
    Message,
    Session,
    Conversation,
    AssistantConfig,
    ChatbotConfig
)
from src.core.config import Config
from src.core.chatbot import Chatbot

__all__ = [
    # Models
    "Message",
    "Session",
    "Conversation",
    "AssistantConfig",
    "ChatbotConfig",
    # Config
    "Config",
    # Chatbot
    "Chatbot"
]
```

- [ ] **Step 4: Verify import health**

```bash
python -c "from src.core import Chatbot, Config; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run smoke test**

```bash
python -c "import main; import api_app; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: same pass/fail count as before this commit (no new failures).

- [ ] **Step 7: Commit**

```bash
git add src/core/__init__.py
git commit -m "refactor: remove orphan session/conversation/assistant manager classes

ChatService uses self.sessions dict directly; these three managers had
zero external callsites after the launch-layer refactor."
```

---

## Task 2: Delete dead model files

**Files:**
- Delete: `src/models/erp_langgraph_models.py`
- Delete: `src/models/models.py`
- Delete: `src/models/standard_types.py`

- [ ] **Step 1: Confirm zero imports**

```bash
grep -r "erp_langgraph_models\|from src.models.models\|from src.models.standard_types\|StandardResponse\|StandardAction" src/ --include="*.py" -l
```

Expected: empty (no output). If any file shows up, stop and investigate.

- [ ] **Step 2: Delete the three files**

```bash
git rm src/models/erp_langgraph_models.py src/models/models.py src/models/standard_types.py
```

- [ ] **Step 3: Check if `src/models/__init__.py` re-exports any of these**

```bash
cat src/models/__init__.py
```

If it imports from the deleted files, remove those lines.

- [ ] **Step 4: Smoke test**

```bash
python -c "import main; import api_app; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run tests**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: remove dead model files (erp_langgraph, standard_types, unused State)

erp_langgraph_models.py: 468 lines, never imported, contains hardcoded
sample data for a different domain. standard_types.py: live response path
uses Pydantic ChatMessageResponse, not StandardResponse."
```

---

## Task 3: Delete core states and messages infrastructure

**Files:**
- Delete: `src/core/states/base_state.py`
- Delete: `src/core/states/state_adapter.py`
- Delete: `src/core/states/state_registry.py`
- Delete: `src/core/states/transformers.py`
- Delete: `src/core/messages/extractors.py`
- Delete: `src/core/messages/validators.py`

- [ ] **Step 1: Confirm zero external callsites**

```bash
grep -r "StateRegistry\|StateAdapter\|StateTransformer\|MessageExtractor\|MessageValidator\|detect_intent" src/ --include="*.py" -l
```

Expected: only the files themselves and possibly their `__init__.py` files.

- [ ] **Step 2: Check `__init__.py` files in these dirs**

```bash
cat src/core/states/__init__.py
cat src/core/messages/__init__.py
```

If they re-export anything from the deleted files, note which lines to remove.

- [ ] **Step 3: Delete the six files**

```bash
git rm src/core/states/base_state.py src/core/states/state_adapter.py \
       src/core/states/state_registry.py src/core/states/transformers.py \
       src/core/messages/extractors.py src/core/messages/validators.py
```

- [ ] **Step 4: Remove empty `__init__.py` files and directories if now empty**

Check if anything remains in each directory:
```bash
ls src/core/states/
ls src/core/messages/
```

If only `__init__.py` remains in each:
```bash
git rm src/core/states/__init__.py src/core/messages/__init__.py
```

Then remove empty directories:
```bash
rmdir src/core/states src/core/messages
```

- [ ] **Step 5: Smoke test**

```bash
python -c "import main; import api_app; print('OK')"
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git commit -m "refactor: remove dead states/messages infrastructure

StateRegistry, StateAdapter, StateTransformer, MessageExtractor,
MessageValidator: decorator-based registration system and async
transforms with zero external callsites."
```

---

## Task 4: Delete builder and adapter layers

**Files:**
- Delete: `src/builders/chatbot_builder.py`
- Delete: `src/builders/dependency_factory.py`
- Delete: `src/builders/adapter_factory.py`
- Delete: `src/adapters/base_state_adapter.py`
- Delete: `src/adapters/default_state_adapter.py`
- Delete: `src/adapters/vegaforza_state_adapter.py`
- Modify: `src/adapters/__init__.py`

- [ ] **Step 1: Confirm zero external callsites**

```bash
grep -r "ChatbotBuilder\|DependencyFactory\|AdapterFactory\|BaseStateAdapter\|DefaultStateAdapter\|VegaforzaStateAdapter" src/ --include="*.py" -l
```

Expected: only `src/builders/__init__.py` (if it exists and re-exports) and `src/adapters/__init__.py`.

```bash
grep -r "from src.builders\|from src.adapters" src/ --include="*.py" -l
```

Expected: only the `__init__.py` files in those directories.

- [ ] **Step 2: Delete the six files**

```bash
git rm src/builders/chatbot_builder.py src/builders/dependency_factory.py \
       src/builders/adapter_factory.py \
       src/adapters/base_state_adapter.py src/adapters/default_state_adapter.py \
       src/adapters/vegaforza_state_adapter.py
```

- [ ] **Step 3: Empty `src/adapters/__init__.py`**

Replace with:
```python
```
(empty file — keep the file so the package still exists in case any future import resolves to it gracefully)

- [ ] **Step 4: Check `src/builders/__init__.py`**

```bash
cat src/builders/__init__.py
```

If it's empty or only imports deleted files, empty it too.

- [ ] **Step 5: Smoke test**

```bash
python -c "import main; import api_app; print('OK')"
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git commit -m "refactor: remove builder/adapter layers defunct after launch-layer refactor

ChatbotBuilder, AdapterFactory, DefaultStateAdapter et al. had zero
callsites after src/launch/ replaced di_container.py as the assembly
point for ChatService."
```

---

## Task 5: Delete graph base remnants

**Files:**
- Delete: `src/graphs/base_graph.py` (root, 42-line stub)
- Delete: `src/graphs/base/graph_config.py`
- Delete: `src/graphs/base/graph_types.py`

- [ ] **Step 1: Confirm no live graph imports the root stub**

```bash
grep -r "from src.graphs.base_graph import\|from src.graphs import base_graph" src/ --include="*.py"
```

Expected: only type-hint-only imports, if any. Investigate any result that isn't a comment.

```bash
grep -r "from src.graphs.base.graph_config import\|from src.graphs.base.graph_types import" src/ --include="*.py"
```

Expected: empty.

- [ ] **Step 2: Delete the three files**

```bash
git rm src/graphs/base_graph.py \
       src/graphs/base/graph_config.py \
       src/graphs/base/graph_types.py
```

- [ ] **Step 3: Confirm `src/graphs/base/__init__.py` and `base/base_graph.py` (enhanced) are untouched**

```bash
ls src/graphs/base/
```

Expected: `__init__.py` and `base_graph.py` still present.

- [ ] **Step 4: Smoke test**

```bash
python -c "import main; import api_app; print('OK')"
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: remove graph base remnants (stub base_graph, yaml-only config, unused TypedDicts)

Active graphs import enhanced src/graphs/base/base_graph.py (460 lines).
graph_config.py's from_yaml methods reference YAML files that don't exist.
GraphOutput/GraphState TypedDicts are unused; each graph has its own state.py."
```

---

## Task 6: Delete miscellaneous dead files

**Files:**
- Delete: `src/interfaces/flask_interface.py`
- Delete: `src/services/container.py`
- Delete: `src/api/models.py` (root file, not the package)

- [ ] **Step 1: Confirm zero imports**

```bash
grep -r "flask_interface\|ServiceContainer\|from src.services.container" src/ --include="*.py"
```

Expected: empty.

```bash
grep -r "from src\.api\.models import\b" src/ --include="*.py"
```

This confirms the root `src/api/models.py` (not the package). Expected: empty — routes import from `src.api.models.requests.*` and `src.api.models.responses.*`.

- [ ] **Step 2: Delete the three files**

```bash
git rm src/interfaces/flask_interface.py \
       src/services/container.py \
       src/api/models.py
```

- [ ] **Step 3: Smoke test**

```bash
python -c "import main; import api_app; print('OK')"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 5: Verify API route package still works**

```bash
python -c "from src.api.models.requests.chat import ChatMessageRequest; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: remove flask_interface, ServiceContainer, duplicate api/models.py

flask_interface: 14-line Flask app, project is FastAPI.
container.py: ServiceContainer with zero callsites.
src/api/models.py: root-level duplicate of src/api/models/ package."
```

---

## Task 7: Remove permanently broken metrics endpoints

**Files:**
- Modify: `src/api/routes/metrics.py`

- [ ] **Step 1: Read the current file to confirm the dead code block**

Run: `grep -n "cache" src/api/routes/metrics.py`

Expected output includes lines like:
```
76: @router.get("/cache/stats", ...)
109:     return {"status": "not_initialized"}
111: @router.post("/cache/reset", ...)
146:     raise HTTPException(status_code=404, ...)
```

Both endpoints contain `cache = None  # TODO` and always return error/404.

- [ ] **Step 2: Write a test that verifies remaining endpoints still respond**

Create `tests/api/routes/test_metrics_endpoints.py`:

```python
"""Regression test: confirm working metrics endpoints survive the dead-code cleanup."""
import pytest
from httpx import AsyncClient
from src.api.main import build_fastapi_app
from src.core.app_config import reset_config


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


@pytest.mark.asyncio
async def test_sessions_endpoint_exists(mock_config):
    """GET /api/metrics/sessions should respond (200 or 503 acceptable)."""
    app = build_fastapi_app(mock_config)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/api/metrics/sessions")
    assert response.status_code in (200, 503)


@pytest.mark.asyncio
async def test_cache_stats_endpoint_removed(mock_config):
    """GET /api/metrics/cache/stats must be gone after cleanup."""
    app = build_fastapi_app(mock_config)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/api/metrics/cache/stats")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cache_reset_endpoint_removed(mock_config):
    """POST /api/metrics/cache/reset must be gone after cleanup."""
    app = build_fastapi_app(mock_config)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/api/metrics/cache/reset")
    assert response.status_code == 404
```

- [ ] **Step 3: Run test to confirm it fails (cache/stats currently returns 200 with broken data)**

```bash
pytest tests/api/routes/test_metrics_endpoints.py -v
```

Expected: `test_cache_stats_endpoint_removed` and `test_cache_reset_endpoint_removed` FAIL.

- [ ] **Step 4: Delete the two dead endpoint functions from `src/api/routes/metrics.py`**

Remove the entire `GET /cache/stats` function (from its `@router.get("/cache/stats"` decorator down through its closing `return {"status": "not_initialized"}`) and the entire `POST /cache/reset` function (from its `@router.post("/cache/reset"` decorator down through its closing `raise HTTPException(...)`).

These are the two functions that begin at approximately lines 76 and 111. Delete everything from the first decorator through the last line of each function body. Do NOT touch any other function in the file.

- [ ] **Step 5: Run tests**

```bash
pytest tests/api/routes/test_metrics_endpoints.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/metrics.py tests/api/routes/test_metrics_endpoints.py
git commit -m "refactor: remove permanently broken cache metrics endpoints

Both GET /metrics/cache/stats and POST /metrics/cache/reset had
'cache = None # TODO' — they always returned not_initialized or 404.
Removed endpoints and added regression tests for remaining metrics."
```

---

## Task 8: Prune dead exception hierarchy

**Files:**
- Modify: `src/core/exceptions/chatbot_exception.py`
- Delete: `src/graphs/routing/exceptions.py`
- Modify: `src/core/chatbot.py` (remove stale import)

- [ ] **Step 1: Confirm which exception classes are actually raised in live code**

```bash
grep -r "raise ConfigurationException\|raise MessageProcessingException\|raise GraphExecutionException\|raise GraphInvocationException\|raise InvalidGraphStateException" src/ --include="*.py"
```

Expected: multiple hits — these 5 are the keepers.

- [ ] **Step 2: Confirm the 23 classes to delete are never raised**

```bash
grep -r "raise InvalidConfigurationException\|raise ConfigurationFileException\|raise InvalidMessageException\|raise MessageValidationException\|raise MessageExtractionException" src/ --include="*.py"
grep -r "raise AdapterException\|raise StateAdaptationException\|raise InvalidAdapterException\|raise BuilderException\|raise BuilderValidationException\|raise InvalidBuilderStateException" src/ --include="*.py"
grep -r "raise ModuleException\|raise ModuleNotFoundException\|raise ModuleInitializationException\|raise ModuleProcessingException" src/ --include="*.py"
grep -r "raise LLMException\|raise LLMInvocationException\|raise InvalidLLMResponseException" src/ --include="*.py"
grep -r "raise DatabaseException\|raise DatabaseConnectionException\|raise QueryExecutionException" src/ --include="*.py"
grep -r "raise ResponseException\|raise ResponseFormattingException" src/ --include="*.py"
```

Expected: all empty (zero hits). If any shows a hit, that class must be kept.

- [ ] **Step 3: Confirm routing exceptions are never caught**

```bash
grep -r "VectorStoreNotFoundError\|UserInputExtractionError\|DocumentRetrievalError\|DocumentSelectionError\|ParameterDetectionError\|ParameterExtractionError\|ToolExecutionError\|URLUpdateError\|OutputFormattingError\|AlternativePageSearchError\|InvalidStateError" src/ --include="*.py" -l
```

Expected: only `src/graphs/routing/exceptions.py` itself. If any other file catches or imports these, stop and investigate.

- [ ] **Step 4: Confirm stale import in `chatbot.py`**

```bash
grep -n "AdapterException\|StateAdaptationException" src/core/chatbot.py
```

Expected output:
```
17: from src.core.exceptions.chatbot_exception import AdapterException, StateAdaptationException
```

These are imported but never raised (just dead imports).

- [ ] **Step 5: Write a test for the 5 keepers**

Create `tests/core/test_exception_hierarchy.py`:

```python
"""Verify the 5 live exception classes survive the prune."""
import pytest
from src.core.exceptions.chatbot_exception import (
    ConfigurationException,
    MessageProcessingException,
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
    ChatbotBaseException,
)


def test_configuration_exception_is_raisable():
    with pytest.raises(ConfigurationException) as exc_info:
        raise ConfigurationException("bad config")
    assert exc_info.value.error_code == "CONFIG_ERROR"


def test_message_processing_exception_is_raisable():
    with pytest.raises(MessageProcessingException) as exc_info:
        raise MessageProcessingException("bad message")
    assert exc_info.value.error_code == "MESSAGE_ERROR"


def test_graph_execution_exception_is_raisable():
    with pytest.raises(GraphExecutionException):
        raise GraphExecutionException("graph failed")


def test_graph_invocation_exception_is_raisable():
    with pytest.raises(GraphInvocationException):
        raise GraphInvocationException("invocation failed", graph_name="test")


def test_invalid_graph_state_exception_is_raisable():
    with pytest.raises(InvalidGraphStateException):
        raise InvalidGraphStateException("bad state", state_type="dict")


def test_all_keepers_are_subclass_of_base():
    for cls in (ConfigurationException, MessageProcessingException,
                GraphExecutionException, GraphInvocationException,
                InvalidGraphStateException):
        assert issubclass(cls, ChatbotBaseException)
```

- [ ] **Step 6: Run tests to confirm they pass (before changes)**

```bash
pytest tests/core/test_exception_hierarchy.py -v
```

Expected: all 6 PASS.

- [ ] **Step 7: Edit `src/core/exceptions/chatbot_exception.py` — delete 23 dead classes**

Delete the following complete class definitions (from their docstring/class header through their last line):
- `InvalidConfigurationException` (lines ~125–156)
- `ConfigurationFileException` (lines ~159–184)
- `InvalidMessageException` (lines ~218–246)
- `MessageValidationException` (lines ~249–273)
- `MessageExtractionException` (lines ~276–300)
- `AdapterException` (entire class, lines ~307–331)
- `StateAdaptationException` (lines ~333–360)
- `InvalidAdapterException` (lines ~363–387)
- `BuilderException` (entire class, lines ~509–532)
- `BuilderValidationException` (lines ~535–560)
- `InvalidBuilderStateException` (lines ~563–587)
- `ModuleException` (entire class, lines ~594–618)
- `ModuleNotFoundException` (lines ~621–644)
- `ModuleInitializationException` (lines ~647–671)
- `ModuleProcessingException` (lines ~674–699)
- `LLMException` (entire class, lines ~706–730)
- `LLMInvocationException` (lines ~733–758)
- `InvalidLLMResponseException` (lines ~761–785)
- `DatabaseException` (entire class, lines ~792–816)
- `DatabaseConnectionException` (lines ~819–849)
- `QueryExecutionException` (lines ~852–878)
- `ResponseException` (entire class, lines ~885–908)
- `ResponseFormattingException` (lines ~911–935)

Also remove the section comment headers for sections that become empty:
- `# Adapter Exceptions` section header (lines ~303–305)
- `# Builder Exceptions` section header (lines ~505–507)
- `# Module Exceptions` section header (lines ~590–592)
- `# LLM Exceptions` section header (lines ~702–704)
- `# Database Exceptions` section header (lines ~788–790)
- `# Response Exceptions` section header (lines ~881–883)

Keep: `ChatbotBaseException`, `ConfigurationException`, `MessageProcessingException`, `GraphExecutionException`, `GraphInvocationException`, `InvalidGraphStateException`, `GraphNodeExecutionException`.

- [ ] **Step 8: Delete `src/graphs/routing/exceptions.py`**

```bash
git rm src/graphs/routing/exceptions.py
```

- [ ] **Step 9: Fix stale import in `src/core/chatbot.py`**

Remove line 17:
```python
from src.core.exceptions.chatbot_exception import AdapterException, StateAdaptationException
```

This import is dead — neither `AdapterException` nor `StateAdaptationException` is raised anywhere in `chatbot.py`.

- [ ] **Step 10: Run tests**

```bash
pytest tests/core/test_exception_hierarchy.py -v
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add src/core/exceptions/chatbot_exception.py \
        src/core/chatbot.py \
        tests/core/test_exception_hierarchy.py
git commit -m "refactor: prune 23 dead exception classes and routing exceptions module

5 classes remain: ConfigurationException, MessageProcessingException,
GraphExecutionException, GraphInvocationException, InvalidGraphStateException.
Also removed stale AdapterException/StateAdaptationException import from chatbot.py."
```

---

## Task 9: Remove async alias methods from ChatService

**Files:**
- Modify: `src/api/services/chat_service.py`
- Modify: `src/interfaces/cli_interface.py`
- Modify: `src/interfaces/gradio_interface.py`

Context: `ChatService` has 4 methods that are pure delegation wrappers:
- `start_session_async(request)` → `return await self.start_session(request)` (line 66–76)
- `send_message_async(request)` → `return await self.send_message(request)` (line 503–...)
- `get_history_async(session_id)` → `return await self.get_session_history(session_id)` (line 640–650)
- `clear_history_async(session_id)` → `return self.clear_conversation(session_id)` (line 673–683)

These aliases exist "for compatibility" but there is no external code that requires them — `cli_interface.py` and `gradio_interface.py` are the only callers and are being updated in the same commit.

- [ ] **Step 1: Confirm the aliases are the only callers**

```bash
grep -rn "start_session_async\|send_message_async\|get_history_async\|clear_history_async" src/ --include="*.py"
```

Expected results: only `chat_service.py` (definitions), `cli_interface.py`, and `gradio_interface.py`. No other files.

- [ ] **Step 2: Write a test for the canonical method names**

Create `tests/api/services/test_chat_service_canonical_methods.py`:

```python
"""Verify canonical async methods work after alias removal."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import SessionStartRequest, ChatMessageRequest


@pytest.fixture
def chat_service():
    chatbot = MagicMock()
    chatbot.send_async = AsyncMock(return_value="test response")
    chatbot.get_graph_output_async = AsyncMock(return_value={"messages": []})
    return ChatService(chatbot=chatbot)


@pytest.mark.asyncio
async def test_start_session_is_callable(chat_service):
    response = await chat_service.start_session(SessionStartRequest())
    assert response.session_id is not None


@pytest.mark.asyncio
async def test_get_session_history_is_callable(chat_service):
    session = await chat_service.start_session(SessionStartRequest())
    response = await chat_service.get_session_history(session.session_id)
    assert hasattr(response, "messages")


def test_clear_conversation_is_callable(chat_service):
    import asyncio
    session = asyncio.run(chat_service.start_session(SessionStartRequest()))
    count = chat_service.clear_conversation(session.session_id)
    assert isinstance(count, int)
```

- [ ] **Step 3: Run test to confirm they pass now (before removal)**

```bash
pytest tests/api/services/test_chat_service_canonical_methods.py -v
```

Expected: all 3 PASS.

- [ ] **Step 4: Delete the 4 alias methods from `src/api/services/chat_service.py`**

Delete the entire method body (including docstring and decorator if any) for each of:
1. `start_session_async` at line ~66–76
2. `send_message_async` at line ~503–...
3. `get_history_async` at line ~640–650
4. `clear_history_async` at line ~673–683

Each deletion is just the function def + docstring + one-line body.

- [ ] **Step 5: Update `src/interfaces/cli_interface.py`**

Find all calls to the old alias names and replace with canonical names:
- `start_session_async(` → `start_session(`
- `send_message_async(` → `send_message(`
- `get_history_async(` → `get_session_history(`
- `await self.chat_service.clear_history_async(` → `self.chat_service.clear_conversation(` (remove `await` — sync method)

Verify by running:
```bash
grep -n "start_session_async\|send_message_async\|get_history_async\|clear_history_async" src/interfaces/cli_interface.py
```

Expected: empty.

- [ ] **Step 6: Update `src/interfaces/gradio_interface.py`**

Same replacements in gradio_interface.py:
- `start_session_async(` → `start_session(` (line ~78)
- `send_message_async(` → `send_message(` (line ~121)
- `get_history_async(` → `get_session_history(` (line ~151 and ~365)
- `await self.chat_service.clear_history_async(` → `self.chat_service.clear_conversation(` (line ~180, remove `await`)

Verify:
```bash
grep -n "start_session_async\|send_message_async\|get_history_async\|clear_history_async" src/interfaces/gradio_interface.py
```

Expected: empty.

- [ ] **Step 7: Run tests**

```bash
pytest tests/api/services/test_chat_service_canonical_methods.py -v
pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 8: Commit**

```bash
git add src/api/services/chat_service.py \
        src/interfaces/cli_interface.py \
        src/interfaces/gradio_interface.py \
        tests/api/services/test_chat_service_canonical_methods.py
git commit -m "refactor: remove async alias methods from ChatService

start_session_async, send_message_async, get_history_async, clear_history_async
were thin delegation wrappers. Callers (cli_interface, gradio_interface)
updated to use canonical method names directly."
```

---

## Task 10: Rename `_from_graph_state` to `extract_response`

**Files:**
- Modify: `src/core/chatbot.py`
- Modify: `src/api/services/chat_service.py`

Context: `chat_service.py:446` calls `self.chatbot._from_graph_state(graph_output)` — an external caller accessing a private method (SRP violation). Renaming to `extract_response` makes the public contract explicit.

Affected call sites in `chatbot.py` itself:
- Line 107: the method definition `def _from_graph_state`
- Line 146: `self._from_graph_state(graph_output)` inside `_to_api_response`
- Line 263: `self._from_graph_state(graph_output)` inside `send`
- Line 431: `self._from_graph_state(graph_output)` inside `send_async`

- [ ] **Step 1: Write test for `extract_response`**

Create `tests/core/test_chatbot_extract_response.py`:

```python
"""Verify extract_response works after rename from _from_graph_state."""
import pytest
from unittest.mock import MagicMock
from src.core.chatbot import Chatbot


@pytest.fixture
def chatbot():
    llm = MagicMock()
    graph = MagicMock()
    return Chatbot(llm=llm, graph=graph)


def test_extract_response_from_message_objects(chatbot):
    msg = MagicMock()
    msg.content = "Hello from graph"
    output = {"messages": [msg]}
    assert chatbot.extract_response(output) == "Hello from graph"


def test_extract_response_from_dict_messages(chatbot):
    output = {"messages": [{"role": "assistant", "content": "Hi there"}]}
    assert chatbot.extract_response(output) == "Hi there"


def test_extract_response_empty_messages(chatbot):
    output = {"messages": []}
    result = chatbot.extract_response(output)
    assert isinstance(result, str)
    assert len(result) > 0  # Returns a fallback string


def test_extract_response_non_dict_input(chatbot):
    result = chatbot.extract_response("raw string")
    assert result == "raw string"


def test_private_name_gone(chatbot):
    """_from_graph_state must no longer exist as a method name."""
    assert not hasattr(chatbot, "_from_graph_state"), \
        "_from_graph_state should have been renamed to extract_response"
```

- [ ] **Step 2: Run test to confirm `test_private_name_gone` currently fails**

```bash
pytest tests/core/test_chatbot_extract_response.py::test_private_name_gone -v
```

Expected: FAIL (method still named `_from_graph_state`).

- [ ] **Step 3: Rename in `src/core/chatbot.py`**

Change every occurrence of `_from_graph_state` in `chatbot.py`:

1. Line 107: `def _from_graph_state(` → `def extract_response(`
2. Line 146: `self._from_graph_state(` → `self.extract_response(`
3. Line 263: `self._from_graph_state(` → `self.extract_response(`
4. Line 431: `self._from_graph_state(` → `self.extract_response(`

Verify no old name remains:
```bash
grep -n "_from_graph_state" src/core/chatbot.py
```

Expected: empty.

- [ ] **Step 4: Update `src/api/services/chat_service.py:446`**

Change:
```python
bot_response_text = self.chatbot._from_graph_state(graph_output)
```
To:
```python
bot_response_text = self.chatbot.extract_response(graph_output)
```

Verify:
```bash
grep -n "_from_graph_state" src/api/services/chat_service.py
```

Expected: empty.

- [ ] **Step 5: Confirm no other files use old name**

```bash
grep -r "_from_graph_state" src/ --include="*.py"
```

Expected: empty.

- [ ] **Step 6: Run all tests**

```bash
pytest tests/core/test_chatbot_extract_response.py -v
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/core/chatbot.py \
        src/api/services/chat_service.py \
        tests/core/test_chatbot_extract_response.py
git commit -m "refactor: rename _from_graph_state to extract_response (public API)

chat_service.py was calling a private method on chatbot, violating SRP.
extract_response is now public, type-annotated, and intentionally callable
from outside the class."
```

---

## Success Criteria

After all 10 tasks complete:

- [ ] `python -c "import main; import api_app; print('OK')"` prints `OK`
- [ ] `pytest tests/` passes with no new failures
- [ ] `grep -r "_from_graph_state" src/` returns empty
- [ ] `grep -r "start_session_async\|send_message_async\|get_history_async\|clear_history_async" src/` returns empty
- [ ] `GET /api/metrics/cache/stats` returns 404
- [ ] `POST /api/metrics/cache/reset` returns 404
- [ ] `GET /api/metrics/sessions` still works
- [ ] Total line reduction: ~3,000 lines
