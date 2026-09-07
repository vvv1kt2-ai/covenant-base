"""Pilot: Find program documents on e-disclosure.ru for ISINs without Finam programs.

Workflow:
1. Load known companyIds from company_ids.json (skip search if found)
2. For each emitter: search e-disclosure.ru → find companyId → save to company_ids.json
3. Navigate to file listing (type=7) → find program document (not prospectus!)
4. Download (handle ZIP archives — extract PDFs)
5. Parse the SPECIFIC section referenced by the decision

Usage:
    python edisclosure_pilot.py [--dry-run]
"""
import json
import logging
import random
import re
import sys
import time
import zipfile
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from pdf_parser import PDFParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

config = Config()

# Persistent companyId database
COMPANY_IDS_PATH = config.base_dir / "company_ids.json"

# Program section references (extracted from decisions)
SECTION_REFS_PATH = config.base_dir / "program_section_refs.json"

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

# Fallback sections if not found in decision
FALLBACK_SECTIONS = ["9.5.1", "9.5", "9.4", "9.3", "9.6", "6.5.1", "10.5.1", "10.5"]


def load_company_ids():
    """Load known companyIds from persistent JSON file."""
    if COMPANY_IDS_PATH.exists():
        with open(COMPANY_IDS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_company_id(company_ids_db, name, company_id, source="edisclosure_search"):
    """Save a companyId to the persistent database and to disk."""
    company_ids_db[name] = {
        "company_id": company_id,
        "source": source,
    }
    with open(COMPANY_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(company_ids_db, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved companyId {company_id} for {name} to {COMPANY_IDS_PATH.name}")


def load_section_refs():
    """Load pre-extracted section references from decisions."""
    if SECTION_REFS_PATH.exists():
        with open(SECTION_REFS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_sections_for_emitter(emitter_name, program_number, section_refs):
    """Get the program sections to search, based on decision references."""
    sections = []

    # Look up by any ISIN from this emitter
    for isin_key, ref_data in section_refs.items():
        if ref_data.get("program_number") == program_number:
            for ref in ref_data.get("sections", []):
                sec = ref.get("section")
                if sec and sec not in sections:
                    sections.append(sec)

    if sections:
        logger.info(f"Sections from decision: {sections}")
    else:
        logger.warning(f"No section refs found for {emitter_name}, using fallback: {FALLBACK_SECTIONS[:3]}")
        sections = FALLBACK_SECTIONS[:3]  # Try top 3

    return sections


def is_captcha_page(page):
    """Detect if current page is a CAPTCHA / anti-bot challenge page."""
    try:
        return page.evaluate("""
            () => {
                const body = (document.body ? document.body.innerText : '').toLowerCase();
                const url = window.location.href;
                // e-disclosure.ru challenge page patterns
                const hasBotChallenge = body.includes('не с ботом')
                    || body.includes('разверните картинку')
                    || body.includes('пожалуйста, пройдите проверку')
                    || body.includes('что-то в поведении вашего браузера')
                    || body.includes('prove you are not a robot');
                const isChallengeUrl = url.includes('/xpvnsulc/')
                    || url.includes('/exhkqyad/')
                    || url.includes('challenge');
                const hasCaptchaIframe = document.querySelector('iframe[src*="captcha"]') !== null
                    || document.querySelector('.captcha') !== null
                    || document.querySelector('#captcha') !== null;
                return hasBotChallenge || isChallengeUrl || hasCaptchaIframe;
            }
        """)
    except Exception:
        return False


def check_and_handle_captcha(page, max_wait_seconds=120):
    """Check for CAPTCHA and wait for manual resolution.

    First 15 seconds: wait even if auto-resolved (gives user time to see/solve)
    After 15s: accept auto-resolution
    Returns True if CAPTCHA was detected but NOT resolved (error),
    False if either no CAPTCHA or CAPTCHA was resolved.
    """
    try:
        if not is_captcha_page(page):
            return False

        logger.warning("=" * 60)
        logger.warning("CAPTCHA / ANTI-BOT CHALLENGE DETECTED!")
        logger.warning("Please solve it in the browser window.")
        logger.warning(f"Waiting up to {max_wait_seconds}s...")
        logger.warning("=" * 60)

        MIN_WAIT = 15  # Minimum seconds even if auto-resolved
        start = time.time()

        while time.time() - start < max_wait_seconds:
            time.sleep(3)
            elapsed = time.time() - start

            try:
                still_captcha = is_captcha_page(page)
            except Exception:
                # Navigation happened (page destroyed) — likely resolved
                still_captcha = False

            if not still_captcha:
                if elapsed < MIN_WAIT:
                    logger.info(f"CAPTCHA seems resolved after {elapsed:.0f}s, "
                                f"but waiting {MIN_WAIT - elapsed:.0f}s more for safety...")
                    time.sleep(MIN_WAIT - elapsed)
                logger.info("CAPTCHA resolved! Continuing...")
                try:
                    page.wait_for_load_state("load", timeout=10_000)
                except Exception:
                    pass
                return False

        logger.error("CAPTCHA not resolved within timeout")
        return True

    except Exception as e:
        logger.debug(f"CAPTCHA check error: {e}")

    return False


def wait_for_page_ready(page, target_url_fragment=None, timeout=20_000):
    """Wait for the page to be fully loaded and not on a challenge page."""
    try:
        page.wait_for_load_state("load", timeout=timeout)
    except Exception:
        pass

    # Extra settle for JS
    time.sleep(3)

    # If still on challenge, wait more
    if is_captcha_page(page):
        return False

    return True


def search_emitter_on_edisclosure(page, emitter_name, isin=None, program_number=None, company_ids_db=None):
    """Search e-disclosure.ru for an emitter.

    Strategy:
    1. Check company_ids.json first (persistent database)
    2. Search for ISIN in message text (#textfieldEvent)
    3. Search by program number in message text (#textfieldEvent)
    4. Search by emitter name in company field (#textfieldCompany)
    """
    # Check persistent database first
    if company_ids_db and emitter_name in company_ids_db:
        cid = company_ids_db[emitter_name]["company_id"]
        logger.info(f"Using cached companyId for {emitter_name}: {cid} "
                     f"(source: {company_ids_db[emitter_name].get('source', '?')})")
        return cid

    # Strategy 1: Search by ISIN in message text
    if isin:
        company_id = _search_in_messages(page, isin, f"ISIN {isin}", search_field="event")
        if company_id:
            return company_id

    # Strategy 2: Search by program number in message text
    if program_number:
        company_id = _search_in_messages(page, program_number, f"program {program_number}", search_field="event")
        if company_id:
            return company_id

    # Strategy 3: Search by emitter name in company field
    company_id = _search_in_messages(page, emitter_name, f"name '{emitter_name}'", search_field="company")
    return company_id


def _search_in_messages(page, query, label, search_field="event"):
    """Search https://e-disclosure.ru/poisk-po-soobshheniyam for a query string.

    The page has two visible search fields:
    - #textfieldCompany — "Название компании, руководитель или код" (for company name/INN)
    - #textfieldEvent — "Слова в сообщении или в заголовке:" (for ISIN, keywords)

    search_field: "event" → #textfieldEvent (ISIN, keywords)
                  "company" → #textfieldCompany (company name, INN, OGRN)
    """
    search_url = "https://e-disclosure.ru/poisk-po-soobshheniyam"
    logger.info(f"Searching messages for {label} (field={search_field}): {search_url}")

    try:
        page.goto(search_url, timeout=config.browser_timeout, wait_until="commit")
        try:
            page.wait_for_load_state("load", timeout=20_000)
        except Exception:
            pass
        time.sleep(5)

        # Check for CAPTCHA — wait for manual resolution
        if check_and_handle_captcha(page, max_wait_seconds=120):
            return None

        # After CAPTCHA resolved, page should be on the search page
        logger.info(f"Current URL: {page.url}")
        time.sleep(3)

        # The search form has TWO visible fields:
        # - #textfieldCompany — "Название компании, руководитель или код"
        # - #textfieldEvent — "Слова в сообщении или в заголовке:"
        # We choose based on search_field parameter

        # Clear both fields first
        for fid in ["#textfieldCompany", "#textfieldEvent"]:
            el = page.query_selector(fid)
            if el and el.is_visible():
                el.fill("")
                time.sleep(0.1)

        if search_field == "company":
            target = page.query_selector("#textfieldCompany")
            field_name = "#textfieldCompany"
        else:
            target = page.query_selector("#textfieldEvent")
            field_name = "#textfieldEvent"

        if not target or not target.is_visible():
            logger.warning(f"{field_name} not found or not visible!")
            return None

        logger.info(f"Using {field_name} for search")

        # Type query into the chosen field
        target.click()
        time.sleep(0.3)
        target.fill("")
        time.sleep(0.2)
        target.type(query, delay=50)
        logger.info(f"Typed query: {query}")

        # Click the "Искать" button
        send_btn = page.query_selector("#sendButton")
        if send_btn and send_btn.is_visible():
            send_btn.click()
            logger.info("Clicked #sendButton")
        else:
            # Fallback: press Enter
            search_field.press("Enter")
            logger.info("Pressed Enter (sendButton not found/visible)")

        # Wait for results to load
        time.sleep(5)

        # Check for CAPTCHA again
        if check_and_handle_captcha(page, max_wait_seconds=120):
            return None

        # Wait for page to settle
        try:
            page.wait_for_load_state("load", timeout=10_000)
        except Exception:
            pass
        time.sleep(3)

        logger.info(f"Results URL: {page.url}")

        # Screenshot of results
        try:
            safe_name = re.sub(r'[^\w]', '_', query)[:30]
            page.screenshot(path=str(config.base_dir / "downloads" / f"edisclosure_results_{safe_name}.png"))
        except Exception:
            pass

        # Extract companyId from search results
        company_id = _extract_company_id_from_page(page)
        if company_id:
            logger.info(f"Found companyId {company_id} via message search for {label}")
            return company_id

        # Also check if search redirected to a specific page with companyId
        company_id = _extract_company_id_from_url(page.url)
        if company_id:
            logger.info(f"Found companyId {company_id} from URL after search for {label}")
            return company_id

        # Last resort: dump result page for debugging
        result_body = page.evaluate("""
            () => (document.body ? document.body.innerText : '').substring(0, 1000)
        """)
        logger.warning(f"No companyId found. Result page body:\n{result_body[:500]}")

    except Exception as e:
        logger.warning(f"Message search error for {label}: {e}")

    return None


def _extract_company_id_from_page(page):
    """Extract companyId from the current page — check URL and links."""
    # Check current URL first
    company_id = _extract_company_id_from_url(page.url)
    if company_id:
        return company_id

    # Extract from links on the page
    results = page.evaluate(r"""
        () => {
            const links = document.querySelectorAll('a');
            const results = [];
            for (const link of links) {
                const href = link.href || '';
                const text = link.innerText || '';
                // Match e-disclosure company links: company.aspx?id=NNNN
                // Also: companyprofile, files.aspx, eventdetail, companyId=
                if (href.includes('company.aspx') || href.includes('companyprofile')
                    || href.includes('files.aspx') || href.includes('company-')
                    || href.includes('eventdetail') || href.includes('companyId=')) {
                    const match = href.match(/[?&]id=(\d+)/);
                    if (match) {
                        results.push({id: match[1], text: text.trim().substring(0, 80), href: href});
                    }
                }
            }
            return results;
        }
    """)

    if results:
        # Prefer company profile links over event links
        company_links = [r for r in results if 'company.aspx' in r['href'] or 'companyprofile' in r['href']]
        if company_links:
            logger.info(f"Found {len(company_links)} company links on page")
            for r in company_links[:5]:
                logger.info(f"  id={r['id']} text={r['text'][:60]}")
            return company_links[0]["id"]

        logger.info(f"Found {len(results)} companyId candidates on page")
        for r in results[:5]:
            logger.info(f"  id={r['id']} text={r['text'][:60]} href={r['href'][-60:]}")
        return results[0]["id"]

    return None


def _extract_company_id_from_url(url):
    """Extract companyId from a URL."""
    match = re.search(r'(?:id=|company-|companyId=)(\d+)', url)
    if match:
        return match.group(1)
    return None


def get_file_list_and_download(page, company_id, emitter_name, program_number, download_dir):
    """Navigate to file listing, find and download program files."""
    url = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
    logger.info(f"Opening file listing: {url}")

    try:
        page.goto(url, timeout=config.browser_timeout, wait_until="commit")
        try:
            page.wait_for_load_state("load", timeout=20_000)
        except Exception:
            pass
        time.sleep(5)

        if check_and_handle_captcha(page, max_wait_seconds=120):
            return [], [], []

        time.sleep(8)

        # Screenshot for debug
        screenshot_path = download_dir / f"edisclosure_{company_id}.png"
        try:
            page.screenshot(path=str(screenshot_path))
        except Exception:
            pass

        # Extract file links from e-disclosure table
        # Structure: <table class="files-table"> with rows containing:
        #   doc type | registration # | dates | <a class="file-link" href="FileLoad.ashx?Fileid=XXX">
        files = page.evaluate("""
            () => {
                const results = [];

                // Method 1: file-link class with FileLoad.ashx href (e-disclosure specific)
                const fileLinks = document.querySelectorAll('a.file-link, a[href*="FileLoad"], a[href*="fileid"], a[data-fileid]');
                for (const link of fileLinks) {
                    const href = link.href || '';
                    const linkText = link.innerText || '';
                    const fileId = link.dataset.fileid || link.dataset.fileId || '';
                    // Get full row context (document type, dates, etc.)
                    let rowText = '';
                    let docType = '';
                    const row = link.closest('tr');
                    if (row) {
                        rowText = row.innerText || '';
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 2) {
                            docType = cells[1] ? cells[1].innerText.trim() : '';
                        }
                    }
                    results.push({fileId, linkText: linkText.trim(), href, rowText: rowText.trim(), docType});
                }

                // Method 2: any link with FileLoad in href (fallback)
                if (results.length === 0) {
                    const allLinks = document.querySelectorAll('a');
                    for (const link of allLinks) {
                        const href = link.href || '';
                        const text = link.innerText || '';
                        if (href.includes('FileLoad') || href.includes('fileid') || href.includes('fileId')) {
                            let rowText = '';
                            const row = link.closest('tr');
                            if (row) rowText = row.innerText || '';
                            results.push({fileId: '', linkText: text.trim(), href, rowText: rowText.trim(), docType: ''});
                        }
                    }
                }

                // Method 3: program-related text links (last resort)
                if (results.length === 0) {
                    const allLinks = document.querySelectorAll('a');
                    for (const link of allLinks) {
                        const href = link.href || '';
                        const text = link.innerText || '';
                        const lower = text.toLowerCase();
                        if (lower.includes('программ') || lower.includes('проспект')
                            || (lower.includes('.pdf') && lower.length > 10)
                            || (lower.includes('.zip') && lower.length > 10)) {
                            let rowText = '';
                            const row = link.closest('tr') || link.parentElement;
                            if (row) rowText = row.innerText || '';
                            results.push({fileId: '', linkText: text.trim(), href, rowText: rowText.trim(), docType: ''});
                        }
                    }
                }

                return results;
            }
        """)

        logger.info(f"Found {len(files)} file entries")
        for i, f in enumerate(files[:15]):
            logger.info(f"  [{i}] {f['linkText'][:80]}")

        # Find program documents — ONLY "Программа облигаций", NOT prospectuses/amendments
        # Keywords to EXCLUDE (prospectuses, amendments, changes, etc.)
        EXCLUDE_KEYWORDS = [
            "проспект", "изменени", "дополн", "приложен", "решение",
            "емиссия", "уведомл", "отчет", "аудит", "справк",
        ]
        # Keywords to INCLUDE
        INCLUDE_KEYWORDS = ["программа"]

        program_files = []
        for f in files:
            combined = (f.get("linkText", "") + " " + f.get("rowText", "") + " " + f.get("docType", "")).lower()
            # Match by program number first (highest priority)
            if program_number and program_number in combined:
                program_files.append(f)
                continue
            # Then check if it's a program document
            is_program = any(kw in combined for kw in INCLUDE_KEYWORDS)
            is_excluded = any(kw in combined for kw in EXCLUDE_KEYWORDS)
            if is_program and not is_excluded:
                program_files.append(f)

        # Deduplicate
        seen = set()
        unique = []
        for f in program_files:
            href = f.get("href", "")
            if href and href not in seen:
                seen.add(href)
                unique.append(f)
        program_files = unique

        logger.info(f"Program files: {len(program_files)}")

        # Download
        downloaded = []
        if program_files:
            download_dir.mkdir(parents=True, exist_ok=True)
            for idx, f in enumerate(program_files):
                href = f.get("href", "")
                if not href:
                    continue

                link_text = f.get("linkText", "program")
                safe_name = re.sub(r'[<>:"/\\|?*]', '_', link_text)[:60]

                logger.info(f"Downloading [{idx+1}/{len(program_files)}]: {link_text[:60]}")

                try:
                    resp = page.request.get(href)
                    if resp.ok:
                        data = resp.body()
                        pdfs, saved_path = extract_pdfs_from_bytes(
                            data, download_dir, prefix=f"program_{idx}_{safe_name}"
                        )
                        downloaded.extend(pdfs)
                    else:
                        logger.warning(f"Download failed: HTTP {resp.status}")

                except Exception as e:
                    logger.warning(f"Download failed: {e}")

        return files, program_files, downloaded

    except Exception as e:
        logger.warning(f"File listing error: {e}")
        return [], [], []


def extract_pdfs_from_zip(zip_path):
    """Extract PDF files from a ZIP archive. Returns list of extracted PDF paths."""
    pdfs = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if name.lower().endswith('.pdf'):
                    pdf_dir = zip_path.parent
                    pdf_path = pdf_dir / Path(name).name
                    # Avoid name collisions
                    if pdf_path.exists():
                        stem = pdf_path.stem
                        pdf_path = pdf_dir / f"{stem}_{hash(name) % 10000}.pdf"
                    with open(pdf_path, 'wb') as f:
                        f.write(zf.read(name))
                    pdfs.append(str(pdf_path))
                    logger.info(f"  Extracted from ZIP: {pdf_path.name}")
    except zipfile.BadZipFile:
        logger.warning(f"Bad ZIP file: {zip_path}")
    return pdfs


def extract_pdfs_from_bytes(data, dest_dir, prefix="program"):
    """Extract PDFs from ZIP bytes. If not a ZIP, assume it's a PDF."""
    # Check if it's a ZIP (PK magic bytes)
    if data[:2] == b'PK':
        zip_path = dest_dir / f"{prefix}.zip"
        zip_path.write_bytes(data)
        logger.info(f"  Saved ZIP: {zip_path.name} ({len(data)} bytes)")
        pdfs = extract_pdfs_from_zip(zip_path)
        return pdfs, str(zip_path)
    elif data[:4] == b'%PDF':
        # It's already a PDF
        pdf_path = dest_dir / f"{prefix}.pdf"
        pdf_path.write_bytes(data)
        logger.info(f"  Saved PDF: {pdf_path.name} ({len(data)} bytes)")
        return [str(pdf_path)], str(pdf_path)
    else:
        # Unknown format — save as-is and try
        pdf_path = dest_dir / f"{prefix}.bin"
        pdf_path.write_bytes(data)
        logger.warning(f"  Unknown format ({data[:4]}), saved as: {pdf_path.name}")
        return [], str(pdf_path)


def parse_program_with_sections(pdf_path, target_sections):
    """Parse program PDF focusing on specific sections from the decision."""
    pdf_parser = PDFParser(config)
    result = pdf_parser.parse_decision(pdf_path)

    if result.error:
        logger.warning(f"Parse error: {result.error}")
        return []
    if not result.has_text_layer:
        logger.warning("No text layer")
        return []

    all_events = []

    # Step 1: Try auto-parsed sections that match our targets
    for clause in result.redemption_clauses:
        if clause.is_provided and clause.events:
            # Check if this section matches any target
            for target in target_sections:
                if clause.section and (clause.section.startswith(target) or target.startswith(clause.section)):
                    logger.info(f"  Matched section {clause.section} (target={target}): {len(clause.events)} events")
                    for ev in clause.events:
                        all_events.append({
                            "event_number": ev.event_number,
                            "title": ev.title,
                            "full_text": ev.full_text,
                            "section": clause.section,
                        })
                    break

    # Step 2: If no match, try explicit section search
    if not all_events:
        logger.info("No auto-parsed match, trying explicit section searches...")
        for target in target_sections:
            clause = pdf_parser._find_redemption_clause(result.raw_text, target)
            if clause and clause.is_provided and clause.events:
                logger.info(f"  Found section {target}: {len(clause.events)} events")
                for ev in clause.events:
                    all_events.append({
                        "event_number": ev.event_number,
                        "title": ev.title,
                        "full_text": ev.full_text,
                        "section": target,
                    })
                break

    # Step 3: Also try all auto-parsed sections (in case targets are wrong)
    if not all_events:
        logger.info("Explicit search failed, checking all auto-parsed sections...")
        for clause in result.redemption_clauses:
            if clause.is_provided and clause.events:
                logger.info(f"  Section {clause.section}: {len(clause.events)} events")
                for ev in clause.events:
                    all_events.append({
                        "event_number": ev.event_number,
                        "title": ev.title,
                        "full_text": ev.full_text,
                        "section": clause.section,
                    })

    return all_events


def main():
    import argparse
    parser = argparse.ArgumentParser(description="e-disclosure.ru program pilot")
    parser.add_argument("--dry-run", action="store_true", help="Only search, don't download")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    # Load persistent data
    section_refs = load_section_refs()
    company_ids_db = load_company_ids()
    logger.info(f"Loaded section refs for {len(section_refs)} ISINs")
    logger.info(f"Loaded {len(company_ids_db)} known companyIds from {COMPANY_IDS_PATH.name}")

    logger.info("Starting Playwright for e-disclosure pilot...")
    logger.info("NOTE: If CAPTCHA appears, solve it manually in the browser window")

    download_base = config.base_dir / "downloads" / "edisclosure_programs"
    download_base.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # Visible for CAPTCHA
        context = browser.new_context(
            user_agent=config.browser_user_agent,
            locale=config.browser_locale,
        )
        page = context.new_page()

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

            # Step 1: Search for company (uses company_ids.json cache first)
            company_id = search_emitter_on_edisclosure(
                page, name, isin=isins[0], program_number=prog_num,
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
                time.sleep(random.uniform(10, 20))
                continue

            # Save newly found companyId to persistent database
            if name not in company_ids_db:
                save_company_id(company_ids_db, name, company_id)

            logger.info(f"companyId: {company_id}")
            time.sleep(random.uniform(5, 10))

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

            # Step 2: Get files and download
            all_files, program_files, downloaded = get_file_list_and_download(
                page, company_id, name, prog_num, emitter_dir
            )

            # Step 3: Parse with specific sections
            program_covenants = {}
            for pdf_path_str in downloaded:
                pdf_path = Path(pdf_path_str)
                logger.info(f"\nParsing: {pdf_path.name}")
                logger.info(f"Target sections: {target_sections}")
                events = parse_program_with_sections(pdf_path, target_sections)
                if events:
                    program_covenants[pdf_path.name] = events
                    logger.info(f"  Covenants found: {len(events)}")
                else:
                    logger.info(f"  No covenants found")

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

            delay = random.uniform(15, 30)
            logger.info(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

        # Save
        output_path = config.base_dir / "edisclosure_pilot.json"
        with open(output_path, "w", encoding="utf-8") as f:
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

        browser.close()

    return results


if __name__ == "__main__":
    main()
