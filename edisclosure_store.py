"""Persistent storage layer for the e-disclosure pipeline.

Owns: the companyId cache (company_ids.json), section references extracted
from decisions (program_section_refs.json), and the lookup logic on top of
them (with fallback sections when a decision names none). Paths are module
constants but every loader takes an optional path= for testability.
"""
import json
import logging
from pathlib import Path

from config import Config

logger = logging.getLogger(__name__)

_config = Config()

# Persistent companyId database
COMPANY_IDS_PATH = _config.base_dir / "company_ids.json"

# Program section references (extracted from decisions)
SECTION_REFS_PATH = _config.base_dir / "program_section_refs.json"

# Fallback sections if not found in decision
FALLBACK_SECTIONS = ["9.5.1", "9.5", "9.4", "9.3", "9.6", "6.5.1", "10.5.1", "10.5"]


def load_company_ids(path=COMPANY_IDS_PATH):
    """Load known companyIds from persistent JSON file."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_company_id(company_ids_db, name, company_id, source="edisclosure_search", path=COMPANY_IDS_PATH):
    """Save a companyId to the persistent database and to disk."""
    company_ids_db[name] = {
        "company_id": company_id,
        "source": source,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(company_ids_db, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved companyId {company_id} for {name} to {Path(path).name}")


def load_section_refs(path=SECTION_REFS_PATH):
    """Load pre-extracted section references from decisions."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_sections_for_emitter(emitter_name, program_number, section_refs):
    """Get the program sections to search, based on decision references."""
    sections = []

    # Look up by program number across all referenced ISINs
    for isin_key, ref_data in section_refs.items():
        if ref_data.get("program_number") == program_number:
            for ref in ref_data.get("sections", []):
                sec = ref.get("section")
                if sec and sec not in sections:
                    sections.append(sec)

    if sections:
        logger.info(f"Sections from decision: {sections}")
    else:
        logger.warning(f"No section refs found for {emitter_name}, using fallback: {FALLBACK_SECTIONS[:3]}")
        sections = FALLBACK_SECTIONS[:3]  # Try top 3

    return sections
