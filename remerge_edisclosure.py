"""Remove old e-disclosure covenants and re-merge with better essence."""
import json
import subprocess
import sys
from pathlib import Path

base = Path(__file__).parent

# Step 1: Remove existing e-disclosure covenants from results.json
with open(base / "results.json", encoding="utf-8") as f:
    results = json.load(f)

removed = 0
for r in results:
    covenants = r.get("covenants", [])
    original_len = len(covenants)
    r["covenants"] = [
        c for c in covenants
        if "e-disclosure" not in c.get("document", "")
    ]
    removed += original_len - len(r["covenants"])
    if original_len != len(r["covenants"]):
        r["total_covenants"] = len(r["covenants"])
        # Reset manual check flags
        r.pop("requires_manual_check", None)
        r.pop("manual_check_reason", None)

with open(base / "results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"Removed {removed} old e-disclosure covenants")

# Step 2: Re-run merge
result = subprocess.run(
    [sys.executable, str(base / "merge_edisclosure.py")],
    capture_output=True, text=True, encoding="utf-8"
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)

# Step 3: Re-run Excel export
result = subprocess.run(
    [sys.executable, str(base / "export_excel.py")],
    capture_output=True, text=True, encoding="utf-8"
)
print(result.stdout)
