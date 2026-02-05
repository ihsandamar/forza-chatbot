import json
import logging
import re
import traceback
from typing import Any, Dict, Optional
from copy import deepcopy
import pyodbc
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
from src.models.llm import LLM
from src.graphs.generic_text2sql.prompts import (
    INTENT_PARSER_PROMPT,
    INTENT_MATCHER_PROMPT,
    SQL_QUERY_BUILDER_PROMPT,
    SQL_ARCHITECT_PROMPT,
    COLUMN_METADATA_DETAILED
)
from src.graphs.generic_text2sql.tools import GENERIC_TEXT2SQL_TOOLS
from src.graphs.generic_text2sql.state import (
    GenericText2SQLState,
    ParsedIntent,
    ResolutionMetadata,
    QueryStep
)
from src.graphs.generic_text2sql.value_resolver_service import ValueResolverService
from src.graphs.generic_text2sql.json_utils import parse_json_robust, extract_sql_from_text
from src.services.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

# Module-level executor for async DB operations
_db_executor = ThreadPoolExecutor(max_workers=3)

# Module-level caches and singletons
_business_rules_cache = None
_business_rules_vector_store = None
_value_resolver_service = None


def _format_conversation_context(conversation_context: Optional[Dict[str, Any]]) -> str:
    """
    Format conversation context for SQL architect prompt (Phase 3).

    Args:
        conversation_context: Previous query context from Report Agent

    Returns:
        Formatted context string for LLM
    """
    if not conversation_context or not conversation_context.get("has_previous_query"):
        return "This is a new query with no previous context."

    context_parts = ["Previous Query Context:"]

    # Previous SQL
    prev_sql = conversation_context.get("previous_sql", "")
    if prev_sql:
        context_parts.append(f"\nPrevious SQL:\n{prev_sql[:200]}...")

    # Previous filters
    prev_filters = conversation_context.get("previous_filters", [])
    if prev_filters:
        filters_str = ", ".join([f"{f.get('column', '?')}={f.get('value', '?')}" for f in prev_filters[:3]])
        context_parts.append(f"\nPrevious Filters: {filters_str}")

    # Previous grouping
    prev_grouping = conversation_context.get("previous_grouping", [])
    if prev_grouping:
        context_parts.append(f"\nPrevious Grouping: {', '.join(prev_grouping[:3])}")

    # Result statistics
    result_count = conversation_context.get("result_row_count", 0)
    context_parts.append(f"\nPrevious Result Count: {result_count} rows")

    # Conversation hints
    context_parts.append("\n\nUser Intent Analysis:")
    context_parts.append("- User is likely refining or modifying the previous query")
    context_parts.append("- Consider reusing previous table/filters when appropriate")
    context_parts.append("- Look for incremental changes (add filter, change limit, etc.)")

    return "\n".join(context_parts)


def _extract_config_value(config: Optional[RunnableConfig], state: dict, config_key: str, default_config, default_value=None):
    """
    Extract configuration value from RunnableConfig, state, or default config.

    Priority: RunnableConfig > state > default_config > default_value

    Args:
        config: RunnableConfig from LangGraph
        state: Current state dict
        config_key: Key to extract (e.g., 'table_name', 'query')
        default_config: Default configuration object (self.config)
        default_value: Final fallback value

    Returns:
        Configuration value
    """
    def _is_valid_value(val):
        """Check if value is not None and not empty string."""
        if val is None:
            return False
        # For strings, check if not empty after strip
        if isinstance(val, str):
            return bool(val.strip())
        # For lists/dicts, check if not empty
        if isinstance(val, (list, dict)):
            return bool(val)
        return True

    # Try RunnableConfig first (highest priority - runtime config)
    if config and "configurable" in config:
        configurable = config["configurable"]
        logger.debug(f"[CONFIG] Checking RunnableConfig for '{config_key}': type={type(configurable)}")

        # Check if configurable is a Pydantic model
        if hasattr(configurable, config_key):
            value = getattr(configurable, config_key)
            if _is_valid_value(value):
                logger.info(f"[CONFIG] ✓ Using '{config_key}' from RunnableConfig (Pydantic model): {repr(value)[:100]}")
                return value
        # Or if it's a dict
        elif isinstance(configurable, dict):
            value = configurable.get(config_key)
            if _is_valid_value(value):
                logger.info(f"[CONFIG] ✓ Using '{config_key}' from RunnableConfig (dict): {repr(value)[:100]}")
                return value

    # Try state (medium priority - injected by BaseGraph)
    if state and config_key in state:
        value = state.get(config_key)
        if _is_valid_value(value):
            logger.info(f"[CONFIG] ✓ Using '{config_key}' from state: {repr(value)[:100]}")
            return value

    # Try default config (low priority - build-time config)
    if default_config and hasattr(default_config, config_key):
        value = getattr(default_config, config_key)
        if _is_valid_value(value):
            logger.info(f"[CONFIG] ✓ Using '{config_key}' from default config: {repr(value)[:100]}")
            return value

    # Final fallback
    logger.warning(f"[CONFIG] ⚠ Using default value for '{config_key}': {default_value}")
    return default_value


def intent_parser_to_json(response_text: str) -> ParsedIntent:
    """
    Convert LLM response text to ParsedIntent model.

    Handles JSON extraction from markdown code blocks and parsing.

    Args:
        response_text: Raw LLM response text (may contain ```json ... ```)

    Returns:
        ParsedIntent: Structured intent model

    Raises:
        json.JSONDecodeError: If JSON parsing fails
        ValueError: If required fields are missing
    """
    # Clean response text
    content = response_text.strip()

    # Handle markdown code blocks
    if content.startswith("```"):
        # Split by ``` and get content between markers
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
            # Remove 'json' prefix if present
            if content.startswith("json"):
                content = content[4:].strip()
            elif content.startswith("JSON"):
                content = content[4:].strip()

    # Log the content before parsing for debugging
    logger.debug(f"Attempting to parse JSON content (first 500 chars):\n{content[:500]}")

    # Parse JSON with better error handling
    try:
        parsed_data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed at position {e.pos}: {e.msg}")
        logger.error(f"Problematic content around error:\n{content[max(0, e.pos-100):e.pos+100]}")
        raise

    # Validate required fields
    if "complexity" not in parsed_data:
        raise ValueError("Missing required field: complexity")
    if "steps" not in parsed_data:
        raise ValueError("Missing required field: steps")
    if "final_output" not in parsed_data:
        raise ValueError("Missing required field: final_output")

    # Cast to ParsedIntent
    intent: ParsedIntent = {
        "complexity": parsed_data["complexity"],
        "steps": parsed_data["steps"],
        "final_output": parsed_data["final_output"],
    }
    

    logger.debug(f"Parsed intent: complexity={intent['complexity']}, steps={len(intent['steps'])}")

    return intent


def get_business_rules_vector_store():
    """
    Get or create BusinessRulesVectorStore instance (singleton pattern).

    Returns:
        Initialized BusinessRulesVectorStore instance
    """
    global _business_rules_vector_store

    if _business_rules_vector_store is None:
        from src.graphs.generic_text2sql.business_rules_vector_store import BusinessRulesVectorStore

        # Get paths
        current_dir = Path(__file__).parent
        rules_file = current_dir / "business_rules.json"
        persist_dir = current_dir / "chroma_db"

        # DEBUG: Log paths
        logger.info(f"Initializing BusinessRulesVectorStore...")
        logger.info(f"  Rules file: {rules_file}")
        logger.info(f"  Rules file exists: {rules_file.exists()}")
        logger.info(f"  Persist dir: {persist_dir}")
        logger.info(f"  Persist dir exists: {persist_dir.exists()}")
        if persist_dir.exists():
            logger.info(f"  Persist dir contents: {list(persist_dir.iterdir())}")

        _business_rules_vector_store = BusinessRulesVectorStore(
            rules_file_path=str(rules_file),
            persist_directory=str(persist_dir),
            similarity_threshold=0.7
        )

        # Ensure collections exist
        try:
            collections = _business_rules_vector_store.client.list_collections()
            collection_names = [c.name for c in collections]

            logger.info(f"  Found collections: {collection_names}")

            if "business_rules" not in collection_names:
                logger.warning("Business rules collections not found, rebuilding index...")
                _business_rules_vector_store.rebuild_index()
            else:
                logger.info("Loading existing business rules collections...")
                _business_rules_vector_store.rules_collection = _business_rules_vector_store.client.get_collection(
                    "business_rules",
                    embedding_function=_business_rules_vector_store.embedding_function
                )
                _business_rules_vector_store.default_rules_collection = _business_rules_vector_store.client.get_collection(
                    "default_business_rules",
                    embedding_function=_business_rules_vector_store.embedding_function
                )
        except Exception as e:
            logger.error(f"Error checking collections: {e}, rebuilding...")
            _business_rules_vector_store.rebuild_index()

        logger.info("BusinessRulesVectorStore initialized successfully")

    return _business_rules_vector_store


def _execute_sql(sql_query: str, db_connection_string: str) -> list:
    """
    Execute SQL query synchronously and return results.

    Args:
        sql_query: SQL query to execute
        db_connection_string: MSSQL connection string

    Returns:
        List of dictionaries representing rows
    """
    try:
        # Parse connection string
        from urllib.parse import urlparse, parse_qs

        if db_connection_string.startswith("mssql+pyodbc://"):
            parsed = urlparse(db_connection_string)
            query_params = parse_qs(parsed.query)
            driver = query_params.get("driver", ["ODBC Driver 17 for SQL Server"])[0]

            # Build server string with port if specified
            server = parsed.hostname
            if parsed.port:
                server = f"{server},{parsed.port}"

            conn_str = (
                f"Driver={{{driver}}};"
                f"Server={server};"
                f"Database={parsed.path.lstrip('/')};"
                f"UID={parsed.username};"
                f"PWD={parsed.password};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=yes;"
                f"Connection Timeout=30"
            )
        else:
            conn_str = db_connection_string

        # Connect and execute
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        logger.debug(f"Executing SQL query:\n{sql_query}")
        cursor.execute(sql_query)

        # Get column names
        columns = [column[0] for column in cursor.description]

        # Fetch all rows and convert to list of dicts
        rows = []
        for row in cursor.fetchall():
            row_dict = {}
            for idx, value in enumerate(row):
                # Convert types for JSON serialization
                if value is None:
                    row_dict[columns[idx]] = None
                elif isinstance(value, Decimal):
                    # Convert Decimal to float
                    row_dict[columns[idx]] = float(value)
                elif hasattr(value, 'isoformat'):
                    # Convert datetime to ISO string
                    row_dict[columns[idx]] = value.isoformat()
                else:
                    row_dict[columns[idx]] = value
            rows.append(row_dict)

        cursor.close()
        conn.close()

        logger.info(f"Query executed successfully: {len(rows)} rows returned")
        return rows

    except Exception as e:
        logger.error(f"SQL execution error: {e}", exc_info=True)
        raise


def _execute_sql_script(sql_script: str, db_connection_string: str):
    """
    Execute multi-statement SQL script synchronously.

    Args:
        sql_script: SQL script with multiple statements
        db_connection_string: Database connection string

    Returns:
        None (script execution)
    """
    import pyodbc
    import logging
    logger = logging.getLogger(__name__)

    # Parse connection string
    if db_connection_string.startswith("mssql+pyodbc://"):
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(db_connection_string)
        query_params = parse_qs(parsed.query)
        driver = query_params.get('driver', ['ODBC Driver 17 for SQL Server'])[0]

        # Build server string with port if specified
        server = parsed.hostname
        if parsed.port:
            server = f"{server},{parsed.port}"

        pyodbc_conn_str = (
            f"Driver={{{driver}}};"
            f"Server={server};"
            f"Database={parsed.path.lstrip('/')};"
            f"UID={parsed.username};"
            f"PWD={parsed.password};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=yes;"
            f"Connection Timeout=30"
        )
        logger.debug(f"Parsed connection string: Driver={driver};Server={server};Database={parsed.path.lstrip('/')};...")
    else:
        pyodbc_conn_str = db_connection_string

    conn = pyodbc.connect(pyodbc_conn_str, autocommit=False)
    cursor = conn.cursor()

    try:
        # Execute the entire script as a batch to preserve temp table scope
        # Split by GO keyword (SQL Server batch separator) instead of semicolon
        batches = [batch.strip() for batch in sql_script.split('GO') if batch.strip()]

        if not batches:
            # If no GO separators, try to execute as single batch
            # Remove comments and execute
            cleaned_sql = '\n'.join(
                line for line in sql_script.split('\n')
                if line.strip() and not line.strip().startswith('--')
            )
            if cleaned_sql:
                cursor.execute(cleaned_sql)
        else:
            # Execute each batch separately (batches are separated by GO)
            for batch in batches:
                # Remove single-line comments
                cleaned_batch = '\n'.join(
                    line for line in batch.split('\n')
                    if line.strip() and not line.strip().startswith('--')
                )
                if cleaned_batch:
                    cursor.execute(cleaned_batch)

        conn.commit()
        logger.info("SQL script executed successfully")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error executing SQL script: {e}", exc_info=True)
        raise
    finally:
        cursor.close()
        conn.close()

def get_db_connection_string(state: dict = None) -> str:
    """
    Get DB connection string from state, config file, or environment.

    Priority:
    1. State config
    2. Config file (database.uri)
    3. Environment variable (DATABASE_URL)
    4. Error (no fallback)
    """
    import os

    # Try state config first
    if state:
        db_conn = state.get("config", {}).get("db_connection_string")
        if db_conn:
            return db_conn

    # Try config file
    try:
        config = ConfigLoader.load_config("config/config.yaml")
        if hasattr(config, 'database') and hasattr(config.database, 'uri'):
            db_conn = config.database.uri
            if db_conn and db_conn != "${DATABASE_URL}":
                return db_conn
    except Exception as e:
        logger.warning(f"Could not load config file: {e}")

    # Try environment variable
    db_conn = os.getenv("DATABASE_URL")
    if db_conn:
        return db_conn

    # No connection string found
    raise ValueError(
        "Database connection string not found! "
        "Please set DATABASE_URL environment variable or configure database.uri in config.yaml"
    )

async def get_value_resolver(db_connection_string: str, table_name: str = "MasterReportDocumentTable") -> ValueResolverService:
    """
    Get or create ValueResolverService instance (singleton pattern with table-based cache).

    Args:
        db_connection_string: Database connection string
        table_name: Table name to query (default: MasterReportDocumentTable)

    Returns:
        Initialized ValueResolverService instance
    """
    global _value_resolver_service

    # Check if we need to reinitialize (different table or not initialized)
    if _value_resolver_service is None or _value_resolver_service.table_name != table_name:
        logger.info(f"Initializing ValueResolverService for table: {table_name}")
        _value_resolver_service = ValueResolverService(db_connection_string, table_name)
        await _value_resolver_service.initialize()
        logger.info(f"ValueResolverService initialized successfully for table: {table_name}")

    return _value_resolver_service

def load_business_rules() -> dict:
    """
    Load business rules from JSON file with caching.

    Returns:
        Dictionary containing business rules
    """
    global _business_rules_cache

    if _business_rules_cache is not None:
        return _business_rules_cache

    try:
        # Get path to business_rules.json
        current_dir = Path(__file__).parent
        rules_path = current_dir / "business_rules.json"

        if not rules_path.exists():
            logger.warning(f"Business rules file not found: {rules_path}")
            return {}

        with open(rules_path, 'r', encoding='utf-8') as f:
            _business_rules_cache = json.load(f)

        logger.info("Business rules loaded successfully")
        return _business_rules_cache

    except Exception as e:
        logger.error(f"Error loading business rules: {e}", exc_info=True)
        return {}
    
def format_business_rules_for_prompt(business_rules: dict) -> str:
        """
        Format business rules for LLM prompt injection.

        Args:
            business_rules: Loaded business rules dictionary

        Returns:
            Formatted string for prompt
        """
        if not business_rules:
            return "(No business rules available)"

        formatted_sections = []

        # Mandatory Filters
        if "mandatory_filters" in business_rules:
            formatted_sections.append("### ZORUNLU FİLTRELER\n")
            for rule in business_rules["mandatory_filters"].get("rules", []):
                rule_id = rule.get("rule_id", "unknown")
                name = rule.get("name", "")
                triggers = ", ".join(rule.get("triggers", []))
                explanation = rule.get("explanation", "")

                formatted_sections.append(f"**{name}** (ID: {rule_id})")
                formatted_sections.append(f"Tetikleyiciler: {triggers}")
                formatted_sections.append(f"Açıklama: {explanation}")

                for condition in rule.get("mandatory_conditions", []):
                    field = condition.get("field", "")
                    operator = condition.get("operator", "")
                    value = condition.get("value", "")
                    desc = condition.get("description", "")

                    if value:
                        formatted_sections.append(f"  - {field} {operator} {value} ({desc})")
                    else:
                        formatted_sections.append(f"  - {field} {operator} ({desc})")

                formatted_sections.append("")

        # Aggregation Rules
        if "aggregation_rules" in business_rules:
            formatted_sections.append("### TOPLAMA KURALLARI\n")
            for rule in business_rules["aggregation_rules"].get("rules", []):
                rule_id = rule.get("rule_id", "unknown")
                name = rule.get("name", "")
                triggers = ", ".join(rule.get("triggers", []))
                explanation = rule.get("explanation", "")

                formatted_sections.append(f"**{name}** (ID: {rule_id})")
                formatted_sections.append(f"Tetikleyiciler: {triggers}")
                formatted_sections.append(f"Açıklama: {explanation}\n")

        return "\n".join(formatted_sections)

def _get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to resource, works for dev and PyInstaller.

    PyInstaller creates a temp folder and stores path in _MEIPASS.
    In development, use the normal file path.
    """
    from pathlib import Path
    import sys
    import os

    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        # Running in normal Python environment
        base_path = Path(__file__).parent

    return base_path / relative_path





class GenericText2SQLNodeKit:
    """NodeKit for generic text2sql graph."""

    def __init__(
        self,
        llm: LLM,
        config: GenericSQLAssistantConfiguration,
        global_config: Any = None,
        vectorstore: Optional[Chroma] = None
    ):
        self.llm = llm
        self.config = config
        self.vectorstore = vectorstore
        self.global_config = global_config
        logger.debug(f"[TEXT2SQL] NodeKit initialized with config")





    async def intent_parser_node(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        Parse user query into generic structured intent (no business logic, no dates).

        Generic parser that understands query structure but doesn't know about
        specific database schema or date resolution (those are in intent_matcher).

        Args:
            state: Current generic text2sql state with user_query

        Returns:
            Updated state with parsed_intent (generic field names) or error
        """
        try:
            logger.debug(f"Parsing user intent for query: {state['user_query'][:50]}...")

            # Get LLM response (generic parsing, no date context)
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            chain = INTENT_PARSER_PROMPT | llm

            response = await chain.ainvoke({
                "user_query": state["user_query"]
            })

            # Convert response to ParsedIntent model
            intent = intent_parser_to_json(response.content)
            state["parsed_intent"] = intent

            logger.info(
                f"Generic intent parsed: complexity={intent['complexity']}, "
                f"steps={len(intent['steps'])}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Intent parsing JSON error: {e}")
            state["error"] = f"Intent parsing hatası (JSON): {str(e)}"
            state["parsed_intent"] = None
        except ValueError as e:
            logger.error(f"Intent validation error: {e}")
            state["error"] = f"Intent validation hatası: {str(e)}"
            state["parsed_intent"] = None
        except Exception as e:
            logger.error(f"Unexpected error in intent_parser_node: {e}", exc_info=True)
            state["error"] = f"Beklenmeyen hata: {str(e)}"
            state["parsed_intent"] = None

        return state

    async def intent_matching_node(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        Match generic intent to specific database schema (business logic).

        Takes generic field_hint values (tarih, şube, ürün, etc.) and maps them
        to actual database column names (DocumentDate, BranchName, ProductName, etc.)
        based on business rules defined in INTENT_MATCHER_PROMPT.
        Also resolves date expressions to SQL date functions.

        Args:
            state: Current generic text2sql state with parsed_intent (generic)

        Returns:
            Updated state with parsed_intent (DB-specific field names) or error
        """
        try:
            logger.debug("Matching generic intent to database schema...")

            # Check if parsed_intent exists
            if not state.get("parsed_intent"):
                logger.error("No parsed_intent found in state")
                state["error"] = "Intent matching için parsed_intent gerekli"
                return state

            # Get current date/time info using tools
            from src.graphs.generic_text2sql.tools import (
                get_today_date,
                get_current_datetime,
                get_current_year,
                get_current_month
            )

            today_date = get_today_date.invoke({})
            current_datetime = get_current_datetime.invoke({})
            current_year = get_current_year.invoke({})
            current_month = get_current_month.invoke({})

            logger.debug(f"Date context: {today_date}, year={current_year}, month={current_month}")

            # Convert parsed_intent to JSON for prompt
            parsed_intent_json = json.dumps(state["parsed_intent"], indent=2, ensure_ascii=False)

            logger.debug(f"Matching intent with {len(state['parsed_intent']['steps'])} step(s)")

            # Get LLM response with business logic mapping and date resolution
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            chain = INTENT_MATCHER_PROMPT | llm

            response = await chain.ainvoke({
                "parsed_intent": parsed_intent_json,
                "today_date": today_date,
                "current_datetime": current_datetime,
                "current_year": current_year,
                "current_month": current_month
            })

            # Convert response to ParsedIntent model
            matched_intent = intent_parser_to_json(response.content)
            state["parsed_intent"] = matched_intent

            logger.info(
                f"Intent matched to DB schema: complexity={matched_intent['complexity']}, "
                f"steps={len(matched_intent['steps'])}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Intent matching JSON error: {e}")
            state["error"] = f"Intent matching hatası (JSON): {str(e)}"
        except ValueError as e:
            logger.error(f"Intent matching validation error: {e}")
            state["error"] = f"Intent matching validation hatası: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error in intent_matching_node: {e}", exc_info=True)
            state["error"] = f"Intent matching beklenmeyen hata: {str(e)}"

        return state


    async def metadata_enrichment_node(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        Extract metadata for only the columns used in the query (token optimization).

        Collects all field_hint values from parsed_intent (select, filters, aggregations, group_by, order_by)
        and retrieves detailed metadata only for those columns.

        Args:
            state: Current generic text2sql state with parsed_intent

        Returns:
            Updated state with enriched_metadata (dict of column -> description)
        """
        try:
            logger.debug("Enriching metadata for used columns...")

            # Check if parsed_intent exists
            if not state.get("parsed_intent"):
                logger.error("No parsed_intent found in state")
                state["error"] = "Metadata enrichment için parsed_intent gerekli"
                return state

            parsed_intent = state["parsed_intent"]
            used_columns = set()

            # Collect all field_hints from all steps
            for step in parsed_intent["steps"]:
                # From select
                if "select" in step and step["select"]:
                    for field in step["select"]:
                        used_columns.add(field)

                # From filters
                if "filters" in step and step["filters"]:
                    for filter_def in step["filters"]:
                        field_hint = filter_def.get("field_hint")
                        if field_hint:
                            used_columns.add(field_hint)

                # From aggregations
                if "aggregations" in step and step["aggregations"]:
                    for agg in step["aggregations"]:
                        field_hint = agg.get("field_hint")
                        if field_hint and field_hint != "*":
                            used_columns.add(field_hint)

                # From group_by
                if "group_by" in step and step["group_by"]:
                    for field in step["group_by"]:
                        used_columns.add(field)

                # From order_by
                if "order_by" in step and step["order_by"]:
                    field_hint = step["order_by"].get("field_hint")
                    if field_hint:
                        used_columns.add(field_hint)

            # Get metadata only for used columns
            enriched_metadata = {}
            for column in used_columns:
                if column in COLUMN_METADATA_DETAILED:
                    enriched_metadata[column] = COLUMN_METADATA_DETAILED[column]
                else:
                    # Column not in metadata dictionary, skip
                    logger.debug(f"No metadata found for column: {column}")

            # Store in state
            state["enriched_metadata"] = enriched_metadata

            logger.info(
                f"Metadata enriched: {len(enriched_metadata)} columns with details "
                f"(out of {len(used_columns)} used columns)"
            )

            # Log which columns got metadata
            if enriched_metadata:
                logger.debug(f"Columns with metadata: {', '.join(enriched_metadata.keys())}")

        except Exception as e:
            logger.error(f"Unexpected error in metadata_enrichment_node: {e}", exc_info=True)
            state["error"] = f"Metadata enrichment hatası: {str(e)}"

        return state



    async def value_resolver_node(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        Resolve user input values to actual database values.

        Takes parsed_intent and resolves all value_hints in filters to actual DB values
        using ValueResolverService with fuzzy matching and Turkish character support.

        Args:
            state: Current generic text2sql state with parsed_intent
            config: LangGraph runtime configuration

        Returns:
            Updated state with resolved_steps and resolution_metadata or error
        """
        try:
            logger.debug("Starting value resolution...")

            # Check if parsed_intent exists
            if not state.get("parsed_intent"):
                logger.error("No parsed_intent found in state")
                state["error"] = "Value resolution için parsed_intent gerekli"
                return state

            # Extract table name - CRITICAL: Check state first for session-based table name
            # State has priority over RunnableConfig to use session-based table from create_master_table
            table_name = state.get("table_name")
            if not table_name:
                # Fallback to config
                table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")
                logger.info(f"[VALUE_RESOLVER] Using table_name from config: {table_name}")
            else:
                logger.info(f"[VALUE_RESOLVER] Using table_name from state: {table_name}")

            # Get ValueResolverService with table name
            db_conn = get_db_connection_string(state)
            resolver = await get_value_resolver(db_conn, table_name)

            # Deep copy steps to avoid mutating original
            parsed_intent = state["parsed_intent"]
            resolved_steps = deepcopy(parsed_intent["steps"])

            # Track resolution statistics
            total_values = 0
            resolved_values = 0
            unresolved_values = []
            confidence_scores = []

            # Resolve values in each step
            for step in resolved_steps:
                if "filters" not in step or not step["filters"]:
                    continue

                for filter_def in step["filters"]:
                    value_hint = filter_def.get("value_hint")
                    field_hint = filter_def.get("field_hint")

                    if not value_hint or not field_hint:
                        continue

                    # Skip uncertain values marked by intent parser
                    if value_hint.strip() == "?":
                        logger.debug(f"Skipping uncertain value '?' for column '{field_hint}'")
                        continue

                    # Skip if value_hint is a reference to previous step
                    if (value_hint.startswith("step_") or
                        "önceki adım" in value_hint.lower() or
                        "previous step" in value_hint.lower()):
                        logger.debug(f"Skipping resolution for reference: {value_hint}")
                        continue

                    # Skip date expressions (already resolved by intent parser as DATEADD/dates)
                    if "DATEADD" in value_hint or value_hint.count("-") == 2:  # ISO date format YYYY-MM-DD
                        logger.debug(f"Skipping resolution for date value: {value_hint}")
                        continue

                    # Skip numeric values (Hour, DayOfWeek, etc. - already correct values)
                    try:
                        # Try to parse as number (int or float)
                        float(str(value_hint))
                        logger.debug(f"Skipping resolution for numeric value '{value_hint}' in column '{field_hint}'")
                        continue
                    except (ValueError, TypeError):
                        # Not a number, continue with resolution
                        pass

                    total_values += 1

                    # Try to resolve the value
                    logger.debug(f"Resolving value '{value_hint}' for column '{field_hint}'")
                    result = await resolver.resolve(value_hint, field_hint)

                    if result:
                        filter_def["resolved_value"] = result["resolved"]
                        filter_def["resolution_confidence"] = result["confidence"]
                        confidence_scores.append(result["confidence"])
                        resolved_values += 1

                        logger.info(
                            f"✓ Resolved '{value_hint}' → '{result['resolved']}' "
                            f"(confidence: {result['confidence']:.1f}%)"
                        )
                    else:
                        unresolved_values.append(f"{field_hint}:{value_hint}")
                        logger.warning(f"✗ Could not resolve '{value_hint}' for column '{field_hint}'")

            # Create resolution metadata
            resolution_metadata: ResolutionMetadata = {
                "total_values": total_values,
                "resolved_values": resolved_values,
                "unresolved_values": unresolved_values,
                "avg_confidence": sum(confidence_scores) / len(confidence_scores) if confidence_scores else None
            }

            state["resolved_steps"] = resolved_steps
            state["resolution_metadata"] = resolution_metadata

            # Log resolution results
            if unresolved_values:
                warning_msg = (
                    f"Bazı değerler çözümlenemedi ({len(unresolved_values)}/{total_values}): "
                    f"{', '.join(unresolved_values)} - value_hint değerleri kullanılacak"
                )
                logger.warning(warning_msg)
                # Don't set error - let SQL generation continue with value_hint

            # Format confidence message
            avg_conf = resolution_metadata['avg_confidence']
            conf_msg = f" (avg confidence: {avg_conf:.1f}%)" if avg_conf is not None else ""

            logger.info(
                f"Value resolution completed: {resolved_values}/{total_values} values resolved{conf_msg}"
            )

        except Exception as e:
            logger.error(f"Unexpected error in value_resolver_node: {e}", exc_info=True)
            state["error"] = f"Value resolution hatası: {str(e)}"

        return state


    async def sql_query_builder_node(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        Build SQL query from resolved steps using LLM.

        Takes resolved_steps (with matched column names and resolved values)
        and generates MSSQL query using GPT-4o-mini.

        Args:
            state: Current generic text2sql state with resolved_steps
            config: LangGraph runtime configuration

        Returns:
            Updated state with sql_queries or error
        """
        try:
            logger.debug("Starting SQL query building...")

            # Check if resolved_steps exists
            if not state.get("resolved_steps"):
                logger.error("No resolved_steps found in state")
                state["error"] = "SQL query oluşturma için resolved_steps gerekli"
                return state

            # Check if there was a critical error in previous steps
            if state.get("error") and "Intent" in state.get("error", ""):
                # Only skip if there was an intent parsing error (critical)
                logger.warning(f"Skipping SQL generation due to critical error: {state['error']}")
                return state

            # Extract table name - CRITICAL: Check state first for session-based table name
            # State has priority over RunnableConfig to use session-based table from create_master_table
            table_name = state.get("table_name")
            if not table_name:
                # Fallback to config
                table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")
                logger.info(f"[SQL_QUERY_BUILDER] Using table_name from config: {table_name}")
            else:
                logger.info(f"[SQL_QUERY_BUILDER] Using table_name from state: {table_name}")

            # Escape table name for SQL Server (handle special chars like hyphens in session-based names)
            escaped_table_name = f"[{table_name}]"
            logger.info(f"[SQL_QUERY_BUILDER] Escaped table_name: {escaped_table_name}")

            resolved_steps = state["resolved_steps"]

            # Prepare resolved steps JSON for prompt
            steps_json = json.dumps(resolved_steps, indent=2, ensure_ascii=False)

            # Prepare enriched metadata (only for used columns)
            enriched_metadata = state.get("enriched_metadata") or {}
            if enriched_metadata:
                metadata_text = "\n".join(
                    f"- {col}: {desc}" for col, desc in enriched_metadata.items()
                )
            else:
                metadata_text = "(No additional metadata available)"

            # Get business rules context
            business_rules_context = state.get("business_rules_context") or "(No business rules available)"

            logger.debug(
                f"Building SQL query for {len(resolved_steps)} step(s) "
                f"with {len(enriched_metadata)} column metadata "
                f"and business rules context ({len(business_rules_context)} chars)"
            )

            # Get LLM response
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            chain = SQL_QUERY_BUILDER_PROMPT | llm

            response = await chain.ainvoke({
                "table_name": escaped_table_name,
                "resolved_steps": steps_json,
                "enriched_metadata": metadata_text,
                "business_rules_context": business_rules_context
            })

            # Extract SQL from response (remove markdown if present)
            sql_query = response.content.strip()

            # Clean markdown code blocks
            if sql_query.startswith("```"):
                parts = sql_query.split("```")
                if len(parts) >= 2:
                    sql_query = parts[1]
                    # Remove 'sql' prefix if present
                    if sql_query.startswith("sql"):
                        sql_query = sql_query[3:].strip()

            # Store SQL query
            state["sql_queries"] = [sql_query]

            logger.info(f"SQL query generated successfully ({len(sql_query)} chars)")
            logger.debug(f"Generated SQL:\n{sql_query}")

        except Exception as e:
            logger.error(f"Unexpected error in sql_query_builder_node: {e}", exc_info=True)
            state["error"] = f"SQL query oluşturma hatası: {str(e)}"

        return state



    async def sql_executor_node(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        Execute SQL query and store results in state.

        Takes sql_queries from state, executes them against MSSQL database,
        and stores results as list of dictionaries.

        Args:
            state: Current generic text2sql state with sql_queries

        Returns:
            Updated state with results or error
        """
        try:
            logger.debug("Starting SQL execution...")

            # Check if sql_queries exists
            if not state.get("sql_queries") or len(state["sql_queries"]) == 0:
                logger.error("No sql_queries found in state")
                state["error"] = "SQL çalıştırma için sql_queries gerekli"
                return state

            # Check if there was an error in previous steps
            if state.get("error"):
                logger.warning(f"Skipping SQL execution due to previous error: {state['error']}")
                return state

            sql_query = state["sql_queries"][0]  # Get first query

            # Get DB connection string
            db_conn = get_db_connection_string(state)

            # Execute SQL asynchronously
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(_db_executor, _execute_sql, sql_query, db_conn)

            # Store results
            state["results"] = results

            logger.info(f"SQL execution completed: {len(results) if results else 0} rows retrieved")

            # Log first few rows for debugging
            if results:
                logger.debug(f"Sample results (first 3 rows):\n{json.dumps(results[:3], indent=2, ensure_ascii=False)}")

        except Exception as e:
            logger.error(f"Unexpected error in sql_executor_node: {e}", exc_info=True)
            state["error"] = f"SQL çalıştırma hatası: {str(e)}"

        return state



        # Deprecated code removed
        logger.debug("Deprecated function removed")


    # ============================================================================
    # OPTIMIZED NODES - Collapsed Architecture
    # ============================================================================




    async def sql_architect_node(self, state: GenericText2SQLState, *, config: RunnableConfig) -> GenericText2SQLState:
        """
        OPTIMIZED: Collapsed SQL Architect Node.

        Combines intent_parser + intent_matching into a single LLM call:
        - Parses user query structure
        - Maps to database schema
        - Resolves date expressions
        - Applies business rules
        - Uses Chain of Thought reasoning

        This eliminates 1 LLM call compared to the original architecture,
        reducing latency by ~3-5 seconds.

        Args:
            state: Current generic text2sql state with user_query
            config: LangGraph runtime configuration

        Returns:
            Updated state with parsed_intent, business_rules, schema_metadata
        """
        try:
            logger.info("=" * 80)
            logger.info("[SQL_ARCHITECT] Starting SQL Architect (collapsed architecture)...")

            # Extract table name - CRITICAL: Check state first for session-based table name
            # State has priority over RunnableConfig to use session-based table from create_master_table
            table_name = state.get("table_name")
            if not table_name:
                # Fallback to config
                table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")
                logger.info(f"[SQL_ARCHITECT] Using table_name from config: {table_name}")
            else:
                logger.info(f"[SQL_ARCHITECT] Using table_name from state: {table_name}")

            # Escape table name for SQL Server (handle special chars like hyphens in session-based names)
            escaped_table_name = f"[{table_name}]"

            column_metadata_dict = _extract_config_value(config, state, "column_metadata", self.config, None)
            business_rules_list = _extract_config_value(config, state, "business_rules", self.config, None)

            logger.info(f"[SQL_ARCHITECT] Escaped table_name: {escaped_table_name}")
            logger.info(f"[SQL_ARCHITECT] Final column_metadata: {len(column_metadata_dict) if column_metadata_dict else 0} columns")
            logger.info(f"[SQL_ARCHITECT] Final business_rules: {len(business_rules_list) if business_rules_list else 0} rules")
            logger.info("=" * 80)

            # Load business rules
            if business_rules_list and len(business_rules_list) > 0:
                business_rules = {
                    "rules": business_rules_list,
                    "source": "config"
                }
            else:
                # Fallback to loading from business_rules.json file
                business_rules = load_business_rules()
                logger.info(f"Using business rules from file")

            state["business_rules"] = business_rules

            # Format business rules for prompt
            business_rules_text = format_business_rules_for_prompt(business_rules)

            # Get current date/time info
            from src.graphs.generic_text2sql.tools import (
                get_today_date,
                get_current_datetime,
                get_current_year,
                get_current_month
            )

            today_date = get_today_date.invoke({})
            current_datetime = get_current_datetime.invoke({})
            current_year = get_current_year.invoke({})
            current_month = get_current_month.invoke({})

            # OPTIMIZED: Use static metadata instead of dynamic schema discovery
            # This eliminates 4-5 second DB query delay before LLM call
            # column_metadata_dict already extracted via helper function
            if column_metadata_dict and len(column_metadata_dict) > 0:
                column_metadata = column_metadata_dict
            else:
                # Fallback to default metadata from prompts
                from src.graphs.generic_text2sql.prompts import COLUMN_METADATA_DETAILED
                column_metadata = COLUMN_METADATA_DETAILED
                logger.info(f"Using default column metadata ({len(column_metadata)} columns)")

            # Format schema metadata for prompt
            schema_text = "\n".join(
                f"- {col_name}: {desc}"
                for col_name, desc in column_metadata.items()
            )

            state["schema_metadata"] = column_metadata

            logger.debug(f"Architecting SQL for query: {state['user_query'][:100]}...")

            # Phase 3: Extract conversation context
            conversation_context = state.get("conversation_context")
            context_text = _format_conversation_context(conversation_context)

            if conversation_context:
                logger.info(f"[SQL_ARCHITECT] ⚡ Phase 3: Using conversation context")
                logger.info(f"[SQL_ARCHITECT] Previous table: {conversation_context.get('previous_table', 'N/A')}")
                logger.info(f"[SQL_ARCHITECT] Previous filters: {len(conversation_context.get('previous_filters', []))}")
                logger.info(f"[SQL_ARCHITECT] Result count: {conversation_context.get('result_row_count', 0)}")

            # Single LLM call with collapsed architecture + Phase 3 context
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            chain = SQL_ARCHITECT_PROMPT | llm

            # table_name already extracted via helper function with proper fallbacks
            logger.info(f"[SQL_ARCHITECT] Using table_name for LLM: {escaped_table_name}")

            response = await chain.ainvoke({
                "user_query": state["user_query"],
                "today_date": today_date,
                "current_datetime": current_datetime,
                "current_year": current_year,
                "current_month": current_month,
                "table_name": escaped_table_name,
                "schema_metadata": schema_text,
                "business_rules": business_rules_text,
                "conversation_context": context_text  # Phase 3: Add context
            })

            # Parse JSON response using robust parser
            expected_keys = ["complexity", "steps", "final_output"]
            parsed_intent = parse_json_robust(response.content, expected_keys=expected_keys)

            if not parsed_intent:
                raise ValueError("Failed to parse intent from LLM response")

            # Cast to ParsedIntent
            intent: ParsedIntent = {
                "complexity": parsed_intent["complexity"],
                "steps": parsed_intent["steps"],
                "final_output": parsed_intent["final_output"],
            }

            state["parsed_intent"] = intent

            # Log applied business rules
            applied_rules = parsed_intent.get("applied_business_rules", [])
            if applied_rules:
                logger.info(f"Applied business rules: {', '.join(applied_rules)}")

            logger.info(
                f"SQL Architect completed: complexity={intent['complexity']}, "
                f"steps={len(intent['steps'])}, "
                f"applied_rules={len(applied_rules)}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"SQL Architect JSON error: {e}")
            state["error"] = f"SQL Architect JSON hatası: {str(e)}"
            state["parsed_intent"] = None
        except ValueError as e:
            logger.error(f"SQL Architect validation error: {e}")
            state["error"] = f"SQL Architect validation hatası: {str(e)}"
            state["parsed_intent"] = None
        except Exception as e:
            logger.error(f"Unexpected error in sql_architect_node: {e}", exc_info=True)
            state["error"] = f"SQL Architect beklenmeyen hata: {str(e)}"
            state["parsed_intent"] = None

        return state


    async def sql_executor_node_with_retry(self, state: GenericText2SQLState, *, config: RunnableConfig = None) -> GenericText2SQLState:
        """
        OPTIMIZED: SQL Executor with self-healing retry logic.

        If SQL execution fails, sends error back to SQL generator for correction
        instead of immediately failing.

        Args:
            state: Current generic text2sql state with sql_queries

        Returns:
            Updated state with results or error
        """
        try:
            logger.debug("Starting SQL execution with retry logic...")

            # Initialize retry tracking
            if "retry_count" not in state or state["retry_count"] is None:
                state["retry_count"] = 0
            if "sql_error_history" not in state or state["sql_error_history"] is None:
                state["sql_error_history"] = []

            # Check if sql_queries exists
            if not state.get("sql_queries") or len(state["sql_queries"]) == 0:
                logger.error("No sql_queries found in state")
                state["error"] = "SQL çalıştırma için sql_queries gerekli"
                return state

            # Check if there was an error in previous steps
            if state.get("error"):
                logger.warning(f"Skipping SQL execution due to previous error: {state['error']}")
                return state

            sql_query = state["sql_queries"][0]  # Get first query

            # Get DB connection string
            db_conn = get_db_connection_string(state)

            # Execute SQL asynchronously
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(_db_executor, _execute_sql, sql_query, db_conn)

                # Store results
                state["results"] = results

                logger.info(f"SQL execution completed successfully: {len(results) if results else 0} rows retrieved")

                # Log first few rows for debugging
                if results:
                    logger.debug(f"Sample results (first 3 rows):\n{json.dumps(results[:3], indent=2, ensure_ascii=False)}")

            except Exception as sql_error:
                # SQL execution failed - prepare for self-healing
                error_msg = str(sql_error)
                logger.error(f"SQL execution error: {error_msg}")

                # Track error history
                state["sql_error_history"].append({
                    "attempt": state["retry_count"] + 1,
                    "query": sql_query,
                    "error": error_msg
                })

                # Check retry limit
                max_retries = 2
                if state["retry_count"] >= max_retries:
                    logger.error(f"Max retries ({max_retries}) exceeded, giving up")
                    state["error"] = f"SQL hatası (max retry aşıldı): {error_msg}"
                    return state

                # Increment retry counter
                state["retry_count"] += 1

                # Set error for routing back to SQL generator
                state["error"] = f"SQL_RETRY_NEEDED: {error_msg}"
                logger.warning(
                    f"SQL execution failed (attempt {state['retry_count']}/{max_retries}), "
                    f"will retry with corrected query"
                )

        except Exception as e:
            logger.error(f"Unexpected error in sql_executor_node_with_retry: {e}", exc_info=True)
            state["error"] = f"SQL çalıştırma hatası: {str(e)}"

        return state


    # ============================================================================
    # BUSINESS RULES VECTOR STORE NODE
    # ============================================================================

    async def create_master_table_node(self, state: GenericText2SQLState, *, config: RunnableConfig) -> GenericText2SQLState:
        """
        Create master table from configuration at the beginning of the graph.

        Table name and creation SQL are loaded from assistant configuration.
        All subsequent queries will run against this temp table.

        Phase 2: Supports table reuse for delta execution.
        If _reuse_table=True, skips table creation and reuses existing table.

        Phase 4: Session-based table naming and TTL management via TableRegistry.
        """
        logger.info("=" * 80)
        logger.info("[CREATE_MASTER_TABLE] Starting table creation...")

        # Phase 4: Get session ID for session-based table management
        session_id = config.get("configurable", {}).get("thread_id") if config else None

        # Phase 2: Check for table reuse flag
        reuse_table = state.get("_reuse_table", False)

        # Phase 4: Check table registry for existing table
        from src.graphs.generic_text2sql.table_registry import get_table_registry
        registry = get_table_registry()

        if reuse_table and session_id:
            existing_table = await registry.check_table_exists(session_id)
            if existing_table:
                logger.info(
                    f"[CREATE_MASTER_TABLE] ⚡ Phase 4: Reusing table {existing_table.table_name} "
                    f"(TTL refreshed, queries={existing_table.query_count})"
                )
                logger.info("[CREATE_MASTER_TABLE] ✓ Table creation skipped (~500ms saved)")
                logger.info("=" * 80)
                state["_table_reused"] = True
                # Store reused table name in state for other nodes to use
                state["table_name"] = existing_table.table_name
                logger.info(f"[CREATE_MASTER_TABLE] Stored reused table_name in state: {existing_table.table_name}")
                return state

        logger.info(f"[CREATE_MASTER_TABLE] config parameter: {config is not None}")
        logger.info(f"[CREATE_MASTER_TABLE] config.configurable exists: {config and 'configurable' in config}")
        if config and "configurable" in config:
            logger.info(f"[CREATE_MASTER_TABLE] configurable type: {type(config['configurable'])}")
            logger.info(f"[CREATE_MASTER_TABLE] configurable content: {config['configurable']}")
        logger.info("=" * 80)

        # Extract configuration values using helper function
        table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")
        logger.info(f"[CREATE_MASTER_TABLE] Using table name: {table_name}")

        query = _extract_config_value(config, state, "query", self.config, None)

        logger.info(f"[CREATE_MASTER_TABLE] Final table_name: {table_name}")
        logger.info(f"[CREATE_MASTER_TABLE] Final query length: {len(query) if query else 0} chars")

        try:
            logger.info(f"[CREATE_MASTER_TABLE] Preparing to create master table...")
            # Get DB connection string
            db_conn = get_db_connection_string(state)
            logger.info(f"[CREATE_MASTER_TABLE] Using connection: {db_conn[:50]}...")

            # Get SQL from configuration or fallback to file
            master_table_sql = None

            if query and query.strip():
                # Use SQL from runtime configuration (already resolved from RunnableConfig or fallbacks)
                master_table_sql = query
                logger.info(f"[CREATE_MASTER_TABLE] Using SQL from configuration ({len(master_table_sql)} characters)")
            else:
                # Fallback: Read SQL file - works in both dev and PyInstaller builds
                sql_file = _get_resource_path("master_table_creation.sql")
                logger.info(f"[CREATE_MASTER_TABLE] SQL file path: {sql_file}")

                if not sql_file.exists():
                    # Try alternative paths for PyInstaller
                    alternative_paths = [
                        _get_resource_path("src/graphs/generic_text2sql/master_table_creation.sql"),
                        Path(__file__).parent / "master_table_creation.sql",
                    ]

                    for alt_path in alternative_paths:
                        logger.info(f"[CREATE_MASTER_TABLE] Trying alternative path: {alt_path}")
                        if alt_path.exists():
                            sql_file = alt_path
                            break
                    else:
                        logger.error(f"Master table creation SQL file not found. Tried: {sql_file}, {alternative_paths}")
                        state["error"] = "Master table creation SQL file not found"
                        return state

                logger.info(f"[CREATE_MASTER_TABLE] Found SQL file at: {sql_file}")

                with open(sql_file, 'r', encoding='utf-8') as f:
                    master_table_sql = f.read()

                logger.info(f"[CREATE_MASTER_TABLE] SQL script loaded: {len(master_table_sql)} characters")

            # No table name replacement needed - using base name directly
            logger.info(f"[CREATE_MASTER_TABLE] Using base table name in SQL: {table_name}")

            # Execute SQL asynchronously
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_db_executor, _execute_sql_script, master_table_sql, db_conn)

            logger.info(f"[CREATE_MASTER_TABLE] {table_name} created successfully")

            # Store session-based table name in state for other nodes to use
            state["table_name"] = table_name
            logger.info(f"[CREATE_MASTER_TABLE] Stored table_name in state: {table_name}")

            # Phase 4: Register table in registry
            if session_id:
                # Get document count from state if available
                document_count = len(state.get("documents", []))
                metadata = await registry.register_table(session_id, table_name, document_count)
                logger.info(
                    f"[CREATE_MASTER_TABLE] Phase 4: Table registered in registry "
                    f"(ttl={metadata.ttl_seconds}s)"
                )

        except Exception as e:
            logger.error(f"[CREATE_MASTER_TABLE] Error creating master table: {e}", exc_info=True)
            state["error"] = f"Master table creation error: {str(e)}"

        return state


    async def cleanup_master_table_node(self, state: GenericText2SQLState, *, config: RunnableConfig) -> GenericText2SQLState:
        """
        Drop master table at the end of the graph.

        Cleanup temp table to free resources. Table name is loaded from configuration.

        Phase 2: Skips cleanup if table is being reused for conversation.
        Table will be cleaned up on session end or timeout.

        Phase 4: TTL-managed tables are handled by TableRegistry background cleanup.
        Only immediate cleanup for non-session tables.
        """
        # Phase 4: Get session ID
        session_id = config.get("configurable", {}).get("thread_id") if config else None

        # Phase 2: Check for table reuse flag
        reuse_table = state.get("_reuse_table", False)

        if reuse_table and session_id:
            # Phase 4: Refresh TTL instead of cleanup
            from src.graphs.generic_text2sql.table_registry import get_table_registry
            registry = get_table_registry()

            existing_table = await registry.check_table_exists(session_id)
            if existing_table:
                logger.info(
                    f"[CLEANUP_MASTER_TABLE] ⚡ Phase 4: Skipping cleanup (TTL-managed) "
                    f"(table={existing_table.table_name}, ttl={existing_table.ttl_remaining():.0f}s)"
                )
                logger.info("[CLEANUP_MASTER_TABLE] ✓ Table cleanup skipped (~200ms saved)")
                logger.info("[CLEANUP_MASTER_TABLE] Table will be cleaned up by TTL background task")
                return state

        # Extract table name using helper function
        table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")

        logger.info(f"[CLEANUP_MASTER_TABLE] Dropping {table_name}...")

        try:
            # Get DB connection string
            db_conn = get_db_connection_string(state)

            # Drop table SQL - escape table name with square brackets for SQL Server
            cleanup_sql = f"DROP TABLE IF EXISTS [{table_name}];"

            # Execute SQL asynchronously
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_db_executor, _execute_sql_script, cleanup_sql, db_conn)

            logger.info(f"[CLEANUP_MASTER_TABLE] {table_name} dropped successfully")

            # Phase 4: Unregister from table registry
            if session_id:
                from src.graphs.generic_text2sql.table_registry import get_table_registry
                registry = get_table_registry()
                unregistered = await registry.unregister_table(session_id)
                if unregistered:
                    logger.info(f"[CLEANUP_MASTER_TABLE] Phase 4: Table unregistered from registry")

        except Exception as e:
            logger.warning(f"[CLEANUP_MASTER_TABLE] Error dropping master table (may not exist): {e}")
            # Don't set error - cleanup failure shouldn't break the flow

        return state



    async def retrieve_business_rules_node(self, state: GenericText2SQLState, *, config: RunnableConfig) -> GenericText2SQLState:
        """
        Retrieve relevant business rules for the user query using vector store.

        Uses semantic search to find the most relevant business rules based on:
        - User query
        - Parsed intent (if available)
        - Detected tables (if available)

        Stores results in state for use in SQL generation.

        Args:
            state: Current generic text2sql state with user_query
            config: LangGraph runtime configuration

        Returns:
            Updated state with business_rules_context, merged_sql_components, applied_business_rules
        """
        try:
            logger.info("Retrieving relevant business rules from vector store...")

            # Get vector store instance
            vector_store = get_business_rules_vector_store()

            # Extract table name - CRITICAL: Check state first for session-based table name
            # State has priority over RunnableConfig to use session-based table from create_master_table
            table_name = state.get("table_name")
            if not table_name:
                # Fallback to config
                table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")
                logger.info(f"[RETRIEVE_BUSINESS_RULES] Using table_name from config: {table_name}")
            else:
                logger.info(f"[RETRIEVE_BUSINESS_RULES] Using table_name from state: {table_name}")

            # Extract detected tables from parsed_intent if available
            detected_tables = state.get("detected_tables")
            if not detected_tables and state.get("parsed_intent"):
                # Use extracted table name
                detected_tables = [table_name]

            # Get relevant rules
            logger.debug(f"Searching rules for query: {state['user_query'][:100]}...")

            result = vector_store.get_relevant_rules_for_query(
                user_query=state['user_query'],
                detected_tables=detected_tables,
                n_results=5,  # Top 5 most relevant rules
                use_hybrid=True  # Use both semantic and keyword search
            )

            # Store results in state
            state["applied_business_rules"] = result['rules']
            state["merged_sql_components"] = result['merged_sql']

            # Format business rules context for LLM prompt
            context_parts = []

            # 1. Default rules (always applied)
            default_rules = [r for r in result['rules'] if r['is_default']]
            if default_rules:
                context_parts.append("## Default Business Rules (Her Zaman Uygulanır):\n")
                for rule in default_rules:
                    desc = rule['metadata']['description']
                    context_parts.append(f"- {desc}")

            # 2. Query-specific rules
            semantic_rules = [r for r in result['rules'] if not r['is_default']]
            if semantic_rules:
                context_parts.append("\n## Bu Sorguya Özel İş Kuralları:\n")
                for rule in semantic_rules:
                    desc = rule['metadata']['description']
                    similarity = rule['similarity']
                    context_parts.append(f"- {desc} (ilgi: {similarity:.2f})")

            # 3. Merged SQL components (SQL oluşturmada kullanılacak)
            if result['merged_sql']:
                context_parts.append("\n## SQL Bileşenleri (Kullanılması Gereken):\n")

                for component, value in result['merged_sql'].items():
                    if value:
                        context_parts.append(f"**{component.upper()}**: `{value}`")

            business_rules_context = "\n".join(context_parts)
            state["business_rules_context"] = business_rules_context

            # Logging
            logger.info(
                f"Business rules retrieved: "
                f"total={result['total_count']}, "
                f"default={result['default_count']}, "
                f"semantic={result['semantic_count']}"
            )

            if result['rules']:
                logger.debug("Applied rules:")
                for rule in result['rules']:
                    logger.debug(
                        f"  - [{rule['rule_id']}] "
                        f"similarity={rule['similarity']:.3f} "
                        f"{'[DEFAULT]' if rule['is_default'] else ''}"
                    )

            logger.debug(f"Business rules context length: {len(business_rules_context)} chars")

        except Exception as e:
            logger.error(f"Error in retrieve_business_rules_node: {e}", exc_info=True)
            # Don't fail the whole graph - continue without business rules
            state["business_rules_context"] = "(Business rules could not be retrieved)"
            state["merged_sql_components"] = {}
            state["applied_business_rules"] = []
            logger.warning("Continuing without business rules due to error")

        return state
