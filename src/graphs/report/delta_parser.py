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
                group_by_str = ", ".join(new_grouping)

                # Check if GROUP BY exists
                if re.search(r'\s+GROUP\s+BY\s+', sql, re.IGNORECASE):
                    # Replace existing GROUP BY
                    modified_sql = re.sub(
                        r'GROUP\s+BY\s+[^;]+',
                        f'GROUP BY {group_by_str}',
                        sql,
                        flags=re.IGNORECASE
                    )
                    logger.info(f"[SQL_MODIFIER] Updated GROUP BY: {group_by_str}")
                else:
                    # Add new GROUP BY before ORDER BY or at end
                    if 'ORDER BY' in sql.upper():
                        modified_sql = re.sub(
                            r'(.*?)\s+(ORDER\s+BY\s+.*)',
                            rf'\1 GROUP BY {group_by_str} \2',
                            sql,
                            flags=re.IGNORECASE
                        )
                    else:
                        # Add at end (before semicolon if exists)
                        if sql.rstrip().endswith(';'):
                            modified_sql = sql.rstrip()[:-1] + f' GROUP BY {group_by_str};'
                        else:
                            modified_sql = sql + f' GROUP BY {group_by_str}'

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
