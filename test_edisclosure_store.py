"""Tests for edisclosure_store — persistent caches and section lookup.

Uses self-cleaning directories (Path.mkdir in cwd) — pytest tmp_path and
tempfile.mkdtemp fail under the DSH sandbox (ACL on cross-process scandir).
"""
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from edisclosure_store import (
    load_company_ids,
    save_company_id,
    load_section_refs,
    get_sections_for_emitter,
    FALLBACK_SECTIONS,
)


@pytest.fixture
def work_dir():
    d = Path(f"covtest-{uuid4().hex[:8]}")
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_load_company_ids_missing_file_returns_empty(work_dir):
    assert load_company_ids(work_dir / "nope.json") == {}


def test_load_company_ids_round_trip(work_dir):
    path = work_dir / "company_ids.json"
    path.write_text(json.dumps({"РОЛЬФ": {"company_id": "37542", "source": "known"}}, ensure_ascii=False), encoding="utf-8")
    db = load_company_ids(path)
    assert db["РОЛЬФ"] == {"company_id": "37542", "source": "known"}


def test_save_company_id_writes_and_updates(work_dir):
    path = work_dir / "company_ids.json"
    db = {}
    save_company_id(db, "МВ ФИНАНС", "38369", path=path)
    assert db["МВ ФИНАНС"]["company_id"] == "38369"
    assert db["МВ ФИНАНС"]["source"] == "edisclosure_search"

    # Reload from disk — persisted
    assert load_company_ids(path)["МВ ФИНАНС"]["company_id"] == "38369"

    # Custom source is respected
    save_company_id(db, "РОЛЬФ", "37542", source="known", path=path)
    assert load_company_ids(path)["РОЛЬФ"]["source"] == "known"


def test_load_section_refs_missing_file_returns_empty(work_dir):
    assert load_section_refs(work_dir / "nope.json") == {}


def test_get_sections_aggregates_across_isins():
    refs = {
        "RU000A10ADJ3": {"program_number": "4-00490-R-001P-02E", "sections": [{"section": "9.5"}]},
        "RU000A10BUM9": {"program_number": "4-00490-R-001P-02E", "sections": [{"section": "9.5"}, {"section": "9.4"}]},
        "RU000A10ZZZ9": {"program_number": "4-99999-R-001P-02E", "sections": [{"section": "6.5.1"}]},
    }
    sections = get_sections_for_emitter("ЭНЕРГОТЕХСЕРВИС", "4-00490-R-001P-02E", refs)
    assert sections == ["9.5", "9.4"]  # aggregated, deduplicated, other program untouched


def test_get_sections_fallback_when_no_refs():
    sections = get_sections_for_emitter("Кто-то", "4-00000-R-001P-02E", {})
    assert sections == FALLBACK_SECTIONS[:3]