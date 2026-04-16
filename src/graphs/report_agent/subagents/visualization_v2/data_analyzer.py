# data_visualization/nodes/data_analyzer.py

from typing import Dict, Any, List, Optional
from datetime import datetime
import re

from src.graphs.report_agent.subagents.visualization_v2.state import (
    DataProfile,
    ColumnInfo,
    ColumnType,
    ColumnRole,
)


class DataAnalyzer:
    """
    Analyzes raw data to create a comprehensive data profile.
    No LLM usage - pure Python analysis.
    
    Responsibilities:
    - Detect column data types (text, numeric, date, etc.)
    - Determine column roles (dimension, metric, time)
    - Calculate basic statistics for numeric columns
    - Identify time series characteristics
    """
    
    # ─────────────────────────────────────────────────────────
    # Column Pattern Definitions
    # ─────────────────────────────────────────────────────────
    
    # Time/Date column patterns (English + Turkish)
    TIME_COLUMN_PATTERNS = [
        r'date', r'time', r'timestamp', r'created', r'updated',
        r'day', r'week', r'month', r'year', r'hour', r'minute',
        r'tarih', r'zaman', r'gun', r'hafta', r'ay', r'yil',
        r'donem', r'period'
    ]
    
    # Dimension column patterns (grouping fields)
    DIMENSION_PATTERNS = [
        r'name$', r'_name$', r'type$', r'_type$', r'category',
        r'branch', r'store', r'region', r'city', r'town',
        r'product', r'customer', r'user', r'employee', r'staff',
        r'adi$', r'isim', r'ismi$', r'tip', r'tipi$', r'tur', r'turu$',
        r'kategori', r'sube', r'magaza', r'bolge', r'sehir', r'ilce',
        r'urun', r'musteri', r'kullanici', r'personel', r'calisan'
    ]
    
    # Metric column patterns (numeric measurements)
    METRIC_PATTERNS = [
        r'amount', r'total', r'sum', r'count', r'quantity', r'qty',
        r'price', r'cost', r'revenue', r'sales', r'profit', r'margin',
        r'avg', r'average', r'rate', r'ratio', r'percent', r'score',
        r'tutar', r'toplam', r'adet', r'miktar', r'fiyat', r'ciro',
        r'maliyet', r'gelir', r'kar', r'oran', r'puan', r'skor'
    ]
    
    # Time granularity ranking (lower = more granular, preferred for x-axis)
    TIME_GRANULARITY = {
        "hour": 1, "saat": 1, "minute": 1, "dakika": 1,
        "day": 2, "gun": 2, "dayofweek": 2,
        "week": 3, "hafta": 3,
        "month": 4, "ay": 4,
        "quarter": 5, "ceyrek": 5,
        "year": 6, "yil": 6,
        "date": 2, "tarih": 2, "time": 1, "zaman": 1,
        "donem": 5, "period": 5,
    }

    # ID column patterns (identifiers, usually not useful for viz)
    ID_PATTERNS = [
        r'^id$', r'_id$', r'id$', r'code$', r'no$', r'num$', r'number$',
        r'kod$', r'numarasi$'
    ]
    
    # ─────────────────────────────────────────────────────────
    # Main Analysis Method
    # ─────────────────────────────────────────────────────────
    
    def analyze(self, state: dict) -> dict:
        """
        Main analysis method.
        
        Args:
            state: Current visualization state with raw_data
            
        Returns:
            Updated state with data_profile
        """
        
        raw_data = state.get("raw_data", [])
        
        # Handle empty data
        if not raw_data:
            return {
                **state,
                "data_profile": None,
                "error": state.get("error") or "No data to analyze"
            }
        
        try:
            data_profile = self._create_profile(raw_data)
            return {
                **state,
                "data_profile": data_profile,
                "error": None
            }
        except Exception as e:
            return {
                **state,
                "data_profile": None,
                "error": f"Data analysis error: {str(e)}"
            }
    
    # ─────────────────────────────────────────────────────────
    # Profile Creation
    # ─────────────────────────────────────────────────────────
    
    def _create_profile(self, data: List[Dict[str, Any]]) -> DataProfile:
        """
        Create complete data profile.
        
        Args:
            data: List of row dictionaries
            
        Returns:
            DataProfile with all analysis results
        """
        
        row_count = len(data)
        columns = list(data[0].keys()) if data else []
        column_count = len(columns)
        
        # Analyze each column
        column_infos: List[ColumnInfo] = []
        dimension_columns: List[str] = []
        metric_columns: List[str] = []
        time_column: Optional[str] = None
        time_candidates: List[ColumnInfo] = []

        for col_name in columns:
            col_info = self._analyze_column(col_name, data)
            column_infos.append(col_info)

            # Categorize by role
            if col_info["role"] == ColumnRole.TIME:
                time_candidates.append(col_info)
            elif col_info["role"] == ColumnRole.DIMENSION:
                dimension_columns.append(col_name)
            elif col_info["role"] == ColumnRole.METRIC:
                metric_columns.append(col_name)
            # IDENTIFIER role is ignored for visualization

        # Select best time column: prefer DATE/DATETIME over NUMERIC,
        # then prefer most granular (Hafta > Yil) via TIME_GRANULARITY ranking.
        # Move non-selected time columns to dimensions (still useful for grouping)
        all_time_names: List[str] = []
        if time_candidates:
            date_typed = [c for c in time_candidates if c["type"] in (ColumnType.DATE, ColumnType.DATETIME)]
            if date_typed:
                time_column = date_typed[0]["name"]
            else:
                sorted_candidates = sorted(
                    time_candidates,
                    key=lambda c: self._get_time_granularity(c["name"]),
                )
                time_column = sorted_candidates[0]["name"]

            all_time_names = [c["name"] for c in sorted(
                time_candidates,
                key=lambda c: self._get_time_granularity(c["name"]),
            )]

            for tc in time_candidates:
                if tc["name"] != time_column:
                    dimension_columns.append(tc["name"])
        
        # Determine data characteristics
        has_time_series = time_column is not None
        has_multiple_dimensions = len(dimension_columns) > 1
        is_aggregated = len(metric_columns) > 0
        
        # Get sample rows (first 3)
        sample_rows = data[:3] if len(data) >= 3 else data.copy()
        
        return DataProfile(
            row_count=row_count,
            column_count=column_count,
            columns=column_infos,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            time_column=time_column,
            time_columns=all_time_names if all_time_names else None,
            has_time_series=has_time_series,
            has_multiple_dimensions=has_multiple_dimensions,
            is_aggregated=is_aggregated,
            sample_rows=sample_rows
        )
    
    # ─────────────────────────────────────────────────────────
    # Column Analysis
    # ─────────────────────────────────────────────────────────
    
    def _get_time_granularity(self, col_name: str) -> int:
        """Return granularity rank for a time column name (lower = more granular)."""
        col_lower = col_name.lower()
        for pattern, rank in self.TIME_GRANULARITY.items():
            if pattern in col_lower:
                return rank
        return 99

    def _analyze_column(self, col_name: str, data: List[Dict[str, Any]]) -> ColumnInfo:
        """
        Analyze a single column.
        
        Args:
            col_name: Column name
            data: Full dataset
            
        Returns:
            ColumnInfo with type, role, and statistics
        """
        
        # Extract column values
        values = [row.get(col_name) for row in data]
        non_null_values = [v for v in values if v is not None]
        
        # Detect data type
        col_type = self._detect_type(non_null_values)
        
        # Detect semantic role
        col_role = self._detect_role(col_name, col_type, non_null_values)
        
        # Get unique values and samples
        unique_values = list(set(str(v) for v in non_null_values if v is not None))
        sample_values = unique_values[:5]  # First 5 unique values
        
        # Calculate numeric statistics
        min_val, max_val, avg_val = None, None, None
        if col_type == ColumnType.NUMERIC and non_null_values:
            numeric_values = [
                float(v) for v in non_null_values 
                if self._is_numeric(v)
            ]
            if numeric_values:
                min_val = min(numeric_values)
                max_val = max(numeric_values)
                avg_val = sum(numeric_values) / len(numeric_values)
        
        return ColumnInfo(
            name=col_name,
            type=col_type,
            role=col_role,
            sample_values=sample_values,
            unique_count=len(unique_values),
            null_count=len(values) - len(non_null_values),
            min_value=min_val,
            max_value=max_val,
            avg_value=avg_val
        )
    
    # ─────────────────────────────────────────────────────────
    # Type Detection
    # ─────────────────────────────────────────────────────────
    
    def _detect_type(self, values: List[Any]) -> ColumnType:
        """
        Detect column data type from values.
        
        Args:
            values: Non-null values from column
            
        Returns:
            ColumnType enum value
        """
        
        if not values:
            return ColumnType.UNKNOWN
        
        # Sample first 10 values for analysis
        sample = values[:10]
        sample_size = len(sample)
        
        # Check for date/datetime (need >70% match)
        date_count = sum(1 for v in sample if self._is_date(v))
        if date_count / sample_size > 0.7:
            if any(self._is_datetime(v) for v in sample):
                return ColumnType.DATETIME
            return ColumnType.DATE
        
        # Check for numeric (need >80% match)
        numeric_count = sum(1 for v in sample if self._is_numeric(v))
        if numeric_count / sample_size > 0.8:
            return ColumnType.NUMERIC
        
        # Check for boolean (need >90% match)
        bool_values = {True, False, 'true', 'false', 1, 0, '1', '0', 'yes', 'no', 'evet', 'hayir'}
        bool_count = sum(
            1 for v in sample 
            if str(v).lower() in {str(b).lower() for b in bool_values}
        )
        if bool_count / sample_size > 0.9:
            return ColumnType.BOOLEAN
        
        # Default to text
        return ColumnType.TEXT
    
    # ─────────────────────────────────────────────────────────
    # Role Detection
    # ─────────────────────────────────────────────────────────
    
    def _detect_role(
        self, 
        col_name: str, 
        col_type: ColumnType, 
        values: List[Any]
    ) -> ColumnRole:
        """
        Detect column semantic role.
        
        Args:
            col_name: Column name
            col_type: Detected column type
            values: Non-null values
            
        Returns:
            ColumnRole enum value
        """
        
        col_lower = col_name.lower()
        
        # Check for ID columns first (should be excluded from viz)
        for pattern in self.ID_PATTERNS:
            if re.search(pattern, col_lower):
                return ColumnRole.IDENTIFIER
        
        # Check for time column
        for pattern in self.TIME_COLUMN_PATTERNS:
            if re.search(pattern, col_lower):
                return ColumnRole.TIME
        
        # Check for metric columns (numeric + pattern match)
        if col_type == ColumnType.NUMERIC:
            for pattern in self.METRIC_PATTERNS:
                if re.search(pattern, col_lower):
                    return ColumnRole.METRIC
            
            # High cardinality numeric = likely metric
            if values:
                unique_count = len(set(str(v) for v in values))
                if unique_count > 10:
                    return ColumnRole.METRIC
        
        # Check for dimension columns (pattern match)
        for pattern in self.DIMENSION_PATTERNS:
            if re.search(pattern, col_lower):
                return ColumnRole.DIMENSION
        
        # Text with low cardinality = dimension
        if col_type == ColumnType.TEXT and values:
            unique_count = len(set(str(v) for v in values))
            total_count = len(values)
            # Less than 50% unique values = likely dimension
            if unique_count <= total_count * 0.5:
                return ColumnRole.DIMENSION
        
        # Numeric without metric pattern = still likely metric
        if col_type == ColumnType.NUMERIC:
            return ColumnRole.METRIC
        
        # Default to dimension
        return ColumnRole.DIMENSION
    
    # ─────────────────────────────────────────────────────────
    # Type Checking Helpers
    # ─────────────────────────────────────────────────────────
    
    def _is_numeric(self, value: Any) -> bool:
        """Check if value is numeric."""
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                # Handle Turkish decimal separator
                float(value.replace(',', '.').replace(' ', ''))
                return True
            except ValueError:
                return False
        return False
    
    def _is_date(self, value: Any) -> bool:
        """Check if value is date-like."""
        if isinstance(value, datetime):
            return True
        if isinstance(value, str):
            # Common date patterns
            date_patterns = [
                r'^\d{4}-\d{2}-\d{2}$',           # 2024-01-15
                r'^\d{2}/\d{2}/\d{4}$',           # 15/01/2024
                r'^\d{2}\.\d{2}\.\d{4}$',         # 15.01.2024
                r'^\d{4}/\d{2}/\d{2}$',           # 2024/01/15
            ]
            for pattern in date_patterns:
                if re.match(pattern, value.strip()):
                    return True
        return False
    
    def _is_datetime(self, value: Any) -> bool:
        """Check if value is datetime (includes time component)."""
        if isinstance(value, datetime):
            return True
        if isinstance(value, str):
            # Datetime patterns (date + time)
            datetime_patterns = [
                r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',  # 2024-01-15T10:30 or 2024-01-15 10:30
                r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}',     # 15/01/2024 10:30
            ]
            for pattern in datetime_patterns:
                if re.match(pattern, value.strip()):
                    return True
        return False
