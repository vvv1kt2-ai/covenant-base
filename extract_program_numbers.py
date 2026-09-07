"""Extract program numbers from decision PDFs for ISINs without program URL.

Scans the first pages of decision PDFs for patterns like:
- "Программа облигаций серии 001P, имеющая идентификационный номер 4-00490-R-001P-02E"
- "Программа или Программа облигаций ... номер X-XXXXX-X-XXX-XX(X)"
- "идентификационный номер" + pattern

Outputs results to program_numbers.json
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

# Pattern for program identification number like 4-00490-R-001P-02E
PROGRAM_NUMBER_PATTERN = re.compile(
    r'(?:идентификационн\w+\s+номер|номер)\s*[:\-–]?\s*'
    r'(\d{1,3}[- ]\d{4,6}[- ]R[- ]\d{3}[A-ZА-Я]{1,3}[- ]\d{1,3}[A-ZА-Я]?)',
    re.IGNORECASE
)

# Broader pattern for program number in context
PROGRAM_CONTEXT_PATTERN = re.compile(
    r'(?:Программ[аыу]\b[^.]{0,300}?номер\s*[:\-–]?\s*)'
    r'(\d{1,3}[- ]\d{4,6}[- ]R[- ]\d{3}[A-ZА-Я]{1,3}[- ]\d{1,3}[A-ZА-Я]?)',
    re.IGNORECASE | re.DOTALL
)

# Pattern for program series
SERIES_PATTERN = re.compile(
    r'серии\s+(\d{3}[A-ZА-Я]{1,3})',
    re.IGNORECASE
)


def extract_program_number(pdf_path: str) -> dict:
    """Extract program number from the first 5 pages of a PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Check first 5 pages (program ref is usually on page 2)
            pages_to_check = min(5, len(pdf.pages))
            full_text = ""
            for i in range(pages_to_check):
                page_text = pdf.pages[i].extract_text() or ""
                full_text += page_text + "\n"

            # Try specific pattern first
            match = PROGRAM_NUMBER_PATTERN.search(full_text)
            if match:
                number = match.group(1).replace(" ", "-")
                # Get series
                series_match = SERIES_PATTERN.search(full_text)
                series = series_match.group(1) if series_match else ""
                # Get context
                start = max(0, match.start() - 100)
                end = min(len(full_text), match.end() + 50)
                context = full_text[start:end].replace("\n", " ").strip()
                return {
                    "program_number": number,
                    "series": series,
                    "context": context,
                    "found": True,
                }

            # Try broader context pattern
            match = PROGRAM_CONTEXT_PATTERN.search(full_text)
            if match:
                number = match.group(1).replace(" ", "-")
                series_match = SERIES_PATTERN.search(full_text)
                series = series_match.group(1) if series_match else ""
                start = max(0, match.start() - 100)
                end = min(len(full_text), match.end() + 50)
                context = full_text[start:end].replace("\n", " ").strip()
                return {
                    "program_number": number,
                    "series": series,
                    "context": context,
                    "found": True,
                }

            # Just find any R-series number pattern
            r_pattern = re.compile(r'(\d{1,3}[- ]\d{4,6}[- ]R[- ]\d{3}[A-ZА-Я]{1,3}[- ]\d{1,3}[A-ZА-Я]?)')
            r_match = r_pattern.search(full_text)
            if r_match:
                number = r_match.group(1).replace(" ", "-")
                return {
                    "program_number": number,
                    "series": "",
                    "context": "",
                    "found": True,
                    "confidence": "low",
                }

            return {"found": False, "error": "No program number pattern found"}

    except Exception as e:
        return {"found": False, "error": str(e)}


def main():
    base = Path(__file__).parent
    downloads_dir = base / "downloads"

    with open(base / "results.json", encoding="utf-8") as f:
        data = json.load(f)

    # ISINs needing program check without program on Finam
    needs_program = [
        r for r in data
        if r.get("needs_program_check", False)
        and (not r.get("program_url") or r["program_url"] == "")
        and r.get("program_status") != "parsed"
    ]

    print(f"ISINs needing program: {len(needs_program)}")
    print(f"Scanning decision PDFs for program numbers...\n")

    results = []

    for entry in needs_program:
        isin = entry["isin"]
        issuer = entry.get("issuer", "")
        decision_url = entry.get("decision_url", "")

        # Find the downloaded decision PDF
        isin_dir = downloads_dir / isin
        if not isin_dir.exists():
            results.append({
                "isin": isin,
                "issuer": issuer,
                "status": "no_download_dir",
            })
            print(f"  {isin} | {issuer} | NO DOWNLOAD DIR")
            continue

        # Find decision PDF
        pdfs = list(isin_dir.glob("*.pdf")) + list(isin_dir.glob("*.zip"))
        if not pdfs:
            results.append({
                "isin": isin,
                "issuer": issuer,
                "status": "no_pdf",
            })
            print(f"  {isin} | {issuer} | NO PDF")
            continue

        # Try each PDF (usually decision.pdf)
        found = False
        for pdf_path in pdfs:
            if pdf_path.suffix == ".zip":
                continue
            result = extract_program_number(str(pdf_path))
            if result.get("found"):
                program_number = result["program_number"]
                series = result.get("series", "")
                confidence = result.get("confidence", "high")
                print(f"  {isin} | {issuer} | #{program_number} (series={series}, conf={confidence})")
                results.append({
                    "isin": isin,
                    "issuer": issuer,
                    "program_number": program_number,
                    "series": series,
                    "confidence": confidence,
                    "context": result.get("context", ""),
                    "pdf": pdf_path.name,
                    "status": "found",
                })
                found = True
                break

        if not found:
            results.append({
                "isin": isin,
                "issuer": issuer,
                "status": "not_found",
            })
            print(f"  {isin} | {issuer} | NOT FOUND IN PDF")

    # Save results
    output_path = base / "program_numbers.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Summary
    found_count = sum(1 for r in results if r["status"] == "found")
    print(f"\n{'='*60}")
    print(f"Found program numbers: {found_count}/{len(results)}")
    print(f"Saved to {output_path}")

    # List found
    if found_count > 0:
        print(f"\nPrograms found:")
        for r in results:
            if r["status"] == "found":
                print(f"  {r['isin']} | {r['issuer']} → {r['program_number']}")


if __name__ == "__main__":
    main()
