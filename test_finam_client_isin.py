"""Выбор карточки выпуска по результатам поиска Finam.

Страница Playwright подменяется заглушкой: проверяется только логика
сопоставления — без браузера и сети.

Факт, на котором держится логика: Finam не показывает ISIN в строке
результата. Опознать выпуск можно по счётчику «Найдено выпусков» —
если поиск по ISIN вернул ровно один выпуск, это и есть ответ поисковика.
Когда результатов несколько, совпадение обязательно: иначе для ISIN A
разбирается карточка выпуска B.
"""
import types

from finam_client import FinamClient


class FakePage:
    """Минимальная заглушка страницы: отвечает на три запроса evaluate."""

    def __init__(self, links=None, onclick=None, count=None):
        self._links = links or []
        self._onclick = onclick or []
        self._count = count

    def evaluate(self, script, arg=None):
        if "onclick*=" in script:
            return self._onclick
        if "Найдено" in script:
            return self._count
        return self._links


def make_client(page):
    """Клиент без запуска браузера: подменяется только сессия."""
    client = FinamClient.__new__(FinamClient)
    client.session = types.SimpleNamespace(page=page)
    client._consecutive_errors = 0
    return client


ISIN = "RU000A10B4K7"
OTHER = "RU000A10ZZZ1"


def link(hex_code, text="", row_text=""):
    return {
        "href": f"https://bonds.finam.ru/issue/details{hex_code}/default.asp",
        "text": text,
        "rowText": row_text,
    }


def onclick(hex_code, text="", row_text=""):
    return {
        "onclick": f".location.href = '/issue/details{hex_code}/default.asp'",
        "text": text,
        "rowText": row_text,
    }


# ---------------------------------------------------------------------------
# Разбор ссылки
# ---------------------------------------------------------------------------

def test_hex_from_href_plain():
    href = "https://bonds.finam.ru/issue/details048A2/default.asp"
    assert FinamClient._hex_from_href(href) == "048A2"


def test_hex_from_href_with_query():
    href = "https://bonds.finam.ru/issue/details00007/default.asp?foo=1"
    assert FinamClient._hex_from_href(href) == "00007"


def test_hex_from_href_from_onclick():
    assert FinamClient._hex_from_href(".location.href = '/issue/details04598/default.asp'") == "04598"


def test_hex_from_href_rejects_foreign_link():
    assert FinamClient._hex_from_href("https://bonds.finam.ru/emitents/123") is None
    assert FinamClient._hex_from_href("") is None


# ---------------------------------------------------------------------------
# Поиск по ISIN: один результат — это ответ поисковика
# ---------------------------------------------------------------------------

def test_single_onclick_result_with_count_one_is_accepted():
    """Живой случай: у Finam ссылка висит в onclick, ISIN в строке нет."""
    page = FakePage(
        onclick=[onclick("04598", text="1  ИЛОН-001Р-01  в обращении  06.03.2026")],
        count=1,
    )
    assert make_client(page)._extract_hex_code_from_results("RU000A10EG44") == "04598"


def test_single_link_result_with_count_one_is_accepted():
    page = FakePage(links=[link("BBBBB", text="Эмитент, облигации")], count=1)
    assert make_client(page)._extract_hex_code_from_results(ISIN) == "BBBBB"


def test_single_result_but_count_reports_several_returns_none():
    """Одна ссылка при счётчике «несколько» — уже не ответ на запрос."""
    page = FakePage(links=[link("BBBBB", text="Что-то")], count=3)
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


def test_missing_count_blocks_single_result():
    """Без счётчика подтвердить выпуск нечем — отказ."""
    page = FakePage(links=[link("BBBBB", text="Что-то")], count=None)
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


# ---------------------------------------------------------------------------
# Поиск по ISIN: точное совпадение в строке важнее счётчика
# ---------------------------------------------------------------------------

def test_exact_isin_match_in_row_text_wins():
    page = FakePage(links=[
        link("AAAAA", text="Первый", row_text=f"{OTHER} Эмитент"),
        link("BBBBB", text="Второй", row_text=f"{ISIN} Нужный эмитент"),
    ], count=2)
    assert make_client(page)._extract_hex_code_from_results(ISIN) == "BBBBB"


# ---------------------------------------------------------------------------
# Поиск по ISIN: догадки запрещены
# ---------------------------------------------------------------------------

def test_many_results_without_match_returns_none():
    """Раньше при нескольких результатах возвращалась первая ссылка."""
    page = FakePage(links=[
        link("AAAAA", row_text=f"{OTHER} Первый"),
        link("BBBBB", row_text="RU000A10YYYY Второй"),
    ], count=2)
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


def test_name_match_is_not_used_when_isin_given():
    """Совпадение по имени эмитента — другая бумага, не ответ на поиск ISIN."""
    page = FakePage(links=[
        link("AAAAA", text="Другой выпуск", row_text="Эмитент"),
        link("BBBBB", text="Ещё выпуск", row_text="Эмитент"),
    ], count=2)
    client = make_client(page)
    assert client._extract_hex_code_from_results(ISIN, issuer_name="Эмитент") is None


def test_two_distinct_onclick_entries_are_refused():
    page = FakePage(onclick=[
        onclick("AAAAA", text="Первый", row_text=OTHER),
        onclick("BBBBB", text="Второй", row_text=OTHER),
    ], count=2)
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


# ---------------------------------------------------------------------------
# Поиск по имени
# ---------------------------------------------------------------------------

def test_name_search_matches_row():
    page = FakePage(links=[
        link("AAAAA", text="Другой эмитент"),
        link("BBBBB", text="Нужный эмитент"),
    ], count=2)
    assert make_client(page)._extract_hex_code_from_results("", issuer_name="Нужный") == "BBBBB"


def test_name_search_single_result_shortcut():
    page = FakePage(links=[link("BBBBB", text="Эмитент, облигации")], count=1)
    assert make_client(page)._extract_hex_code_from_results("", issuer_name="Эмитент") == "BBBBB"


def test_name_search_without_match_returns_none():
    page = FakePage(links=[link("AAAAA", text="Один"), link("BBBBB", text="Два")], count=2)
    assert make_client(page)._extract_hex_code_from_results("", issuer_name="Нужный") is None
