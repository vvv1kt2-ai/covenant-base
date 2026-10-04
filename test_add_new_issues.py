"""Tests for add_new_issues — MOEX export loading, rating window, diffing.

Uses self-cleaning dirs in cwd (pytest tmp_path is unusable under the DSH
sandbox — see test_covenant_models).
"""
import csv
import json
import shutil
import uuid
from pathlib import Path

import pytest

from add_new_issues import (
    in_rating_window,
    load_issues,
    load_issues_csv,
    load_issues_json,
    parse_rating_code,
    rating_score,
    select_new,
)
from covenant_models import ResultEntry, load_results, save_results


@pytest.fixture
def work_dir():
    d = Path(f"covtest-{uuid.uuid4().hex[:8]}")
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rating normalisation (agency formats differ)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("BB+|ru|", "BB+"),
    ("BBB+(RU)", "BBB+"),
    ("ruB", "B"),
    ("ruBB-", "BB-"),
    ("B", "B"),
    ("AA-(RU)", "AA-"),
    ("B-", "B-"),
    ("", ""),
    (None, ""),
    ("без рейтинга", ""),
])
def test_parse_rating_code(raw, expected):
    assert parse_rating_code(raw) == expected


def test_rating_score_orders_the_scale():
    scores = [rating_score(r) for r in
              ["B-", "B", "B+", "BB-", "BB", "BB+", "BBB-", "BBB+", "A-"]]
    assert all(s is not None for s in scores)
    assert scores == sorted(scores)


def test_rating_score_window_is_documented():
    # B- = 11, BBB+ = 19 — the window the MOEX export was built with
    assert rating_score("B-") == 11
    assert rating_score("BBB+") == 19
    assert rating_score("мусор") is None


# ---------------------------------------------------------------------------
# Window filter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rating,expected", [
    ("B-", True), ("B", True), ("B+", True), ("BB-", True),
    ("BB+", True), ("BBB-", True), ("BBB+", True),
    ("CCC", False), ("CCC+", False),      # below B-
    ("A-", False), ("A+", False),         # above BBB+
    ("", False),                          # unknown rating cannot be in window
])
def test_in_rating_window_inclusive(rating, expected):
    assert in_rating_window(rating, "B-", "BBB+") is expected


# ---------------------------------------------------------------------------
# Loading (JSON and CSV carry the same data)
# ---------------------------------------------------------------------------

MOEX_JSON = {
    "from": "2026-09-01", "till": "2026-10-04",
    "ratingMin": "B-", "ratingMax": "BBB+", "count": 2,
    "bonds": [
        {"isin": "RU000A10G7Z9", "rating": "BB+", "ratingValue": "BB+|ru|",
         "ratingAgency": "НРА", "ratingSource": "эмитент", "issuedate": "2026-09-29",
         "emitterShort": 'ООО "ПКО "АСВ"', "name": "АСВ БО-06-001P"},
        {"isin": "RU000A10G700", "rating": "BBB+", "ratingValue": "BBB+(RU)",
         "ratingAgency": "АКРА", "ratingSource": "выпуск", "issuedate": "2026-09-25",
         "emitterShort": 'ООО "РСГ-Финанс"', "name": "РСГ-Финанс 001Р-04"},
    ],
}

MOEX_CSV_COLUMNS = ["issuedate", "name", "secname", "isin", "secid", "rating",
                    "ratingValue", "ratingAgency", "ratingDate", "ratingSource",
                    "emitterShort", "emitterName"]


def test_load_issues_json(work_dir):
    path = work_dir / "new-issues.json"
    path.write_text(json.dumps(MOEX_JSON, ensure_ascii=False), encoding="utf-8")

    issues = load_issues(path)
    assert [i["isin"] for i in issues] == ["RU000A10G7Z9", "RU000A10G700"]
    assert issues[0]["rating"] == "BB+"
    assert issues[0]["agency"] == "НРА"
    assert issues[0]["emitter"] == 'ООО "ПКО "АСВ"'


def test_load_issues_csv_matches_json(work_dir):
    """Both formats must yield the same records for the same issues."""
    json_path = work_dir / "new-issues.json"
    json_path.write_text(json.dumps(MOEX_JSON, ensure_ascii=False), encoding="utf-8")

    csv_path = work_dir / "new-issues.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MOEX_CSV_COLUMNS)
        writer.writeheader()
        for bond in MOEX_JSON["bonds"]:
            writer.writerow({
                "issuedate": bond["issuedate"], "name": bond["name"],
                "secname": bond["name"], "isin": bond["isin"], "secid": bond["isin"],
                "rating": bond["rating"], "ratingValue": bond["ratingValue"],
                "ratingAgency": bond["ratingAgency"], "ratingDate": "",
                "ratingSource": bond["ratingSource"],
                "emitterShort": bond["emitterShort"], "emitterName": bond["emitterShort"],
            })

    from_csv = load_issues(csv_path)
    from_json = load_issues(json_path)
    assert from_csv == from_json


def test_load_issues_detects_format(work_dir):
    json_path = work_dir / "a.json"
    json_path.write_text(json.dumps(MOEX_JSON, ensure_ascii=False), encoding="utf-8")
    assert len(load_issues(json_path)) == 2

    with pytest.raises(ValueError):
        load_issues(work_dir / "a.txt")


# ---------------------------------------------------------------------------
# Diffing against results.json
# ---------------------------------------------------------------------------

def issues(*specs):
    return [
        {"isin": isin, "rating": rating, "rating_value": rating, "agency": "АКРА",
         "source": "эмитент", "issuedate": "2026-09-01", "emitter": "Эмитент", "name": ""}
        for isin, rating in specs
    ]


def test_select_new_splits_three_ways(work_dir):
    data = issues(("NEW1", "BB"), ("OLD1", "BB+"), ("LOW", "CCC"), ("HIGH", "A-"))
    new, out_of_window, already = select_new(data, {"OLD1"}, "B-", "BBB+")

    assert [i["isin"] for i in new] == ["NEW1"]
    assert [i["isin"] for i in out_of_window] == ["LOW", "HIGH"]
    assert [i["isin"] for i in already] == ["OLD1"]


def test_select_new_deduplicates_input():
    data = issues(("DUP", "BB"), ("DUP", "BB"), ("OTHER", "B"))
    new, _, _ = select_new(data, set(), "B-", "BBB+")
    assert [i["isin"] for i in new] == ["DUP", "OTHER"]


def test_select_new_against_real_results_file(work_dir):
    """End-to-end diff against a results.json written by the model."""
    results_path = work_dir / "results.json"
    save_results(results_path, [ResultEntry(isin="OLD1")])

    known = {r.isin for r in load_results(results_path)}
    new, _, already = select_new(issues(("NEW1", "BB"), ("OLD1", "BB+")), known, "B-", "BBB+")
    assert [i["isin"] for i in new] == ["NEW1"]
    assert [i["isin"] for i in already] == ["OLD1"]