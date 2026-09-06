"""Test PDF parser on existing test files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from pdf_parser import PDFParser


def test_parse_dosrok():
    config = Config()
    parser = PDFParser(config)

    test_file = Path(__file__).parent / "dosrok_test.txt"
    if not test_file.exists():
        print(f"Test file not found: {test_file}")
        return

    text = test_file.read_text(encoding="utf-8")
    print(f"Test text ({len(text)} chars):")
    print(text[:500])
    print("---")

    import re
    section_pattern = re.compile(
        r"5\.6\.1[\.\s](.*?)(?=\n\s*\d+\.\d+[\.\s]|\n\s*6[\.\s]|$)",
        re.DOTALL | re.IGNORECASE,
    )

    match = section_pattern.search(text)
    if match:
        raw_section = match.group(0).strip()
        print(f"\nFound section 5.6.1:")
        print(raw_section[:300])
        print("---")

        is_provided = "не предусмотрена" not in raw_section.lower() and "не предусмотрено" not in raw_section.lower()
        print(f"Redemption by holders provided: {is_provided}")
    else:
        print("Section 5.6.1 not found")


if __name__ == "__main__":
    test_parse_dosrok()
