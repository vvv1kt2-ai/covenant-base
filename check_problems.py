"""Quick check: parse problem ISINs."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import Config
from pdf_parser import PDFParser

config = Config()
parser = PDFParser(config)

with open("results.json", encoding="utf-8") as f:
    data = json.load(f)

# All АПРИ + ПКО + problem ISINs
check = []
for r in data:
    issuer = r.get("issuer", "")
    if any(x in issuer for x in ["АПРИ", "ЮРИДИЧЕСКАЯ", "ЛАЙФСТРИМ", "СИМПЛ", "ЛАЗЕРНЫЕ", "ТД РКС", "СЛАВЯНСК", "ЭКОНОМЛИЗИНГ", "ФИЛБЕРТ"]):
        check.append(r["isin"])

for isin in check:
    pdf_path = Path("downloads") / isin / "decision.pdf"
    if not pdf_path.exists():
        print(f"{isin}: PDF NOT FOUND\n")
        continue

    result = parser.parse_decision(pdf_path)
    issuer = next((r["issuer"] for r in data if r["isin"] == isin), "")

    cov_count = 0
    for clause in result.redemption_clauses:
        if not clause.has_federal_law_only or clause.events:
            cov_count += len(clause.events) if clause.events else (1 if clause.is_provided else 0)

    print(f"{isin} | {issuer[:35]:35s} | covenants={cov_count} | events={len(clause.events) if result.redemption_clauses else 0}")
    for clause in result.redemption_clauses:
        if clause.events:
            for ev in clause.events:
                print(f"  [{ev.event_number}] {ev.title[:100]}")
        elif clause.is_provided and not clause.has_federal_law_only:
            print(f"  (single) {clause.section_title[:80]}")
        elif clause.has_federal_law_only:
            print(f"  (0 — не предусмотрена / ссылка)")
    print()
