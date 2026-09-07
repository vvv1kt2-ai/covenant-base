"""Shared covenant building and classification functions.

Eliminates duplication between parser.py, merge_programs.py, merge_edisclosure.py.
Single source of truth for covenant dict schema and category logic.
"""
import re

MAX_QUOTE_LEN = 500
MAX_COND_LEN = 1000
MAX_ESSENCE_LEN = 400


def build_covenant(existing_count, clause=None, event=None, section_title="", is_provided=True):
    """Build a covenant dict from decision PDF clause/event data.

    Used by: parser.py (main parse pipeline)
    """
    if event:
        section = f"п. {clause.section}, {event.event_number}" if clause and clause.section else event.event_number
        return {
            "number": existing_count + 1,
            "category": "Досрочное погашение по требованию владельцев",
            "essence": event.title,
            "document": "Решение о выпуске",
            "section": section,
            "page": event.page or (clause.page if clause else 0),
            "quote": event.full_text[:MAX_QUOTE_LEN],
            "is_provided": True,
            "conditions": event.full_text[:MAX_COND_LEN],
            "total_covenants": 0,  # caller sets after collecting all
        }
    else:
        return {
            "number": existing_count + 1,
            "category": "Досрочное погашение по требованию владельцев",
            "essence": section_title or (clause.section_title if clause else ""),
            "document": "Решение о выпуске",
            "section": f"п. {clause.section}" if clause and clause.section else "",
            "page": clause.page if clause else 0,
            "quote": (clause.full_text[:MAX_QUOTE_LEN] if clause else ""),
            "is_provided": is_provided,
            "conditions": (clause.conditions[:MAX_COND_LEN] if clause and clause.conditions else ""),
            "total_covenants": 0,
        }


def build_program_covenant(existing_count, title, section, full_text, document_source):
    """Build a covenant dict from program PDF data.

    Used by: merge_programs.py, merge_edisclosure.py
    document_source: 'Программа облигаций' or 'Программа облигаций (e-disclosure)'
    """
    essence = _extract_essence(full_text, section) if full_text else title
    category = categorize_covenant(full_text or title)

    return {
        "number": existing_count + 1,
        "category": category,
        "essence": essence,
        "document": document_source,
        "section": f"п. {section}" if section else "",
        "page": 0,
        "quote": full_text[:MAX_QUOTE_LEN] if full_text else "",
        "is_provided": True,
        "conditions": full_text[:MAX_COND_LEN] if full_text else "",
    }


def categorize_covenant(text):
    """Classify a covenant into one of the defined categories.

    Categories:
    - Раскрытие отчётности
    - Выплата дивидендов, распределение прибыли
    - Утрата контроля
    - Долговая нагрузка
    - Кросс-дефолт
    - Делистинг
    - Иное
    """
    lower = text.lower() if text else ""

    # Делистинг
    if "делистинг" in lower:
        return "Делистинг"

    # Раскрытие отчётности
    if any(kw in lower for kw in [
        "отчётност", "отчетност", "консолидир", "промежуточ",
        "годов", "аудит", "раскрытие информации", "бухгалтерск",
    ]):
        return "Раскрытие отчётности"

    # Выплата дивидендов
    if any(kw in lower for kw in [
        "дивиденд", "распределени прибыл", "выплату доход",
        "купон", "выплат доход",
    ]):
        return "Выплата дивидендов, распределение прибыли"

    # Утрата контроля
    if any(kw in lower for kw in [
        "утрат", "контрол", "отчуждени", "снижение дол",
        "сделк", "реорганизац", "концентрац",
    ]):
        return "Утрата контроля"

    # Долговая нагрузка
    if any(kw in lower for kw in [
        "задолженност", "долгов", "кредитор", "заём",
        "платёжеспособн", "финансов полож",
        "соотношение дол", "леверидж", "целев",
    ]):
        return "Долговая нагрузка"

    # Кросс-дефолт
    if any(kw in lower for kw in [
        "кросс-дефолт", "кросс дефолт", "дефолт по друг",
        "неисполнени обязательств по иным",
    ]):
        return "Кросс-дефолт"

    return "Иное"


def is_real_covenant(text):
    """Check if a program-sourced covenant is a real covenant (not just mechanism description).

    From user: only 'delisting' is a real covenant from programs.
    Liquidation, 'provided by law', and partial redemption mechanism are not.
    """
    lower = text.lower() if text else ""
    return "делистинг" in lower


def _extract_essence(full_text, section):
    """Extract meaningful essence from program covenant full_text.

    Prioritizes early redemption conditions over general rights.
    Skips abbreviations (п. ст. с.) when finding sentence boundaries.
    """
    if not full_text:
        return f"Положение п. {section} Программы (из Программы)"

    text = full_text.replace("\n", " ").strip()

    def _find_sentence(text, start_pattern):
        """Find a sentence, skipping abbreviations (п. ст. с.)."""
        m = re.search(start_pattern, text, re.IGNORECASE)
        if not m:
            return None
        start = m.start()
        pos = m.end()
        while pos < len(text):
            if text[pos] == '.':
                rest = text[pos+1:pos+4].lstrip()
                if not rest or rest[0].isupper() or rest[0] in '«"':
                    return text[start:pos+1].strip()
            pos += 1
        return text[start:].strip()[:MAX_ESSENCE_LEN]

    # PRIORITY 1: "право требовать досрочного погашения"
    dosr = _find_sentence(text, r'(?:имеет право|вправе|предоставляется право)\s+требовать[^.]*досрочн')
    if dosr:
        case = _find_sentence(text, r'в случае[а-яё]*\s+(?:принятия|нарушения|ликвидации|делистинга|ненаступления)')
        if not case:
            case = _find_sentence(text, r'в случае[а-яё]*\s+')
        essence = (case + " " + dosr) if case else dosr
        return (essence[:MAX_ESSENCE_LEN] + "…")[:MAX_ESSENCE_LEN + 1] if len(essence) > MAX_ESSENCE_LEN else essence

    # PRIORITY 2: "в случае делистинга/ликвидации"
    case = _find_sentence(text, r'в случае[а-яё]*\s+(?:делистинг|ликвидаци)')
    if case:
        return (case[:MAX_ESSENCE_LEN] + "…")[:MAX_ESSENCE_LEN + 1] if len(case) > MAX_ESSENCE_LEN else case

    # PRIORITY 3: "по 100% от непогашенной части"
    price = re.search(r'((?:по|в размере)\s+\d+%[^.]+?\.)', text, re.IGNORECASE)
    if price:
        p = price.group(1).strip()
        return (p[:MAX_ESSENCE_LEN] + "…")[:MAX_ESSENCE_LEN + 1] if len(p) > MAX_ESSENCE_LEN else p

    # PRIORITY 4: Any "в случае..."
    for m in re.finditer(r'(в случае[а-яё]*\s+[^.]+?\.)', text, re.IGNORECASE):
        c = m.group(1).strip()
        if len(c) >= 30 or not c.rstrip().endswith(('п.', 'ст.', 'с.', 'пп.')):
            return (c[:MAX_ESSENCE_LEN] + "…")[:MAX_ESSENCE_LEN + 1] if len(c) > MAX_ESSENCE_LEN else c

    # Fallback
    sentences = [s.strip() for s in text.split(".") if len(s.strip()) > 30]
    if sentences:
        e = sentences[0] + "."
        return (e[:MAX_ESSENCE_LEN] + "…")[:MAX_ESSENCE_LEN + 1] if len(e) > MAX_ESSENCE_LEN else e

    return f"Положение п. {section} Программы (из Программы)"
