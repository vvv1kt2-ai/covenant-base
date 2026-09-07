"""Merge e-disclosure program covenants into results.json.

Reads edisclosure_pilot.json, adds new covenants to results.json
with source='Программа облигаций (e-disclosure)'.
Marks PDFs without text layer as requiring manual check.
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

EDISCLOSURE_SOURCE = "Программа облигаций (e-disclosure)"


def main():
    base = Path(__file__).parent

    with open(base / "results.json", encoding="utf-8") as f:
        results = json.load(f)

    with open(base / "edisclosure_pilot.json", encoding="utf-8") as f:
        edisclosure = json.load(f)

    # Index results by ISIN
    results_by_isin = {r["isin"]: r for r in results}

    merged_count = 0
    new_covenant_count = 0
    no_text_layer_isins = []

    for entry in edisclosure:
        emitter = entry.get("emitter", "?")
        company_id = entry.get("company_id", "?")
        prog_num = entry.get("program_number", "?")
        isins = entry.get("isins", [])
        sections = entry.get("target_sections", [])
        status = entry.get("status", "")
        downloaded_files = entry.get("downloaded", [])
        program_covenants = entry.get("program_covenants", {})

        # Check if PDF had no text layer
        if status == "downloaded" and not program_covenants:
            # File downloaded but no covenants parsed — might be no text layer
            for isin in isins:
                if isin in results_by_isin:
                    entry_r = results_by_isin[isin]
                    entry_r["program_checked"] = True
                    entry_r["program_url"] = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
                    entry_r["program_status"] = "no_covenants_found"
                    entry_r["requires_manual_check"] = True
                    entry_r["manual_check_reason"] = (
                        "Программа облигаций скачана с e-disclosure, "
                        "но ковенанты не найдены (возможно, нет текстового слоя)"
                    )
                    no_text_layer_isins.append(isin)
                    logger.warning(f"  {isin} ({emitter}): downloaded but no covenants — marked for manual check")
            continue

        # Process covenants for each ISIN
        for isin in isins:
            if isin not in results_by_isin:
                logger.warning(f"ISIN {isin} not found in results.json, skipping")
                continue

            entry_r = results_by_isin[isin]
            existing_count = len(entry_r.get("covenants", []))

            # Collect all covenants from all downloaded program files
            all_program_events = []
            for fname, events in program_covenants.items():
                for ev in events:
                    all_program_events.append(ev)

            if not all_program_events:
                continue

            for ev in all_program_events:
                title = ev.get("title", "")
                section = ev.get("section", "?")
                full_text = ev.get("full_text", "")

                # Determine essence from title
                if "делистинг" in title.lower():
                    essence = "Досрочное погашение в случае делистинга (из Программы)"
                elif "ликвидаци" in title.lower():
                    essence = "Досрочное погашение в случае ликвидации (из Программы)"
                elif "нарушен" in title.lower() or "отчетност" in title.lower():
                    essence = f"{title} (из Программы)"
                else:
                    essence = f"{title} (из Программы)" if title else "Досрочное погашение (из Программы)"

                new_covenant = {
                    "number": existing_count + 1,
                    "category": "Досрочное погашение по требованию владельцев",
                    "essence": essence,
                    "document": EDISCLOSURE_SOURCE,
                    "section": f"п. {section}",
                    "page": 0,
                    "quote": full_text[:500],
                    "is_provided": True,
                    "conditions": full_text[:500],
                }
                entry_r["covenants"].append(new_covenant)
                existing_count += 1
                new_covenant_count += 1
                logger.info(f"  +{isin} ({emitter}): {essence}")

            entry_r["total_covenants"] = len(entry_r["covenants"])
            entry_r["program_checked"] = True
            entry_r["program_url"] = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
            entry_r["program_status"] = status
            merged_count += 1

    # Save
    with open(base / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"MERGE COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"ISINs with new covenants merged: {merged_count}")
    logger.info(f"Total new covenants added: {new_covenant_count}")
    if no_text_layer_isins:
        logger.info(f"Marked for manual check (no covenants found): {len(no_text_layer_isins)}")
        for isin in no_text_layer_isins:
            logger.info(f"  {isin}")

    total_covenants = sum(len(r.get("covenants", [])) for r in results)
    isins_with_covs = sum(1 for r in results if len(r.get("covenants", [])) > 0)
    manual_check = sum(1 for r in results if r.get("requires_manual_check"))
    logger.info(f"\nUpdated totals:")
    logger.info(f"  Total ISINs: {len(results)}")
    logger.info(f"  ISINs with covenants: {isins_with_covs}")
    logger.info(f"  Total covenants: {total_covenants}")
    logger.info(f"  Requires manual check: {manual_check}")


if __name__ == "__main__":
    main()
