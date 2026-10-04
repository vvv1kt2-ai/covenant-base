"""Tests for export_new_issues — picking a batch's covenant-bearing issues."""
from covenant_models import Covenant, ResultEntry
from export_new_issues import enrich_ratings, select_with_covenants


def entry(isin, covenants=0, rating=""):
    e = ResultEntry(isin=isin, rating=rating)
    for i in range(covenants):
        e.add_covenant(Covenant(essence=f"ковенант {i}"))
    return e


def issue(isin, rating):
    return {"isin": isin, "rating": rating}


def test_selects_only_entries_with_covenants():
    entries = [entry("A", 2), entry("B"), entry("C", 1)]
    assert [e.isin for e in select_with_covenants(entries, ["A", "B", "C"])] == ["A", "C"]


def test_preserves_batch_order_not_results_order():
    entries = [entry("C", 1), entry("A", 1), entry("B", 1)]
    assert [e.isin for e in select_with_covenants(entries, ["A", "B", "C"])] == ["A", "B", "C"]


def test_ignores_isins_missing_from_results():
    entries = [entry("A", 1)]
    assert [e.isin for e in select_with_covenants(entries, ["A", "NOT-PARSED"])] == ["A"]


def test_empty_when_batch_has_no_covenants():
    entries = [entry("A"), entry("B")]
    assert select_with_covenants(entries, ["A", "B"]) == []


# ---------------------------------------------------------------------------
# Rating enrichment (the Finam card never yields a rating)
# ---------------------------------------------------------------------------

def test_enrich_fills_empty_ratings_from_batch():
    entries = [entry("A", 1), entry("B", 1), entry("C", 1)]
    batch = [issue("A", "BB+"), issue("B", "BBB+"), issue("C", "B")]
    assert enrich_ratings(entries, batch) == 3
    assert [e.rating for e in entries] == ["BB+", "BBB+", "B"]


def test_enrich_never_overwrites_existing_rating():
    entries = [entry("A", 1, rating="A-(RU)")]
    assert enrich_ratings(entries, [issue("A", "BB+")]) == 0
    assert entries[0].rating == "A-(RU)"


def test_enrich_skips_isins_absent_from_batch():
    entries = [entry("A", 1), entry("MISSING", 1)]
    assert enrich_ratings(entries, [issue("A", "BB+")]) == 1
    assert entries[1].rating == ""


def test_enrich_skips_blank_rating_in_batch():
    entries = [entry("A", 1)]
    assert enrich_ratings(entries, [issue("A", "")]) == 0
    assert entries[0].rating == ""
