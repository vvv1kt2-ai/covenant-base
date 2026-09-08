"""Pilot: Find program documents on e-disclosure.ru for ISINs without Finam programs.

Workflow:
1. Load known companyIds from company_ids.json (skip search if found)
2. For each emitter: search e-disclosure.ru → find companyId → save to company_ids.json
3. Navigate to file listing (type=7) → find program document (not prospectus!)
4. Download (handle ZIP archives — extract PDFs)
5. Parse the SPECIFIC section referenced by the decision

Supporting modules:
    edisclosure_store.py  — persistent caches (companyIds, section refs)
    edisclosure_client.py — site interaction (search, listing, downloads)
    pdf_parser.py         — program PDF parsing (parse_program_with_sections)

Usage:
    python edisclosure_pilot.py [--dry-run]
"""
import logging
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from browser_session import BrowserSession
from pdf_parser import PDFParser
from edisclosure_store import (
    COMPANY_IDS_PATH,
    load_company_ids,
    load_section_refs,
    save_company_id,
    get_sections_for_emitter,
)
from edisclosure_client import EdisclosureClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

config = Config()

# Emitters to search (from program_numbers.json)
EMITTERS = [
    {"name": "ЭНЕРГОТЕХСЕРВИС", "program_number": "4-00490-R-001P-02E",
     "isins": ["RU000A10ADJ3", "RU000A10BUM9", "RU000A10BVT2", "RU000A10EKX1", "RU000A10ETM5"]},
    {"name": "МВ ФИНАНС", "program_number": "4-00590-R-001P-02E",
     "isins": ["RU000A10BFP3"]},
    {"name": "ТАЛАН-ФИНАНС", "program_number": "4-00416-R-001P-02E",
     "isins": ["RU000A10C5J1"]},
    {"name": "ЭКОНОМЛИЗИНГ", "program_number": "4-00461-R-001P-02E",
     "isins": ["RU000A10B081"]},
    {"name": "ЭКОНОМЛИЗИНГ", "program_number": "4-00461-R-002P-02E",
     "isins": ["RU000A10ERA4", "RU000A10FSV5"]},
    {"name": "РОЛЬФ", "program_number": "4-00406-R-001P-02E",
     "isins": ["RU000A10ASD4", "RU000A10ASE2", "RU000A10BQ60", "RU000A10F850"]},
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="e-disclosure.ru program pilot")
    parser.add_argument("--dry-run", action="store_true", help="Only search, don't download")
    args = parser.parse_args()

    # Load persistent data
    section_refs = load_section_refs()
    company_ids_db = load_company_ids()
    logger.info(f"Loaded section refs for {len(section_refs)} ISINs")
    logger.info(f"Loaded {len(company_ids_db)} known companyIds from {COMPANY_IDS_PATH.name}")

    logger.info("e-disclosure pilot starting (browser launches lazily, on first real search)")
    logger.info("NOTE: If CAPTCHA appears, solve it manually in the browser window")

    download_base = config.base_dir / "downloads" / "edisclosure_programs"
    download_base.mkdir(parents=True, exist_ok=True)

    # Visible browser (manual CAPTCHA solving); lazy — dry-run with a warm
    # company_ids.json cache never touches Playwright at all
    session = BrowserSession(config, delay_range=config.edisclosure_delay, headless=False, lazy=True)
    client = EdisclosureClient(session)
    pdf_parser = PDFParser(config)

    try:
        results = []

        for emitter in EMITTERS:
            name = emitter["name"]
            prog_num = emitter["program_number"]
            isins = emitter["isins"]

            logger.info(f"\n{'='*60}")
            logger.info(f"Emitter: {name} | Program: {prog_num}")
            logger.info(f"ISINs: {', '.join(isins)}")
            logger.info(f"{'='*60}")

            # Step 0: Get sections from decision
            target_sections = get_sections_for_emitter(name, prog_num, section_refs)

            emitter_dir = download_base / name.replace(" ", "_")
            emitter_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Search for company (cache-first; a warm cache never
            # touches the browser — lazy session stays cold in dry-run)
            company_id = client.search_emitter(
                name, isin=isins[0], program_number=prog_num,
                company_ids_db=company_ids_db
            )

            if not company_id:
                logger.warning(f"Could not find companyId for {name}")
                results.append({
                    "emitter": name,
                    "program_number": prog_num,
                    "isins": isins,
                    "target_sections": target_sections,
                    "status": "company_not_found",
                })
                time.sleep(random.uniform(*config.edisclosure_retry_delay))
                continue

            # Save newly found companyId to persistent database
            if name not in company_ids_db:
                save_company_id(company_ids_db, name, company_id)

            logger.info(f"companyId: {company_id}")

            if args.dry_run:
                results.append({
                    "emitter": name,
                    "program_number": prog_num,
                    "company_id": company_id,
                    "isins": isins,
                    "target_sections": target_sections,
                    "status": "dry_run",
                })
                continue

            # Politeness pause between real page visits (cache-only dry-run skips it)
            time.sleep(random.uniform(*config.edisclosure_nav_delay))

            # Step 2: Get files and download
            all_files, program_files, downloaded = client.get_file_list_and_download(
                session.page, company_id, name, prog_num, emitter_dir
            )

            # Step 3: Parse with specific sections
            program_covenants = {}
            for pdf_path_str in downloaded:
                pdf_path = Path(pdf_path_str)
                logger.info(f"\nParsing: {pdf_path.name}")
                logger.info(f"Target sections: {target_sections}")
                events = pdf_parser.parse_program_with_sections(pdf_path, target_sections)
                if events:
                    program_covenants[pdf_path.name] = events

            results.append({
                "emitter": name,
                "program_number": prog_num,
                "company_id": company_id,
                "isins": isins,
                "target_sections": target_sections,
                "total_files": len(all_files),
                "program_files_found": len(program_files),
                "downloaded": [Path(p).name for p in downloaded],
                "program_covenants": program_covenants,
                "status": "parsed" if program_covenants else ("downloaded" if downloaded else "no_program_files"),
            })

            session.human_delay()
            logger.info("Delay done.")

        # Save
        output_path = config.base_dir / "edisclosure_pilot.json"
        with open(output_path, "w", encoding="utf-8") as f:
            import json
            json.dump(results, f, ensure_ascii=False, indent=2)

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"PILOT SUMMARY")
        logger.info(f"{'='*60}")
        total_new = 0
        for r in results:
            cov_count = sum(len(v) for v in r.get("program_covenants", {}).values())
            total_new += cov_count
            logger.info(f"  {r['emitter']} | {r['status']} | company={r.get('company_id', '?')} "
                        f"| sections={r.get('target_sections', [])} "
                        f"| downloaded={len(r.get('downloaded', []))} | covenants={cov_count}")
            for fname, events in r.get("program_covenants", {}).items():
                for ev in events:
                    logger.info(f"    #{ev['event_number']} [{ev['section']}]: {ev['title'][:70]}")

        logger.info(f"\nTotal new covenants from e-disclosure: {total_new}")

    finally:
        session.stop()  # no-op if the lazy session never started

    return results


if __name__ == "__main__":
    main()
