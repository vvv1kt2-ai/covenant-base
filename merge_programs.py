"""Merge program covenants from results_programs.json into results.json.

For each ISIN with new covenants from programs, adds them to the covenants array
in results.json with source='Программа облигаций'.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    base = Path(__file__).parent

    # Load both files
    with open(base / "results.json", encoding="utf-8") as f:
        results = json.load(f)

    with open(base / "results_programs.json", encoding="utf-8") as f:
        programs = json.load(f)

    # Index results by ISIN
    results_by_isin = {r["isin"]: r for r in results}

    # Find ISINs with new covenants from programs
    merged_count = 0
    new_covenant_count = 0

    for prog in programs:
        isin = prog["isin"]
        new_covs = prog.get("new_covenants", [])
        total_new = prog.get("total_new", 0)

        if total_new == 0 or not new_covs:
            continue

        if isin not in results_by_isin:
            logger.warning(f"ISIN {isin} not found in results.json, skipping")
            continue

        entry = results_by_isin[isin]
        existing_count = len(entry.get("covenants", []))

        # Add new covenants from program
        for ev in new_covs:
            # Determine category based on event title
            title = ev.get("title", "")
            if "делистинг" in title.lower():
                category = "Досрочное погашение по требованию владельцев"
                essence = "Досрочное погашение в случае делистинга (из Программы)"
            elif "ликвидаци" in title.lower():
                category = "Досрочное погашение по требованию владельцев"
                essence = "Досрочное погашение в случае ликвидации (из Программы)"
            elif "нарушен" in title.lower() or "отчетност" in title.lower():
                category = "Досрочное погашение по требованию владельцев"
                essence = f"{title} (из Программы)"
            else:
                category = "Досрочное погашение по требованию владельцев"
                essence = f"{title} (из Программы)"

            new_covenant = {
                "number": existing_count + 1,
                "category": category,
                "essence": essence,
                "document": "Программа облигаций",
                "section": f"п. {ev.get('section', '9.5.1')}",
                "page": 0,  # unknown page from program
                "quote": ev.get("full_text", "")[:500],
                "is_provided": True,
                "conditions": ev.get("full_text", "")[:500],
            }
            entry["covenants"].append(new_covenant)
            existing_count += 1
            new_covenant_count += 1
            logger.info(f"  +{isin}: {essence}")

        entry["total_covenants"] = len(entry["covenants"])

        # Mark that we checked the program
        entry["program_checked"] = True
        entry["program_url"] = prog.get("program_url", "")
        entry["program_status"] = prog.get("status", "")

        merged_count += 1

    # Mark ISINs that were checked but had no program
    for prog in programs:
        isin = prog["isin"]
        if isin in results_by_isin and prog.get("total_new", 0) == 0:
            entry = results_by_isin[isin]
            entry["program_checked"] = True
            entry["program_url"] = prog.get("program_url", "")
            entry["program_status"] = prog.get("status", "")

    # Save updated results.json
    with open(base / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"MERGE COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"ISINs with new covenants merged: {merged_count}")
    logger.info(f"Total new covenants added: {new_covenant_count}")

    # Final stats
    total_covenants = sum(len(r.get("covenants", [])) for r in results)
    isins_with_covs = sum(1 for r in results if len(r.get("covenants", [])) > 0)
    logger.info(f"\nUpdated totals:")
    logger.info(f"  Total ISINs: {len(results)}")
    logger.info(f"  ISINs with covenants: {isins_with_covs}")
    logger.info(f"  Total covenants: {total_covenants}")


if __name__ == "__main__":
    main()
