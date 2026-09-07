"""Pilot: download and parse bond PROGRAM PDFs for covenants.

For ISINs where the decision references the program (section 9.5.1),
download the program and check for additional covenants.

Usage:
    python pilot_programs.py
"""
import json
import logging
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from finam_client import FinamClient
from pdf_parser import PDFParser

# Pilot ISINs: need to check programs for additional covenants
PILOT_ISINS = [
    "RU000A109LC8",  # РОЛЬФ-001Р-03 (2 covenants in decision, program may have more)
    "RU000A10ADJ3",  # ЭНЕРГОТЕХСЕРВИС-001Р-06 (1 covenant)
    "RU000A105M59",  # РОДЕЛЕН-001Р-03 (1 covenant)
    "RU000A10BFP3",  # МВ ФИНАНС-001Р-06 (0 covenants, Type B - program-only)
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

config = Config()


def main():
    client = FinamClient(config)
    parser = PDFParser(config)

    with open(config.base_dir / "results.json", encoding="utf-8") as f:
        data = json.load(f)

    try:
        client.start()
        time.sleep(2)  # Extra delay before first request

        for isin in PILOT_ISINS:
            logger.info(f"{'='*60}")
            logger.info(f"PILOT: {isin}")
            logger.info(f"{'='*60}")

            # Get existing result
            existing = next((r for r in data if r["isin"] == isin), None)
            if not existing:
                logger.warning(f"ISIN {isin} not found in results.json")
                continue

            logger.info(f"Issuer: {existing.get('issuer', '?')}")
            logger.info(f"Decision covenants: {existing.get('total_covenants', 0)}")

            # Search for ISIN to get hex_code (pass issuer name as fallback match)
            issuer_name = existing.get('issuer', '')
            hex_code = client.search_by_isin(isin, issuer_name)
            if not hex_code:
                # Fallback: search by issuer name directly
                logger.info(f"ISIN search failed, trying by issuer name: {issuer_name}")
                hex_code = client.search_by_name(issuer_name)
            if not hex_code:
                logger.warning(f"ISIN {isin} not found on Finam")
                continue

            # Get bond card (includes program_url)
            card = client.get_bond_card(isin, hex_code)
            if not card:
                logger.warning(f"Failed to get card for {isin}")
                continue

            if not card.program_url:
                logger.warning(f"No program URL for {isin}")
                continue

            logger.info(f"Program URL: {card.program_url}")

            # Download program PDF
            isin_dir = config.isin_download_dir(isin)
            program_url = card.program_url.replace("\\", "/")

            filename = program_url.split("/")[-1].split("?")[0]
            program_path = isin_dir / filename

            if not program_path.exists():
                logger.info(f"Downloading program...")
                success = client.download_file(program_url, program_path)
                if not success or not program_path.exists():
                    logger.warning(f"Failed to download program for {isin}")
                    continue
            else:
                logger.info(f"Program already downloaded: {filename}")

            # Parse program PDF
            logger.info(f"Parsing program PDF...")
            result = parser.parse_decision(program_path)

            if result.error:
                logger.warning(f"Parse error: {result.error}")
                continue

            if not result.has_text_layer:
                logger.warning("No text layer in program PDF")
                continue

            logger.info(f"Redemption clauses found: {len(result.redemption_clauses)}")

            for clause in result.redemption_clauses:
                logger.info(f"  Section {clause.section}: is_provided={clause.is_provided}, events={len(clause.events)}")
                for ev in clause.events:
                    logger.info(f"    #{ev.event_number}: {ev.title[:100]}")
                    logger.info(f"      quote: {ev.full_text[:150]}...")

            # Also try section 9.5.1 specifically
            if not any(cl.section == "9.5.1" for cl in result.redemption_clauses):
                # Try parsing with explicit section hint
                logger.info("Trying section 9.5.1 explicitly...")
                for section_num in ["9.5.1", "9.5"]:
                    clause = parser._find_redemption_clause(result.raw_text, section_num)
                    if clause:
                        logger.info(f"  Found section {section_num}: is_provided={clause.is_provided}, events={len(clause.events)}")
                        for ev in clause.events:
                            logger.info(f"    #{ev.event_number}: {ev.title[:100]}")
                            logger.info(f"      quote: {ev.full_text[:150]}...")
                        break

            # Pause between ISINs
            delay = random.uniform(5, 10)
            logger.info(f"Waiting {delay:.1f}s before next ISIN...")
            time.sleep(delay)

    finally:
        client.stop()


if __name__ == "__main__":
    main()
