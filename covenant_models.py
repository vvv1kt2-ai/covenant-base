"""Single source of truth for the covenant data model.

Owns:
- Covenant / ResultEntry dataclasses — the schema of results.json,
- tolerant JSON (de)serialisation (from_dict / to_dict),
- results.json I/O (load_results / save_results),
- covenant construction from decision and program documents,
- category classification (unified 7-category taxonomy).

Consumers: parser.py, merge_programs.py, merge_edisclosure.py,
reparse_missing.py, export_excel.py, reclassify_categories.py.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_QUOTE_LEN = 500
MAX_COND_LEN = 1000
MAX_ESSENCE_LEN = 400


# ---------------------------------------------------------------------------
# Schema: results.json
# ---------------------------------------------------------------------------

@dataclass
class Covenant:
    """One covenant extracted from a decision or program document."""

    number: int = 0  # assigned by ResultEntry.add_covenant
    category: str = ""
    essence: str = ""
    document: str = ""
    section: str = ""
    page: int = 0
    quote: str = ""
    is_provided: bool = True
    conditions: str = ""

    @classmethod
    def from_dict(cls, data):
        """Build from JSON dict. Missing fields -> defaults, unknown keys ignored
        (old records carry a dead per-covenant 'total_covenants' key)."""
        return cls(
            number=data.get("number", 0),
            category=data.get("category", ""),
            essence=data.get("essence", ""),
            document=data.get("document", ""),
            section=data.get("section", ""),
            page=data.get("page", 0),
            quote=data.get("quote", ""),
            is_provided=data.get("is_provided", True),
            conditions=data.get("conditions", ""),
        )

    @property
    def is_from_program(self) -> bool:
        """True if this covenant came from a bond program document
        (either merged from Finam or e-disclosure)."""
        return self.document.startswith("Программа")

    def to_dict(self):
        return {
            "number": self.number,
            "category": self.category,
            "essence": self.essence,
            "document": self.document,
            "section": self.section,
            "page": self.page,
            "quote": self.quote,
            "is_provided": self.is_provided,
            "conditions": self.conditions,
        }


@dataclass
class ResultEntry:
    """One ISIN record in results.json."""

    isin: str
    issuer: str = ""
    issue_name: str = ""
    rating: str = ""
    decision_url: str = ""
    decision_pdf: str = ""
    covenants: list = field(default_factory=list)  # list[Covenant]
    parse_errors: list = field(default_factory=list)  # list[str]
    processed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Program-pipeline fields (set by parser.py / merge_* scripts)
    needs_program_check: bool = False
    program_checked: bool = False
    program_url: str = ""
    program_status: str = ""
    requires_manual_check: bool = False
    manual_check_reason: str = ""

    @property
    def total_covenants(self) -> int:
        """Always len(covenants); never stored separately."""
        return len(self.covenants)

    def add_covenant(self, cov: Covenant) -> Covenant:
        """Append a covenant and assign its sequential number."""
        cov.number = len(self.covenants) + 1
        self.covenants.append(cov)
        return cov

    @classmethod
    def from_dict(cls, data):
        """Build from JSON dict. Missing fields -> defaults, unknown keys ignored."""
        covenants = [Covenant.from_dict(c) for c in data.get("covenants", [])]
        return cls(
            isin=data.get("isin", ""),
            issuer=data.get("issuer", ""),
            issue_name=data.get("issue_name", ""),
            rating=data.get("rating", ""),
            decision_url=data.get("decision_url", ""),
            decision_pdf=data.get("decision_pdf", ""),
            covenants=covenants,
            parse_errors=data.get("parse_errors", []),
            processed_at=data.get("processed_at", ""),
            needs_program_check=data.get("needs_program_check", False),
            program_checked=data.get("program_checked", False),
            program_url=data.get("program_url", ""),
            program_status=data.get("program_status", ""),
            requires_manual_check=data.get("requires_manual_check", False),
            manual_check_reason=data.get("manual_check_reason", ""),
        )

    def to_dict(self):
        return {
            "isin": self.isin,
            "issuer": self.issuer,
            "issue_name": self.issue_name,
            "rating": self.rating,
            "decision_url": self.decision_url,
            "decision_pdf": self.decision_pdf,
            "covenants": [c.to_dict() for c in self.covenants],
            "total_covenants": self.total_covenants,
            "parse_errors": self.parse_errors,
            "processed_at": self.processed_at,
            "needs_program_check": self.needs_program_check,
            "program_checked": self.program_checked,
            "program_url": self.program_url,
            "program_status": self.program_status,
            "requires_manual_check": self.requires_manual_check,
            "manual_check_reason": self.manual_check_reason,
        }


def load_results(path) -> list:
    """Load results.json into ResultEntry models (tolerant of old shapes)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [ResultEntry.from_dict(d) for d in data]


def save_results(path, entries: list) -> None:
    """Save ResultEntry models to results.json in canonical form."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in entries], f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Classification (unified 7-category taxonomy)
# ---------------------------------------------------------------------------

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


def classify_covenant_text(essence, conditions=""):
    """Two-stage classification rule used by builders and reclassification alike.

    Stage 1: classify on essence alone (the event/trigger title carries the type).
    Stage 2: if that yields 'Иное', retry with conditions appended (full clause text).
    """
    category = categorize_covenant(essence)
    if category != "Иное":
        return category
    return categorize_covenant(f"{essence} {conditions or ''}")


def is_real_covenant(text):
    """Check if a program-sourced covenant is a real covenant (not just mechanism description).

    From user: only 'delisting' is a real covenant from programs.
    Liquidation, 'provided by law', and partial redemption mechanism are not.
    """
    lower = text.lower() if text else ""
    return "делистинг" in lower


def reclassify_results(path) -> int:
    """Reclassify stored covenants into the unified taxonomy. Returns count changed.

    Explicit migration pass: from_dict/to_dict stay honest (round-trip never
    mutates data silently). is_provided=False records are markers ("put не
    предусмотрен"), not covenants — their category is left untouched.
    Classification input matches build time: essence + conditions.
    """
    entries = load_results(path)
    changed = 0
    for entry in entries:
        for cov in entry.covenants:
            if not cov.is_provided:
                continue
            new_category = classify_covenant_text(cov.essence, cov.conditions)
            if new_category != cov.category:
                cov.category = new_category
                changed += 1
    save_results(path, entries)
    return changed


# ---------------------------------------------------------------------------
# Builders (return Covenant without number; caller assigns via add_covenant)
# ---------------------------------------------------------------------------

def build_covenant(clause=None, event=None, section_title="", is_provided=True):
    """Build a Covenant from decision PDF clause/event data.

    Used by: parser.py, reparse_missing.py
    """
    if event:
        section = f"п. {clause.section}, {event.event_number}" if clause and clause.section else event.event_number
        conditions = event.full_text[:MAX_COND_LEN]
        return Covenant(
            category=classify_covenant_text(event.title, conditions),
            essence=event.title,
            document="Решение о выпуске",
            section=section,
            page=event.page or (clause.page if clause else 0),
            quote=event.full_text[:MAX_QUOTE_LEN],
            is_provided=True,
            conditions=conditions,
        )
    else:
        essence = section_title or (clause.section_title if clause else "")
        conditions = clause.conditions[:MAX_COND_LEN] if clause and clause.conditions else ""
        if is_provided:
            category = classify_covenant_text(essence, conditions)
        else:
            # Marker record ("put не предусмотрен") — not a classified covenant.
            category = "Досрочное погашение по требованию владельцев"
        return Covenant(
            category=category,
            essence=essence,
            document="Решение о выпуске",
            section=f"п. {clause.section}" if clause and clause.section else "",
            page=clause.page if clause else 0,
            quote=(clause.full_text[:MAX_QUOTE_LEN] if clause else ""),
            is_provided=is_provided,
            conditions=conditions,
        )


def build_program_covenant(title, section, full_text, document_source):
    """Build a Covenant from program PDF data.

    Used by: merge_programs.py, merge_edisclosure.py
    document_source: 'Программа облигаций' or 'Программа облигаций (e-disclosure)'
    """
    essence = _extract_essence(full_text, section) if full_text else title
    conditions = full_text[:MAX_COND_LEN] if full_text else ""
    return Covenant(
        category=classify_covenant_text(essence, conditions),
        essence=essence,
        document=document_source,
        section=f"п. {section}" if section else "",
        page=0,
        quote=full_text[:MAX_QUOTE_LEN] if full_text else "",
        is_provided=True,
        conditions=conditions,
    )


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
