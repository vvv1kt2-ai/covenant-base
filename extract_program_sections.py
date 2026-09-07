"""Extract program section references from decision PDFs.

Searches for patterns like:
- "п. 9.5.1 Программы"
- "пункта 9.5.1 Программы"
- "раздела 9.5.1 Программы"
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import pdfplumber
except ImportError:
    print("ERROR: pip install pdfplumber")
    exit(1)

# Pattern: "п. X.X.X Программы" or "пункта X.X.X Программы" etc.
SECTION_REF_PATTERN = re.compile(
    r'(?:пункт[а-яё]*|п\.\s*|раздел[а-яё]*\s+)\s*'
    r'(\d+(?:\.\d+){1,3})\s+'
    r'(?:Программ[аыуиеё]\b)',
    re.IGNORECASE
)

# Broader: just "X.X.X Программы" 
SECTION_REF_BROAD = re.compile(
    r'(\d+\.\d+\.\d+)\s+'
    r'(?:Программ[аыуиеё]\b)',
    re.IGNORECASE
)


def extract_section_refs(pdf_path):
    """Extract program section references from decision PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Check first 5 pages (section refs usually in definitions section)
            pages_to_check = min(5, len(pdf.pages))
            full_text = ""
            for i in range(pages_to_check):
                page_text = pdf.pages[i].extract_text() or ""
                full_text += page_text + "\n"

            sections = set()

            # Try specific pattern first
            for match in SECTION_REF_PATTERN.finditer(full_text):
                sections.add(match.group(1))

            # Try broad pattern
            for match in SECTION_REF_BROAD.finditer(full_text):
                sections.add(match.group(1))

            # Get context for each found section
            results = []
            for sec in sorted(sections):
                # Find context
                idx = full_text.find(sec)
                if idx >= 0:
                    start = max(0, idx - 80)
                    end = min(len(full_text), idx + len(sec) + 80)
                    context = full_text[start:end].replace("\n", " ").strip()
                else:
                    context = ""
                results.append({"section": sec, "context": context})

            return results

    except Exception as e:
        return [{"error": str(e)}]


def main():
    base = Path(__file__).parent
    downloads_dir = base / "downloads"

    with open(base / "program_numbers.json", encoding="utf-8") as f:
        pn = json.load(f)

    found = [r for r in pn if r.get("status") == "found"]

    print(f"Checking {len(found)} decisions for program section references...\n")

    results = {}

    for entry in found:
        isin = entry["isin"]
        issuer = entry.get("issuer", "")
        prog_num = entry.get("program_number", "")

        isin_dir = downloads_dir / isin
        if not isin_dir.exists():
            print(f"  {isin} | {issuer} | NO DIR")
            continue

        pdfs = list(isin_dir.glob("*.pdf"))
        if not pdfs:
            print(f"  {isin} | {issuer} | NO PDF")
            continue

        pdf_path = pdfs[0]
        refs = extract_section_refs(str(pdf_path))

        if refs and not refs[0].get("error"):
            sections = [r["section"] for r in refs]
            print(f"  {isin} | {issuer} | Program sections: {sections}")
            for r in refs:
                print(f"    {r['section']}: ...{r['context']}...")
        else:
            print(f"  {isin} | {issuer} | NO SECTION REF FOUND")
            if refs and refs[0].get("error"):
                print(f"    Error: {refs[0]['error']}")

        results[isin] = {
            "issuer": issuer,
            "program_number": prog_num,
            "sections": refs,
        }

    # Save
    output_path = base / "program_section_refs.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path}")

    # Summary of unique sections
    all_sections = set()
    for r in results.values():
        for ref in r["sections"]:
            if ref.get("section"):
                all_sections.add(ref["section"])
    print(f"\nUnique program sections referenced: {sorted(all_sections)}")


if __name__ == "__main__":
    main()
