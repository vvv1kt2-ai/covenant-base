"""Tests for merge_results.merge_entries — idempotent append into results.json."""
from covenant_models import Covenant, ResultEntry
from merge_results import merge_entries


def entry(isin, covenants=0):
    e = ResultEntry(isin=isin)
    for i in range(covenants):
        e.add_covenant(Covenant(essence=f"c{i}"))
    return e


def test_merge_adds_new_records_and_keeps_existing_order():
    existing = [entry("A"), entry("B")]
    merged, stats = merge_entries(existing, [entry("C"), entry("D")])
    assert [e.isin for e in merged] == ["A", "B", "C", "D"]
    assert stats == {"added": 2, "replaced": 0}


def test_merge_replaces_same_isin_with_incoming():
    existing = [entry("A", covenants=1), entry("B")]
    merged, stats = merge_entries(existing, [entry("A", covenants=3)])
    assert stats == {"added": 0, "replaced": 1}
    assert [e.isin for e in merged] == ["B", "A"]
    assert [e.total_covenants for e in merged] == [0, 3]  # incoming wins


def test_merge_is_idempotent():
    existing = [entry("A"), entry("B")]
    incoming = [entry("C")]
    once, _ = merge_entries(existing, incoming)
    twice, stats = merge_entries(once, incoming)
    assert [e.isin for e in twice] == [e.isin for e in once]
    assert stats == {"added": 0, "replaced": 1}


def test_merge_into_empty_target():
    merged, stats = merge_entries([], [entry("A")])
    assert [e.isin for e in merged] == ["A"]
    assert stats == {"added": 1, "replaced": 0}
