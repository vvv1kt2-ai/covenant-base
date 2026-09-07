"""Remove e-disclosure covenants, re-merge, re-export."""
import json
from pathlib import Path

base = Path(__file__).parent

# Remove existing e-disclosure covenants
with open(base / "results.json", encoding="utf-8") as f:
    results = json.load(f)

removed = 0
for r in results:
    covenants = r.get("covenants", [])
    original_len = len(covenants)
    r["covenants"] = [c for c in covenants if "e-disclosure" not in c.get("document", "")]
    removed += original_len - len(r["covenants"])
    if original_len != len(r["covenants"]):
        r["total_covenants"] = len(r["covenants"])
        r.pop("requires_manual_check", None)
        r.pop("manual_check_reason", None)
        r.pop("program_checked", None)
        r.pop("program_url", None)
        r.pop("program_status", None)

with open(base / "results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"Removed {removed} old e-disclosure covenants")
print(f"Total now: {sum(len(r.get('covenants', [])) for r in results)}")
