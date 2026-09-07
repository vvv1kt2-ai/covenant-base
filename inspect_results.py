"""Inspect results.json structure."""
import json

with open("results.json", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total ISINs: {len(data)}")
print(f"First entry keys: {list(data[0].keys())}")
total_cov = sum(len(e.get("covenants", [])) for e in data)
print(f"Total covenants: {total_cov}")
pc = sum(1 for e in data if e.get("program_checked"))
print(f"program_checked: {pc}")
errors = [e for e in data if e.get("error")]
print(f"Errors: {len(errors)}")
for e in errors[:5]:
    print(f"  {e['isin']}: {str(e.get('error',''))[:80]}")
no_cov = [e for e in data if not e.get("covenants") and not e.get("error")]
print(f"Without covenants: {len(no_cov)}")
