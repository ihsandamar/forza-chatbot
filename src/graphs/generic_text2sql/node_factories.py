"""
Text2SQL Node Factories

Reusable node factory functions for embedding Text2SQL nodes into Report Agent.
Each factory creates a node that accepts RunnableConfig for runtime configuration.

Usage:
    # Create node factories
    sql_architect = create_sql_architect_node(node_kit)
    value_resolver = create_value_resolver_node(node_kit)

    # Add to graph
    graph.add_node("sql_architect", sql_architect)
    graph.add_node("value_resolver", value_resolver)

    # Runtime config
    result = await graph.ainvoke(input_state, config={
        "configurable": {
            "table_name": "MasterReportDocumentTable",
            "column_metadata": {...},
            "business_rules": [...]
        }
    })
"""

import logging
from typing import Dict, Any, Optional
from langchain_core.runnables import RunnableConfig

from .nodekit import GenericText2SQLNodeKit
from .state import GenericText2SQLState

logger = logging.getLogger(__name__)


# =============================================================================
# SQL ARCHITECT NODE FACTORY
# =============================================================================

def create_sql_architect_node(node_kit: GenericText2SQLNodeKit):
    """
    Create SQL architect node factory.

    Wraps NodeKit's sql_architect_node for use in Report Agent.
    Supports runtime config via RunnableConfig.

    Runtime config usage:
    - table_name: Target table name
    - column_metadata: Table metadata dict
    - business_rules: Business rules list

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Async node function with RunnableConfig support
    """
    async def sql_architect_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """
        SQL architect node - designs SQL query structure.

        Reads from runtime config:
        - table_name
        - column_metadata
        - business_rules
        """
        logger.info("[SQL_ARCHITECT] Starting SQL design (merged into Report Agent)...")

        try:
            # Call NodeKit method (already supports RunnableConfig)
            result = await node_kit.sql_architect_node(state, config=config)

            logger.info("[SQL_ARCHITECT] ✓ SQL design completed")

            return result

        except Exception as e:
            logger.error(f"[SQL_ARCHITECT] Error: {e}", exc_info=True)
            return {
                "error": f"SQL design failed: {e}",
                "parsed_intent": None
            }

    return sql_architect_node


# =============================================================================
# VALUE RESOLVER NODE FACTORY
# =============================================================================

def create_value_resolver_node(node_kit: GenericText2SQLNodeKit):
    """
    Create value resolver node factory.

    Wraps NodeKit's value_resolver_node for use in Report Agent.
    Supports runtime config via RunnableConfig.

    Runtime config usage:
    - table_name: Target table name
    - column_metadata: Table metadata dict
    - enable_value_resolution: Enable/disable resolution

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Async node function with RunnableConfig support
    """
    async def value_resolver_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """
        Value resolver node - resolves ambiguous values.

        Reads from runtime config:
        - table_name
        - column_metadata
        - enable_value_resolution
        """
        logger.info("[VALUE_RESOLVER] Starting value resolution (merged into Report Agent)...")

        try:
            # Call NodeKit method (already supports RunnableConfig)
            result = await node_kit.value_resolver_node(state, config=config)

            logger.info("[VALUE_RESOLVER] ✓ Value resolution completed")

            return result

        except Exception as e:
            logger.error(f"[VALUE_RESOLVER] Error: {e}", exc_info=True)
            return {
                "error": f"Value resolution failed: {e}",
                "resolved_steps": state.get("parsed_intent", {}).get("steps", [])
            }

    return value_resolver_node


# =============================================================================
# METADATA ENRICHMENT NODE FACTORY
# =============================================================================

def create_metadata_enrichment_node(node_kit: GenericText2SQLNodeKit):
    """
    Create metadata enrichment node factory.

    Wraps NodeKit's metadata_enrichment_node for use in Report Agent.

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Async node function with RunnableConfig support
    """
    async def metadata_enrichment_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """Enrich metadata from database."""
        logger.info("[METADATA_ENRICHMENT] Starting metadata enrichment...")

        try:
            result = await node_kit.metadata_enrichment_node(state, config=config)

            logger.info("[METADATA_ENRICHMENT] ✓ Metadata enrichment completed")

            return result

        except Exception as e:
            logger.error(f"[METADATA_ENRICHMENT] Error: {e}", exc_info=True)
            return {"enriched_metadata": state.get("column_metadata", {})}

    return metadata_enrichment_node


# =============================================================================
# BUSINESS RULES NODE FACTORY
# =============================================================================

def create_business_rules_node(node_kit: GenericText2SQLNodeKit):
    """
    Create business rules retrieval node factory.

    Wraps NodeKit's retrieve_business_rules_node for use in Report Agent.

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Async node function with RunnableConfig support
    """
    async def retrieve_business_rules_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """Retrieve business rules from vector store."""
        logger.info("[BUSINESS_RULES] Retrieving business rules...")

        try:
            result = await node_kit.retrieve_business_rules_node(state, config=config)

            logger.info("[BUSINESS_RULES] ✓ Business rules retrieved")

            return result

        except Exception as e:
            logger.error(f"[BUSINESS_RULES] Error: {e}", exc_info=True)
            return {"business_rules": state.get("business_rules", {})}

    return retrieve_business_rules_node


# =============================================================================
# SQL QUERY BUILDER NODE FACTORY
# =============================================================================

def create_sql_query_builder_node(node_kit: GenericText2SQLNodeKit):
    """
    Create SQL query builder node factory.

    Wraps NodeKit's sql_query_builder_node for use in Report Agent.

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Async node function with RunnableConfig support
    """
    async def sql_query_builder_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """Build SQL queries from resolved steps."""
        logger.info("[SQL_QUERY_BUILDER] Building SQL queries...")

        try:
            result = await node_kit.sql_query_builder_node(state, config=config)

            logger.info("[SQL_QUERY_BUILDER] ✓ SQL queries built")

            return result

        except Exception as e:
            logger.error(f"[SQL_QUERY_BUILDER] Error: {e}", exc_info=True)
            return {"error": f"SQL query building failed: {e}", "sql_queries": []}

    return sql_query_builder_node


# =============================================================================
# DB OPERATIONS NODE FACTORIES
# =============================================================================

def create_db_operations_nodes(node_kit: GenericText2SQLNodeKit) -> Dict[str, Any]:
    """
    Create DB operation node factories.

    Wraps NodeKit's DB operation nodes for use in Report Agent.

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Dict of node functions:
        - create_table
        - sql_executor
        - cleanup_table
    """
    async def create_table_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """Create temporary master table."""
        logger.info("[CREATE_TABLE] Creating temporary table...")

        try:
            result = await node_kit.create_master_table_node(state, config=config)

            logger.info("[CREATE_TABLE] ✓ Table created")

            return result

        except Exception as e:
            logger.error(f"[CREATE_TABLE] Error: {e}", exc_info=True)
            return {"error": f"Table creation failed: {e}"}


    async def sql_executor_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """Execute SQL queries with retry."""
        logger.info("[SQL_EXECUTOR] Executing SQL queries...")

        try:
            result = await node_kit.sql_executor_node_with_retry(state, config=config)

            sql_queries = result.get("sql_queries", [])
            results = result.get("results", [])
            logger.info(f"[SQL_EXECUTOR] ✓ Executed {len(sql_queries)} queries, got {len(results)} rows")

            return result

        except Exception as e:
            logger.error(f"[SQL_EXECUTOR] Error: {e}", exc_info=True)
            return {"error": f"SQL execution failed: {e}", "results": []}


    async def cleanup_table_node(
        state: Dict[str, Any],
        config: RunnableConfig = None
    ) -> Dict[str, Any]:
        """Cleanup temporary master table."""
        logger.info("[CLEANUP] Cleaning up temporary table...")

        try:
            result = await node_kit.cleanup_master_table_node(state, config=config)

            logger.info("[CLEANUP] ✓ Cleanup completed")

            return result

        except Exception as e:
            logger.warning(f"[CLEANUP] Cleanup error: {e}")
            return {}


    return {
        "create_table": create_table_node,
        "sql_executor": sql_executor_node,
        "cleanup_table": cleanup_table_node
    }


# =============================================================================
# CONVENIENCE FUNCTION - Create All Nodes
# =============================================================================

def create_all_text2sql_nodes(node_kit: GenericText2SQLNodeKit) -> Dict[str, Any]:
    """
    Create all Text2SQL node factories at once.

    Convenience function to get all nodes for embedding in Report Agent.

    Args:
        node_kit: GenericText2SQLNodeKit instance

    Returns:
        Dict of all node functions:
        - sql_architect
        - value_resolver
        - metadata_enrichment
        - retrieve_business_rules
        - sql_query_builder
        - create_table
        - sql_executor
        - cleanup_table
    """
    # Create individual nodes
    sql_architect = create_sql_architect_node(node_kit)
    value_resolver = create_value_resolver_node(node_kit)
    metadata_enrichment = create_metadata_enrichment_node(node_kit)
    business_rules = create_business_rules_node(node_kit)
    query_builder = create_sql_query_builder_node(node_kit)
    db_ops = create_db_operations_nodes(node_kit)

    # Combine all nodes
    all_nodes = {
        "sql_architect": sql_architect,
        "value_resolver": value_resolver,
        "metadata_enrichment": metadata_enrichment,
        "retrieve_business_rules": business_rules,
        "sql_query_builder": query_builder,
        **db_ops  # create_table, sql_executor, cleanup_table
    }

    logger.info(f"[NODE_FACTORIES] Created {len(all_nodes)} Text2SQL node factories")

    return all_nodes
