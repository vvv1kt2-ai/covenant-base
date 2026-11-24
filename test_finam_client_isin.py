"""Выбор карточки выпуска по результатам поиска Finam.

Страница Playwright подменяется заглушкой: проверяется только логика
сопоставления ISIN — без браузера и сети.

Смысл набора: при поиске по ISIN клиент обязан либо найти карточку этого
выпуска, либо вернуть None. Любая «догадка» означает разбор чужой бумаги
и порчу данных, поэтому такие случаи закреплены как ошибки.
"""
import types

from finam_client import FinamClient


class FakePage:
    """Минимальная заглушка страницы: отвечает на три запроса evaluate."""

    def __init__(self, links=None, onclick=None, page_links=None, page_has_isin=False):
        self._links = links or []
        self._onclick = onclick or []
        self._page_links = page_links or []
        self._page_has_isin = page_has_isin

    def evaluate(self, script, arg=None):
        if "onclick*=" in script:
            return self._onclick
        if "searchIsin" in script:
            return {
                "found": self._page_has_isin,
                "links": self._page_links,
                "bodySnippet": "",
            }
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


# ---------------------------------------------------------------------------
# Разбор ссылки
# ---------------------------------------------------------------------------

def test_hex_from_href_plain():
    href = "https://bonds.finam.ru/issue/details048A2/default.asp"
    assert FinamClient._hex_from_href(href) == "048A2"


def test_hex_from_href_with_query():
    href = "https://bonds.finam.ru/issue/details00007/default.asp?foo=1"
    assert FinamClient._hex_from_href(href) == "00007"


def test_hex_from_href_strips_quotes():
    assert FinamClient._hex_from_href("location='/issue/details048A2/default.asp'") == "048A2"


def test_hex_from_href_rejects_foreign_link():
    assert FinamClient._hex_from_href("https://bonds.finam.ru/emitents/123") is None
    assert FinamClient._hex_from_href("") is None


# ---------------------------------------------------------------------------
# Поиск по ISIN: точное совпадение
# ---------------------------------------------------------------------------

def test_exact_isin_match_in_row_text():
    page = FakePage(links=[
        link("AAAAA", text="Облигация 1", row_text=f"{OTHER} Эмитент"),
        link("BBBBB", text="Облигация 2", row_text=f"{ISIN} Нужный эмитент"),
    ])
    assert make_client(page)._extract_hex_code_from_results(ISIN) == "BBBBB"


def test_exact_isin_match_in_href():
    page = FakePage(links=[link(ISIN), link("BBBBB")])
    assert make_client(page)._extract_hex_code_from_results(ISIN) == ISIN


# ---------------------------------------------------------------------------
# Поиск по ISIN: догадки запрещены (регрессия на прежнее поведение)
# ---------------------------------------------------------------------------

def test_single_result_with_other_isin_returns_none():
    """Раньше единственная ссылка принималась без проверки ISIN."""
    page = FakePage(links=[link("BBBBB", row_text=f"{OTHER} Другой эмитент")])
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


def test_many_results_without_match_returns_none():
    """Раньше при нескольких результатах возвращалась первая ссылка."""
    page = FakePage(links=[
        link("AAAAA", row_text=f"{OTHER} Первый"),
        link("BBBBB", row_text="RU000A10YYYY Второй"),
    ])
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


def test_name_match_is_not_used_when_isin_given():
    """Совпадение по имени эмитента — это другая бумага, не ответ на поиск ISIN."""
    page = FakePage(links=[link("BBBBB", text="Эмитент", row_text="Эмитент, другой выпуск")])
    client = make_client(page)
    assert client._extract_hex_code_from_results(ISIN, issuer_name="Эмитент") is None


def test_onclick_first_entry_not_guessed():
    page = FakePage(onclick=[
        {"onclick": "location='/issue/detailsAAAAA/default.asp'", "text": "Первый", "rowText": OTHER},
        {"onclick": "location='/issue/detailsBBBBB/default.asp'", "text": "Второй", "rowText": OTHER},
    ])
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


def test_page_text_isin_without_link_carrying_it_returns_none():
    """ISIN может встретиться на странице рядом с чужой бумагой."""
    page = FakePage(
        links=[],
        page_has_isin=True,
        page_links=[{"href": "https://bonds.finam.ru/issue/detailsAAAAA/default.asp", "text": "Чужая"}],
    )
    assert make_client(page)._extract_hex_code_from_results(ISIN) is None


def test_page_text_link_carrying_isin_is_accepted():
    page = FakePage(
        links=[],
        page_has_isin=True,
        page_links=[{
            "href": f"https://bonds.finam.ru/issue/details{ISIN}/default.asp",
            "text": f"Облигация {ISIN}",
        }],
    )
    assert make_client(page)._extract_hex_code_from_results(ISIN) == ISIN


# ---------------------------------------------------------------------------
# Поиск по имени: короткий путь допустим
# ---------------------------------------------------------------------------

def test_name_search_single_result_shortcut():
    page = FakePage(links=[link("BBBBB", text="Эмитент, облигации")])
    assert make_client(page)._extract_hex_code_from_results("", issuer_name="Эмитент") == "BBBBB"


def test_name_search_onclick_single_result_shortcut():
    page = FakePage(onclick=[
        {"onclick": "location='/issue/detailsBBBBB/default.asp'", "text": "Эмитент", "rowText": ""},
    ])
    assert make_client(page)._extract_hex_code_from_results("", issuer_name="Эмитент") == "BBBBB"
