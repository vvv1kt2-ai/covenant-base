"""Shared Playwright browser session with anti-bot plumbing.

Owns: lifecycle (launch with full anti-detection for every source,
shutdown), human-like delays, and the CAPTCHA wait loop. CAPTCHA detection
itself is pluggable — two adapters (Finam CSS-based, e-disclosure
text-based) share one loop. Block detection (consecutive-error cooldown)
is Finam/ServicePipe-specific and stays in finam_client.FinamClient.
"""
import logging
import random
import time

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Chromium flags + init script shared by every source
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
]
ANTI_DETECT_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
"""


class BrowserSession:
    """Playwright lifecycle + delays. One session per source run.

    Usable as a context manager (with BrowserSession(...) as session:) or
    via explicit start()/stop().
    """

    def __init__(self, config, delay_range=None, headless=None, lazy=False):
        self.config = config
        self.delay_range = delay_range
        self.headless = config.browser_headless if headless is None else headless
        self._lazy = lazy
        self._started = False
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _start_impl(self):
        logger.info("Starting Playwright browser (headless=%s)...", self.headless)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=LAUNCH_ARGS,
        )
        self._context = self._browser.new_context(
            user_agent=self.config.browser_user_agent,
            viewport={"width": 1366, "height": 768},
            locale=self.config.browser_locale,
            timezone_id="Europe/Moscow",
        )
        self._context.add_init_script(ANTI_DETECT_INIT_SCRIPT)
        self._page = self._context.new_page()
        logger.info("Browser started.")

    def ensure_started(self):
        """Launch the browser unless already running (idempotent)."""
        if not self._started:
            self._start_impl()
            self._started = True

    @property
    def page(self):
        """The session's page. In lazy mode the first access starts the browser."""
        self.ensure_started()
        return self._page

    def start(self):
        """Eagerly launch the browser (no-op in lazy mode until page is touched)."""
        self.ensure_started()

    def stop(self):
        """Clean shutdown (no-op if never started)."""
        if not self._started:
            return
        logger.info("Stopping browser...")
        if self._page:
            self._page.close()
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._started = False
        logger.info("Browser stopped.")

    def __enter__(self):
        if not self._lazy:
            self.ensure_started()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        return False

    def human_delay(self, delay_range=None):
        """Sleep for a random duration within the (min, max) range."""
        lo, hi = delay_range or self.delay_range
        time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------------------
# CAPTCHA: detection adapters + one shared wait loop
# ---------------------------------------------------------------------------

class FinamCaptchaDetector:
    """CSS-based detection of the Finam captcha frame.

    Never fired in practice — kept as a safety net.
    """

    def detect(self, page) -> bool:
        try:
            captcha_div = page.query_selector("#id_captcha_frame_div")
            if captcha_div:
                display = captcha_div.evaluate("el => getComputedStyle(el).display")
                if display and display != "none":
                    return True
        except Exception:
            pass
        return False


class EdisclosureCaptchaDetector:
    """Text/URL/iframe-based detection of the e-disclosure challenge page."""

    _CHECK_JS = """
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
    """

    def detect(self, page) -> bool:
        try:
            return page.evaluate(self._CHECK_JS)
        except Exception:
            # Navigation destroyed the page — treat as no captcha
            return False


FINAM_CAPTCHA = FinamCaptchaDetector()
EDISCLOSURE_CAPTCHA = EdisclosureCaptchaDetector()

_POLL_INTERVAL = 3  # seconds between detection attempts


def wait_captcha_resolved(page, detector, timeout_seconds, min_wait=0.0) -> bool:
    """Poll until the detector stops firing. True = resolved / no captcha.

    The loop does not dictate error policy — callers decide what a False
    means (Finam raises, e-disclosure records a failure status). On
    disappearance it sleeps out min_wait (e-disclosure gives the user time
    even when the challenge auto-resolves), then waits for load state.
    """
    if not detector.detect(page):
        return True

    start = time.time()
    while time.time() - start < timeout_seconds:
        time.sleep(_POLL_INTERVAL)
        elapsed = time.time() - start

        if not detector.detect(page):
            if elapsed < min_wait:
                logger.info(
                    f"CAPTCHA seems resolved after {elapsed:.0f}s, "
                    f"but waiting {min_wait - elapsed:.0f}s more for safety..."
                )
                time.sleep(min_wait - elapsed)
            logger.info("CAPTCHA resolved! Continuing...")
            try:
                page.wait_for_load_state("load", timeout=10_000)
            except Exception:
                pass
            return True

    logger.error(f"CAPTCHA not resolved within {timeout_seconds:.0f}s")
    return False
