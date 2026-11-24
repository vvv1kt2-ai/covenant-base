# Ревью кода: covenant-base — 24.11.2026

| | |
| --- | --- |
| Репозиторий | `vvv1kt2-ai/covenant-base` |
| Фиксированная точка | `95681957` (корневой коммит, 06.09.2026) |
| Диапазон | `95681957...HEAD` (`094be7a1`) |
| Объём дифа | 51 файл, 11 637 вставок, 717 удалений, 20 коммитов |
| Метод | двухосное ревью: Standards + Spec, параллельные под-агенты |
| Модели | Standards — `deepseek-v4.1-flash-1017`; Spec — `claude-sonnet-5.5` |

Оси намеренно не слиты и не переранжированы: изменение может пройти одну и провалить другую.

**Ограничение метода.** Формальной спеки в репозитории нет: отсутствуют `docs/agents/issue-tracker.md`, каталоги `docs/`, `specs/`, `.scratch/`, нет ссылок на issue в коммитах. За заявленный замысел приняты `README.md`, `CONTEXT.md`, `STATUS.md` и `CODE_REVIEW.md`. Это ограничение метода, а не факт о проекте.

---

## Standards

Документированных стандартов в репозитории нет: ни `CODING_STANDARDS.md`, ни `CONTRIBUTING.md`, ни `pyproject.toml`, ни ruff/flake8, ни `.editorconfig`. Ниже — только смеллы базовой линии (Фаулер, «Refactoring», гл. 3), все как суждения.

1. **Mysterious Name** — `covenant_models.py:270`, `is_real_covenant`. Тело — `return "делистинг" in lower`. Имя обещает «настоящий ковенант», проверяется одно слово; из-за этого `merge_programs.py` и `merge_edisclosure.py` молча отбрасывают все прочие ковенанты программ. → назвать `is_delisting` или вынести правило в данные.
2. **Duplicated Code** — `finam_client.py:236`. `parts = href.split("/issue/details"); hex_part = parts[1].split("/")[0].split("?")[0]` повторён 5× (286, 301, 311, 402, 411); `search_by_name` (187) копирует весь поток `search_by_isin` (135): goto → servicepipe → captcha → три попытки. → `_hex_from_href()` и общий `_search(query, field)`.
3. **Shotgun Surgery + Duplicated Code** — поля программы `program_checked/program_url/program_status` правятся в dataclass, `from_dict`, `to_dict`, `export_excel.py` и двух merge-скриптах; `merge_programs.py` и `merge_edisclosure.py` — один и тот же цикл, отличается лишь `document_source`. → `ResultEntry.mark_program_checked(...)` и один `merge_program_results`.
4. **Duplicated Code** — `parse_programs.py:225`. Шаг 4b сам ищет `9.5.1`/`9.5`, хотя `PDFParser.parse_program_with_sections` (`pdf_parser.py:543`) делает это для `edisclosure_pilot.py`. Две реализации разойдутся. → вызывать метод парсера.
5. **Data Clumps** — `parse_programs.py:121-219`, `add_new_issues.py`. Словарь `{isin, issuer, status, new_covenants, total_new}` собран шесть раз в ветках ошибок; `_record()` принимает 8 позиционных строк. → `ProgramOutcome` и `Issue`.
6. **Duplicated Code** — `pdf_parser.py:383` и `:415`. `bullet_pattern` и `bullet_single_pattern` — один regex, скомпилированный и просканированный дважды по одному тексту; фильтр `_is_disclosure_or_procedural` и перенумерация продублированы в четырёх паттернах (304, 332, 371, 425). → один проход + общий `_finalize(events)`.
7. **Mysterious Name / Divergent Change** — `covenant_models.py:306`, `build_covenant`. Ветки по `if event:` возвращают разные наборы полей, рядом `build_program_covenant`. → разделить на `build_from_event` / `build_from_clause`.
8. **Primitive Obsession** — `category: str`. Семь категорий и маркер `"Досрочное погашение по требованию владельцев"` — литералы в модели, `export_excel.py`, тестах; `is_from_program` — `document.startswith("Программа")`, switch по строке. → `CovenantCategory` и явное поле `source`.
9. **Middle Man** — `finam_client.py:57-75`. `start`/`stop`/`_random_delay`/`_check_captcha` только делегируют в `session`, о чём сказано в докстрингах. → отдавать `session` наружу.
10. **Feature Envy** — `export_excel.py:157`, `parse_programs.py:161`. Оба места режут URL (`split("/")[-1].split("?")[0]`) ради имени файла. → `ResultEntry.program_filename`.

## Spec

Сверка трёх «КРИТИЧНО» из `CODE_REVIEW.md`:

| Пункт | Вердикт |
| --- | --- |
| 1. Неверный ISIN при нескольких результатах поиска | **не исправлено** |
| 2. Тройное дублирование построения covenant | исправлено |
| 3. Сброс счётчика ошибок после cooldown | исправлено |

### (c) Реализовано, но неверно

1. **Неверный ISIN (#1).** Предупреждение «No exact ISIN match found» только логируется, затем выполняется Method 3, который всё равно возвращает чужую карточку: `elif links: # Multiple links — return the first one (search is specific enough)`, затем `href = links[0]`. Pass 3 (`len(links_data) == 1`) отдаёт единственную ссылку без проверки ISIN. Тестов на `finam_client` нет.
2. **Потеря данных в `reparse_missing.py`.** Скрипт делает `r.covenants = []` и пересобирает только из решения, поэтому ковенанты из программ, добавленные `merge_programs.py` и `merge_edisclosure.py`, теряются, а `needs_program_check` не пересчитывается.
3. **`is_real_covenant`.** Проверяет подстроку во всём `full_text`, поэтому текст про ликвидацию, где упомянут делистинг, проходит как реальная ковенанта.
4. **Маркер `is_provided=False` недостижим.** `add_covenants_from_clauses` делает `continue` для `has_federal_law_only`, поэтому ветка `build_covenant(is_provided=False)` из сборки не вызывается.
5. **`_clean_event_text`** по-прежнему содержит `считается\s+наступившим.*$` с `DOTALL` — дефект #10 из прежнего ревью не закрыт.

### (a) Заявлено, но отсутствует или частично

6. **Рейтинг не заполняется.** README обещает `"rating": "A-(RU)"` и колонку «Рейтинг» в Excel; в `results.json` рейтинг пуст у всех 202 записей — `_extract_rating` ничего не находит, `export_new_issues.enrich_ratings` заполняет его только для MOEX-пакета.
7. **`pilot_programs.py`** перечислен в README и STATUS, в HEAD файла нет.
8. **Цифры устарели.** Заявлено 192 ISIN / 71 с ковенантами / 133 ковенанта; фактически 202 / 77 / 145, плюс 5 `requires_manual_check`. «Выплата дивидендов 8» против 1, «Раскрытие отчётности 89» против 97, кросс-дефолт (8) не упомянут вовсе. `STATUS.md` описывает состояние на коммите `9add047`.
9. **Тесты.** CONTEXT заявляет «57 в пяти файлах»; фактически около 84 `def test_` в девяти файлах. `test_pdf_parser.py` и `test_fallback.py` удалены, покрытия для 5.6.1-паттернов нет.

### (b) Scope creep

10. **MOEX-воркфлоу** не описан ни в README, ни в CONTEXT, ни в STATUS: `add_new_issues.py` (фильтр по рейтингу B−…BBB+), `merge_results.py`, `export_new_issues.py`, флаг `--isins` в `export_excel.py`.
11. **Артефакты в git:** `new_issues_covenants.*`, `covarianants_v3.xlsx`, `results.json` на 5 324 строки.

---

## Итог

- **Standards:** 10 находок; худшая — `is_real_covenant`, из-за которой ковенанты молча теряются при слиянии.
- **Spec:** 11 находок; худшая — неверный ISIN не исправлен, парсер может читать карточку чужого выпуска.

Приоритет исправлений: ISIN и `is_real_covenant` портят данные; остальное — дублирование, косметика и рассинхрон документации с кодом.
