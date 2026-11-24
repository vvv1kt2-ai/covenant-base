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

    _DETAILS_MARKER = "/issue/details"

    @staticmethod
    def _hex_from_href(href: str) -> Optional[str]:
        """Bond hex code from a Finam link: `/issue/details048A2/default.asp` → `048A2`."""
        if not href or FinamClient._DETAILS_MARKER not in href:
            return None
        rest = href.split(FinamClient._DETAILS_MARKER, 1)[1]
        hex_part = rest.split("/")[0].split("?")[0].strip("'\"")
        return hex_part or None

    @staticmethod
    def _mentions(needle: str, *haystacks: str) -> bool:
        """Case-insensitive substring check across several fields."""
        if not needle:
            return False
        needle = needle.upper()
        return any(needle in (hay or "").upper() for hay in haystacks)

    def _result_candidates(self):
        """Кандидаты со страницы результатов: [(hex, text, row_text)].

        Ссылка на карточку бывает и обычным <a href>, и onclick-обработчиком
        на строке таблицы, поэтому источников два.
        """
        candidates = []

        try:
            links_data = self._page.evaluate("""
                () => {
                    const results = [];
                    for (const link of document.querySelectorAll('a')) {
                        const href = link.href || '';
                        if (!href.includes('details')) continue;
                        const row = link.closest('tr') || link.closest('div') || link.parentElement;
                        results.push({
                            href: href,
                            text: link.innerText || '',
                            rowText: row ? (row.innerText || '') : '',
                        });
                    }
                    return results;
                }
            """) or []
        except Exception as e:
            logger.warning(f"JavaScript link extraction failed: {e}")
            links_data = []

        try:
            onclick_data = self._page.evaluate("""
                () => {
                    const results = [];
                    for (const el of document.querySelectorAll('[onclick*="details"]')) {
                        const row = el.closest('tr') || el.closest('div') || el.parentElement;
                        results.push({
                            onclick: el.getAttribute('onclick') || '',
                            text: el.innerText || '',
                            rowText: row ? (row.innerText || '') : '',
                        });
                    }
                    return results;
                }
            """) or []
        except Exception as e:
            logger.warning(f"JavaScript onclick extraction failed: {e}")
            onclick_data = []

        for item in links_data:
            code = self._hex_from_href(item.get('href', ''))
            if code:
                candidates.append((code, item.get('text', ''), item.get('rowText', '')))

        for item in onclick_data:
            code = self._hex_from_href(item.get('onclick', ''))
            if code:
                candidates.append((code, item.get('text', ''), item.get('rowText', '')))

        for code, text, row_text in candidates:
            logger.info(f"  candidate {code}: text={text[:60]!r} row={row_text[:120]!r}")

        return candidates

    def _search_result_count(self) -> Optional[int]:
        """«Найдено выпусков: N» со страницы результатов; None, если не разобрать."""
        try:
            count = self._page.evaluate(r"""
                () => {
                    const body = document.body ? document.body.innerText : '';
                    const m = body.match(/Найдено\s+выпусков:\s*(\d+)/);
                    return m ? parseInt(m[1], 10) : null;
                }
            """)
        except Exception as e:
            logger.warning(f"JavaScript result-count extraction failed: {e}")
            return None
        return count if isinstance(count, int) else None

    def _extract_hex_code_from_results(self, isin: str, issuer_name: str = "") -> Optional[str]:
        """Код карточки выпуска со страницы результатов поиска.

        Finam не показывает ISIN в строке результата — в таблице только выпуск,
        статус, даты и объём. Опознать выпуск можно по тому, что поиск по ISIN
        вернул ровно один результат: это ответ поисковика на конкретный запрос.

        Правило: при заданном ISIN карточка принимается, если (а) ISIN всё-таки
        встречается в строке результата, либо (б) страница сообщает
        «Найдено выпусков: 1» и на ней ровно одна ссылка на карточку.
        Несколько результатов без точного совпадения — отказ (None), а не
        «первая ссылка»: иначе для ISIN A разбирается карточка выпуска B.
        """
        candidates = self._result_candidates()
        distinct = {code for code, _, _ in candidates}

        if isin:
            for code, text, row_text in candidates:
                if self._mentions(isin, text, row_text):
                    logger.info(f"Found hex code {code} from ISIN match in result row")
                    return code

            count = self._search_result_count()
            if count == 1 and len(distinct) == 1:
                code = next(iter(distinct))
                logger.info(
                    f"Found hex code {code}: search reported exactly one issue for ISIN {isin}"
                )
                return code

            logger.warning(
                f"ISIN {isin}: no exact match in rows, search reported {count} issue(s), "
                f"{len(distinct)} distinct card link(s) — refusing to guess"
            )
            return None

        if issuer_name:
            for code, text, row_text in candidates:
                if self._mentions(issuer_name, text, row_text):
                    logger.info(f"Found hex code {code} from issuer name match ({issuer_name!r})")
                    return code

        if len(distinct) == 1:
            code = next(iter(distinct))
            logger.info(f"Found hex code {code} from single-result shortcut")
            return code

        logger.warning(
            f"No match for issuer name {issuer_name!r} among {len(distinct)} distinct result(s)"
        )
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
                logger.warning(
                    f"Connection error on card page "
                    f"(consecutive: {self._consecutive_errors}): {e}"
                )
                if self._consecutive_errors >= self.config.max_consecutive_errors:
                    self._handle_block()
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
