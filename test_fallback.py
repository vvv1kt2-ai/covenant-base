"""Quick test: re-parse 24 ISINs with the new fallback, using already downloaded PDFs."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from pdf_parser import PDFParser

config = Config()
parser = PDFParser(config)

with open("results.json", encoding="utf-8") as f:
    data = json.load(f)

no_covenant = [r for r in data if not r["parse_errors"] and r["total_covenants"] == 0]
print(f"Re-parsing {len(no_covenant)} ISINs with fallback...\n")

fixed = 0
still_empty = 0

for r in no_covenant:
    isin = r["isin"]
    pdf_path = Path("downloads") / isin / "decision.pdf"
    if not pdf_path.exists():
        print(f"  {isin} | PDF NOT FOUND")
        continue

    result = parser.parse_decision(pdf_path)

    if result.redemption_clauses:
        clause = result.redemption_clauses[0]
        status = "ПРЕДУСМОТРЕНА" if clause.is_provided else "НЕ предусмотрена"
        print(f"  {isin} | {r['issuer'][:30]:30s} | ✅ {status} | п.{clause.page} | {clause.section}")
        fixed += 1
    else:
        print(f"  {isin} | {r['issuer'][:30]:30s} | ❌ Still not found")
        still_empty += 1

print(f"\nResult: {fixed} fixed, {still_empty} still empty")
