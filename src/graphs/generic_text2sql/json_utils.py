"""
JSON Extraction Utilities.

Robust JSON parsing with regex-based extraction for handling
LLM responses that may contain additional text outside JSON blocks.
"""

import json
import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def extract_json_from_text(text: str, fallback_to_search: bool = True) -> Optional[str]:
    """
    Extract JSON from text that may contain markdown code blocks or extra text.

    Supports:
    - Markdown code blocks: ```json ... ```
    - Raw JSON in text
    - Mixed content with JSON somewhere in the middle

    Args:
        text: Raw text containing JSON
        fallback_to_search: If True, search for JSON pattern in text if initial extraction fails

    Returns:
        Extracted JSON string or None if not found
    """
    text = text.strip()

    # Method 1: Try markdown code block extraction
    if "```" in text:
        # Match ```json ... ``` or ``` ... ```
        code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        matches = re.findall(code_block_pattern, text, re.DOTALL)

        if matches:
            # Return the first code block found
            json_text = matches[0].strip()
            logger.debug(f"Extracted JSON from code block ({len(json_text)} chars)")
            return json_text

    # Method 2: Check if entire text is valid JSON
    try:
        json.loads(text)
        logger.debug("Entire text is valid JSON")
        return text
    except json.JSONDecodeError:
        pass

    # Method 3: Regex-based JSON object/array search
    if fallback_to_search:
        # Look for JSON object pattern { ... }
        object_pattern = r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}'
        matches = re.findall(object_pattern, text, re.DOTALL)

        for match in matches:
            try:
                # Validate it's parseable JSON
                json.loads(match)
                logger.debug(f"Found valid JSON object via regex ({len(match)} chars)")
                return match
            except json.JSONDecodeError:
                continue

        # Look for JSON array pattern [ ... ]
        array_pattern = r'\[(?:[^\[\]]|(?:\[(?:[^\[\]]|(?:\[[^\[\]]*\]))*\]))*\]'
        matches = re.findall(array_pattern, text, re.DOTALL)

        for match in matches:
            try:
                json.loads(match)
                logger.debug(f"Found valid JSON array via regex ({len(match)} chars)")
                return match
            except json.JSONDecodeError:
                continue

    logger.warning("Could not extract valid JSON from text")
    return None


def parse_json_robust(text: str, expected_keys: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    Robustly parse JSON from text with validation.

    Args:
        text: Text containing JSON
        expected_keys: Optional list of required keys to validate

    Returns:
        Parsed JSON dict or None if parsing fails

    Raises:
        ValueError: If expected_keys are missing from parsed JSON
    """
    # Extract JSON from text
    json_text = extract_json_from_text(text)

    if json_text is None:
        logger.error("Failed to extract JSON from text")
        return None

    # Parse JSON
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {e}")
        logger.debug(f"Problematic JSON (first 500 chars):\n{json_text[:500]}")
        return None

    # Validate expected keys
    if expected_keys:
        missing_keys = [key for key in expected_keys if key not in parsed]
        if missing_keys:
            raise ValueError(f"Missing required keys: {missing_keys}")

    return parsed


def clean_json_string(text: str) -> str:
    """
    Clean common JSON formatting issues.

    Fixes:
    - Trailing commas
    - Single quotes to double quotes (basic cases)
    - Escaped newlines

    Args:
        text: JSON string with potential issues

    Returns:
        Cleaned JSON string
    """
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Replace escaped newlines
    text = text.replace('\\n', '\n')

    return text


def safe_json_loads(text: str, default: Any = None) -> Any:
    """
    Safely load JSON with fallback to default value.

    Args:
        text: JSON string
        default: Default value if parsing fails

    Returns:
        Parsed JSON or default value
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"JSON parsing failed, returning default: {e}")
        return default


def extract_sql_from_text(text: str) -> Optional[str]:
    """
    Extract SQL query from text that may contain markdown code blocks.

    Args:
        text: Text containing SQL query

    Returns:
        Extracted SQL query or None
    """
    text = text.strip()

    # Check for markdown code blocks
    if text.startswith("```"):
        # Split by ``` and get content between markers
        parts = text.split("```")
        if len(parts) >= 2:
            sql_text = parts[1]
            # Remove 'sql' prefix if present
            if sql_text.strip().lower().startswith("sql"):
                sql_text = sql_text[3:].strip()
            logger.debug(f"Extracted SQL from code block ({len(sql_text)} chars)")
            return sql_text

    # If no markdown, assume entire text is SQL
    logger.debug("No code block found, using entire text as SQL")
    return text


# Regex patterns for common extraction tasks
PATTERNS = {
    "json_object": r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}',
    "json_array": r'\[(?:[^\[\]]|(?:\[(?:[^\[\]]|(?:\[[^\[\]]*\]))*\]))*\]',
    "code_block": r'```(?:json|sql|python)?\s*\n?(.*?)\n?```',
    "sql_comment": r'--.*$',
    "multiline_comment": r'/\*.*?\*/',
}


def remove_comments_from_sql(sql: str) -> str:
    """
    Remove SQL comments from query.

    Args:
        sql: SQL query with potential comments

    Returns:
        SQL query without comments
    """
    # Remove single-line comments
    sql = re.sub(PATTERNS["sql_comment"], '', sql, flags=re.MULTILINE)

    # Remove multi-line comments
    sql = re.sub(PATTERNS["multiline_comment"], '', sql, flags=re.DOTALL)

    return sql.strip()
