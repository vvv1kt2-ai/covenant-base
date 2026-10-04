"""Append a parsed results file into the main results.json (model-aware I/O).

Incoming records replace same-ISIN records already present, so re-running the
merge is idempotent; all other existing records keep their order.

Usage:
    python merge_results.py results_new.json --into results.json
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from covenant_models import load_results, save_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def merge_entries(existing, incoming):
    """Merge incoming entries into existing ones.

    Returns (merged, stats) where stats = {"added", "replaced"}.
    Incoming wins on ISIN collision; existing order is preserved for the rest.
    """
    incoming_isins = {e.isin for e in incoming}
    kept = [e for e in existing if e.isin not in incoming_isins]
    existing_isins = {e.isin for e in existing}
    added = sum(1 for e in incoming if e.isin not in existing_isins)
    replaced = len(incoming) - added
    return kept + list(incoming), {"added": added, "replaced": replaced}


def main():
    parser = argparse.ArgumentParser(description="Merge a results file into the main results.json")
    parser.add_argument("incoming", help="Results file to merge in (e.g. results_new.json)")
    parser.add_argument("--into", default="results.json", help="Target results file")
    args = parser.parse_args()

    incoming_path = Path(args.incoming)
    target_path = Path(args.into)

    if not incoming_path.exists():
        logger.error(f"Incoming file not found: {incoming_path}")
        sys.exit(1)

    incoming = load_results(incoming_path)
    existing = load_results(target_path) if target_path.exists() else []

    merged, stats = merge_entries(existing, incoming)

    with_covenants = sum(1 for e in incoming if e.total_covenants > 0)
    logger.info(f"Incoming: {len(incoming)} records ({with_covenants} with covenants)")
    logger.info(f"Target before: {len(existing)} records")
    logger.info(f"Merged: +{stats['added']} added, {stats['replaced']} replaced")
    logger.info(f"Target after: {len(merged)} records")

    save_results(target_path, merged)
    logger.info(f"Saved {target_path}")


if __name__ == "__main__":
    main()
