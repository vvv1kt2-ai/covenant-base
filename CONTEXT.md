# Контекст проекта: Парсинг эмиссионной документации облигаций с Finam

## Доменная модель

### Источники данных
- **bonds.finam.ru** — основной источник. Карточки выпусков облигаций с ссылками на PDF-документы (решения о выпуске, программы облигаций). Использует ServicePipe anti-bot protection (JS challenge). URL карточек: `https://bonds.finam.ru/issue/details{ID}/default.asp`. Задержки между запросами: **20–45 сек** (`config.finam_delay`). CAPTCHA-детектор — предохранитель (не срабатывала ни разу); реальный риск — бан по IP (block-detection в `finam_client.py`).
- **e-disclosure.ru** (ЦРКИ Интерфакс) — запасной источник для программ облигаций. Документы по эмитенту (companyId), не по ISIN. Требует Playwright + CAPTCHA (ручной ввод, таймаут 120 сек, MIN_WAIT 15 сек) → браузер всегда видимый (`headless=False`). URL файлов: `https://e-disclosure.ru/portal/files.aspx?id={companyId}&type=7`. Задержки: между эмитентами **15–30 сек** (`config.edisclosure_delay`), навигация 5–10 сек, после неудачного поиска 10–20 сек — все в `config.py`.
- Загрузка файлов st.finam.ru идёт через httpx **без анти-бота** — вне браузерного шва.

### Ключевые сущности
- **ISIN** — международный код ценной бумаги (например, RU000A1089A3). Основной ключ поиска.
- **Решение о выпуске** — PDF-документ, содержащий условия эмиссии. Содержит пункт 5.6.1 «Досрочное погашение облигаций по требованию их владельцев».
- **Программа облигаций** — PDF-документ, на который ссылается решение. Ковенанты живут в разных секциях: 9.5, 9.5.1, 9.3, 6.5.1 и др. (не обязательно 5.6.1).
- **Ковенант** — условие/ограничение в эмиссионной документации. Из программ реальными ковенантами считаются только события **делистинга** (ликвидация, «предусмотрено законом», механизм частичного погашения — не ковенанты).

### Модель данных (interface — `covenant_models.py`)
`covenant_models.py` — единственный владелец схемы: dataclass-модели `Covenant` и `ResultEntry`, толерантный `from_dict`/`to_dict`, I/O `load_results`/`save_results`, строители `build_covenant` (решения) и `build_program_covenant` (программы), классификатор `categorize_covenant`.

- `ResultEntry.total_covenants` — property, всегда `len(covenants)`.
- Нумерация ковенантов — только через `ResultEntry.add_covenant()`.
- Сборка из результатов парсинга — `ResultEntry.add_covenants_from_clauses(clauses)`: пропускает federal-law-only (ставит `needs_program_check`), события → по одному ковенанту на событие, без событий → один агрегат. Ноль принятых ковенантов = ссылка на Программу, проверить вручную.
- `from_dict` терпит отсутствующие поля (старые записи без `program_*`) и игнорирует неизвестные ключи; round-trip не меняет данные молча.

### Архитектура (швы)

```
parser.py / parse_programs.py      CLI-оркестраторы (Finam-сторона)
        │
        ├── FinamClient (finam_client.py)      block-detection (бан по IP) — здесь
        │       └── BrowserSession (browser_session.py)   ← ЕДИНЫЙ браузерный шов
        │
edisclosure_pilot.py               CLI-оркестратор (e-disclosure, ~200 строк)
        ├── EdisclosureClient (edisclosure_client.py)     весь сайт e-disclosure
        ├── edisclosure_store.py                          company_ids.json, section_refs
        └── BrowserSession                                ← тот же шов
```

- **`browser_session.py`** — deep module: lifecycle с полным анти-детектом для всех источников (args + viewport + timezone + init-script), `human_delay()` из конфига, `wait_captcha_resolved(page, detector, timeout, min_wait) → bool` (общая петля poll 3с; политику ошибок решает вызывающий: Finam — raise, e-disclosure — статус). CAPTCHA-детекторы подключаемые: `FinamCaptchaDetector` (CSS `#id_captcha_frame_div`), `EdisclosureCaptchaDetector` (body-text + challenge-URL + iframe). **Lazy-режим**: `BrowserSession(..., lazy=True)` стартует браузер при первом обращении к `.page` — dry-run с тёплым кэшем company_ids.json не касается Playwright вообще.
- **`edisclosure_client.py`** — `EdisclosureClient(session)`; глобали config нет, всё из `session.config`. Чистые функции: `filter_program_files` (приоритет: номер программы → ключевые слова «программа»/исключения, дедуп по href), `extract_pdfs_from_zip/bytes`, `extract_company_id_from_url`.
- **`pdf_parser.py`** — `parse_decision()` (секция 5.6.1 решений) и `parse_program_with_sections()` (программы, 3-ступенчатый матчинг таргет-секций) — публичный шов, используемый обеими сторонами; `find_redemption_clause` публичен.

### Категории ковенантов (единая таксономия, 7 категорий)
| Категория | Триггер |
|-----------|---------|
| Раскрытие отчётности | непредоставление промежуточной/годовой/консолидированной отчётности |
| Выплата дивидендов, распределение прибыли | дивиденды, купон, выплата дохода |
| Утрата контроля | отчуждение, снижение доли, реорганизация |
| Долговая нагрузка | задолженность, леверидж, целевое использование |
| Кросс-дефолт | дефолт по иным обязательствам |
| Делистинг | снятие с торгов на биржах |
| Иное | не попало в остальные |

Классификация двухступенчатая: сначала по сути (essence), при «Иное» — по сути+условиям (conditions). Метка «Досрочное погашение по требованию владельцев» осталась только у маркеров `is_provided=False` (put не предусмотрен — это не ковенант).

### Структура данных (JSON-выход, каноническая форма)
```json
{
  "isin": "RU000A10FSG6",
  "issuer": "Название эмитента",
  "issue_name": "Название выпуска",
  "rating": "BB",
  "decision_url": "https://bonds.finam.ru/...",
  "decision_pdf": "decision.pdf",
  "covenants": [
    {
      "number": 1,
      "category": "Делистинг",
      "essence": "В случае делистинга облигаций...",
      "document": "Решение о выпуске | Программа облигаций | Программа облигаций (e-disclosure)",
      "section": "п. 5.6.1, 1",
      "page": 9,
      "quote": "Событием досрочного погашения по требованию владельцев...",
      "is_provided": true,
      "conditions": "..."
    }
  ],
  "total_covenants": 1,
  "parse_errors": [],
  "processed_at": "2026-09-08T12:00:00",
  "needs_program_check": false,
  "program_checked": true,
  "program_url": "https://e-disclosure.ru/...",
  "program_status": "parsed",
  "requires_manual_check": false,
  "manual_check_reason": ""
}
```
Поля `needs_program_check` ставит `parser.py` (входной флаг для `parse_programs.py`); `program_checked`/`program_url`/`program_status` — мержи (выход); `requires_manual_check`/`manual_check_reason` — `merge_edisclosure.py`.

### Формат шаблона (Excel)
Колонки: Эмитент | Выпуск | ISIN | Рейтинг | Ковенантов в выпуске | № | Категория ковенанта | Суть ковенанта | Документ | Пункт | Стр. | Файл | Цитата из эмиссионной документации | Источник (Финам)

## Технические решения
- **Язык**: Python 3.14 (venv `D:\data-scraping\venv`; pytest 9.1.1)
- **Зависимости**: pdfplumber, httpx, beautifulsoup4, lxml, playwright, openpyxl
- **Кэширование**: PDF кэшируются в `downloads/{ISIN}/`; companyIds и section-refs — в `company_ids.json` / `program_section_refs.json` (через `edisclosure_store.py`)
- **Тесты**: 57 в пяти файлах — `test_covenant_models.py` (22, вкл. 4 сборки), `test_export_excel.py` (3), `test_browser_session.py` (17: lazy/eager, delay-границы, wait-loop, детекторы), `test_edisclosure_store.py` (6), `test_edisclosure_client.py` (9). Запуск: `python -m pytest -p no:cacheprovider` (tmp_path/mkdtemp в песочнице не работают — фикстуры создают `covtest-*` каталоги в cwd и сами себя удаляют). Браузер в тестах не запускается; launch-путь проверяется ручным прогоном пилота.
- **Инвариант данных**: 192 ISIN, 71 с ковенантами, 133 ковенанта, 46 needs_program_check — проверяется после каждого рефакторинга round-trip'ом.

## Открытые вопросы
- **Классификатор категорий: качество недостаточно, ошибки остаются** (вернуться позже). Исправлен порядок проверки — Кросс-дефолт раньше Долговой нагрузки (формула кросс-дефолта содержит «иным долговым обязательствам»; 6 записей реклассифицировано, 7/7 кросс-дефолтов теперь верны). Гипотеза о другом символе тире опровергнута — в данных обычный HYPHEN-MINUS. Пользователь рассматривал LLM или простую ML-модель, но отмечает: ключевые слова и регулярки работали достаточно хорошо; решение не принято. Переклассификация — idempotent прогон `reclassify_categories.py`.
- **6 отсканированных PDF без текстового слоя** не парсятся (pdfplumber) — кандидат на PaddleOCR, решение не принято.
