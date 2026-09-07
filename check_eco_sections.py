"""Deep search for program section refs in ЭКОНОМЛИЗИНГ decisions."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import pdfplumber
except ImportError:
    print("ERROR: pip install pdfplumber")
    exit(1)

isin = "RU000A10B081"
base = Path(__file__).parent
pdf_dir = base / "downloads" / isin

pdfs = list(pdf_dir.glob("*.pdf"))
if not pdfs:
    print(f"No PDF found in {pdf_dir}")
    sys.exit(1)

pdf_path = pdfs[0]
print(f"Analyzing: {pdf_path}\n")

with pdfplumber.open(pdf_path) as pdf:
    # Get ALL text
    all_text = ""
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        all_text += f"\n--- PAGE {i+1} ---\n{text}"

    # Search for all section references with "Программ"
    patterns = [
        re.compile(r'(?:пункт[а-яё]*|п\.\s*|раздел[а-яё]*\s+)(\d+(?:\.\d+){1,3})\s+(?:Программ[аыуиеё])', re.IGNORECASE),
        re.compile(r'(\d+\.\d+(?:\.\d+)?)\s+(?:Программ[аыуиеё])', re.IGNORECASE),
        re.compile(r'Программ[аыуиеё][^.]{0,100}(?:пункт[а-яё]*|п\.\s*|раздел[а-яё]*\s+)(\d+(?:\.\d+){1,3})', re.IGNORECASE),
    ]

    found_sections = set()
    for pat in patterns:
        for m in pat.finditer(all_text):
            sec = m.group(1)
            found_sections.add(sec)
            start = max(0, m.start() - 100)
            end = min(len(all_text), m.end() + 100)
            context = all_text[start:end].replace("\n", " ")
            print(f"Found: {sec}")
            print(f"  Context: ...{context}...")

    if not found_sections:
        print("No direct 'п. X.X.X Программы' pattern found")
        print("\nSearching for 'Досрочное погашение' section references...")
        # Search for any section ref related to early redemption
        early_re = re.compile(r'(?:пункт[а-яё]*|п\.\s*|раздел[а-яё]*\s+)(\d+(?:\.\d+){1,3})[^.]*?(?:досрочн|погашен|требовани)', re.IGNORECASE)
        for m in early_re.finditer(all_text):
            sec = m.group(1)
            found_sections.add(sec)
            start = max(0, m.start() - 80)
            end = min(len(all_text), m.end() + 80)
            context = all_text[start:end].replace("\n", " ")
            print(f"  Found: {sec} -> {context}")

        # Also search for section 9 in general
        print("\nAll mentions of section 9.x:")
        sec9 = re.compile(r'(?:п\.\s*|пункт[а-яё]*\s+)(9\.\d+(?:\.\d+)?)', re.IGNORECASE)
        for m in sec9.finditer(all_text):
            sec = m.group(1)
            start = max(0, m.start() - 60)
            end = min(len(all_text), m.end() + 60)
            context = all_text[start:end].replace("\n", " ")
            print(f"  {sec}: ...{context}...")

    print(f"\nAll unique sections found: {sorted(found_sections)}")
