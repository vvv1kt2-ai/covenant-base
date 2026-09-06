"""Re-parse ALL ISINs with the new multi-event logic."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from pdf_parser import PDFParser
from parser import build_covenant

config = Config()
parser = PDFParser(config)

with open("results.json", encoding="utf-8") as f:
    data = json.load(f)

updated = 0
covenant_count = 0
skipped = 0

for r in data:
    isin = r["isin"]
    pdf_path = config.downloads_dir / isin / "decision.pdf"

    if not pdf_path.exists():
        skipped += 1
        continue

    result = parser.parse_decision(pdf_path)

    if not result.has_text_layer:
        skipped += 1
        continue

    # Clear old covenants
    r["covenants"] = []

    for clause in result.redemption_clauses:
        # Skip federal-law-only / Program-only references
        if clause.has_federal_law_only and not clause.events:
            if clause.needs_program_check:
                r["needs_program_check"] = True
            continue

        if clause.events:
            for event in clause.events:
                r["covenants"].append(
                    build_covenant(len(r["covenants"]), clause=clause, event=event)
                )
        else:
            r["covenants"].append(
                build_covenant(len(r["covenants"]), clause=clause)
            )

    r["total_covenants"] = len(r["covenants"])
    covenant_count += r["total_covenants"]
    updated += 1

    if r["total_covenants"] > 0:
        print(f"  ✅ {isin} | {r['issuer'][:30]:30s} | {r['total_covenants']} covenant(s)")
    else:
        print(f"  ⬜ {isin} | {r['issuer'][:30]:30s} | 0 covenants")

print(f"\n=== RESULT ===")
print(f"Re-parsed: {updated} ISINs")
print(f"Skipped (no PDF / no text): {skipped}")
print(f"Total covenants: {covenant_count}")

with open("results.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("Saved.")
