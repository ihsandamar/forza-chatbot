import pytest
from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver


@pytest.fixture
def resolver():
    return ColumnResolver()


# ── Doğrudan alias testi ────────────────────────────────────────────────────

def test_resolve_turkish_column_alias(resolver):
    assert resolver.resolve("Kategori") == "CategoryName"
    assert resolver.resolve("tutar") == "RowAmount"
    assert resolver.resolve("Sube") == "BranchName"


def test_resolve_already_db_column(resolver):
    assert resolver.resolve("CategoryName") == "CategoryName"
    assert resolver.resolve("RowAmount") == "RowAmount"
    assert resolver.resolve("BranchName") == "BranchName"


def test_resolve_metric_satis(resolver):
    assert resolver.resolve("satış") == "RowAmount"


def test_resolve_case_insensitive(resolver):
    assert resolver.resolve("KATEGORI") == "CategoryName"
    assert resolver.resolve("rowamount") == "RowAmount"


# ── Türkçe suffix soyma ─────────────────────────────────────────────────────

def test_strip_possessive_si(resolver):
    assert resolver.resolve("kategorisi") == "CategoryName"


def test_strip_possessive_si_with_locative(resolver):
    assert resolver.resolve("kategorisindeki") == "CategoryName"


def test_strip_ablative_den(resolver):
    assert resolver.resolve("şubeden") == "BranchName"


def test_strip_locative_de(resolver):
    assert resolver.resolve("şubede") == "BranchName"


# ── column_hint fallback ────────────────────────────────────────────────────

def test_column_hint_used_when_raw_text_unknown(resolver):
    assert resolver.resolve("espresso", column_hint="CategoryName") == "CategoryName"
    assert resolver.resolve("xyz123", column_hint="BranchName") == "BranchName"


def test_column_hint_ignored_when_raw_text_resolves(resolver):
    assert resolver.resolve("tutar", column_hint="BranchName") == "RowAmount"


# ── Bulunamama durumu ───────────────────────────────────────────────────────

def test_resolve_unknown_returns_none(resolver):
    assert resolver.resolve("xyzABCunknown") is None


def test_resolve_unknown_with_bad_hint_returns_none(resolver):
    assert resolver.resolve("abc", column_hint="NotAColumn") is None


# ── Fuzzy match (db_columns provided) ──────────────────────────────────────

def test_fuzzy_match_near_db_column():
    """db_columns verildiğinde yakın eşleşmeler fuzzy match ile bulunur."""
    try:
        import rapidfuzz  # noqa: F401
    except ImportError:
        pytest.skip("rapidfuzz not installed")
    resolver = ColumnResolver(db_columns=["RowAmount", "BranchName", "CategoryName"])
    result = resolver.resolve("RowAmont")  # typo, 85+ similarity
    assert result == "RowAmount"


def test_with_db_columns_helper():
    """with_db_columns factory — returns new instance with db_columns set."""
    base = ColumnResolver()
    enriched = base.with_db_columns(["RowAmount"])
    assert enriched._db_columns == ["RowAmount"]
    # base instance unchanged
    assert base._db_columns == []
    # still resolves aliases correctly
    assert enriched.resolve("tutar") == "RowAmount"
