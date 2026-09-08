"""Merge e-disclosure program covenants into results.json.

Reads/writes results.json exclusively through covenant_models.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from covenant_models import build_program_covenant, is_real_covenant, load_results, save_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

EDISCLOSURE_SOURCE = "Программа облигаций (e-disclosure)"


def main():
    base = Path(__file__).parent

    results = load_results(base / "results.json")

    with open(base / "edisclosure_pilot.json", encoding="utf-8") as f:
        edisclosure = json.load(f)

    results_by_isin = {r.isin: r for r in results}
    merged_count = 0
    new_covenant_count = 0
    no_text_layer_isins = []

    for entry_data in edisclosure:
        emitter = entry_data.get("emitter", "?")
        company_id = entry_data.get("company_id", "?")
        isins = entry_data.get("isins", [])
        status = entry_data.get("status", "")
        program_covenants = entry_data.get("program_covenants", {})

        # Mark ISINs with no covenants found as requiring manual check
        if status == "downloaded" and not program_covenants:
            for isin in isins:
                if isin in results_by_isin:
                    r = results_by_isin[isin]
                    r.program_checked = True
                    r.program_url = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
                    r.program_status = "no_covenants_found"
                    r.requires_manual_check = True
                    r.manual_check_reason = (
                        "Программа облигаций скачана с e-disclosure, "
                        "но ковенанты не найдены (возможно, нет текстового слоя)"
                    )
                    no_text_layer_isins.append(isin)
                    logger.warning(f"  {isin} ({emitter}): no covenants — manual check")
            continue

        for isin in isins:
            if isin not in results_by_isin:
                logger.warning(f"ISIN {isin} not found in results.json, skipping")
                continue

            r = results_by_isin[isin]

            all_events = []
            for events in program_covenants.values():
                all_events.extend(events)

            if not all_events:
                continue

            for ev in all_events:
                title = ev.get("title", "")
                section = ev.get("section", "?")
                full_text = ev.get("full_text", "")
                text_to_check = full_text or title

                # Filter: only real covenants
                if not is_real_covenant(text_to_check):
                    logger.info(f"  SKIP {isin}: not a real covenant: {title[:60]}")
                    continue

                new_cov = r.add_covenant(build_program_covenant(
                    title=title,
                    section=section,
                    full_text=full_text,
                    document_source=EDISCLOSURE_SOURCE,
                ))
                new_covenant_count += 1
                logger.info(f"  +{isin} ({emitter}): {new_cov.essence[:70]}")

            r.program_checked = True
            r.program_url = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
            r.program_status = status
            merged_count += 1

    save_results(base / "results.json", results)

    logger.info(f"\n{'='*60}")
    logger.info(f"MERGE COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"ISINs merged: {merged_count}")
    logger.info(f"New covenants added: {new_covenant_count}")
    if no_text_layer_isins:
        logger.info(f"Manual check needed: {len(no_text_layer_isins)} ISINs")

    total_covenants = sum(r.total_covenants for r in results)
    isins_with_covs = sum(1 for r in results if r.total_covenants > 0)
    manual = sum(1 for r in results if r.requires_manual_check)
    logger.info(f"\nTotals: {len(results)} ISINs, {isins_with_covs} with covenants, "
                f"{total_covenants} covenants, {manual} manual check")


if __name__ == "__main__":
    main()
