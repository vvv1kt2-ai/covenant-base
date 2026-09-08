"""Client for bonds.finam.ru using Playwright to bypass ServicePipe."""
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from playwright.sync_api import Page

from config import Config
from browser_session import BrowserSession, FINAM_CAPTCHA, wait_captcha_resolved

logger = logging.getLogger(__name__)


@dataclass
class BondCard:
    """Parsed bond card data."""
    isin: str
    hex_code: str
    issuer: str
    issue_name: str
    rating: str
    decision_url: Optional[str] = None
    program_url: Optional[str] = None
    card_url: Optional[str] = None


try:
    import httpx as _httpx
except ImportError:
    _httpx = None


class FinamClient:
    """Manages Playwright browser session for bonds.finam.ru."""

    def __init__(self, config: Config):
        self.config = config
        self.session = BrowserSession(config, delay_range=config.finam_delay)
        self._consecutive_errors = 0

    @property
    def _page(self) -> Page:
        return self.session.page

    def start(self):
        """Launch browser and create context (delegates to the shared session)."""
        self.session.start()

    def stop(self):
        """Clean shutdown (delegates to the shared session)."""
        self.session.stop()

    def _random_delay(self):
        """Sleep for a random duration between the configured Finam delay range."""
        self.session.human_delay()

    def _check_block(self):
        """If consecutive errors hit the threshold, pause and warn."""
        if self._consecutive_errors >= self.config.max_consecutive_errors:
            cooldown = self.config.block_cooldown_seconds
            logger.warning(
                f"Possible IP block detected ({self._consecutive_errors} consecutive errors). "
                f"Pausing for {cooldown}s ({cooldown//60} min). "
                f"Tip: disconnect VPN or wait."
            )
            time.sleep(cooldown)
            self._consecutive_errors = 0  # reset after cooldown

    def _handle_block(self):
        """Explicitly handle a block detection — long pause + restart browser."""
        cooldown = self.config.block_cooldown_seconds
        logger.error(
            f"BLOCK DETECTED: {self._consecutive_errors} consecutive connection errors. "
            f"Finam likely blocked this IP. Pausing for {cooldown}s ({cooldown//60} min). "
            f"If this persists, disconnect VPN or wait longer."
        )
        time.sleep(cooldown)
        # Restart browser after cooldown — connection may be stale
        logger.info("Restarting browser after block cooldown...")
        self.stop()
        self.start()
        self._consecutive_errors = 0

    def _wait_for_servicepipe(self, timeout_ms: int = None):
        """Wait for ServicePipe JS challenge to complete and page to fully load."""
        timeout = timeout_ms or self.config.browser_timeout
        start_time = time.time()

        logger.info(f"Waiting for ServicePipe challenge (timeout {timeout/1000:.0f}s)...")

        # Phase 1: Wait for challenge to complete
        challenge_passed = False
        while time.time() - start_time < timeout / 1000:
            try:
                content = self._page.content()
                has_spinner = "id_spinner" in content
                has_challenge = "servicepipe" in content.lower() or "checkjs" in content.lower()

                if not has_spinner and not has_challenge:
                    logger.info("ServicePipe challenge completed")
                    challenge_passed = True
                    break

            except Exception as e:
                logger.debug(f"Check error: {e}")

            time.sleep(0.5)

        if not challenge_passed:
            logger.error(f"ServicePipe challenge not completed within {timeout/1000:.0f}s")

        # Phase 2: Wait for page content to load (AJAX/JS rendering)
        logger.info("Waiting for page content to fully load...")
        time.sleep(3)

        # Try to wait for specific elements
        try:
            # Wait for any table or link to appear
            self._page.wait_for_function(
                """() => {
                    return document.querySelectorAll('a').length > 5 ||
                           document.querySelectorAll('table').length > 1;
                }""",
                timeout=10000,
            )
            logger.info("Page content loaded successfully")
        except Exception as e:
            logger.debug(f"Wait for content: {e}")

        time.sleep(1)

    def search_by_isin(self, isin: str, issuer_name: str = "") -> Optional[str]:
        """
        Search for a bond by ISIN and return the hex code from the card URL.
        Returns None if not found.
        Retries up to 3 times. Handles IP blocking with cooldown.

        If issuer_name is provided, it's used as a secondary match criterion.
        """
        # Check if we're potentially blocked
        self._check_block()

        url = f"{self.config.finam_search_url}?emitterCustomName={isin}"
        logger.info(f"Searching for ISIN {isin}: {url}")

        try:
            self._page.goto(url, timeout=self.config.browser_timeout, wait_until="domcontentloaded")
        except Exception as e:
            error_str = str(e).lower()
            if "timed_out" in error_str or "err_connection" in error_str or "err_aborted" in error_str:
                self._consecutive_errors += 1
                logger.warning(
                    f"Connection error for ISIN {isin} "
                    f"(consecutive: {self._consecutive_errors}): {e}"
                )
                if self._consecutive_errors >= self.config.max_consecutive_errors:
                    self._handle_block()
                return None
            raise

        self._wait_for_servicepipe()

        if self._check_captcha():
            logger.warning("CAPTCHA detected during search. Waiting for manual resolution...")
            self._wait_for_captcha_resolution()

        for attempt in range(3):
            hex_code = self._extract_hex_code_from_results(isin, issuer_name)

            if hex_code:
                logger.info(f"Found hex code {hex_code} for ISIN {isin}")
                self._consecutive_errors = 0  # reset on success
                self._random_delay()
                return hex_code

            if attempt < 2:
                logger.info(f"No results on attempt {attempt+1}, retrying (reload page)...")
                time.sleep(3)

        logger.warning(f"No results found for ISIN {isin}")
        self._random_delay()
        return None

    def search_by_name(self, name: str) -> Optional[str]:
        """
        Search for a bond by issuer name and return the hex code from the card URL.
        Returns None if not found.
        Retries up to 3 times. Handles IP blocking with cooldown.
        """
        self._check_block()

        url = f"{self.config.finam_search_url}?emitterCustomName={name}"
        logger.info(f"Searching by name '{name}': {url}")

        try:
            self._page.goto(url, timeout=self.config.browser_timeout, wait_until="domcontentloaded")
        except Exception as e:
            error_str = str(e).lower()
            if "timed_out" in error_str or "err_connection" in error_str or "err_aborted" in error_str:
                self._consecutive_errors += 1
                logger.warning(
                    f"Connection error for name search '{name}' "
                    f"(consecutive: {self._consecutive_errors}): {e}"
                )
                if self._consecutive_errors >= self.config.max_consecutive_errors:
                    self._handle_block()
                return None
            raise

        self._wait_for_servicepipe()

        if self._check_captcha():
            logger.warning("CAPTCHA detected during search. Waiting for manual resolution...")
            self._wait_for_captcha_resolution()

        for attempt in range(3):
            hex_code = self._extract_hex_code_from_results("", name)

            if hex_code:
                logger.info(f"Found hex code {hex_code} for name '{name}'")
                self._consecutive_errors = 0
                self._random_delay()
                return hex_code

            if attempt < 2:
                logger.info(f"No results on attempt {attempt+1}, retrying (reload page)...")
                time.sleep(3)

        logger.warning(f"No results found for name '{name}'")
        self._random_delay()
        return None

    def _extract_hex_code_from_results(self, isin: str, issuer_name: str = "") -> Optional[str]:
        """
        Extract the bond hex code from search results page.

        The search results contain links like:
        /issue/details00007/default.asp
        /issue/details048A2/default.asp

        Matching strategy:
        1. ISIN in link text or href
        2. ISIN in parent row/table cell text
        3. Issuer name in link text (for name-based search)
        4. Single-result shortcut (if only 1 details link, use it)
        """
        # Method 1: Use JavaScript to find all links with row context
        try:
            links_data = self._page.evaluate("""
                () => {
                    const links = document.querySelectorAll('a');
                    const results = [];
                    for (const link of links) {
                        const href = link.href || '';
                        const text = link.innerText || '';
                        if (href.includes('details')) {
                            // Get parent row/cell text for context
                            let rowText = '';
                            const row = link.closest('tr') || link.closest('div') || link.parentElement;
                            if (row) {
                                rowText = row.innerText || '';
                            }
                            results.push({href: href, text: text, rowText: rowText});
                        }
                    }
                    return results;
                }
            """)
            logger.info(f"Found {len(links_data)} links with 'details' in href")
            for i, link_info in enumerate(links_data):
                logger.info(f"  [{i}] text={link_info.get('text', '')!r} href={link_info.get('href', '')[-50:]}")
                row_preview = link_info.get('rowText', '')[:200]
                logger.info(f"       rowText={row_preview!r}")

            # Pass 1: exact ISIN match in text or href
            if isin:
                for link_info in links_data:
                    href = link_info.get('href', '')
                    text = link_info.get('text', '')
                    row_text = link_info.get('rowText', '')

                    if isin.upper() in text.upper() or isin.upper() in href.upper() or isin.upper() in row_text.upper():
                        if "/issue/details" in href:
                            parts = href.split("/issue/details")
                            if len(parts) > 1:
                                hex_part = parts[1].split("/")[0].split("?")[0]
                                logger.info(f"Found hex code {hex_part} from ISIN match")
                                return hex_part

            # Pass 2: issuer name match (for name-based search)
            if issuer_name:
                for link_info in links_data:
                    href = link_info.get('href', '')
                    text = link_info.get('text', '')
                    row_text = link_info.get('rowText', '')

                    if issuer_name.upper() in text.upper() or issuer_name.upper() in row_text.upper():
                        if "/issue/details" in href:
                            parts = href.split("/issue/details")
                            if len(parts) > 1:
                                hex_part = parts[1].split("/")[0].split("?")[0]
                                logger.info(f"Found hex code {hex_part} from issuer name match ({issuer_name!r})")
                                return hex_part

            # Pass 3: if only 1 details link, use it (search is specific enough)
            if len(links_data) == 1:
                href = links_data[0].get('href', '')
                if "/issue/details" in href:
                    parts = href.split("/issue/details")
                    if len(parts) > 1:
                        hex_part = parts[1].split("/")[0].split("?")[0]
                        logger.info(f"Found hex code {hex_part} from single-result shortcut")
                        return hex_part

            if links_data:
                logger.warning(f"No exact ISIN match found in {len(links_data)} search results")

        except Exception as e:
            logger.warning(f"JavaScript link extraction failed: {e}")

        # Method 2: Check onclick handlers
        try:
            onclick_data = self._page.evaluate("""
                () => {
                    const elements = document.querySelectorAll('[onclick*="details"]');
                    const results = [];
                    for (const el of elements) {
                        const onclick = el.getAttribute('onclick') || '';
                        if (onclick.includes('details')) {
                            let rowText = '';
                            const row = el.closest('tr') || el.closest('div') || el.parentElement;
                            if (row) {
                                rowText = row.innerText || '';
                            }
                            results.push({onclick: onclick, text: el.innerText || '', rowText: rowText});
                        }
                    }
                    return results;
                }
            """)
            logger.info(f"Found {len(onclick_data)} elements with 'details' in onclick")
            for i, item in enumerate(onclick_data):
                logger.info(f"  [{i}] text={item.get('text', '')!r} onclick={item.get('onclick', '')[-50:]}")

            for item in onclick_data:
                onclick = item.get('onclick', '')
                text = item.get('text', '')
                row_text = item.get('rowText', '')

                if "/issue/details" in onclick:
                    parts = onclick.split("/issue/details")
                    if len(parts) > 1:
                        hex_part = parts[1].split("/")[0].split("?")[0].strip("'\"")
                        if isin and (isin.upper() in text.upper() or isin.upper() in row_text.upper()):
                            logger.info(f"Found hex code {hex_part} from onclick ISIN match")
                            return hex_part
                        if issuer_name and (issuer_name.upper() in text.upper() or issuer_name.upper() in row_text.upper()):
                            logger.info(f"Found hex code {hex_part} from onclick issuer name match")
                            return hex_part

            # Single-result shortcut for onclick too
            if len(onclick_data) == 1:
                onclick = onclick_data[0].get('onclick', '')
                if "/issue/details" in onclick:
                    parts = onclick.split("/issue/details")
                    if len(parts) > 1:
                        hex_part = parts[1].split("/")[0].split("?")[0].strip("'\"")
                        logger.info(f"Found hex code {hex_part} from onclick single-result shortcut")
                        return hex_part

        except Exception as e:
            logger.warning(f"JavaScript onclick extraction failed: {e}")

        # Method 3: Full-page ISIN search — find ISIN text anywhere on the page
        # and associate it with the nearest details link
        try:
            page_match = self._page.evaluate("""
                (searchIsin) => {
                    // Search entire page body for the ISIN string
                    const body = document.body ? document.body.innerText : '';
                    if (!searchIsin || !body.toUpperCase().includes(searchIsin.toUpperCase())) {
                        return {found: false, bodySnippet: body.substring(0, 500)};
                    }
                    // Find all details links and their positions
                    const links = document.querySelectorAll('a[href*="details"]');
                    const results = [];
                    for (const link of links) {
                        results.push({href: link.href, text: link.innerText || ''});
                    }
                    return {found: true, links: results, bodySnippet: body.substring(0, 500)};
                }
            """, isin)

            if page_match and page_match.get('found'):
                logger.info(f"ISIN {isin} found in page text")
                links = page_match.get('links', [])
                if len(links) == 1:
                    href = links[0].get('href', '')
                    if "/issue/details" in href:
                        parts = href.split("/issue/details")
                        if len(parts) > 1:
                            hex_part = parts[1].split("/")[0].split("?")[0]
                            logger.info(f"Found hex code {hex_part} from page-text single link")
                            return hex_part
                elif links:
                    # Multiple links — return the first one (search is specific enough)
                    href = links[0].get('href', '')
                    if "/issue/details" in href:
                        parts = href.split("/issue/details")
                        if len(parts) > 1:
                            hex_part = parts[1].split("/")[0].split("?")[0]
                            logger.info(f"Found hex code {hex_part} from page-text first link ({len(links)} total)")
                            return hex_part
            else:
                snippet = (page_match or {}).get('bodySnippet', '')[:200]
                logger.warning(f"ISIN {isin} not found in page text. Body snippet: {snippet!r}")

        except Exception as e:
            logger.warning(f"JavaScript page-text search failed: {e}")

        logger.warning(f"Could not find hex code for ISIN {isin} in search results")
        return None

    def get_bond_card(self, isin: str, hex_code: str) -> Optional[BondCard]:
        """Navigate to bond card page and extract document links."""
        url = self.config.finam_card_url_template.format(hex_code=hex_code)
        logger.info(f"Opening bond card: {url}")

        try:
            self._page.goto(url, timeout=self.config.browser_timeout, wait_until="domcontentloaded")
        except Exception as e:
            error_str = str(e).lower()
            if "timed_out" in error_str or "err_connection" in error_str:
                self._consecutive_errors += 1
                logger.warning(f"Connection error on card page: {e}")
                return None
            raise

        self._wait_for_servicepipe()

        if self._check_captcha():
            logger.warning("CAPTCHA detected on card page. Waiting...")
            self._wait_for_captcha_resolution()

        card = BondCard(
            isin=isin, hex_code=hex_code,
            issuer="", issue_name="", rating="", card_url=url,
        )

        # Extract issuer and issue name
        card.issuer = self._extract_text(".emission h2") or self._extract_text("h2")
        card.issue_name = self._extract_text(".emission .issue-name") or ""

        # Extract rating
        card.rating = self._extract_rating()

        # Extract document links
        card.decision_url = self._extract_doc_link("Решение о выпуске")
        card.program_url = self._extract_doc_link("Программа облигаций")

        if not card.decision_url:
            card.decision_url = self._extract_doc_link_by_href("decision")
        if not card.program_url:
            card.program_url = self._extract_doc_link_by_href("prospect")

        logger.info(
            f"Bond card: issuer={card.issuer}, decision={card.decision_url}, "
            f"program={card.program_url}"
        )

        self._random_delay()
        return card

    def _extract_text(self, selector: str) -> str:
        """Extract text content from element matching selector."""
        try:
            el = self._page.query_selector(selector)
            if el:
                return el.inner_text().strip()
        except Exception as e:
            logger.debug(f"Failed to extract text for selector {selector}: {e}")
        return ""

    def _extract_rating(self) -> str:
        """Extract credit rating from the bond card page."""
        selectors = [".rating", "[class*='rating']"]
        for sel in selectors:
            text = self._extract_text(sel)
            if text:
                return text
        return ""

    def _extract_doc_link(self, link_text: str) -> Optional[str]:
        """Extract document link by link text."""
        try:
            links = self._page.query_selector_all("a")
            for link in links:
                text = (link.inner_text() or "").strip()
                if link_text.lower() in text.lower():
                    href = link.get_attribute("href")
                    if href:
                        # Fix backslashes in URL
                        return href.replace("\\", "/")
        except Exception as e:
            logger.debug(f"Failed to extract doc link for '{link_text}': {e}")
        return None

    def _extract_doc_link_by_href(self, pattern: str) -> Optional[str]:
        """Extract document link by href pattern."""
        try:
            links = self._page.query_selector_all(f"a[href*='{pattern}']")
            for link in links:
                href = link.get_attribute("href")
                if href and (href.endswith(".pdf") or href.endswith(".zip")):
                    # Fix backslashes in URL
                    return href.replace("\\", "/")
        except Exception as e:
            logger.debug(f"Failed to extract doc link by href pattern '{pattern}': {e}")
        return None

    def _check_captcha(self) -> bool:
        """Check if CAPTCHA is present on the page (delegates to the detector)."""
        return FINAM_CAPTCHA.detect(self._page)

    def _wait_for_captcha_resolution(self):
        """Wait for CAPTCHA to be resolved (manual intervention)."""
        logger.info("Waiting for CAPTCHA resolution (please solve in browser)...")
        resolved = wait_captcha_resolved(
            self._page, FINAM_CAPTCHA,
            timeout_seconds=self.config.captcha_timeout / 1000,
            min_wait=0,
        )
        if not resolved:
            raise TimeoutError(
                f"CAPTCHA not resolved within {self.config.captcha_timeout / 1000:.0f}s"
            )

    def download_file(self, url: str, dest_path: Path) -> bool:
        """Download a file from st.finam.ru (no anti-bot)."""
        if _httpx is None:
            logger.error("httpx not installed. Run: pip install httpx")
            return False

        # Fix backslashes in URL (some links use \ instead of /)
        url = url.replace("\\", "/")
        logger.info(f"Downloading {url} -> {dest_path.name}")

        headers = {
            "User-Agent": self.config.browser_user_agent,
            "Accept": "*/*",
            "Referer": "https://bonds.finam.ru/",
        }

        try:
            with _httpx.Client(headers=headers, timeout=60, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(dest_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
            logger.info(f"Downloaded: {dest_path.name}")
            return True
        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            return False
