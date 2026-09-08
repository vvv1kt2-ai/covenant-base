"""Re-parse ALL ISINs with the current builder logic (reads cached PDFs)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from covenant_models import build_covenant, load_results, save_results
from pdf_parser import PDFParser

config = Config()
parser = PDFParser(config)

results = load_results("results.json")

updated = 0
covenant_count = 0
skipped = 0

for r in results:
    isin = r.isin
    pdf_path = config.downloads_dir / isin / "decision.pdf"

    if not pdf_path.exists():
        skipped += 1
        continue

    result = parser.parse_decision(pdf_path)

    if not result.has_text_layer:
        skipped += 1
        continue

    # Clear old covenants and rebuild with current logic
    r.covenants = []

    for clause in result.redemption_clauses:
        # Skip federal-law-only / Program-only references
        if clause.has_federal_law_only and not clause.events:
            if clause.needs_program_check:
                r.needs_program_check = True
            continue

        if clause.events:
            for event in clause.events:
                r.add_covenant(build_covenant(clause=clause, event=event))
        else:
            r.add_covenant(build_covenant(clause=clause))

    covenant_count += r.total_covenants
    updated += 1

    if r.total_covenants > 0:
        print(f"  ✅ {isin} | {r.issuer[:30]:30s} | {r.total_covenants} covenant(s)")
    else:
        print(f"  ⬜ {isin} | {r.issuer[:30]:30s} | 0 covenants")

print(f"\n=== RESULT ===")
print(f"Re-parsed: {updated} ISINs")
print(f"Skipped (no PDF / no text): {skipped}")
print(f"Total covenants: {covenant_count}")

save_results("results.json", results)
print("Saved.")
