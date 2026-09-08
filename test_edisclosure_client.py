"""Tests for edisclosure_client — pure helpers only (no page interaction)."""
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from edisclosure_client import (
    EdisclosureClient,
    extract_company_id_from_url,
    extract_pdfs_from_bytes,
    extract_pdfs_from_zip,
    filter_program_files,
)


@pytest.fixture
def work_dir():
    d = Path(f"covtest-{uuid4().hex[:8]}")
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_file(text, href="https://e-disclosure.ru/FileLoad.ashx?Fileid=1", doc_type="", row=""):
    return {"fileId": "", "linkText": text, "href": href, "rowText": row, "docType": doc_type}


# ---------------------------------------------------------------------------
# extract_company_id_from_url
# ---------------------------------------------------------------------------

def test_extract_company_id_various_url_shapes():
    assert extract_company_id_from_url("https://e-disclosure.ru/portal/company.aspx?id=37542") == "37542"
    assert extract_company_id_from_url("https://e-disclosure.ru/portal/company-37542.ashx") == "37542"
    assert extract_company_id_from_url("https://x.ru/eventdetail.aspx?companyId=38026") == "38026"
    assert extract_company_id_from_url("https://e-disclosure.ru/poisk") is None


# ---------------------------------------------------------------------------
# filter_program_files
# ---------------------------------------------------------------------------

def test_filter_matches_program_number_first():
    files = [
        make_file("Отчет эмитента", row="какой-то отчет программа"),
        make_file("Документ 4-00490-R-001P-02E от 01.02.2022"),
    ]
    picked = filter_program_files(files, "4-00490-R-001P-02E")
    assert len(picked) == 1
    assert "4-00490-R-001P-02E" in picked[0]["linkText"]


def test_filter_include_exclude_keywords():
    files = [
        make_file("Программа облигаций", row="Программа облигаций серии 001P"),
        make_file("Проспект ценных бумаг", row="Проспект программы нельзя обмануть словом"),
        make_file("Отчет эмитента", row="отчет"),
    ]
    picked = filter_program_files(files)
    assert len(picked) == 1
    assert "Программа облигаций" == picked[0]["linkText"]


def test_filter_deduplicates_by_href():
    files = [
        make_file("Программа облигаций", href="https://x.ru/FileLoad.ashx?Fileid=7"),
        make_file("Программа (копия)", href="https://x.ru/FileLoad.ashx?Fileid=7"),
        make_file("Программа другая", href="https://x.ru/FileLoad.ashx?Fileid=8"),
    ]
    picked = filter_program_files(files)
    assert len(picked) == 2


def test_filter_program_number_wins_over_exclusion():
    # Program-number match takes priority even if excluded keywords present
    files = [make_file("Изменения в программу 4-00490-R-001P-02E")]
    picked = filter_program_files(files, "4-00490-R-001P-02E")
    assert len(picked) == 1


# ---------------------------------------------------------------------------
# ZIP / PDF extraction
# ---------------------------------------------------------------------------

def test_extract_pdfs_from_zip(work_dir):
    # Build a real ZIP with two PDFs and a txt
    zip_path = work_dir / "prog.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("docs/one.pdf", b"%PDF-1.4 fake")
        zf.writestr("docs/two.pdf", b"%PDF-1.4 fake2")
        zf.writestr("docs/note.txt", b"not a pdf")

    pdfs = extract_pdfs_from_zip(zip_path)
    assert len(pdfs) == 2
    assert all(Path(p).read_bytes().startswith(b"%PDF") for p in pdfs)


def test_extract_pdfs_from_bad_zip_is_empty(work_dir):
    bad = work_dir / "bad.zip"
    bad.write_bytes(b"PK\x03\x04 garbage not really a zip")
    assert extract_pdfs_from_zip(bad) == []


def test_extract_pdfs_from_bytes_dispatch(work_dir):
    pdfs, saved = extract_pdfs_from_bytes(b"%PDF-1.4 hello", work_dir, prefix="p1")
    assert len(pdfs) == 1 and saved.endswith("p1.pdf")

    zip_bytes = b"PK\x03\x04" + b"\x00" * 10  # PK magic but broken zip
    pdfs, saved = extract_pdfs_from_bytes(zip_bytes, work_dir, prefix="p2")
    assert pdfs == [] and saved.endswith("p2.zip")  # saved as zip, extraction failed gracefully

    pdfs, saved = extract_pdfs_from_bytes(b"\x00\x01 weird", work_dir, prefix="p3")
    assert pdfs == [] and saved.endswith("p3.bin")


# ---------------------------------------------------------------------------
# EdisclosureClient wiring (config comes from session — no module global)
# ---------------------------------------------------------------------------

def test_client_config_delegates_to_session():
    session_config = SimpleNamespace(browser_timeout=12_345)
    session = SimpleNamespace(config=session_config)
    assert EdisclosureClient(session).config.browser_timeout == 12_345