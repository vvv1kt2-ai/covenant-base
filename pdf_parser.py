"""PDF parsing for bond emission documents using pdfplumber."""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

import pdfplumber

from config import Config

logger = logging.getLogger(__name__)

# Keywords that start a covenant event
_EVENT_KEYWORDS = [
    "нераскрыт", "неопубликован", "не опубликован", "нарушен", "нарушени",
    "изменени", "превышен", "превышени", "ликвидаци", "реорганизац",
    "снижени", "понижени", "установлен", "невыплат", "неперечислен",
    "существенн", "ухудшен", " прекращени",
]

# Words that indicate a date definition, not a real event
_DATE_DEF_WORDS = ["является", "считается", "наступает", "возникает"]

# Keywords that indicate disclosure/reporting/procedural text, NOT covenant events
_DISCLOSURE_KEYWORDS = [
    "в ленте новостей",
    "ленте новостей",
    "порядок раскрытия",
    "раскрывается эмитентом",
    "эмитент раскрывает",
    "информация об итогах",
    "сведения о количестве",
    "информация о возникновении",
    "информация о прекращении",
]

# Plain-text trigger patterns (for sections that state covenants as flowing text)
_PLAIN_TRIGGER_PATTERNS = [
    re.compile(r"в\s+случа[ея]\s+(делистинг\w+)", re.IGNORECASE),
    re.compile(r"в\s+случа[ея]\s+(нарушен\w+\s+эмитент\w+\s+срок\w+)", re.IGNORECASE),
    re.compile(
        r"в\s+случа[ея]\s+(снижени\w+|ликвидаци\w+|реорганизац\w+|конкурсн\w+|банкротств\w+|установлен\w+\s+существенн\w+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"в\s+случа[ея]\s+(неопубликовани\w+|невыплат\w+|неперечислен\w+)",
        re.IGNORECASE,
    ),
]


@dataclass
class CovenantEvent:
    """A single covenant event (trigger condition) from section 5.6.1."""
    event_number: str
    title: str
    full_text: str
    page: int


@dataclass
class RedemptionClause:
    """Parsed redemption clause from a bond document."""
    section: str
    section_title: str
    full_text: str
    page: int
    is_provided: bool
    conditions: str = ""
    program_reference: Optional[str] = None
    events: List[CovenantEvent] = field(default_factory=list)
    has_federal_law_only: bool = False
    needs_program_check: bool = False


@dataclass
class DocumentParseResult:
    """Result of parsing a single PDF document."""
    file_path: str
    has_text_layer: bool
    redemption_clauses: list = field(default_factory=list)
    raw_text: str = ""
    error: Optional[str] = None


class PDFParser:
    """Parse bond emission PDF documents."""

    def __init__(self, config: Config):
        self.config = config

    def parse_decision(self, pdf_path: Path) -> DocumentParseResult:
        """Parse a bond issuance decision PDF. Look for section 5.6.1."""
        result = DocumentParseResult(file_path=str(pdf_path), has_text_layer=False)

        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        result.has_text_layer = True
                        full_text += f"\n--- PAGE {page_num} ---\n{text}"

                result.raw_text = full_text

                if not result.has_text_layer:
                    result.error = "No text layer in PDF"
                    logger.warning(f"No text layer in {pdf_path.name}")
                    return result

                clause = self._find_redemption_clause(full_text, "5.6.1")
                if clause:
                    result.redemption_clauses.append(clause)
                else:
                    fallback = self._find_not_provided_fallback(full_text)
                    if fallback:
                        result.redemption_clauses.append(fallback)
                        logger.info(f"Found 'не предусмотрена' fallback in {pdf_path.name}")
                    else:
                        logger.info(f"Section 5.6.1 not found in {pdf_path.name}")

        except Exception as e:
            result.error = f"PDF parse error: {e}"
            logger.error(f"Failed to parse {pdf_path.name}: {e}")

        return result

    def parse_program(self, pdf_path: Path, section_hint: str = None) -> DocumentParseResult:
        """Parse a bond program PDF."""
        result = DocumentParseResult(file_path=str(pdf_path), has_text_layer=False)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        result.has_text_layer = True
                        full_text += f"\n--- PAGE {page_num} ---\n{text}"
                result.raw_text = full_text
                if not result.has_text_layer:
                    result.error = "No text layer in PDF"
                    return result
                for pattern in [r"5\.6\.1", r"досрочн\w+\s+погашени\w+", r"по\s+требовани\w+\s+владельцев"]:
                    result.redemption_clauses.extend(self._find_sections_by_pattern(full_text, pattern))
        except Exception as e:
            result.error = f"PDF parse error: {e}"
        return result

    def _is_not_provided(self, text: str) -> bool:
        """Check if the text says put option is NOT provided."""
        patterns = [
            r"не\s+предусмотрен[аоы]",
            r"не\s+установлен[аоы]",
            r"не\s+предоставлен[аоы]",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_disclosure_or_procedural(self, text: str) -> bool:
        """Check if text is a disclosure/reporting procedure, NOT a covenant event."""
        text_lower = text.lower().strip()

        # Direct check: starts with disclosure keywords
        for kw in _DISCLOSURE_KEYWORDS:
            if text_lower.startswith(kw):
                return True

        # Check if the text is primarily about disclosure timing
        if re.match(
            r"(?:в\s+ленте\s+новостей|раскрывает\w*|раскрывается)\b.*"
            r"не\s+позднее\s+\d+",
            text_lower,
        ):
            has_event = any(kw in text_lower for kw in _EVENT_KEYWORDS)
            if not has_event:
                return True

        return False

    def _extract_plain_text_triggers(self, section_text: str) -> List[CovenantEvent]:
        """Extract covenants stated as plain text (not in numbered/bullet lists)."""
        events = []
        seen_titles = set()

        for pattern in _PLAIN_TRIGGER_PATTERNS:
            for m in pattern.finditer(section_text):
                trigger_name = m.group(1).strip()

                start = max(0, m.start() - 300)
                end = min(len(section_text), m.end() + 300)
                event_text = self._clean_event_text(section_text[start:end])

                title = f"Досрочное погашение в случае {trigger_name}"
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                events.append(CovenantEvent(
                    event_number=str(len(events) + 1),
                    title=title,
                    full_text=event_text,
                    page=0,
                ))

        return events

    def _find_redemption_clause(self, text: str, section_number: str) -> Optional[RedemptionClause]:
        """Find section 5.6.1 and parse its contents."""
        section_pattern = re.compile(
            rf"{re.escape(section_number)}[\.\s]"
            rf"(.*?)"
            rf"(?=\n\s*(?:---\s*PAGE\s+\d+\s*---\s*\n\s*)?\d+\.\d+[\.\s]"
            rf"|\n\s*(?:---\s*PAGE\s+\d+\s*---\s*\n\s*)?6[\.\s]"
            rf"|\Z)",
            re.DOTALL | re.IGNORECASE,
        )

        match = section_pattern.search(text)
        if not match:
            return None

        raw_section = match.group(0).strip()

        title_match = re.match(
            rf"{re.escape(section_number)}[\.\s]*(.*?)(?:\n|$)",
            raw_section, re.IGNORECASE,
        )
        section_title = title_match.group(1).strip() if title_match else ""
        page = self._find_page_number(text, match.start())

        defining_text = "\n".join(raw_section.split("\n")[:5]).lower()

        if self._is_not_provided(defining_text):
            program_ref = self._find_program_reference(raw_section)
            has_program_ref = bool(re.search(
                r"программ[аы]\s+облигаций|пункт[а-я]*\s+\d+\.\d+.*программ|п\.\s*\d+\.\d+",
                raw_section.lower()
            ))
            return RedemptionClause(
                section=section_number, section_title=section_title,
                full_text=raw_section, page=page, is_provided=False,
                conditions="", program_reference=program_ref,
                events=[], has_federal_law_only=True,
                needs_program_check=has_program_ref,
            )

        events = self._extract_events(raw_section)

        if not events:
            program_ref = self._find_program_reference(raw_section)
            has_program_ref = bool(re.search(
                r"программ[аы]\s+облигаций|пункт[а-я]*\s+\d+\.\d+.*программ|п\.\s*\d+\.\d+",
                raw_section.lower()
            ))
            first_sentences = re.split(r'(?<=[.!?])\s+', raw_section[:500])
            title = first_sentences[0] if first_sentences else section_title
            if len(title) > 200:
                title = title[:200]
            single_event = CovenantEvent(
                event_number="1", title=title,
                full_text=raw_section[:1000], page=0,
            )
            return RedemptionClause(
                section=section_number, section_title=section_title,
                full_text=raw_section, page=page, is_provided=True,
                conditions=raw_section[:1000], program_reference=program_ref,
                events=[single_event], has_federal_law_only=False,
                needs_program_check=has_program_ref,
            )

        return RedemptionClause(
            section=section_number, section_title=section_title,
            full_text=raw_section, page=page, is_provided=True,
            conditions=raw_section, program_reference=self._find_program_reference(raw_section),
            events=events,
        )

    def _extract_events(self, section_text: str) -> List[CovenantEvent]:
        """
        Extract individual covenant events from section 5.6.1 text.
        Priority:
          1. "Событие досрочного погашения ... – N:" (formal pattern)
          2. "Событие N:" at START of line only
          3. Numbered items "1) ..." that start with event keywords
          4. Bullet/checkmark items with event keywords
          5. Plain-text triggers ("в случае делистинга/нарушения/etc.")
        After extraction, disclosure/procedural items are filtered out.
        """
        events = []

        # --- Pattern 1: "Событие досрочного погашения ... – N:" ---
        event_pattern_1 = re.compile(
            r"Событи[ея]\s+досрочного\s+погашени\w+[^:\n]*?[–\-—]\s*(\d+)[\s:]+",
            re.IGNORECASE,
        )
        matches = list(event_pattern_1.finditer(section_text))

        if matches and len(matches) >= 2:
            seen_nums = {}
            for i, m in enumerate(matches):
                num = m.group(1)
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(section_text)
                event_text = self._clean_event_text(section_text[start:end])
                first_words = event_text.lower()[:50]
                if any(w in first_words for w in _DATE_DEF_WORDS):
                    continue
                if self._is_disclosure_or_procedural(event_text):
                    continue
                if num in seen_nums:
                    continue
                seen_nums[num] = True
                title = self._extract_event_title(event_text)
                events.append(CovenantEvent(
                    event_number=num, title=title,
                    full_text=event_text, page=0,
                ))
            if events:
                return events

        # --- Pattern 2: "Событие N:" at START of line, colon required ---
        event_pattern_2 = re.compile(
            r"(?:^|\n)\s*Событие\s+(\d+)\s*[:]\s*(.+?)(?=(?:\n\s*Событие\s+\d+\s*[:])|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        matches = list(event_pattern_2.finditer(section_text))

        if matches and len(matches) >= 2:
            seen_nums = {}
            for m in matches:
                num = m.group(1)
                event_text = self._clean_event_text(m.group(2))
                first_words = event_text.lower()[:50]
                if any(w in first_words for w in _DATE_DEF_WORDS):
                    continue
                if self._is_disclosure_or_procedural(event_text):
                    continue
                if num in seen_nums:
                    continue
                seen_nums[num] = True
                title = self._extract_event_title(event_text)
                events.append(CovenantEvent(
                    event_number=num, title=title,
                    full_text=event_text, page=0,
                ))
            if events:
                return events

        # --- Pattern 3: Numbered list "1) ..." / "1. ..." ---
        numbered_pattern = re.compile(
            r"(?:^|\n)\s*(\d+)\s*[)\.]+\s+(.+?)(?=(?:\n\s*\d+\s*[)\.]+\s)|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        matches = list(numbered_pattern.finditer(section_text))

        if len(matches) >= 2:
            event_like = 0
            for m in matches:
                text_start = m.group(2).lower()[:100]
                if any(kw in text_start for kw in _EVENT_KEYWORDS):
                    event_like += 1

            if event_like >= len(matches) * 0.5:
                seen_nums = {}
                for m in matches:
                    num = m.group(1)
                    event_text = self._clean_event_text(m.group(2))
                    if self._is_disclosure_or_procedural(event_text):
                        continue
                    title = self._extract_event_title(event_text)
                    if title.strip() and num not in seen_nums:
                        seen_nums[num] = True
                        events.append(CovenantEvent(
                            event_number=num, title=title,
                            full_text=event_text, page=0,
                        ))
                if events:
                    return events

        # --- Pattern 4: Bullet/checkmark items "✓ ..." or "- ..." ---
        bullet_pattern = re.compile(
            r"(?:^|\n)\s*[✓✔•◆▪\-–—\uf0fc]\s+(.+?)(?=(?:\n\s*[✓✔•◆▪\-–—\uf0fc]\s)|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        matches = list(bullet_pattern.finditer(section_text))
        if len(matches) >= 2:
            raw_events = []
            for i, m in enumerate(matches):
                event_text = self._clean_event_text(m.group(1))
                title = self._extract_event_title(event_text)
                is_disclosure = self._is_disclosure_or_procedural(event_text)
                if title.strip():
                    raw_events.append((CovenantEvent(
                        event_number=str(i + 1), title=title,
                        full_text=event_text, page=0,
                    ), is_disclosure))
            # Filter out disclosure items
            real_events = [ev for ev, disc in raw_events if not disc]
            # Re-number
            for idx, ev in enumerate(real_events):
                ev.event_number = str(idx + 1)
            if len(real_events) >= 2:
                return real_events
            events = real_events  # Keep for potential merge with plain-text

        # --- Pattern 5: Plain-text triggers ---
        # "в случае делистинга", "в случае нарушения" etc.
        plain_events = self._extract_plain_text_triggers(section_text)
        if plain_events:
            # Merge: existing events + plain-text triggers
            all_events = events.copy() if events else []
            for pe in plain_events:
                # Avoid duplicates (check overlap in first 50 chars of title)
                if not any(
                    pe.title.lower()[:50] in ev.title.lower()
                    or ev.title.lower()[:50] in pe.title.lower()
                    for ev in all_events
                ):
                    all_events.append(pe)
            # Re-number
            for idx, ev in enumerate(all_events):
                ev.event_number = str(idx + 1)
            if all_events:
                return all_events

        # --- Deduplicate: keep only first event per number ---
        if events:
            seen = set()
            unique = []
            for ev in events:
                key = ev.event_number
                if key not in seen:
                    seen.add(key)
                    unique.append(ev)
            events = unique

        return events

    def _clean_event_text(self, text: str) -> str:
        """Clean event text: remove trailing boilerplate phrases."""
        text = re.sub(
            r"\s*считается\s+наступившим.*$",
            "", text, flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"\s*---\s*PAGE\s+\d+\s*---\s*", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_event_title(self, event_text: str) -> str:
        """Extract a short title from event text."""
        first_sentence = re.match(r"(.+?)(?:\.|;|\n\n|\Z)", event_text)
        title = first_sentence.group(1).strip() if first_sentence else event_text[:150].strip()
        title = re.sub(r"\s+", " ", title)
        if len(title) > 200:
            title = title[:200] + "…"
        return title

    def _find_sections_by_pattern(self, text: str, pattern: str) -> list:
        """Find all sections matching a regex pattern."""
        results = []
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 1000)
            context = text[start:end]
            page = self._find_page_number(text, match.start())
            clause = RedemptionClause(
                section="", section_title="",
                full_text=context.strip(), page=page,
                is_provided=not self._is_not_provided(context.lower()),
            )
            results.append(clause)
        return results

    def _find_page_number(self, text: str, position: int) -> int:
        """Find the page number for a given position in the text."""
        page_pattern = re.compile(r"--- PAGE (\d+) ---")
        last_page = 1
        for m in page_pattern.finditer(text):
            if m.start() <= position:
                last_page = int(m.group(1))
            else:
                break
        return last_page

    def _find_program_reference(self, text: str) -> Optional[str]:
        """Find reference to program document in the text."""
        m = re.search(
            r"(?:https?://[^\s]+|[\w\-]+\.pdf|программ[аы]\s+облигаций)",
            text, re.IGNORECASE,
        )
        return m.group(0) if m else None

    def _find_not_provided_fallback(self, text: str) -> Optional[RedemptionClause]:
        """Fallback: search for "погашение ... не предусмотрена" without section number."""
        pattern = re.compile(
            r"погашени\w+.*?по\s+требовани\w+.*?владельцев.*?(?:не\s+предусмотрен[аоы]|не\s+установлен[аоы])",
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None

        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 200)
        context = text[start:end].strip()

        preceding = text[max(0, match.start() - 300):match.start()]
        section_match = re.search(r"(\d+\.\d+)\s", preceding)
        section = section_match.group(1) if section_match else ""
        page = self._find_page_number(text, match.start())

        return RedemptionClause(
            section=section,
            section_title="Досрочное погашение облигаций по требованию владельцев",
            full_text=context, page=page, is_provided=False,
            conditions="", events=[], has_federal_law_only=True,
        )
