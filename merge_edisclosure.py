"""Merge e-disclosure program covenants into results.json.

Reads edisclosure_pilot.json, adds new covenants to results.json
with source='Программа облигаций (e-disclosure)'.
Marks PDFs without text layer as requiring manual check.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

EDISCLOSURE_SOURCE = "Программа облигаций (e-disclosure)"


def extract_essence(full_text, section):
    """Extract meaningful essence from program covenant full_text.

    Prioritizes early redemption conditions over general rights.
    """
    if not full_text:
        return f"Положение п. {section} Программы (из Программы)"

    text = full_text.replace("\n", " ").strip()
    import re

    def _find_sentence(text, start_pattern):
        """Find a sentence starting with pattern, skipping abbreviations (п. ст. с.).
        Matches until a period followed by space+capital letter or end of text."""
        m = re.search(start_pattern, text, re.IGNORECASE)
        if not m:
            return None
        start = m.start()
        # Now find the end of this sentence: period NOT followed by lowercase letter
        pos = m.end()
        while pos < len(text):
            if text[pos] == '.':
                # Check if next char is space+capital or end → sentence end
                rest = text[pos+1:pos+4].lstrip()
                if not rest or rest[0].isupper() or rest[0] in '«"':
                    # Sentence end
                    return text[start:pos+1].strip()
            pos += 1
        # No proper sentence end found, return everything from start
        return text[start:].strip()[:400]

    # PRIORITY 1: "право требовать досрочного погашения"
    dosr_sentence = _find_sentence(text, r'(?:имеет право|вправе|предоставляется право)\s+требовать[^.]*досрочн')
    if dosr_sentence:
        # Prepend the condition: "в случае..."
        case_sentence = _find_sentence(text, r'в случае[а-яё]*\s+(?:принятия|нарушения|ликвидации|делистинга|ненаступления)')
        if not case_sentence:
            case_sentence = _find_sentence(text, r'в случае[а-яё]*\s+')
        essence = ""
        if case_sentence:
            essence = case_sentence + " "
        essence += dosr_sentence
        if len(essence) > 400:
            essence = essence[:400] + "…"
        return essence + " (из Программы)"

    # PRIORITY 2: "в случае делистинга/ликвидации"
    case_sentence = _find_sentence(text, r'в случае[а-яё]*\s+(?:делистинг|ликвидаци)')
    if case_sentence:
        if len(case_sentence) > 400:
            case_sentence = case_sentence[:400] + "…"
        return case_sentence + " (из Программы)"

    # PRIORITY 3: "по 100% от непогашенной части"
    price_match = re.search(r'((?:по|в размере)\s+\d+%[^.]+?\.)', text, re.IGNORECASE)
    if price_match:
        essence = price_match.group(1).strip()
        if len(essence) > 400:
            essence = essence[:400] + "…"
        return essence + " (из Программы)"

    # PRIORITY 4: Any "в случае..."
    case_sentence = _find_sentence(text, r'в случае[а-яё]*\s+')
    if case_sentence:
        if len(case_sentence) > 400:
            case_sentence = case_sentence[:400] + "…"
        return case_sentence + " (из Программы)"

    # Fallback: first meaningful sentence
    sentences = [s.strip() for s in text.split(".") if len(s.strip()) > 30]
    if sentences:
        essence = sentences[0] + "."
        if len(essence) > 400:
            essence = essence[:400] + "…"
        return essence + " (из Программы)"

    return f"Положение п. {section} Программы (из Программы)"


def main():
    base = Path(__file__).parent

    with open(base / "results.json", encoding="utf-8") as f:
        results = json.load(f)

    with open(base / "edisclosure_pilot.json", encoding="utf-8") as f:
        edisclosure = json.load(f)

    # Index results by ISIN
    results_by_isin = {r["isin"]: r for r in results}

    merged_count = 0
    new_covenant_count = 0
    no_text_layer_isins = []

    for entry in edisclosure:
        emitter = entry.get("emitter", "?")
        company_id = entry.get("company_id", "?")
        prog_num = entry.get("program_number", "?")
        isins = entry.get("isins", [])
        sections = entry.get("target_sections", [])
        status = entry.get("status", "")
        downloaded_files = entry.get("downloaded", [])
        program_covenants = entry.get("program_covenants", {})

        # Check if PDF had no text layer
        if status == "downloaded" and not program_covenants:
            # File downloaded but no covenants parsed — might be no text layer
            for isin in isins:
                if isin in results_by_isin:
                    entry_r = results_by_isin[isin]
                    entry_r["program_checked"] = True
                    entry_r["program_url"] = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
                    entry_r["program_status"] = "no_covenants_found"
                    entry_r["requires_manual_check"] = True
                    entry_r["manual_check_reason"] = (
                        "Программа облигаций скачана с e-disclosure, "
                        "но ковенанты не найдены (возможно, нет текстового слоя)"
                    )
                    no_text_layer_isins.append(isin)
                    logger.warning(f"  {isin} ({emitter}): downloaded but no covenants — marked for manual check")
            continue

        # Process covenants for each ISIN
        for isin in isins:
            if isin not in results_by_isin:
                logger.warning(f"ISIN {isin} not found in results.json, skipping")
                continue

            entry_r = results_by_isin[isin]
            existing_count = len(entry_r.get("covenants", []))

            # Collect all covenants from all downloaded program files
            all_program_events = []
            for fname, events in program_covenants.items():
                for ev in events:
                    all_program_events.append(ev)

            if not all_program_events:
                continue

            for ev in all_program_events:
                title = ev.get("title", "")
                section = ev.get("section", "?")
                full_text = ev.get("full_text", "")

                # Generate meaningful essence from full_text
                essence = extract_essence(full_text, section)

                new_covenant = {
                    "number": existing_count + 1,
                    "category": "Досрочное погашение по требованию владельцев",
                    "essence": essence,
                    "document": EDISCLOSURE_SOURCE,
                    "section": f"п. {section}",
                    "page": 0,
                    "quote": full_text[:500],
                    "is_provided": True,
                    "conditions": full_text[:500],
                }
                entry_r["covenants"].append(new_covenant)
                existing_count += 1
                new_covenant_count += 1
                logger.info(f"  +{isin} ({emitter}): {essence}")

            entry_r["total_covenants"] = len(entry_r["covenants"])
            entry_r["program_checked"] = True
            entry_r["program_url"] = f"https://e-disclosure.ru/portal/files.aspx?id={company_id}&type=7"
            entry_r["program_status"] = status
            merged_count += 1

    # Save
    with open(base / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"MERGE COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"ISINs with new covenants merged: {merged_count}")
    logger.info(f"Total new covenants added: {new_covenant_count}")
    if no_text_layer_isins:
        logger.info(f"Marked for manual check (no covenants found): {len(no_text_layer_isins)}")
        for isin in no_text_layer_isins:
            logger.info(f"  {isin}")

    total_covenants = sum(len(r.get("covenants", [])) for r in results)
    isins_with_covs = sum(1 for r in results if len(r.get("covenants", [])) > 0)
    manual_check = sum(1 for r in results if r.get("requires_manual_check"))
    logger.info(f"\nUpdated totals:")
    logger.info(f"  Total ISINs: {len(results)}")
    logger.info(f"  ISINs with covenants: {isins_with_covs}")
    logger.info(f"  Total covenants: {total_covenants}")
    logger.info(f"  Requires manual check: {manual_check}")


if __name__ == "__main__":
    main()
