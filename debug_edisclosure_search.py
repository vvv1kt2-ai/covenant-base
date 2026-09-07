"""Debug: check e-disclosure search page structure."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config

config = Config()


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=config.browser_user_agent,
            locale=config.browser_locale,
        )
        page = context.new_page()

        url = "https://e-disclosure.ru/poisk-po-soobshheniyam"
        print(f"Opening: {url}")

        # goto() with wait_until="domcontentloaded" returns before JS challenge redirect
        page.goto(url, timeout=config.browser_timeout, wait_until="commit")
        print(f"Initial URL: {page.url}")

        # The anti-bot JS challenge will redirect. Wait for navigation to settle.
        # Try multiple strategies:
        # 1. Wait for "load" state (waits for final navigation)
        try:
            page.wait_for_load_state("load", timeout=30_000)
            print(f"After load state: {page.url}")
        except Exception as e:
            print(f"Load state timeout: {e}")

        # 2. Extra settle time for JS to fully execute
        print("Waiting 10s for JS challenge to settle...")
        time.sleep(10)

        print(f"Current URL: {page.url}")
        print(f"Page title: {page.title()}")

        # Check if we landed on a CAPTCHA page
        body_text = page.inner_text("body") if page.query_selector("body") else ""
        if len(body_text) < 100:
            print(f"\nShort body ({len(body_text)} chars), might be challenge page")
            print(f"Body: {body_text[:300]}")
        else:
            print(f"\nBody length: {len(body_text)} chars — looks like a real page")

        # Dump page structure
        info = page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input, textarea, select');
                const buttons = document.querySelectorAll('button, input[type="submit"], a.btn, input[type="button"]');
                const forms = document.querySelectorAll('form');
                const iframes = document.querySelectorAll('iframe');
                const links = document.querySelectorAll('a[href]');
                return {
                    title: document.title,
                    url: window.location.href,
                    inputs: Array.from(inputs).map(i => ({
                        tag: i.tagName, type: i.type || '', name: i.name || '',
                        id: i.id || '', placeholder: i.placeholder || '',
                        class: (i.className || '').substring(0, 80),
                        value: (i.value || '').substring(0, 40)
                    })),
                    buttons: Array.from(buttons).map(b => ({
                        tag: b.tagName, text: (b.innerText || b.value || '').substring(0, 40),
                        type: b.type || '', class: (b.className || '').substring(0, 80),
                        id: b.id || ''
                    })),
                    forms: Array.from(forms).map(f => ({
                        action: f.action, method: f.method,
                        id: f.id || '', class: (f.className || '').substring(0, 80)
                    })),
                    iframes: Array.from(iframes).map(i => ({
                        src: (i.src || '').substring(0, 150), id: i.id || '',
                        class: (i.className || '').substring(0, 80)
                    })),
                    sampleLinks: Array.from(links).slice(0, 30).map(a => ({
                        href: (a.href || '').substring(0, 120),
                        text: (a.innerText || '').substring(0, 60),
                        class: (a.className || '').substring(0, 60)
                    })),
                    bodyLen: (document.body.innerText || '').length,
                    bodySnippet: (document.body.innerText || '').substring(0, 800),
                    fullHtml: document.body.innerHTML.substring(0, 3000)
                };
            }
        """)

        print(f"\n{'='*60}")
        print(f"Title: {info['title']}")
        print(f"URL: {info['url']}")
        print(f"Body length: {info['bodyLen']}")

        print(f"\n--- Inputs ({len(info['inputs'])}) ---")
        for inp in info['inputs']:
            print(f"  {inp}")

        print(f"\n--- Buttons ({len(info['buttons'])}) ---")
        for btn in info['buttons']:
            print(f"  {btn}")

        print(f"\n--- Forms ({len(info['forms'])}) ---")
        for form in info['forms']:
            print(f"  {form}")

        print(f"\n--- Iframes ({len(info['iframes'])}) ---")
        for iframe in info['iframes']:
            print(f"  {iframe}")

        print(f"\n--- Sample Links ({len(info['sampleLinks'])}) ---")
        for link in info['sampleLinks']:
            print(f"  {link}")

        print(f"\n--- Body snippet ---")
        print(info['bodySnippet'])

        # Save full HTML for offline inspection
        html_path = config.base_dir / "downloads" / "edisclosure_search_page.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(info['fullHtml'], encoding='utf-8')
        print(f"\nFull HTML saved to {html_path}")

        # Take screenshot
        ss_path = config.base_dir / "downloads" / "edisclosure_search_debug.png"
        page.screenshot(path=str(ss_path))
        print(f"Screenshot saved to {ss_path}")

        input("\nPress Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    main()
