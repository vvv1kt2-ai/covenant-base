"""Scale: parse bond PROGRAMS for all ISINs with needs_program_check=True.

For each ISIN:
1. Search on Finam by ISIN/issuer name
2. Get bond card → extract program_url
3. Download program PDF
4. Parse section 9.5.1 for covenants
5. Save results to results_programs.json

Delays: 20-45s between ISINs to avoid Cloudflare/IP blocking.

Usage:
    python parse_programs.py [--dry-run] [--limit N] [--fresh]
"""
import json
import logging
import sys
import time
import random
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from finam_client import FinamClient
from pdf_parser import PDFParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

config = Config()


def main():
    parser = argparse.ArgumentParser(description="Parse bond programs for covenants")
    parser.add_argument("--dry-run", action="store_true", help="Only list ISINs, don't parse")
    parser.add_argument("--limit", type=int, default=0, help="Max ISINs to process (0=all)")
    parser.add_argument("--fresh", action="store_true", help="Start fresh, ignore previous results")
    args = parser.parse_args()

    client = FinamClient(config)
    pdf_parser = PDFParser(config)

    # Load results.json
    results_path = config.base_dir / "results.json"
    with open(results_path, encoding="utf-8") as f:
        data = json.load(f)

    # Load programs results (for resume — always resume unless --fresh)
    programs_path = config.base_dir / "results_programs.json"
    programs_results = []
    if not args.fresh and programs_path.exists():
        with open(programs_path, encoding="utf-8") as f:
            programs_results = json.load(f)
        logger.info(f"Resuming: {len(programs_results)} already processed")

    # Filter ISINs with needs_program_check=True
    needs_program = [r for r in data if r.get("needs_program_check", False)]
    logger.info(f"Total ISINs with needs_program_check: {len(needs_program)}")

    # Skip already processed (resume mode)
    processed_isins = {r["isin"] for r in programs_results}
    if not args.fresh:
        remaining = [r for r in needs_program if r["isin"] not in processed_isins]
        logger.info(f"Already processed: {len(processed_isins)}, remaining: {len(remaining)}")
        needs_program = remaining

    if args.limit > 0:
        needs_program = needs_program[:args.limit]
        logger.info(f"Processing first {args.limit} ISINs")

    if args.dry_run:
        logger.info("DRY RUN - listing ISINs only:")
        for r in needs_program:
            logger.info(f"  {r['isin']} | {r['issuer']} | covenants={r.get('total_covenants', 0)}")
        return

    # Ensure downloads directory
    programs_downloads = config.base_dir / "downloads" / "programs"
    programs_downloads.mkdir(parents=True, exist_ok=True)

    stats = {
        "total": len(needs_program),
        "found_on_finam": 0,
        "has_program": 0,
        "program_downloaded": 0,
        "program_parsed": 0,
        "new_covenants": 0,
        "errors": 0,
        "no_program_url": 0,
    }

    try:
        client.start()
        time.sleep(10)

        for i, entry in enumerate(needs_program):
            isin = entry["isin"]
            issuer = entry.get("issuer", "")
            existing_covenants = entry.get("total_covenants", 0)

            logger.info(f"{'='*60}")
            logger.info(f"[{i+1}/{len(needs_program)}] {isin} | {issuer} | existing={existing_covenants}")
            logger.info(f"{'='*60}")

            # Step 1: Search on Finam
            hex_code = client.search_by_isin(isin, issuer)
            if not hex_code:
                logger.warning(f"NOT FOUND on Finam: {isin}")
                stats["errors"] += 1
                programs_results.append({
                    "isin": isin,
                    "issuer": issuer,
                    "status": "not_found_on_finam",
                    "new_covenants": [],
                    "total_new": 0,
                })
                # Delay between ISINs
                client.session.human_delay()
                continue

            stats["found_on_finam"] += 1

            # Step 2: Get bond card
            card = client.get_bond_card(isin, hex_code)
            if not card:
                logger.warning(f"Failed to get card for {isin}")
                stats["errors"] += 1
                programs_results.append({
                    "isin": isin,
                    "issuer": issuer,
                    "status": "card_error",
                    "new_covenants": [],
                    "total_new": 0,
                })
                client.session.human_delay()
                continue

            if not card.program_url:
                logger.info(f"No program URL on Finam card for {isin}")
                stats["no_program_url"] += 1
                programs_results.append({
                    "isin": isin,
                    "issuer": issuer,
                    "hex_code": hex_code,
                    "status": "no_program_url",
                    "new_covenants": [],
                    "total_new": 0,
                })
                client.session.human_delay()
                continue

            stats["has_program"] += 1
            logger.info(f"Program URL: {card.program_url}")

            # Step 3: Download program PDF
            isin_dir = config.isin_download_dir(isin)
            program_url = card.program_url.replace("\\", "/")
            filename = program_url.split("/")[-1].split("?")[0]
            program_path = isin_dir / filename

            if not program_path.exists():
                logger.info(f"Downloading program...")
                success = client.download_file(program_url, program_path)
                if not success or not program_path.exists():
                    logger.warning(f"Failed to download program for {isin}")
                    stats["errors"] += 1
                    programs_results.append({
                        "isin": isin,
                        "issuer": issuer,
                        "hex_code": hex_code,
                        "program_url": card.program_url,
                        "status": "download_error",
                        "new_covenants": [],
                        "total_new": 0,
                    })
                    client.session.human_delay()
                    continue
            else:
                logger.info(f"Program already downloaded: {filename}")

            stats["program_downloaded"] += 1

            # Step 4: Parse program PDF
            logger.info(f"Parsing program PDF...")
            result = pdf_parser.parse_decision(program_path)

            if result.error:
                logger.warning(f"Parse error: {result.error}")
                stats["errors"] += 1
                programs_results.append({
                    "isin": isin,
                    "issuer": issuer,
                    "hex_code": hex_code,
                    "program_url": card.program_url,
                    "status": "parse_error",
                    "error": result.error,
                    "new_covenants": [],
                    "total_new": 0,
                })
                client.session.human_delay()
                continue

            if not result.has_text_layer:
                logger.warning("No text layer in program PDF")
                stats["errors"] += 1
                programs_results.append({
                    "isin": isin,
                    "issuer": issuer,
                    "hex_code": hex_code,
                    "program_url": card.program_url,
                    "status": "no_text_layer",
                    "new_covenants": [],
                    "total_new": 0,
                })
                client.session.human_delay()
                continue

            # Step 4b: Try section 9.5.1 explicitly
            program_events = []

            # Check parsed sections
            for clause in result.redemption_clauses:
                if clause.section == "9.5.1" and clause.is_provided:
                    for ev in clause.events:
                        program_events.append({
                            "event_number": ev.event_number,
                            "title": ev.title,
                            "full_text": ev.full_text,
                            "section": "9.5.1",
                        })
                        logger.info(f"  §9.5.1 #{ev.event_number}: {ev.title[:80]}")

            # If no 9.5.1 found, try explicit search
            if not program_events:
                logger.info("Trying section 9.5.1 explicitly...")
                for section_num in ["9.5.1", "9.5"]:
                    clause = pdf_parser.find_redemption_clause(result.raw_text, section_num)
                    if clause and clause.is_provided:
                        for ev in clause.events:
                            program_events.append({
                                "event_number": ev.event_number,
                                "title": ev.title,
                                "full_text": ev.full_text,
                                "section": section_num,
                            })
                            logger.info(f"  §{section_num} #{ev.event_number}: {ev.title[:80]}")
                        break

            if not program_events:
                logger.info("No covenants found in program section 9.5.1")

            stats["program_parsed"] += 1
            stats["new_covenants"] += len(program_events)

            programs_results.append({
                "isin": isin,
                "issuer": issuer,
                "hex_code": hex_code,
                "program_url": card.program_url,
                "program_pdf": filename,
                "status": "parsed",
                "new_covenants": program_events,
                "total_new": len(program_events),
            })

            # Save intermediate results every 5 ISINs
            if (i + 1) % 5 == 0:
                with open(programs_path, "w", encoding="utf-8") as f:
                    json.dump(programs_results, f, ensure_ascii=False, indent=2)
                logger.info(f"Intermediate save: {len(programs_results)} results")

            # Delay between ISINs
            delay_range = client.session.delay_range
            delay = random.uniform(*delay_range)
            logger.info(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

    except KeyboardInterrupt:
        logger.warning("Interrupted! Saving partial results...")
    finally:
        client.stop()

        # Save final results
        with open(programs_path, "w", encoding="utf-8") as f:
            json.dump(programs_results, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(programs_results)} results to {programs_path}")

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total ISINs: {stats['total']}")
    logger.info(f"Found on Finam: {stats['found_on_finam']}")
    logger.info(f"Has program URL: {stats['has_program']}")
    logger.info(f"No program URL: {stats['no_program_url']}")
    logger.info(f"Program downloaded: {stats['program_downloaded']}")
    logger.info(f"Program parsed: {stats['program_parsed']}")
    logger.info(f"New covenants from programs: {stats['new_covenants']}")
    logger.info(f"Errors: {stats['errors']}")

    # List ISINs with new covenants
    new_cov = [r for r in programs_results if r.get("total_new", 0) > 0]
    if new_cov:
        logger.info(f"\nISINs with NEW covenants from programs ({len(new_cov)}):")
        for r in new_cov:
            logger.info(f"  {r['isin']} | {r['issuer']}: +{r['total_new']}")
            for ev in r["new_covenants"]:
                logger.info(f"    #{ev['event_number']}: {ev['title'][:80]}")
    else:
        logger.info("\nNo new covenants found in programs")


if __name__ == "__main__":
    main()
