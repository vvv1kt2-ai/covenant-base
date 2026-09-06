"""Quick check: do the 24 ISINs without covenants actually have 5.6.1 in their PDFs?"""
import json
import pdfplumber
from pathlib import Path

results_path = Path("results.json")
proj_dir = Path(".")

with open(results_path, encoding="utf-8") as f:
    data = json.load(f)

no_covenant = [r for r in data if not r["parse_errors"] and r["total_covenants"] == 0]
print(f"Checking {len(no_covenant)} ISINs without covenants...\n")

for r in no_covenant:
    isin = r["isin"]
    pdf_path = proj_dir / "downloads" / isin / "decision.pdf"
    if not pdf_path.exists():
        print(f"{isin} | {r['issuer']} | PDF NOT FOUND")
        continue

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"

        has_561 = "5.6.1" in full_text or "5.6.1." in full_text
        has_56 = "5.6" in full_text
        has_pogashenie = "погашени" in full_text.lower()
        has_trebovanie = "требовани" in full_text.lower()
        has_ne_pred = "не предусмотрена" in full_text.lower() or "не предусмотрено" in full_text.lower()

        # Extract surrounding context if 5.6.1 exists
        context = ""
        if has_561:
            idx = full_text.find("5.6.1")
            context = full_text[max(0,idx-20):idx+200].replace("\n", " ")
        elif has_ne_pred:
            # Find where "не предусмотрена" appears
            for phrase in ["не предусмотрена", "не предусмотрено"]:
                idx = full_text.lower().find(phrase)
                if idx >= 0:
                    start = max(0, full_text.rfind("\n", 0, idx))
                    context = full_text[start:idx+100].replace("\n", " ").strip()
                    break

        status = "HAS 5.6.1!" if has_561 else ("не предусмотрена" if has_ne_pred else "???")
        print(f"{isin} | {r['issuer'][:30]:30s} | 5.6.1:{has_561} | погаш:{has_pogashenie} | треб:{has_trebovanie} | не_пред:{has_ne_pred} | {status}")
        if has_561 or (not has_561 and not has_ne_pred):
            print(f"  Context: {context[:200]}")

    except Exception as e:
        print(f"{isin} | ERROR: {e}")
