"""Pick new bond issues from a MOEX export and prepare them for parsing.

Input: a MOEX new-issues export — JSON ({"bonds": [...]}) or CSV, detected by
suffix; both carry the same fields, so either is accepted.
Filters: issue rating inside a window (inclusive), issues already present in
results.json, duplicates within the file.
Output: a plain ISIN list for `parser.py --input` plus a console table.

Usage:
    python add_new_issues.py "D:\\API мосбиржи\\data\\new-issues-2026-09-01_2026-10-04.csv"
    python add_new_issues.py new-issues.json --min B- --max BBB+ --out new_isins.txt
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from covenant_models import load_results

# National-scale letters, longest first so BBB matches before BB/B
_RATING_RE = re.compile(r"(AAA|AA|A|BBB|BB|B|CCC|CC|C|D)\s*([+-])?", re.IGNORECASE)

# AAA = 9 ... D = 0, one letter step = 3 points, modifier shifts by one
_BASE_SCORE = {"AAA": 9, "AA": 8, "A": 7, "BBB": 6, "BB": 5, "B": 4, "CCC": 3, "CC": 2, "C": 1, "D": 0}
_MODIFIER = {"+": 1, "": 0, "-": -1}


def parse_rating_code(value):
    """Normalize an agency rating to a plain code.

    Handles the formats MOEX returns: "BB+|ru|" → BB+, "BBB+(RU)" → BBB+,
    "ruB" → B, "ruBB-" → BB-. Returns "" when no rating can be read.
    """
    if not value:
        return ""
    match = _RATING_RE.search(str(value))
    if not match:
        return ""
    return f"{match.group(1).upper()}{match.group(2) or ''}"


def rating_score(code):
    """Numeric score for a rating code, or None when unparsable."""
    parsed = parse_rating_code(code)
    if not parsed:
        return None
    modifier = parsed[-1] if parsed[-1] in "+-" else ""
    letters = parsed[:-1] if modifier else parsed
    if letters not in _BASE_SCORE:
        return None
    return _BASE_SCORE[letters] * 3 + _MODIFIER[modifier]


def in_rating_window(rating, min_code, max_code):
    """Is the rating inside [min_code, max_code] (inclusive)?"""
    score = rating_score(rating)
    low, high = rating_score(min_code), rating_score(max_code)
    if score is None or low is None or high is None:
        return False
    return low <= score <= high


def _record(isin, rating, rating_value, agency, source, issuedate, emitter, name):
    return {
        "isin": (isin or "").strip(),
        "rating": parse_rating_code(rating) or parse_rating_code(rating_value),
        "rating_value": (rating_value or rating or "").strip(),
        "agency": (agency or "").strip(),
        "source": (source or "").strip(),
        "issuedate": (issuedate or "").strip(),
        "emitter": (emitter or "").strip(),
        "name": (name or "").strip(),
    }


def load_issues_json(path):
    """Load MOEX JSON export ({"bonds": [...]})."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    bonds = data.get("bonds", data if isinstance(data, list) else [])
    return [
        _record(
            b.get("isin"), b.get("rating"), b.get("ratingValue"),
            b.get("ratingAgency"), b.get("ratingSource"), b.get("issuedate"),
            b.get("emitterShort") or b.get("emitterName"), b.get("name"),
        )
        for b in bonds
    ]


def load_issues_csv(path):
    """Load a flattened CSV export of the same issues."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [
        _record(
            r.get("isin"), r.get("rating"), r.get("ratingValue"),
            r.get("ratingAgency"), r.get("ratingSource"), r.get("issuedate"),
            r.get("emitterShort") or r.get("emitterName"), r.get("name") or r.get("secname"),
        )
        for r in rows
    ]


def load_issues(path):
    """Load issues from JSON or CSV, detected by suffix."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_issues_json(path)
    if suffix == ".csv":
        return load_issues_csv(path)
    raise ValueError(f"Unsupported input format: {path.suffix} (expected .json or .csv)")


def select_new(issues, known_isins, min_code, max_code):
    """Split issues into (new, out_of_window, already_parsed), keeping file order.

    Duplicate ISINs inside the input are collapsed to the first occurrence.
    """
    new, out_of_window, already = [], [], []
    seen = set()
    for issue in issues:
        isin = issue["isin"]
        if not isin or isin in seen:
            continue
        seen.add(isin)
        if not in_rating_window(issue["rating"], min_code, max_code):
            out_of_window.append(issue)
        elif isin in known_isins:
            already.append(issue)
        else:
            new.append(issue)
    return new, out_of_window, already


def main():
    parser = argparse.ArgumentParser(description="Prepare new MOEX issues for covenant parsing")
    parser.add_argument("input", help="MOEX new-issues export (.json or .csv)")
    parser.add_argument("--results", default="results.json", help="Existing results to diff against")
    parser.add_argument("--min", dest="rating_min", default="B-", help="Rating window lower bound")
    parser.add_argument("--max", dest="rating_max", default="BBB+", help="Rating window upper bound")
    parser.add_argument("--out", default="new_isins.txt", help="Where to write the ISIN list")
    args = parser.parse_args()

    if rating_score(args.rating_min) is None or rating_score(args.rating_max) is None:
        parser.error(f"Cannot parse rating bounds: {args.rating_min!r} / {args.rating_max!r}")

    issues = load_issues(args.input)

    results_path = Path(args.results)
    known = {r.isin for r in load_results(results_path)} if results_path.exists() else set()

    new, out_of_window, already = select_new(issues, known, args.rating_min, args.rating_max)

    print(f"File: {args.input}")
    print(f"Rating window: {args.rating_min}..{args.rating_max} "
          f"(scores {rating_score(args.rating_min)}..{rating_score(args.rating_max)})")
    print(f"Known ISINs in {results_path.name}: {len(known)}")
    print()

    new_isins = {i["isin"] for i in new}
    already_isins = {i["isin"] for i in already}

    for issue in issues:
        if issue["isin"] in new_isins:
            mark = "НОВАЯ   "
        elif issue["isin"] in already_isins:
            mark = "уже есть"
        else:
            mark = "вне окна"
        print(f"  {mark}  {issue['isin']}  {issue['rating']:>5s} {issue['agency']:<11s} "
              f"{issue['issuedate']:<10s} {issue['emitter'][:42]}")

    print()
    print(f"Итого в файле: {len(issues)} | в окне и новые: {len(new)} "
          f"| уже спарсено: {len(already)} | вне окна: {len(out_of_window)}")

    out_path = Path(args.out)
    out_path.write_text("\n".join(i["isin"] for i in new) + ("\n" if new else ""), encoding="utf-8")
    print(f"Список новых ISIN: {out_path} ({len(new)} шт.)")
    if new:
        print(f"Запуск: python parser.py --input {out_path} --output results.json --resume")


if __name__ == "__main__":
    main()
