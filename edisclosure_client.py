"""e-disclosure.ru client: company search, file listing, downloads.

Owns every page interaction with e-disclosure.ru: the three-strategy
companyId search, the type=7 file listing with program-file filtering,
and ZIP/PDF extraction. Holds no module-level config — everything comes
from the (lazy) BrowserSession, so the client is testable with a fake.

Pure helpers (filter_program_files, extract_pdfs_from_*, _extract_company_id_*)
never touch a page.
"""
import logging
import re
import time
import zipfile
from pathlib import Path

from browser_session import EDISCLOSURE_CAPTCHA, wait_captcha_resolved

logger = logging.getLogger(__name__)

SEARCH_URL = "https://e-disclosure.ru/poisk-po-soobshheniyam"

# Program document keywords: match "Программа облигаций", exclude
# prospectuses/amendments/reports and other non-program documents
INCLUDE_KEYWORDS = ["программа"]
EXCLUDE_KEYWORDS = [
    "проспект", "изменени", "дополн", "приложен", "решение",
    "емиссия", "уведомл", "отчет", "аудит", "справк",
]


# ---------------------------------------------------------------------------
# CAPTCHA wrappers (delegates to the shared detectors/loop)
# ---------------------------------------------------------------------------

def is_captcha_page(page):
    """Detect if current page is a CAPTCHA / anti-bot challenge page."""
    return EDISCLOSURE_CAPTCHA.detect(page)


def check_and_handle_captcha(page, max_wait_seconds=120):
    """Check for CAPTCHA and wait for manual resolution.

    Delegates to the shared wait loop (min 15s even after auto-resolution).
    Returns True if CAPTCHA was detected but NOT resolved (error),
    False if either no CAPTCHA or CAPTCHA was resolved.
    """
    if not EDISCLOSURE_CAPTCHA.detect(page):
        return False

    logger.warning("=" * 60)
    logger.warning("CAPTCHA / ANTI-BOT CHALLENGE DETECTED!")
    logger.warning("Please solve it in the browser window.")
    logger.warning(f"Waiting up to {max_wait_seconds}s...")
    logger.warning("=" * 60)

    return not wait_captcha_resolved(
        page, EDISCLOSURE_CAPTCHA,
        timeout_seconds=max_wait_seconds,
        min_wait=15,
    )


# ---------------------------------------------------------------------------
# Pure helpers (no page interaction)
# ---------------------------------------------------------------------------

def extract_company_id_from_url(url):
    """Extract companyId from a URL."""
    match = re.search(r'(?:id=|company-|companyId=)(\d+)', url)
    return match.group(1) if match else None


def filter_program_files(files, program_number=None):
    """Pick program documents out of a file-listing dump.

    files: list of dicts {fileId, linkText, href, rowText, docType} as
    extracted by EdisclosureClient.get_file_list_and_download.

    Priority: match by program number first, then include/exclude keywords.
    Deduplicates by href.
    """
    program_files = []
    for f in files:
        combined = (f.get("linkText", "") + " " + f.get("rowText", "") + " " + f.get("docType", "")).lower()
        # Match by program number first (highest priority). Case-insensitive:
        # numbers like 4-00490-R-001P-02E carry uppercase R/P while the page
        # text is lowercased above.
        if program_number and program_number.lower() in combined:
            program_files.append(f)
            continue
        # Then check if it's a program document
        is_program = any(kw in combined for kw in INCLUDE_KEYWORDS)
        is_excluded = any(kw in combined for kw in EXCLUDE_KEYWORDS)
        if is_program and not is_excluded:
            program_files.append(f)

    # Deduplicate by href
    seen = set()
    unique = []
    for f in program_files:
        href = f.get("href", "")
        if href and href not in seen:
            seen.add(href)
            unique.append(f)
    return unique


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


# ---------------------------------------------------------------------------
# Page-level client
# ---------------------------------------------------------------------------

class EdisclosureClient:
    """Page interactions with e-disclosure.ru over a BrowserSession."""

    def __init__(self, session):
        self.session = session

    @property
    def config(self):
        return self.session.config

    # -- company search -----------------------------------------------------

    def search_emitter(self, emitter_name, isin=None, program_number=None, company_ids_db=None):
        """Find a companyId for an emitter. Cache-first; the browser starts
        only on a cache miss (lazy session)."""
        # Check persistent database first
        if company_ids_db and emitter_name in company_ids_db:
            cid = company_ids_db[emitter_name]["company_id"]
            logger.info(f"Using cached companyId for {emitter_name}: {cid} "
                        f"(source: {company_ids_db[emitter_name].get('source', '?')})")
            return cid

        # Cache missed — a real search follows, browser starts here on first use
        page = self.session.page

        # Strategy 1: Search by ISIN in message text
        if isin:
            company_id = self._search_in_messages(page, isin, f"ISIN {isin}", search_field="event")
            if company_id:
                return company_id

        # Strategy 2: Search by program number in message text
        if program_number:
            company_id = self._search_in_messages(page, program_number, f"program {program_number}", search_field="event")
            if company_id:
                return company_id

        # Strategy 3: Search by emitter name in company field
        return self._search_in_messages(page, emitter_name, f"name '{emitter_name}'", search_field="company")

    def _search_in_messages(self, page, query, label, search_field="event"):
        """Search the e-disclosure message-search page for a query string.

        The page has two visible search fields:
        - #textfieldCompany — company name / INN
        - #textfieldEvent — words in message text (ISIN, keywords)

        search_field: "event" → #textfieldEvent
                      "company" → #textfieldCompany
        """
        logger.info(f"Searching messages for {label} (field={search_field}): {SEARCH_URL}")

        try:
            page.goto(SEARCH_URL, timeout=self.config.browser_timeout, wait_until="commit")
            try:
                page.wait_for_load_state("load", timeout=20_000)
            except Exception:
                pass
            time.sleep(5)

            # Check for CAPTCHA — wait for manual resolution
            if check_and_handle_captcha(page, max_wait_seconds=120):
                return None

            logger.info(f"Current URL: {page.url}")
            time.sleep(3)

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
                # Fallback: press Enter in the search field itself
                target.press("Enter")
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
                page.screenshot(path=str(self.config.base_dir / "downloads" / f"edisclosure_results_{safe_name}.png"))
            except Exception:
                pass

            # Extract companyId from search results
            company_id = self._extract_company_id_from_page(page)
            if company_id:
                logger.info(f"Found companyId {company_id} via message search for {label}")
                return company_id

            # Also check if search redirected to a specific page with companyId
            company_id = extract_company_id_from_url(page.url)
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

    def _extract_company_id_from_page(self, page):
        """Extract companyId from the current page — check URL and links."""
        # Check current URL first
        company_id = extract_company_id_from_url(page.url)
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

    # -- file listing / download ---------------------------------------------

    def get_file_list_and_download(self, page, company_id, emitter_name, program_number, download_dir):
        """Navigate to file listing, find and download program files."""
        url = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
        logger.info(f"Opening file listing: {url}")

        try:
            page.goto(url, timeout=self.config.browser_timeout, wait_until="commit")
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
            files = page.evaluate(self._FILE_LINKS_JS)

            logger.info(f"Found {len(files)} file entries")
            for i, f in enumerate(files[:15]):
                logger.info(f"  [{i}] {f['linkText'][:80]}")

            program_files = filter_program_files(files, program_number)
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

    _FILE_LINKS_JS = r"""
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
    """
