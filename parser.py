"""Main parser pipeline for bond emission documents."""
import argparse
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from config import Config
from covenant_models import ResultEntry, build_covenant, load_results, save_results
from finam_client import FinamClient, BondCard
from pdf_parser import PDFParser, DocumentParseResult


def setup_logging(log_dir: Path, verbose: bool = False):
    """Set up logging to file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"parser_{datetime.now():%Y%m%d_%H%M%S}.log"

    level = logging.DEBUG if verbose else logging.INFO

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    ))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Silence noisy third-party loggers
    for noisy in ["httpcore", "httpx", "playwright", "asyncio", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file


def load_isin_list(csv_path: Path) -> list:
    """Load ISIN codes from CSV file (one per line or from a column)."""
    isins = []

    if not csv_path.exists():
        raise FileNotFoundError(f"ISIN file not found: {csv_path}")

    text = csv_path.read_text(encoding="utf-8-sig")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in lines:
        if line.lower().startswith("isin") and len(line) < 10:
            continue
        if "," in line or "\t" in line or ";" in line:
            parts = re.split(r"[,;\t]", line)
            for part in parts:
                part = part.strip().strip('"').strip("'")
                if _is_valid_isin(part):
                    isins.append(part)
                    break
        elif _is_valid_isin(line):
            isins.append(line)

    logging.info(f"Loaded {len(isins)} ISINs from {csv_path.name}")
    return isins


def _is_valid_isin(s: str) -> bool:
    """Check if a string looks like a valid ISIN."""
    return bool(re.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", s.upper()))


def download_pdf(client, url, dest_dir, filename=None):
    """Download a PDF/ZIP file and return the path."""
    if not url:
        return None

    # Fix backslashes in URL
    url = url.replace("\\", "/")

    if not filename:
        filename = url.split("/")[-1].split("?")[0]

    dest_path = dest_dir / filename

    if dest_path.exists():
        logging.info(f"Already downloaded: {filename}")
        return dest_path

    success = client.download_file(url, dest_path)
    if success:
        return dest_path
    return None


def unzip_if_needed(pdf_path):
    """If the file is a ZIP, extract the first PDF from it."""
    if not pdf_path or not pdf_path.exists():
        return None

    if pdf_path.suffix.lower() == ".zip":
        import zipfile
        extract_dir = pdf_path.parent / "extracted"
        extract_dir.mkdir(exist_ok=True)

        try:
            with zipfile.ZipFile(pdf_path, "r") as zf:
                pdf_files = [f for f in zf.namelist() if f.lower().endswith(".pdf")]
                if pdf_files:
                    zf.extract(pdf_files[0], extract_dir)
                    extracted = extract_dir / pdf_files[0]
                    logging.info(f"Extracted {pdf_files[0]} from ZIP")
                    return extracted
                else:
                    logging.warning(f"No PDF files found in ZIP: {pdf_path.name}")
                    return None
        except Exception as e:
            logging.error(f"Failed to extract ZIP {pdf_path.name}: {e}")
            return None

    return pdf_path



def process_isin(isin, client, pdf_parser, config):
    """Process a single ISIN: search, download, parse."""
    logger = logging.getLogger(__name__)
    logger.info(f"{'='*60}")
    logger.info(f"Processing ISIN: {isin}")
    logger.info(f"{'='*60}")

    result = ResultEntry(isin=isin)

    try:
        # Step 1: Search for ISIN
        hex_code = client.search_by_isin(isin)
        if not hex_code:
            result.parse_errors.append(f"ISIN {isin} not found on Finam")
            logger.warning(f"ISIN {isin} not found")
            return result

        # Step 2: Get bond card
        card = client.get_bond_card(isin, hex_code)
        if not card:
            result.parse_errors.append(f"Failed to load bond card for {isin}")
            return result

        result.issuer = card.issuer
        result.issue_name = card.issue_name
        result.rating = card.rating
        result.decision_url = card.decision_url or ""

        # Step 3: Download decision PDF
        isin_dir = config.isin_download_dir(isin)
        decision_path = download_pdf(client, card.decision_url, isin_dir, "decision.pdf")
        if decision_path:
            decision_path = unzip_if_needed(decision_path)
            result.decision_pdf = decision_path.name if decision_path else ""

        if not decision_path:
            result.parse_errors.append(f"Failed to download decision PDF for {isin}")
            return result

        # Step 4: Parse decision PDF
        logger.info(f"Parsing decision PDF: {decision_path.name}")
        doc_result = pdf_parser.parse_decision(decision_path)

        if not doc_result.has_text_layer:
            result.parse_errors.append(f"No text layer in decision PDF for {isin}")
            return result

        if doc_result.error:
            result.parse_errors.append(doc_result.error)

        # Process redemption clauses
        for clause in doc_result.redemption_clauses:
            # Skip if no real covenants (only federal law / "не предусмотрена")
            if clause.has_federal_law_only and not clause.events:
                note = ""
                if clause.needs_program_check:
                    note = " (ссылка на Программу — проверить вручную)"
                    result.needs_program_check = True
                logger.info(f"  {isin}: 0 covenants{note}")
                continue

            if clause.events:
                for event in clause.events:
                    result.add_covenant(build_covenant(clause=clause, event=event))
            else:
                result.add_covenant(build_covenant(clause=clause))

        logger.info(
            f"Completed {isin}: {result.total_covenants} covenants found, "
            f"{len(result.parse_errors)} errors"
        )

    except Exception as e:
        error_msg = f"Unexpected error processing {isin}: {e}"
        logger.error(error_msg)
        result.parse_errors.append(error_msg)

    return result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Parse bond emission documents from Finam",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", help="Path to CSV file with ISIN codes")
    parser.add_argument("--output", "-o", default="results.json", help="Output JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--retry-errors", action="store_true", help="Retry only ISINs with errors")
    parser.add_argument("--no-headless", action="store_true", help="Run browser in visible mode")
    parser.add_argument("--isin", help="Process a single ISIN")
    parser.add_argument("--limit", "-l", type=int, help="Limit number of ISINs to process")
    parser.add_argument("--resume", action="store_true", help="Skip already successfully processed ISINs")

    args = parser.parse_args()

    if not args.input and not args.isin:
        parser.error("Either --input or --isin is required")

    config = Config()
    if args.no_headless:
        config.browser_headless = False

    log_file = setup_logging(config.logs_dir, args.verbose)
    logger = logging.getLogger(__name__)
    logger.info(f"Log file: {log_file}")

    if args.isin:
        isins = [args.isin.upper()]
    elif args.retry_errors and not args.input:
        # --retry-errors without --input: load error ISINs from results.json
        output_path = Path(args.output)
        if output_path.exists():
            existing = load_results(output_path)
            isins = [r.isin for r in existing if r.parse_errors]
            logger.info(f"Retry mode: loaded {len(isins)} error ISINs from {args.output}")
        else:
            logger.error("--retry-errors without --input requires existing results.json")
            sys.exit(1)
    else:
        isins = load_isin_list(Path(args.input))

    if not isins:
        logger.error("No ISINs to process")
        sys.exit(1)

    if args.limit and len(isins) > args.limit:
        logger.info(f"Limiting to first {args.limit} ISINs (from {len(isins)})")
        isins = isins[:args.limit]

    output_path = Path(args.output)
    existing_results = []
    processed_isins = set()

    # Resume mode: load existing results, skip already-processed ISINs
    if args.resume and output_path.exists():
        try:
            for r in load_results(output_path):
                # Skip ISINs that were processed without fatal errors
                if not r.parse_errors or r.total_covenants > 0:
                    processed_isins.add(r.isin)
                    existing_results.append(r)
            logger.info(f"Resume mode: {len(processed_isins)} ISINs already processed, will skip them")
        except Exception as e:
            logger.warning(f"Failed to load existing results for resume: {e}")

    if args.retry_errors and output_path.exists():
        try:
            error_isins = {r.isin for r in load_results(output_path) if r.parse_errors}
            isins = [i for i in isins if i in error_isins]
            logger.info(f"Retry mode: {len(isins)} ISINs with errors to retry")
        except Exception as e:
            logger.warning(f"Failed to load existing results: {e}")

    # Filter out already processed ISINs
    if processed_isins:
        before = len(isins)
        isins = [i for i in isins if i not in processed_isins]
        logger.info(f"Skipping {before - len(isins)} already-processed ISINs, {len(isins)} remaining")

    pdf_parser = PDFParser(config)
    client = FinamClient(config)

    results = list(existing_results) if existing_results else []
    start_time = time.time()

    try:
        client.start()

        for idx, isin in enumerate(isins, 1):
            logger.info(f"\n[{idx}/{len(isins)}] Processing {isin}...")
            result = process_isin(isin, client, pdf_parser, config)
            results.append(result)

            if idx % 10 == 0:
                save_results(output_path, results)
                logger.info(f"Progress: {idx}/{len(isins)} ISINs processed")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        client.stop()

    save_results(output_path, results)

    elapsed = time.time() - start_time
    total = len(results)
    errors = sum(1 for r in results if r.parse_errors)
    found = sum(1 for r in results if r.total_covenants > 0)

    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total ISINs: {total}")
    logger.info(f"With covenants: {found}")
    logger.info(f"With errors: {errors}")
    if total:
        logger.info(f"Time: {elapsed:.1f}s ({elapsed/total:.1f}s per ISIN)")
    logger.info(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
