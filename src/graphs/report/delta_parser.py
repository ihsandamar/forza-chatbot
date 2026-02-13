"""
Advanced Delta Parser for Complex SQL Modifications

Phase 4: LLM-based parsing for complex SQL changes including:
- Column additions/removals
- Aggregation changes (GROUP BY, HAVING)
- Complex multi-modification queries

Uses structured JSON output for reliable parsing with confidence scoring
for multi-level fallback.

Features:
- Column addition/removal support
- Aggregation modification (GROUP BY, SUM, AVG, etc.)
- Filter changes (WHERE clause)
- Limit/offset modifications
- Confidence scoring for fallback logic

Fallback Levels:
1. Advanced LLM parser (this module) - complex changes
2. Simple LLM parser (Phase 3) - basic filter/limit changes
3. Pattern matching (Phase 2) - simple text patterns
4. Full SQL regeneration (Phase 1) - fallback to complete flow
"""

import logging
import json
from typing import Dict, Any, Optional, List
import re

logger = logging.getLogger(__name__)


# =============================================================================
# ADVANCED DELTA PARSER
# =============================================================================

class AdvancedDeltaParser:
    """
    LLM-based parser for complex SQL modifications.

    Handles advanced delta operations beyond simple filters:
    - Adding/removing columns
    - Changing aggregations
    - Modifying GROUP BY clauses
    """

    def __init__(self, llm):
        """
        Initialize advanced delta parser.

        Args:
            llm: LangChain LLM instance for parsing
        """
        self.llm = llm
        logger.info("[DELTA_PARSER] Advanced delta parser initialized")

    async def parse_advanced_delta(
        self,
        user_query: str,
        active_context: Dict[str, Any],
        intent_type: str,
        schema_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Parse complex delta changes with structured output.

        Args:
            user_query: User's modification request
            active_context: Active SQL context with current SQL
            intent_type: Intent classification
            schema_metadata: Table schema with available columns (CRITICAL!)

        Returns:
            Dictionary with:
            - modification_type: Type of modification
            - filters_to_add: List of filter changes
            - columns_to_add: List of columns to add
            - columns_to_remove: List of columns to remove
            - aggregation_changes: Aggregation modifications
            - limit_offset_changes: Limit/offset modifications
            - confidence: Confidence score (0-1)
        """
        current_sql = active_context.get("sql_query", "")

        # Build prompt for LLM with schema context
        prompt = self._build_parsing_prompt(user_query, current_sql, intent_type, schema_metadata)

        try:
            # Call LLM
            response = await self.llm.ainvoke(prompt)
            content = response.content.strip()

            # Extract JSON from response
            delta_changes = self._extract_json(content)

            # Validate and normalize
            delta_changes = self._validate_delta_changes(delta_changes)

            logger.info(
                f"[DELTA_PARSER] Parsed delta: type={delta_changes['modification_type']}, "
                f"confidence={delta_changes['confidence']:.2f}"
            )

            return delta_changes

        except Exception as e:
            logger.error(f"[DELTA_PARSER] Failed to parse delta: {e}", exc_info=True)
            return {
                "modification_type": "unknown",
                "confidence": 0.0,
                "error": str(e)
            }

    def _build_parsing_prompt(
        self,
        user_query: str,
        current_sql: str,
        intent_type: str,
        schema_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build prompt for delta parsing with schema context."""

        # Build available columns section from schema metadata
        available_columns_section = ""
        if schema_metadata:
            columns = []

            # Extract column names from schema_metadata
            # schema_metadata can be a dict or list depending on source
            if isinstance(schema_metadata, dict):
                # If dict with column_name keys
                for col_name, col_info in schema_metadata.items():
                    if isinstance(col_info, dict):
                        col_type = col_info.get("type", "unknown")
                        col_desc = col_info.get("description", "")
                        columns.append(f"  - {col_name} ({col_type}): {col_desc}")
                    else:
                        columns.append(f"  - {col_name}")
            elif isinstance(schema_metadata, list):
                # If list of column dicts
                for col in schema_metadata:
                    if isinstance(col, dict):
                        col_name = col.get("column_name") or col.get("name", "")
                        col_type = col.get("type", "")
                        if col_name:
                            columns.append(f"  - {col_name} ({col_type})")
                    else:
                        columns.append(f"  - {col}")

            if columns:
                available_columns_section = f"""
## ⚠️ AVAILABLE COLUMNS IN TABLE (USE ONLY THESE!)
```
{chr(10).join(columns)}
```

**CRITICAL**: You MUST use ONLY the column names listed above. Do NOT invent or guess column names!
If user mentions a concept not in the list, find the closest matching column or return low confidence.

"""

        prompt = f"""Kullanıcının SQL sorgusu değişikliği talebini analiz et ve yapısal JSON formatında çıktı ver.

## MEVCUT SQL SORGUSU
```sql
{current_sql}
```
{available_columns_section}
## KULLANICI DEĞİŞİKLİK TALEBİ
"{user_query}"

## TALEP TİPİ
{intent_type}

## GÖREV
Kullanıcının ne tür bir değişiklik istediğini belirle ve aşağıdaki JSON formatında çıktı ver.

## ÇIKTI FORMATI (JSON)
```json
{{
  "modification_type": "filter_change" | "column_addition" | "column_removal" | "aggregation_change" | "limit_change" | "complex",
  "filters_to_add": [
    {{
      "column": "BranchCityName",
      "operator": "=",
      "value": "Istanbul",
      "logic": "AND"
    }}
  ],
  "columns_to_add": [
    {{
      "name": "ToplamTutar",
      "expression": "SUM(RowAmount)",
      "alias": "ToplamTutar",
      "is_aggregation": true
    }}
  ],
  "columns_to_remove": ["CustomerName", "DocumentDate"],
  "aggregation_changes": {{
    "new_grouping": ["BranchCityName", "CategoryName"],
    "remove_grouping": false,
    "having_clause": "SUM(RowAmount) > 1000"
  }},
  "limit_offset_changes": {{
    "limit": 10,
    "offset": 0
  }},
  "confidence": 0.95,
  "explanation": "Kullanıcı Istanbul şehri için toplam tutarı görmek istiyor"
}}
```

## KURALLAR
1. modification_type: Değişikliğin ana tipi (tek tür seç)
2. filters_to_add: WHERE koşullarına eklenecek filtreler
3. columns_to_add: SELECT'e eklenecek sütunlar (aggregation varsa expression kullan)
4. columns_to_remove: SELECT'ten çıkarılacak sütunlar
5. aggregation_changes: GROUP BY değişiklikleri
6. confidence: Parsing güven skoru (0-1)
7. explanation: Kısa açıklama (Türkçe)

## ÖNEMLİ
- Sadece JSON çıktı ver, başka metin ekleme
- Tüm alanlar opsiyonel (boş liste/null olabilir)
- confidence < 0.7 ise "unknown" type kullan
- Turkish column/value names için UTF-8 kullan

## ÖRNEKLER

## ÖNEMLİ: GERÇEK KOLON İSİMLERİNİ KULLAN
- Şehir için → "BranchCityName" (SehirAdi DEĞİL!)
- Kategori için → "CategoryName" (KategoriAdi DEĞİL!)
- Tutar için → "RowAmount" (Tutar DEĞİL!)
- Ürün için → "ProductName" (UrunAdi DEĞİL!)

Örnek 1 - Filtre ekleme:
Kullanıcı: "Sadece Istanbul için göster"
```json
{{
  "modification_type": "filter_change",
  "filters_to_add": [{{"column": "BranchCityName", "operator": "=", "value": "Istanbul", "logic": "AND"}}],
  "confidence": 0.95
}}
```

Örnek 2 - Aggregation ekleme:
Kullanıcı: "Toplamları da göster"
```json
{{
  "modification_type": "aggregation_change",
  "columns_to_add": [{{"name": "ToplamTutar", "expression": "SUM(RowAmount)", "alias": "ToplamTutar", "is_aggregation": true}}],
  "aggregation_changes": {{"new_grouping": ["BranchCityName"]}},
  "confidence": 0.90
}}
```

Örnek 3 - Kompleks değişiklik:
Kullanıcı: "Istanbul ve Ankara için kategori bazında toplamları göster, 10 kayıtla sınırla"
```json
{{
  "modification_type": "complex",
  "filters_to_add": [
    {{"column": "BranchCityName", "operator": "IN", "value": ["Istanbul", "Ankara"], "logic": "AND"}}
  ],
  "columns_to_add": [
    {{"name": "ToplamTutar", "expression": "SUM(RowAmount)", "alias": "ToplamTutar", "is_aggregation": true}},
    {{"name": "KayitSayisi", "expression": "COUNT(*)", "alias": "KayitSayisi", "is_aggregation": true}}
  ],
  "aggregation_changes": {{"new_grouping": ["BranchCityName", "CategoryName"]}},
  "limit_offset_changes": {{"limit": 10}},
  "confidence": 0.88
}}
```

JSON çıktısını şimdi üret:"""

        return prompt

    def _extract_json(self, content: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""
        # Try to extract JSON from code blocks
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find JSON directly
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise ValueError("No JSON found in response")

        # Parse JSON
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"[DELTA_PARSER] JSON decode error: {e}")
            logger.error(f"[DELTA_PARSER] Content: {json_str[:200]}...")
            raise

    def _validate_delta_changes(self, delta: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize delta changes."""
        # Ensure all required fields exist
        normalized = {
            "modification_type": delta.get("modification_type", "unknown"),
            "filters_to_add": delta.get("filters_to_add", []),
            "columns_to_add": delta.get("columns_to_add", []),
            "columns_to_remove": delta.get("columns_to_remove", []),
            "aggregation_changes": delta.get("aggregation_changes", {}),
            "limit_offset_changes": delta.get("limit_offset_changes", {}),
            "confidence": delta.get("confidence", 0.5),
            "explanation": delta.get("explanation", "")
        }

        # Validate confidence
        if not (0.0 <= normalized["confidence"] <= 1.0):
            logger.warning(f"[DELTA_PARSER] Invalid confidence: {normalized['confidence']}, setting to 0.5")
            normalized["confidence"] = 0.5

        # If confidence is too low, mark as unknown
        if normalized["confidence"] < 0.5:
            normalized["modification_type"] = "unknown"

        return normalized


# =============================================================================
# SQL MODIFICATION HELPERS
# =============================================================================

class SQLModifier:
    """Helper class for applying SQL modifications."""

    def __init__(self, value_resolver=None):
        """
        Initialize SQL modifier.

        Args:
            value_resolver: ValueResolverService instance for column name resolution
        """
        self.value_resolver = value_resolver

    def add_columns(self, sql: str, columns_to_add: List[Dict[str, Any]]) -> str:
        """
        Add columns to SELECT clause.

        Args:
            sql: Original SQL query
            columns_to_add: List of column definitions

        Returns:
            Modified SQL with new columns
        """
        if not columns_to_add:
            return sql

        try:
            # Find SELECT clause
            select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
            if not select_match:
                logger.error("[SQL_MODIFIER] Could not find SELECT clause")
                return sql

            current_columns = select_match.group(1).strip()

            # Add new columns
            new_columns = []
            for col in columns_to_add:
                # Resolve semantic column names to actual DB columns
                col_name = col.get("name", "")
                resolved_name = self._resolve_column_name(col_name)

                if "expression" in col and col.get("is_aggregation"):
                    # Aggregation: resolve column in expression
                    expression = self._resolve_expression_columns(col['expression'])
                    alias = col.get('alias', resolved_name or col_name)
                    new_col = f"{expression} AS {alias}"
                elif "expression" in col:
                    # Expression: resolve columns in expression
                    expression = self._resolve_expression_columns(col['expression'])
                    alias = col.get('alias', resolved_name or col_name)
                    new_col = f"{expression} AS {alias}"
                else:
                    # Simple column: use resolved name
                    new_col = resolved_name or col_name

                new_columns.append(new_col)
                logger.debug(f"[SQL_MODIFIER] Column '{col_name}' → '{new_col}'")

            # Combine
            updated_columns = current_columns + ", " + ", ".join(new_columns)

            # Replace SELECT clause
            modified_sql = sql.replace(select_match.group(0), f"SELECT {updated_columns} FROM")

            logger.info(f"[SQL_MODIFIER] Added {len(columns_to_add)} columns")
            return modified_sql

        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error adding columns: {e}")
            return sql

    def remove_columns(self, sql: str, columns_to_remove: List[str]) -> str:
        """
        Remove columns from SELECT clause.

        Args:
            sql: Original SQL query
            columns_to_remove: List of column names to remove (semantic or DB names)

        Returns:
            Modified SQL without specified columns
        """
        if not columns_to_remove:
            return sql

        try:
            # Find SELECT clause
            select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
            if not select_match:
                return sql

            current_columns = select_match.group(1).strip()

            # Split columns
            columns = [c.strip() for c in current_columns.split(',')]

            # Resolve semantic column names to DB columns
            resolved_columns_to_remove = []
            for col_name in columns_to_remove:
                resolved = self._resolve_column_name(col_name)
                resolved_columns_to_remove.append(resolved if resolved else col_name)
                if resolved and resolved != col_name:
                    logger.info(f"[SQL_MODIFIER] Removing column: '{col_name}' → '{resolved}'")

            # Filter out columns to remove
            filtered_columns = [
                col for col in columns
                if not any(remove_col in col for remove_col in resolved_columns_to_remove)
            ]

            if not filtered_columns:
                logger.warning("[SQL_MODIFIER] Cannot remove all columns")
                return sql

            # Replace SELECT clause
            updated_columns = ", ".join(filtered_columns)
            modified_sql = sql.replace(select_match.group(0), f"SELECT {updated_columns} FROM")

            logger.info(f"[SQL_MODIFIER] Removed {len(columns_to_remove)} columns")
            return modified_sql

        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error removing columns: {e}")
            return sql

    def modify_aggregations(self, sql: str, agg_changes: Dict[str, Any]) -> str:
        """
        Modify GROUP BY clause and aggregations.

        Args:
            sql: Original SQL query
            agg_changes: Aggregation changes

        Returns:
            Modified SQL with updated GROUP BY
        """
        if not agg_changes:
            return sql

        try:
            new_grouping = agg_changes.get("new_grouping", [])
            remove_grouping = agg_changes.get("remove_grouping", False)
            having_clause = agg_changes.get("having_clause")

            # Resolve column names in new_grouping
            if new_grouping:
                resolved_grouping = []
                for col_name in new_grouping:
                    resolved = self._resolve_column_name(col_name)
                    resolved_grouping.append(resolved if resolved else col_name)
                    if resolved and resolved != col_name:
                        logger.info(f"[SQL_MODIFIER] GROUP BY column: '{col_name}' → '{resolved}'")
                new_grouping = resolved_grouping

            # Resolve columns in having_clause
            if having_clause:
                having_clause = self._resolve_expression_columns(having_clause)

            if remove_grouping:
                # Remove GROUP BY clause
                modified_sql = re.sub(r'\s+GROUP\s+BY\s+[^;]+', '', sql, flags=re.IGNORECASE)
                logger.info("[SQL_MODIFIER] Removed GROUP BY clause")
                return modified_sql

            if new_grouping:
                # CRITICAL FIX: Ensure GROUP BY columns are in SELECT clause
                # This prevents "Invalid column name" errors
                modified_sql = self._ensure_grouping_columns_in_select(sql, new_grouping)

                group_by_str = ", ".join(new_grouping)

                # CRITICAL FIX 2: Handle CTE (WITH ... AS) structure
                # If SQL has CTE, GROUP BY must be added INSIDE the CTE, not in final SELECT
                if self._is_cte_query(modified_sql):
                    modified_sql = self._add_group_by_to_cte(modified_sql, group_by_str, new_grouping)
                    logger.info(f"[SQL_MODIFIER] Added GROUP BY to CTE: {group_by_str}")
                else:
                    # Check if GROUP BY exists
                    if re.search(r'\s+GROUP\s+BY\s+', modified_sql, re.IGNORECASE):
                        # Replace existing GROUP BY
                        modified_sql = re.sub(
                            r'GROUP\s+BY\s+[^;]+',
                            f'GROUP BY {group_by_str}',
                            modified_sql,
                            flags=re.IGNORECASE
                        )
                        logger.info(f"[SQL_MODIFIER] Updated GROUP BY: {group_by_str}")
                    else:
                        # Add new GROUP BY before ORDER BY or at end
                        if 'ORDER BY' in modified_sql.upper():
                            modified_sql = re.sub(
                                r'(.*?)\s+(ORDER\s+BY\s+.*)',
                                rf'\1 GROUP BY {group_by_str} \2',
                                modified_sql,
                                flags=re.IGNORECASE
                            )
                        else:
                            # Add at end (before semicolon if exists)
                            if modified_sql.rstrip().endswith(';'):
                                modified_sql = modified_sql.rstrip()[:-1] + f' GROUP BY {group_by_str};'
                            else:
                                modified_sql = modified_sql + f' GROUP BY {group_by_str}'

                        logger.info(f"[SQL_MODIFIER] Added GROUP BY: {group_by_str}")

                # Add HAVING clause if specified
                if having_clause:
                    if 'HAVING' in modified_sql.upper():
                        modified_sql = re.sub(
                            r'HAVING\s+[^;]+',
                            f'HAVING {having_clause}',
                            modified_sql,
                            flags=re.IGNORECASE
                        )
                    else:
                        modified_sql = modified_sql.replace(
                            f'GROUP BY {group_by_str}',
                            f'GROUP BY {group_by_str} HAVING {having_clause}'
                        )
                    logger.info(f"[SQL_MODIFIER] Added HAVING: {having_clause}")

                return modified_sql

            return sql

        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error modifying aggregations: {e}")
            return sql

    def _is_cte_query(self, sql: str) -> bool:
        """
        Check if SQL query uses CTE (WITH ... AS) structure.

        Args:
            sql: SQL query to check

        Returns:
            True if query uses CTE, False otherwise
        """
        return bool(re.search(r'^\s*WITH\s+\w+\s+AS\s*\(', sql, re.IGNORECASE | re.MULTILINE))

    def _add_group_by_to_cte(self, sql: str, group_by_str: str, grouping_columns: List[str]) -> str:
        """
        Add GROUP BY clause inside CTE and update final SELECT.

        Handles CTE structure properly:
        WITH step_1 AS (
          SELECT ... FROM ... WHERE ...
          GROUP BY col  ← Add here
        )
        SELECT col, agg FROM step_1  ← Update SELECT columns

        Args:
            sql: Original SQL with CTE
            group_by_str: GROUP BY clause string (e.g., "CategoryName, BranchName")
            grouping_columns: List of grouping column names

        Returns:
            Modified SQL with GROUP BY in CTE and updated final SELECT
        """
        try:
            # Find the CTE closing parenthesis
            # CTE structure: WITH name AS ( ... ) SELECT ...
            # We need to add GROUP BY before the closing )

            # Pattern to match: WITH ... AS ( ... )
            # We want to insert GROUP BY before the last ) before SELECT
            cte_pattern = r'(WITH\s+\w+\s+AS\s*\(.*?)\s*\)\s*(SELECT.*FROM\s+\w+)'

            match = re.search(cte_pattern, sql, re.IGNORECASE | re.DOTALL)
            if not match:
                logger.warning("[SQL_MODIFIER] Could not parse CTE structure, applying GROUP BY normally")
                return sql

            cte_body = match.group(1)  # Everything up to closing )
            final_select = match.group(2)  # Final SELECT ... FROM cte_name

            # Check if GROUP BY already exists in CTE
            if re.search(r'\s+GROUP\s+BY\s+', cte_body, re.IGNORECASE):
                # Replace existing GROUP BY in CTE
                cte_body = re.sub(
                    r'GROUP\s+BY\s+[^\)]+',
                    f'GROUP BY {group_by_str}',
                    cte_body,
                    flags=re.IGNORECASE
                )
                logger.info(f"[SQL_MODIFIER] Replaced GROUP BY in CTE: {group_by_str}")
            else:
                # Add GROUP BY at end of CTE (before closing parenthesis)
                cte_body = cte_body.rstrip() + f'\n  GROUP BY {group_by_str}'
                logger.info(f"[SQL_MODIFIER] Added GROUP BY to CTE: {group_by_str}")

            # Update final SELECT to include grouping columns
            final_select = self._update_final_select_for_grouping(final_select, grouping_columns)

            # Reconstruct SQL
            modified_sql = cte_body + "\n)\n" + final_select

            return modified_sql

        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error adding GROUP BY to CTE: {e}", exc_info=True)
            return sql

    def _update_final_select_for_grouping(self, final_select: str, grouping_columns: List[str]) -> str:
        """
        Update final SELECT statement to include grouping columns.

        Args:
            final_select: Final SELECT statement (e.g., "SELECT TotalRevenue FROM step_1")
            grouping_columns: List of grouping columns to add

        Returns:
            Updated SELECT with grouping columns
        """
        try:
            # Find SELECT clause in final select
            select_match = re.search(r'SELECT\s+(.*?)\s+FROM', final_select, re.IGNORECASE | re.DOTALL)
            if not select_match:
                logger.warning("[SQL_MODIFIER] Could not parse final SELECT for grouping columns")
                return final_select

            current_columns = select_match.group(1).strip()

            # Check which grouping columns are missing
            columns_to_add = []
            for col in grouping_columns:
                col_pattern = rf'\b{re.escape(col)}\b'
                if not re.search(col_pattern, current_columns, re.IGNORECASE):
                    columns_to_add.append(col)

            # Add missing columns at the beginning (grouping columns should come first)
            if columns_to_add:
                updated_columns = ", ".join(columns_to_add) + ", " + current_columns
                final_select = final_select.replace(
                    select_match.group(0),
                    f"SELECT {updated_columns} FROM"
                )
                logger.info(f"[SQL_MODIFIER] Added {len(columns_to_add)} grouping columns to final SELECT")

            return final_select

        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error updating final SELECT: {e}")
            return final_select

    def _ensure_grouping_columns_in_select(self, sql: str, grouping_columns: List[str]) -> str:
        """
        Ensure GROUP BY columns are present in SELECT clause.

        This prevents "Invalid column name" SQL errors when GROUP BY references
        columns that are not in the SELECT list.

        Args:
            sql: Original SQL query
            grouping_columns: List of columns to be used in GROUP BY

        Returns:
            Modified SQL with grouping columns added to SELECT if needed
        """
        try:
            # Find SELECT clause (handle CTE case)
            select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
            if not select_match:
                logger.error("[SQL_MODIFIER] Could not find SELECT clause for grouping column check")
                return sql

            current_columns = select_match.group(1).strip()
            columns_to_add = []

            # Check each grouping column
            for col in grouping_columns:
                # Check if column is already in SELECT (case-insensitive)
                # Handle both "column" and "column AS alias" cases
                col_pattern = rf'\b{re.escape(col)}\b'
                if not re.search(col_pattern, current_columns, re.IGNORECASE):
                    # Column not in SELECT, need to add it
                    columns_to_add.append(col)
                    logger.info(f"[SQL_MODIFIER] Adding missing GROUP BY column to SELECT: {col}")

            # Add missing columns to SELECT
            if columns_to_add:
                updated_columns = current_columns + ", " + ", ".join(columns_to_add)
                modified_sql = sql.replace(select_match.group(0), f"SELECT {updated_columns} FROM")
                logger.info(f"[SQL_MODIFIER] Added {len(columns_to_add)} GROUP BY columns to SELECT")
                return modified_sql

            return sql

        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error ensuring grouping columns in SELECT: {e}")
            return sql

    def _resolve_column_name(self, semantic_name: str) -> Optional[str]:
        """
        Resolve semantic column name to actual DB column using ValueResolver.

        Args:
            semantic_name: Semantic/natural language column name

        Returns:
            Resolved DB column name, or original name if resolver not available
        """
        if not self.value_resolver:
            logger.debug(f"[SQL_MODIFIER] No value_resolver available, using '{semantic_name}' as-is")
            return semantic_name

        try:
            resolved = self.value_resolver.resolve_column_name(semantic_name)
            if resolved and resolved != semantic_name:
                logger.info(f"[SQL_MODIFIER] ✅ Resolved column: '{semantic_name}' → '{resolved}'")
                return resolved
            return semantic_name
        except Exception as e:
            logger.error(f"[SQL_MODIFIER] Error resolving column '{semantic_name}': {e}")
            return semantic_name

    def _resolve_expression_columns(self, expression: str) -> str:
        """
        Resolve semantic column names within SQL expressions.

        Args:
            expression: SQL expression (e.g., "SUM(Tutar)", "AVG(SatisTutari)")

        Returns:
            Expression with resolved column names

        Examples:
            "SUM(Tutar)" → "SUM(RowAmount)"
            "AVG(SatisTutari)" → "AVG(RowAmount)"
        """
        if not self.value_resolver:
            return expression

        # Extract column names from expression using regex
        # Matches: function(ColumnName), ColumnName, etc.
        pattern = r'\b([A-Za-z_][A-Za-z0-9_]*)\b'
        sql_keywords = {
            'sum', 'avg', 'count', 'min', 'max', 'as', 'case', 'when', 'then',
            'else', 'end', 'and', 'or', 'not', 'in', 'like', 'between', 'is', 'null'
        }

        def replace_column(match):
            column = match.group(1)
            # Skip SQL keywords
            if column.lower() in sql_keywords:
                return column

            # Try to resolve
            resolved = self._resolve_column_name(column)
            return resolved if resolved else column

        resolved_expression = re.sub(pattern, replace_column, expression)

        if resolved_expression != expression:
            logger.debug(f"[SQL_MODIFIER] Resolved expression: '{expression}' → '{resolved_expression}'")

        return resolved_expression
