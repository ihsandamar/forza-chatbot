"""
Turkey province map utilities.

Provides city column detection and GeoJSON asset loading for
the turkey_map chart type.
"""
import pathlib
import unicodedata
from typing import List, Optional

_ASSET_DIR = pathlib.Path(__file__).parent / "assets"
TURKEY_GEOJSON_PATH = _ASSET_DIR / "turkey_provinces.geojson"

# Column name fragments (lowercased, stripped of _ and space) that indicate a city dimension
_CITY_HINTS = frozenset({
    "city", "cityname", "sehir", "sehiradi",
    "branchcity", "branchcityname", "iladi", "il",
})


def detect_city_column(dim_cols: List[str]) -> Optional[str]:
    """
    Return the first column in dim_cols that looks like a Turkish city dimension.
    Returns None if no match.
    """
    for col in dim_cols:
        normalized = col.lower().replace("_", "").replace(" ", "")
        if normalized in _CITY_HINTS or "city" in normalized or "sehir" in normalized:
            return col
    return None


_TURKISH_CHAR_MAP = str.maketrans({
    "ı": "i",   # U+0131 LATIN SMALL LETTER DOTLESS I
    "İ": "i",   # U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE
    "ğ": "g",   # U+011F LATIN SMALL LETTER G WITH BREVE
    "Ğ": "g",   # U+011E LATIN CAPITAL LETTER G WITH BREVE
    "ş": "s",   # U+015F LATIN SMALL LETTER S WITH CEDILLA
    "Ş": "s",   # U+015E LATIN CAPITAL LETTER S WITH CEDILLA
    "ç": "c",   # U+00E7 LATIN SMALL LETTER C WITH CEDILLA
    "Ç": "c",   # U+00C7 LATIN CAPITAL LETTER C WITH CEDILLA
    "ö": "o",   # U+00F6 LATIN SMALL LETTER O WITH DIAERESIS
    "Ö": "o",   # U+00D6 LATIN CAPITAL LETTER O WITH DIAERESIS
    "ü": "u",   # U+00FC LATIN SMALL LETTER U WITH DIAERESIS
    "Ü": "u",   # U+00DC LATIN CAPITAL LETTER U WITH DIAERESIS
})


def normalize_city_name(name: str) -> str:
    """
    Lowercase + strip Turkish/Latin diacritics for fuzzy name matching.
    Example: 'İstanbul' -> 'istanbul', 'Şanlıurfa' -> 'sanliurfa'
    """
    # Apply Turkish-specific substitutions first (NFKD alone doesn't handle dotless-ı etc.)
    mapped = name.translate(_TURKISH_CHAR_MAP)
    nfkd = unicodedata.normalize("NFKD", mapped.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def load_turkey_geojson() -> Optional[dict]:
    """
    Load Turkey provinces GeoJSON from the bundled asset file.
    Returns None if the asset file does not exist (renderer falls back gracefully).
    """
    if not TURKEY_GEOJSON_PATH.exists():
        return None
    import json
    with open(TURKEY_GEOJSON_PATH, encoding="utf-8") as f:
        return json.load(f)
