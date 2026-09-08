"""Tests for covenant_models — the schema interface of results.json.

Covers: tolerant (de)serialisation, round-trip fidelity, the unified
7-category classification, total_covenants property, add_covenant
numbering, builders, and load/save I/O.
"""
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from covenant_models import (
    Covenant,
    ResultEntry,
    build_covenant,
    build_program_covenant,
    categorize_covenant,
    classify_covenant_text,
    is_real_covenant,
    load_results,
    reclassify_results,
    save_results,
)


@pytest.fixture
def results_file():
    """Fresh temp dir inside cwd, created and removed by this process.

    (pytest's tmp_path fixture and tempfile.mkdtemp walk/restrict dirs in
    ways the DSH sandbox forbids; a plain mkdir'd dir works.)
    """
    d = Path(f"covtest-{uuid.uuid4().hex[:8]}")
    d.mkdir()
    yield d / "results.json"
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tolerant deserialisation
# ---------------------------------------------------------------------------

def test_covenant_from_dict_ignores_dead_and_unknown_keys():
    """Old records carry a per-covenant 'total_covenants' dead key."""
    cov = Covenant.from_dict({
        "number": 2,
        "category": "Делистинг",
        "essence": "В случае делистинга...",
        "total_covenants": 0,  # dead legacy key
        "unknown_key": "whatever",
    })
    assert cov.number == 2
    assert cov.category == "Делистинг"
    assert cov.is_provided is True
    assert "total_covenants" not in cov.to_dict()
    assert "unknown_key" not in cov.to_dict()


def test_result_entry_defaults_fill_legacy_records():
    """Records written before the program pipeline lack program fields."""
    entry = ResultEntry.from_dict({
        "isin": "RU000A105TG7",
        "issuer": "АО «Компания»",
        "covenants": [{"number": 1, "essence": "Put"}],
    })
    assert entry.isin == "RU000A105TG7"
    assert entry.program_checked is False
    assert entry.program_url == ""
    assert entry.requires_manual_check is False
    assert entry.needs_program_check is False
    assert len(entry.covenants) == 1
    assert entry.covenants[0].essence == "Put"


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------

def make_full_entry():
    entry = ResultEntry(
        isin="RU000A1089A3",
        issuer="АО «Эмитент»",
        issue_name="ЭМИТЕНТ-БО-01",
        rating="A-(RU)",
        decision_url="https://bonds.finam.ru/issue/detailsABC/default.asp",
        decision_pdf="decision.pdf",
        parse_errors=["boom"],
        processed_at="2026-09-08T12:00:00",
        needs_program_check=True,
        program_checked=True,
        program_url="https://e-disclosure.ru/portal/files.aspx?id=1&type=7",
        program_status="parsed",
        requires_manual_check=True,
        manual_check_reason="нет текстового слоя",
    )
    entry.add_covenant(build_program_covenant(
        title="Делистинг", section="9.5",
        full_text="В случае делистинга облигаций владельцы имеют право требовать досрочного погашения.",
        document_source="Программа облигаций",
    ))
    return entry


def test_result_entry_round_trip_via_dict():
    entry = make_full_entry()
    restored = ResultEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_load_save_round_trip(results_file):
    entries = [make_full_entry()]
    save_results(results_file, entries)
    assert load_results(results_file) == entries


def test_total_covenants_property_and_numbering():
    entry = ResultEntry(isin="X")
    assert entry.total_covenants == 0
    a = entry.add_covenant(Covenant(essence="a"))
    b = entry.add_covenant(Covenant(essence="b"))
    assert a.number == 1
    assert b.number == 2
    assert entry.total_covenants == 2
    # No stored total_covenants field to desynchronise
    assert not hasattr(entry, "_total_covenants")


# ---------------------------------------------------------------------------
# Unified classification (7 categories)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("В случае делистинга облигаций", "Делистинг"),
    ("Нераскрытие промежуточной отчётности эмитента", "Раскрытие отчётности"),
    ("Выплата дивидендов за счёт чистой прибыли", "Выплата дивидендов, распределение прибыли"),
    ("Отчуждение существующего имущества и утрата контроля", "Утрата контроля"),
    ("Задолженность по кредитам превысит леверидж", "Долговая нагрузка"),
    ("Кросс-дефолт по иным обязательствам", "Кросс-дефолт"),
    ("Положение п. 9.5 Программы", "Иное"),
])
def test_categorize_covenant_seven_categories(text, expected):
    assert categorize_covenant(text) == expected


def test_cross_default_beats_debt_keyword_order():
    """Cross-default formula mentions 'долговым обязательствам' — the specific
    category must win over the generic debt keyword regardless of order."""
    formula = ("Нарушение Эмитентом своих обязательств перед иными третьими лицам "
               "(кросс-дефолт): просрочка платежа по иным долговым обязательствам "
               "Эмитента более чем на 10 дней")
    assert categorize_covenant(formula) == "Кросс-дефолт"
    # Pure debt covenant (no cross words) still classifies as debt
    assert categorize_covenant("Соотношение долга и левериджа превысит порог") == "Долговая нагрузка"


def test_classify_two_stage_falls_back_to_conditions():
    """Generic essence gets classified via conditions text."""
    assert classify_covenant_text("Событие досрочного погашения") == "Иное"
    assert classify_covenant_text(
        "Событие досрочного погашения",
        "В случае делистинга владельцы имеют право требовать выкупа",
    ) == "Делистинг"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def make_event(**overrides):
    base = dict(event_number=1, title="Делистинг облигаций на всех биржах",
                full_text="В случае делистинга облигаций на всех биржах "
                          "владельцы имеют право требовать досрочного погашения.",
                page=12)
    base.update(overrides)
    return SimpleNamespace(**base)


def make_clause(**overrides):
    base = dict(section="5.6.1", section_title="Досрочное погашение облигаций",
                page=12, full_text="текст пункта", conditions="",
                events=[], has_federal_law_only=False, needs_program_check=False)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_covenant_from_event_classifies_and_skips_number():
    cov = build_covenant(clause=make_clause(), event=make_event())
    assert cov.number == 0  # assigned by ResultEntry.add_covenant
    assert cov.category == "Делистинг"
    assert cov.document == "Решение о выпуске"
    assert cov.section == "п. 5.6.1, 1"
    assert cov.page == 12
    assert cov.is_provided is True


def test_build_covenant_not_provided_keeps_marker_category():
    """Non-covenant markers keep the document-level label, not a 7-category one."""
    cov = build_covenant(clause=make_clause(), is_provided=False)
    assert cov.is_provided is False
    assert cov.category == "Досрочное погашение по требованию владельцев"


def test_build_program_covenant_extracts_essence():
    cov = build_program_covenant(
        title="п. 9.5",
        section="9.5",
        full_text="В случае делистинга облигаций Эмитент обязан уведомить владельцев. "
                  "Владельцы имеют право требовать досрочного погашения облигаций.",
        document_source="Программа облигаций (e-disclosure)",
    )
    assert "делистинг" in cov.essence.lower()
    assert cov.category == "Делистинг"
    assert cov.document == "Программа облигаций (e-disclosure)"
    assert cov.section == "п. 9.5"


def test_is_real_covenant_only_delisting():
    assert is_real_covenant("в случае делистинга облигаций")
    assert not is_real_covenant("в случае ликвидации эмитента")
    assert not is_real_covenant("предусмотрено законом")


# ---------------------------------------------------------------------------
# Reclassification pass
# ---------------------------------------------------------------------------

def test_reclassify_updates_only_provided_covenants(results_file):
    entry = ResultEntry(isin="RU000X", processed_at="2026-01-01T00:00:00")
    entry.add_covenant(Covenant(
        category="Досрочное погашение по требованию владельцев",
        essence="Делистинг облигаций на всех биржах",
        is_provided=True,
    ))
    entry.add_covenant(Covenant(
        category="Досрочное погашение по требованию владельцев",
        essence="Досрочное погашение облигаций по требованию владельцев",
        is_provided=False,  # marker — must stay untouched
    ))
    save_results(results_file, [entry])

    changed = reclassify_results(results_file)

    assert changed == 1
    reloaded = load_results(results_file)[0]
    assert reloaded.covenants[0].category == "Делистинг"
    assert reloaded.covenants[1].category == "Досрочное погашение по требованию владельцев"

    # Idempotent: second run changes nothing
    assert reclassify_results(results_file) == 0


# ---------------------------------------------------------------------------
# Assembly: ResultEntry.add_covenants_from_clauses
# ---------------------------------------------------------------------------

def test_add_covenants_from_clauses_events_path():
    entry = ResultEntry(isin="RU000X")
    clauses = [make_clause(events=[make_event(), make_event(event_number=2)])]
    entry.add_covenants_from_clauses(clauses)

    assert entry.total_covenants == 2
    assert entry.covenants[0].number == 1
    assert entry.covenants[1].number == 2
    assert entry.covenants[1].section == "п. 5.6.1, 2"
    assert not entry.needs_program_check


def test_add_covenants_from_clauses_eventless_clause():
    entry = ResultEntry(isin="RU000X")
    clauses = [make_clause()]
    entry.add_covenants_from_clauses(clauses)

    assert entry.total_covenants == 1
    assert entry.covenants[0].section == "п. 5.6.1"
    assert entry.covenants[0].essence == "Досрочное погашение облигаций"


def test_add_covenants_from_clauses_skips_federal_law_only():
    entry = ResultEntry(isin="RU000X")
    clauses = [
        make_clause(has_federal_law_only=True),
        make_clause(has_federal_law_only=True, needs_program_check=True),
        make_clause(events=[make_event()]),  # real covenant survives
    ]
    entry.add_covenants_from_clauses(clauses)

    assert entry.total_covenants == 1
    assert entry.needs_program_check is True


def test_add_covenants_from_clauses_appends_with_continuous_numbering():
    entry = ResultEntry(isin="RU000X")
    entry.add_covenant(Covenant(essence="существующий"))
    entry.add_covenants_from_clauses([make_clause(events=[make_event()])])

    assert entry.total_covenants == 2
    assert entry.covenants[0].number == 1
    assert entry.covenants[1].number == 2
