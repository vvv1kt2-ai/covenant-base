"""Export the covenant-bearing issues of one MOEX batch into their own files.

Takes a MOEX new-issues export (JSON or CSV), keeps the issues that ended up
with covenants in results.json, and writes them as a standalone Excel (same
template as the main export) plus a standalone JSON.

Usage:
    python export_new_issues.py "D:\\API мосбиржи\\data\\new-issues-....csv"
    python export_new_issues.py issues.json --xlsx new_issues_covenants.xlsx \\
        --json new_issues_covenants.json
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from add_new_issues import load_issues
from covenant_models import load_results, save_results
from export_excel import export_entries_to_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def select_with_covenants(entries, isins):
    """Records from entries whose ISIN is in isins and that have covenants.

    Order follows the ISIN list, so the batch order from MOEX is preserved.
    """
    by_isin = {e.isin: e for e in entries}
    return [by_isin[i] for i in isins if i in by_isin and by_isin[i].total_covenants > 0]


def enrich_ratings(entries, batch):
    """Fill empty rating fields from the MOEX batch.

    `_extract_rating` on the Finam card finds nothing, so every record carries
    an empty rating; the MOEX export states the rating for exactly these ISINs.
    Existing non-empty ratings are never overwritten.
    """
    by_isin = {i["isin"]: i for i in batch}
    filled = 0
    for entry in entries:
        issue = by_isin.get(entry.isin)
        if issue and not entry.rating and issue.get("rating"):
            entry.rating = issue["rating"]
            filled += 1
    return filled


def main():
    parser = argparse.ArgumentParser(description="Export covenant-bearing issues of a MOEX batch")
    parser.add_argument("input", help="MOEX new-issues export (.json or .csv)")
    parser.add_argument("--results", default="results.json", help="Parsed results to read")
    parser.add_argument("--xlsx", default="new_issues_covenants.xlsx", help="Output Excel path")
    parser.add_argument("--json", dest="json_path", default="new_issues_covenants.json",
                        help="Output JSON path ('' to skip)")
    args = parser.parse_args()

    batch = load_issues(args.input)
    batch_isins = [i["isin"] for i in batch if i["isin"]]

    entries = load_results(args.results)
    known = {e.isin: e for e in entries}
    selected = select_with_covenants(entries, batch_isins)

    without = [i for i in batch_isins if i in known and known[i].total_covenants == 0]
    missing = [i for i in batch_isins if i not in known]

    logger.info(f"Batch {args.input}: {len(batch_isins)} issues")
    logger.info(f"With covenants: {len(selected)} | without: {len(without)} | not in results yet: {len(missing)}")
    if missing:
        logger.warning(f"Not parsed yet: {', '.join(missing)}")

    if not selected:
        logger.warning("No covenant-bearing issues in this batch — nothing written")
        return

    for e in selected:
        logger.info(f"  {e.isin}  cov={e.total_covenants}  {e.issuer[:45]}")

    filled = enrich_ratings(selected, batch)
    if filled:
        logger.info(f"Ratings filled from the MOEX file: {filled}")

    export_entries_to_excel(selected, output_path=args.xlsx)

    if args.json_path:
        save_results(args.json_path, selected)
        logger.info(f"Saved: {args.json_path}")


if __name__ == "__main__":
    main()
