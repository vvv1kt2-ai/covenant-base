"""Tests for parser.plan_run — resume/retry record reconciliation.

Regression cover for the bug where --resume silently dropped existing records
that had parse errors or no covenants (192 -> 185 entries).
"""
from covenant_models import Covenant, ResultEntry
from parser import plan_run


def entry(isin, errors=(), covenants=0):
    e = ResultEntry(isin=isin)
    e.parse_errors = list(errors)
    for i in range(covenants):
        e.add_covenant(Covenant(essence=f"ковенант {i}"))
    return e


# ---------------------------------------------------------------------------
# Fresh run (no existing file)
# ---------------------------------------------------------------------------

def test_fresh_run_processes_everything():
    to_process, kept = plan_run([], ["A", "B"], resume=True)
    assert to_process == ["A", "B"]
    assert kept == []


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def test_resume_skips_clean_records_and_keeps_them():
    existing = [entry("A", covenants=2), entry("B")]
    to_process, kept = plan_run(existing, ["A", "B", "C"], resume=True)
    assert to_process == ["C"]                      # A and B already done cleanly
    assert [r.isin for r in kept] == ["A", "B"]     # and both survive


def test_resume_preserves_error_records_not_in_input():
    """The original bug: error records vanished from the output file."""
    existing = [entry("A", covenants=1), entry("OLD", errors=["not found"]), entry("Z")]
    to_process, kept = plan_run(existing, ["A", "NEW"], resume=True)
    assert to_process == ["NEW"]
    assert [r.isin for r in kept] == ["A", "OLD", "Z"]   # nothing lost


def test_resume_retries_error_records_in_input():
    existing = [entry("A", errors=["timeout"]), entry("B", covenants=1)]
    to_process, kept = plan_run(existing, ["A", "B"], resume=True)
    assert to_process == ["A"]                  # A has errors -> retried
    assert [r.isin for r in kept] == ["B"]      # A dropped so the fresh result replaces it


def test_resume_retry_does_not_duplicate():
    existing = [entry("A", errors=["timeout"])]
    to_process, kept = plan_run(existing, ["A"], resume=True)
    assert to_process == ["A"]
    assert "A" not in {r.isin for r in kept}


# ---------------------------------------------------------------------------
# Retry-errors
# ---------------------------------------------------------------------------

def test_retry_errors_processes_only_error_isins():
    existing = [entry("A", errors=["x"]), entry("B", covenants=3), entry("C", errors=["y"])]
    to_process, kept = plan_run(existing, ["A", "B", "C", "D"], retry_errors=True)
    assert to_process == ["A", "C"]
    assert [r.isin for r in kept] == ["B"]      # successful record stays, retried ones replaced


def test_retry_errors_without_existing_is_empty():
    to_process, kept = plan_run([], ["A"], retry_errors=True)
    assert to_process == ["A"]
    assert kept == []


def test_plain_run_with_existing_replaces_nothing_special():
    """Without resume/retry flags the input is processed as given."""
    existing = [entry("A", covenants=1)]
    to_process, kept = plan_run(existing, ["B"], resume=False, retry_errors=False)
    assert to_process == ["B"]
    assert [r.isin for r in kept] == ["A"]