"""Merge program covenants from results_programs.json into results.json.

Uses covenant_models.build_program_covenant for dict construction.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from covenant_models import build_program_covenant, is_real_covenant

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    base = Path(__file__).parent

    with open(base / "results.json", encoding="utf-8") as f:
        results = json.load(f)

    with open(base / "results_programs.json", encoding="utf-8") as f:
        programs = json.load(f)

    results_by_isin = {r["isin"]: r for r in results}
    merged_count = 0
    new_covenant_count = 0

    for prog in programs:
        isin = prog["isin"]
        new_covs = prog.get("new_covenants", [])
        total_new = prog.get("total_new", 0)

        if total_new == 0 or not new_covs:
            # Mark checked even with no covenants
            if isin in results_by_isin:
                entry = results_by_isin[isin]
                entry["program_checked"] = True
                entry["program_url"] = prog.get("program_url", "")
                entry["program_status"] = prog.get("status", "")
            continue

        if isin not in results_by_isin:
            logger.warning(f"ISIN {isin} not found in results.json, skipping")
            continue

        entry = results_by_isin[isin]
        existing_count = len(entry.get("covenants", []))

        for ev in new_covs:
            title = ev.get("title", "")
            full_text = ev.get("full_text", "")
            section = ev.get("section", "9.5.1")
            text_to_check = full_text or title

            # Filter: only real covenants from programs
            if not is_real_covenant(text_to_check):
                logger.info(f"  SKIP {isin}: not a real covenant: {title[:60]}")
                continue

            new_covenant = build_program_covenant(
                existing_count=existing_count,
                title=title,
                section=section,
                full_text=full_text,
                document_source="Программа облигаций",
            )
            entry["covenants"].append(new_covenant)
            existing_count += 1
            new_covenant_count += 1
            logger.info(f"  +{isin}: {new_covenant['essence'][:70]}")

        entry["total_covenants"] = len(entry["covenants"])
        entry["program_checked"] = True
        entry["program_url"] = prog.get("program_url", "")
        entry["program_status"] = prog.get("status", "")
        merged_count += 1

    with open(base / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"MERGE COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"ISINs with new covenants merged: {merged_count}")
    logger.info(f"Total new covenants added: {new_covenant_count}")

    total_covenants = sum(len(r.get("covenants", [])) for r in results)
    isins_with_covs = sum(1 for r in results if len(r.get("covenants", [])) > 0)
    logger.info(f"\nUpdated totals:")
    logger.info(f"  Total ISINs: {len(results)}")
    logger.info(f"  ISINs with covenants: {isins_with_covs}")
    logger.info(f"  Total covenants: {total_covenants}")


if __name__ == "__main__":
    main()
