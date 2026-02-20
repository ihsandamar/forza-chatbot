
import json
import logging
from copy import deepcopy
import pyodbc
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from langchain_openai import ChatOpenAI
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
# REMOVED: schema_discovery import (optimized to use static metadata)


logger = logging.getLogger(__name__)


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

# Module-level cache for ValueResolverService
_value_resolver_service = None

# Module-level executor for async DB operations
_db_executor = ThreadPoolExecutor(max_workers=3)


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


async def intent_parser_node(state: GenericText2SQLState) -> GenericText2SQLState:
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

async def intent_matching_node(state: GenericText2SQLState) -> GenericText2SQLState:
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


async def metadata_enrichment_node(state: GenericText2SQLState) -> GenericText2SQLState:
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


async def get_value_resolver(db_connection_string: str) -> ValueResolverService:
    """
    Get or create ValueResolverService instance (singleton pattern).

    Args:
        db_connection_string: Database connection string

    Returns:
        Initialized ValueResolverService instance
    """
    global _value_resolver_service

    if _value_resolver_service is None:
        logger.info("Initializing ValueResolverService...")
        _value_resolver_service = ValueResolverService(db_connection_string)
        await _value_resolver_service.initialize()
        logger.info("ValueResolverService initialized successfully")

    return _value_resolver_service


async def value_resolver_node(state: GenericText2SQLState) -> GenericText2SQLState:
    """
    Resolve user input values to actual database values.

    Takes parsed_intent and resolves all value_hints in filters to actual DB values
    using ValueResolverService with fuzzy matching and Turkish character support.

    Args:
        state: Current generic text2sql state with parsed_intent

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

        # Get ValueResolverService
        db_conn = get_db_connection_string(state)
        resolver = await get_value_resolver(db_conn)

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


async def sql_query_builder_node(state: GenericText2SQLState) -> GenericText2SQLState:
    """
    Build SQL query from resolved steps using LLM.

    Takes resolved_steps (with matched column names and resolved values)
    and generates MSSQL query using GPT-4o-mini.

    Args:
        state: Current generic text2sql state with resolved_steps

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

        resolved_steps = state["resolved_steps"]

        # ✅ FIX: Inject previous filters from conversation_context
        conversation_context = state.get("conversation_context", {})
        previous_filters = conversation_context.get("previous_filters", [])

        if previous_filters:
            logger.info(f"[SQL_BUILDER] Found {len(previous_filters)} previous filters, injecting into resolved_steps")

            # Add previous filters to first step's filters (if not already present)
            if len(resolved_steps) > 0:
                step_filters = resolved_steps[0].get("filters", [])

                # Get existing filter columns to avoid duplicates
                existing_columns = {f.get("field_hint") for f in step_filters if f.get("field_hint")}

                # Inject missing previous filters
                for prev_filter in previous_filters:
                    column = prev_filter.get("column")
                    if column and column not in existing_columns:
                        # Add as resolved filter
                        new_filter = {
                            "field_hint": column,
                            "operator": prev_filter.get("operator", "="),
                            "value_hint": prev_filter.get("value"),
                            "resolved_value": prev_filter.get("value"),  # Already resolved
                            "resolution_confidence": 100,
                            "_source": "previous_context"  # Mark source
                        }
                        step_filters.append(new_filter)
                        logger.info(f"[SQL_BUILDER] Injected previous filter: {column} {prev_filter.get('operator')} {prev_filter.get('value')}")

                resolved_steps[0]["filters"] = step_filters

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


async def sql_executor_node(state: GenericText2SQLState) -> GenericText2SQLState:
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

# Module-level cache for business rules
_business_rules_cache = None


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


async def sql_architect_node(state: GenericText2SQLState) -> GenericText2SQLState:
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

    Returns:
        Updated state with parsed_intent, business_rules, schema_metadata
    """
    try:
        logger.info("Starting SQL Architect (collapsed architecture)...")

        # Load business rules
        business_rules = load_business_rules()
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
        from src.graphs.generic_text2sql.prompts import COLUMN_METADATA_DETAILED

        # Format schema metadata for prompt (using static metadata)
        schema_text = "\n".join(
            f"- {col_name}: {desc}"
            for col_name, desc in COLUMN_METADATA_DETAILED.items()
        )

        state["schema_metadata"] = COLUMN_METADATA_DETAILED

        logger.debug(f"Architecting SQL for query: {state['user_query'][:100]}...")

        # Single LLM call with collapsed architecture
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        chain = SQL_ARCHITECT_PROMPT | llm

        response = await chain.ainvoke({
            "user_query": state["user_query"],
            "today_date": today_date,
            "current_datetime": current_datetime,
            "current_year": current_year,
            "current_month": current_month,
            "table_name": "MasterReportDocumentTable",
            "schema_metadata": schema_text,
            "business_rules": business_rules_text
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


async def sql_executor_node_with_retry(state: GenericText2SQLState) -> GenericText2SQLState:
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

# Module-level cache for vector store
_business_rules_vector_store = None


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


async def create_master_table_node(state: GenericText2SQLState) -> GenericText2SQLState:
    """
    Create MasterReportDocumentTable temp table at the beginning of the graph.

    This table is created from Documents, TempDocuments and related tables.
    All subsequent queries will run against this temp table.
    """
    logger.info("[CREATE_MASTER_TABLE] Creating MasterReportDocumentTable...")

    try:
        # Get DB connection string
        db_conn = get_db_connection_string(state)
        logger.info(f"[CREATE_MASTER_TABLE] Using connection: {db_conn[:50]}...")

        # Read SQL file - works in both dev and PyInstaller builds
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

        # Execute SQL asynchronously
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_db_executor, _execute_sql_script, master_table_sql, db_conn)

        logger.info("[CREATE_MASTER_TABLE] MasterReportDocumentTable created successfully")

    except Exception as e:
        logger.error(f"[CREATE_MASTER_TABLE] Error creating master table: {e}", exc_info=True)
        state["error"] = f"Master table creation error: {str(e)}"

    return state


async def cleanup_master_table_node(state: GenericText2SQLState) -> GenericText2SQLState:
    """
    Drop MasterReportDocumentTable at the end of the graph.

    Cleanup temp table to free resources.
    """
    logger.info("[CLEANUP_MASTER_TABLE] Dropping MasterReportDocumentTable...")

    try:
        # Get DB connection string
        db_conn = get_db_connection_string(state)

        # Drop table SQL
        cleanup_sql = "DROP TABLE IF EXISTS MasterReportDocumentTable;"

        # Execute SQL asynchronously
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_db_executor, _execute_sql_script, cleanup_sql, db_conn)

        logger.info("[CLEANUP_MASTER_TABLE] MasterReportDocumentTable dropped successfully")

    except Exception as e:
        logger.warning(f"[CLEANUP_MASTER_TABLE] Error dropping master table (may not exist): {e}")
        # Don't set error - cleanup failure shouldn't break the flow

    return state


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


async def retrieve_business_rules_node(state: GenericText2SQLState) -> GenericText2SQLState:
    """
    Retrieve relevant business rules for the user query using vector store.

    Uses semantic search to find the most relevant business rules based on:
    - User query
    - Parsed intent (if available)
    - Detected tables (if available)

    Stores results in state for use in SQL generation.

    Args:
        state: Current generic text2sql state with user_query

    Returns:
        Updated state with business_rules_context, merged_sql_components, applied_business_rules
    """
    try:
        logger.info("Retrieving relevant business rules from vector store...")

        # Get vector store instance
        vector_store = get_business_rules_vector_store()

        # Extract detected tables from parsed_intent if available
        detected_tables = state.get("detected_tables")
        if not detected_tables and state.get("parsed_intent"):
            # Try to extract table names from field hints
            # (for now, we use MasterReportDocumentTable as default)
            detected_tables = ["MasterReportDocumentTable"]

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