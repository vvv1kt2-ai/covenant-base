"""Configuration for bond emission document parser."""
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    """Project configuration."""

    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent)
    downloads_dir: Path = field(default_factory=lambda: Path(__file__).parent / "downloads")
    logs_dir: Path = field(default_factory=lambda: Path(__file__).parent / "logs")

    # Finam URLs
    finam_search_url: str = "https://bonds.finam.ru/issue/search/default.asp"
    finam_card_url_template: str = "https://bonds.finam.ru/issue/details{hex_code}/default.asp"
    finam_doc_base: str = "https://st.finam.ru/ipo/"

    # Browser settings (Playwright)
    browser_headless: bool = True
    browser_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    browser_locale: str = "ru-RU"
    browser_timeout: int = 60_000  # ms
    captcha_timeout: int = 120_000  # ms — time to wait for manual CAPTCHA solve

    # Rate limiting
    min_delay: float = 3.0  # seconds between requests
    max_delay: float = 8.0  # seconds between requests

    # Block detection
    block_cooldown_seconds: int = 300  # pause for 5 minutes if blocked
    max_consecutive_errors: int = 3  # pause after N consecutive connection errors

    # PDF parsing
    redemption_section_pattern: str = r"5\.6\.1"  # section number to search
    redemption_keywords: list = field(default_factory=lambda: [
        "досрочное погашение",
        "по требованию",
        "по требованию владельцев",
    ])

    # Retry
    max_retries: int = 3

    def __post_init__(self):
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def isin_download_dir(self, isin: str) -> Path:
        """Get download directory for a specific ISIN."""
        d = self.downloads_dir / isin
        d.mkdir(parents=True, exist_ok=True)
        return d
