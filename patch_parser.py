"""Patch pdf_parser.py for edge cases."""
import re
from pathlib import Path

import sys
sys.stdout.reconfigure(encoding='utf-8')

pdf_parser_path = Path(r'D:\парсинг эмиссионки с финам') / 'pdf_parser.py'
content = pdf_parser_path.read_text(encoding='utf-8')

# FIX 1: Pattern 3 - handle "1)." format
# Change [)\.]\s+ to [)\.]+\s+ to match "1)." and "1)" and "1."
old3 = r'[)\.]\s+(.+?)(?=(?:\n\s*\d+\s*[)\.]\s)|\Z)'
new3 = r'[)\.]+\s+(.+?)(?=(?:\n\s*\d+\s*[)\.]+\s)|\Z)'
if old3 in content:
    content = content.replace(old3, new3)
    print("FIX 1 applied: Pattern 3 updated to handle '1).' format")
else:
    print("FIX 1: pattern not found (may already be patched)")

# FIX 2: Pattern 4 - add dash and special chars to bullets
old_bullet = r'[✓✔\u2022\u25C6\u25AA]'
new_bullet = r'[✓✔\u2022\u25C6\u25AA\u002D\u2013\u2014\uf0fc]'
if old_bullet in content:
    content = content.replace(old_bullet, new_bullet)
    print("FIX 2 applied: Added dash, en-dash, em-dash, 0xf0fc to bullets")
else:
    print("FIX 2: pattern not found, trying alternate...")
    # Try finding the bullet pattern
    m = re.search(r'bullet_pattern\s*=\s*re\.compile\(', content)
    if m:
        # Find the full line
        line_start = content.rfind('\n', 0, m.start()) + 1
        line_end = content.find('\n', m.end())
        print(f"  bullet_pattern at char {m.start()}")
        print(f"  Line: {content[line_start:line_end][:200]}")

# FIX 3: Fallback - when is_provided=True but events empty, create single covenant
old_fallback = '''        if not events:
            # "Предусмотрена" but no events — check for Program reference
            program_ref = self._find_program_reference(raw_section)
            has_program_ref = bool(re.search(
                r"программ[аы]\\s+облигаций|пункт[а-я]*\\s+\\d+\\.\\d+.*программ|п\\.\\s*\\d+\\.\\d+",
                raw_section.lower()
            ))
            return RedemptionClause(
                section=section_number, section_title=section_title,
                full_text=raw_section, page=page, is_provided=True,
                conditions="", program_reference=program_ref,
                events=[], has_federal_law_only=True,
                needs_program_check=has_program_ref,
            )'''

new_fallback = '''        if not events:
            # "Предусмотрена" but no structured events found —
            # treat the whole section as a single covenant
            program_ref = self._find_program_reference(raw_section)
            has_program_ref = bool(re.search(
                r"программ[аы]\\s+облигаций|пункт[а-я]*\\s+\\d+\\.\\d+.*программ|п\\.\\s*\\d+\\.\\d+",
                raw_section.lower()
            ))
            # Create a single event from the defining statement
            first_sentences = re.split(r'(?<=[.!?])\\s+', raw_section[:500])
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
            )'''

if old_fallback in content:
    content = content.replace(old_fallback, new_fallback)
    print("FIX 3 applied: Fallback now creates single covenant event")
else:
    print("FIX 3: old fallback not found exactly")
    # Check if new fallback already exists
    if 'has_federal_law_only=False' in content.split('if not events:')[1].split('return RedemptionClause')[0] if 'if not events:' in content else '':
        print("  -> New fallback already present")
    else:
        print("  -> Manual intervention needed")

pdf_parser_path.write_text(content, encoding='utf-8')
print("\\nDone! File saved.")