
import json
import logging
from copy import deepcopy
import pyodbc
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from langchain_openai import ChatOpenAI
from src.graphs.generic_text2sql.prompts import (
    INTENT_PARSER_PROMPT,
    INTENT_MATCHER_PROMPT,
    SQL_QUERY_BUILDER_PROMPT,
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


logger = logging.getLogger(__name__)

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
    Parse user query into generic structured intent (no business logic).

    Generic parser that understands query structure and resolves dates,
    but doesn't know about specific database schema.

    Args:
        state: Current generic text2sql state with user_query

    Returns:
        Updated state with parsed_intent (generic field names) or error
    """
    try:
        logger.debug(f"Parsing user intent for query: {state['user_query'][:50]}...")

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

        # Get LLM response with date context (generic parsing)
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        chain = INTENT_PARSER_PROMPT | llm

        response = await chain.ainvoke({
            "user_query": state["user_query"],
            "today_date": today_date,
            "current_datetime": current_datetime,
            "current_year": current_year,
            "current_month": current_month
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

        # Convert parsed_intent to JSON for prompt
        parsed_intent_json = json.dumps(state["parsed_intent"], indent=2, ensure_ascii=False)

        logger.debug(f"Matching intent with {len(state['parsed_intent']['steps'])} step(s)")

        # Get LLM response with business logic mapping
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        chain = INTENT_MATCHER_PROMPT | llm

        response = await chain.ainvoke({
            "parsed_intent": parsed_intent_json
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

    Collects all field_hint values from parsed_intent (filters, aggregations, group_by, order_by)
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
            # From filters
            if "filters" in step:
                for filter_def in step["filters"]:
                    field_hint = filter_def.get("field_hint")
                    if field_hint:
                        used_columns.add(field_hint)

            # From aggregations
            if "aggregations" in step:
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
        # TODO: Get DB connection string from config
        db_conn = "mssql+pyodbc://sa:Vega1234@DESKTOP-TIEAGO8/harbi?driver=ODBC+Driver+17+for+SQL+Server"
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

        # Prepare resolved steps JSON for prompt
        steps_json = json.dumps(resolved_steps, indent=2, ensure_ascii=False)

        # Prepare enriched metadata (only for used columns)
        enriched_metadata = state.get("enriched_metadata", {})
        if enriched_metadata:
            metadata_text = "\n".join(
                f"- {col}: {desc}" for col, desc in enriched_metadata.items()
            )
        else:
            metadata_text = "(No additional metadata available)"

        logger.debug(f"Building SQL query for {len(resolved_steps)} step(s) with {len(enriched_metadata)} column metadata")

        # Get LLM response
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        chain = SQL_QUERY_BUILDER_PROMPT | llm

        response = await chain.ainvoke({
            "resolved_steps": steps_json,
            "enriched_metadata": metadata_text
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

            conn_str = (
                f"Driver={{{driver}}};"
                f"Server={parsed.hostname};"
                f"Database={parsed.path.lstrip('/')};"
                f"UID={parsed.username};"
                f"PWD={parsed.password};"
                "Trusted_Connection=no;"
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
        # TODO: Get from config
        db_conn = "mssql+pyodbc://sa:Vega1234@DESKTOP-TIEAGO8/harbi?driver=ODBC+Driver+17+for+SQL+Server"

        # Execute SQL asynchronously
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(_db_executor, _execute_sql, sql_query, db_conn)

        # Store results
        state["results"] = results

        logger.info(f"SQL execution completed: {len(results)} rows retrieved")

        # Log first few rows for debugging
        if results:
            logger.debug(f"Sample results (first 3 rows):\n{json.dumps(results[:3], indent=2, ensure_ascii=False)}")

    except Exception as e:
        logger.error(f"Unexpected error in sql_executor_node: {e}", exc_info=True)
        state["error"] = f"SQL çalıştırma hatası: {str(e)}"

    return state



    """
    Resolve column names based on parsed intent.

    Args:
        state: Current generic text2sql state

    Returns:
        Updated state with resolved columns
    """
    # Kullanım
    resolver = ValueResolver(COLUMN_METADATA)
    result = resolver.resolve_value("istanbul")
    
    # → {"table": "sales_view", "column": "region", "value": "Istanbul"}


    
    logger.debug("Resolving columns based on parsed intent...")