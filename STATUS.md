# Project Status: bonds.finam.ru Bond Covenant Parser

## Architecture
- **Pipeline**: bonds.finam.ru (Playwright) → st.finam.ru (PDF download) → pdfplumber → JSON → Excel
- **Venv**: `D:\data-scraping\venv`
- **Working dir**: `D:\парсинг эмиссионки сфинам` (note: disk path has space before "сфинам", DSH maps without space)

## Results (after disclosure filter + single-bullet fix)
- **192 ISIN** total (from BBB.csv)
- **185** successfully parsed, **7** errors, **25** skipped (no PDF / broken)
- **69 ISIN** with covenants → **125 covenant events** total
- **116 ISIN** without covenants
- **7 ISIN** with errors — marked "Требует ручной проверки" in Excel

## Key Files
| File | Purpose |
|------|---------|
| `parser.py` | CLI entry: `--input`, `--isin`, `--limit`, `--resume`, `--retry-errors`, `--no-headless` |
| `finam_client.py` | Playwright client for bonds.finam.ru (anti-bot, ServicePipe) |
| `pdf_parser.py` | PDF section 5.6.1 extraction with 5 patterns + disclosure filter |
| `export_excel.py` | JSON → Excel export (covarianants.xlsx) with yellow error highlights |
| `config.py` | Delays, timeouts, block detection, browser settings |
| `reparse_missing.py` | Re-pars all ISINs from cached PDFs |
| `pilot_programs.py` | PILOT: Download and parse bond PROGRAM PDFs (section 9.5.1) |
| `BBB.csv` | 192 ISINs, one per line, no header |

## Covenant Parser Logic (pdf_parser.py — 5 patterns)
Section 5.6.1 "Досрочное погашение по требованию владельцев":

1. **is_provided check**: First 5 lines → `не предусмотрена/установлена/предоставлена` → 0 covenants
2. **Event extraction** (5 patterns, priority order):
   - Pattern 1: `Событие досрочного погашения ... – N:` (formal, ≥2 matches)
   - Pattern 2: `Событие N:` at line start (nominative case, ≥2 matches)
   - Pattern 3: Numbered list `N) ...` or `N). ...` (≥50% event-keyword match, ≥2 items)
   - Pattern 4: Bullet items `✓/-/–/—/•/◆/▪/�0fc` (≥2 items, filtered for disclosure)
   - Pattern 5: Plain-text triggers `в случае делистинга/нарушения/etc.`
   - Single-bullet scan: lone bullets with event keywords (merged with Pattern 5)
3. **Disclosure filter** (`_is_disclosure_or_procedural`): removes "В Ленте новостей", "Порядок раскрытия", etc.
4. **Fallback**: `is_provided=True` + no events → single CovenantEvent from section text
5. **Deduplication**: by event number across all patterns
6. Federal law references NOT counted as covenants
7. Program references flagged with `needs_program_check=True`

## Key Fixes Applied (2 commits)
### Commit d2b60bd: Disclosure filter + plain-text triggers
- Added `_is_disclosure_or_procedural()` — filters "в Ленте новостей" disclosure items
- Added Pattern 5: plain-text triggers ("в случае делистинга/нарушения/снижения")
- Added merge logic: Pattern 4 single events + Pattern 5 triggers
- **Fixed**: ФИЛБЕРТ 3→1, ТАЛК 03P-01 3→1, ТД РКС-004 3→1
- **Fixed**: РОЛЬФ-001Р-09 correctly gets 2 covenants (нарушение + делистинг)

### Commit b128f80: Single-bullet scan
- After Pattern 5, scan for lone bullets with event keywords
- Pattern 4 requires ≥2 bullets, so single bullets were missed
- **Fixed**: РОЛЬФ-001Р-03/-06/-07/-08 now correctly show 2 covenants (делистинг + нераскрытие отчётности)
- Total covenants: 121 → 125

### Regression test results
- 69 ISINs with covenants tested on each fix: 0 regressions
- Only intentional changes: ФИЛБЕРТ, ТАЛК, ТД РКС-004 (disclosure filter), РОЛЬФ (single-bullet)

## Edge Cases Handled
- `1).` format (dot after paren) — Pattern 3 regex `[)\.]+`
- `- нераскрытие` dash-bullets — Pattern 4 expanded with `-`, `–`, `—`, `\uf0fc`
- Single-covenant paragraphs — fallback creates 1 CovenantEvent
- Plain-text triggers (делистинг, нарушение) — Pattern 5
- Lone bullet events — single-bullet scan after Pattern 5
- Disclosure false positives — `_is_disclosure_or_procedural()` filter

## Error ISINs (7)
| ISIN | Issuer | Error |
|------|--------|-------|
| RU000A101T72 | АПТЕЧНАЯ СЕТЬ 36,6-002P-01 | No text layer (scan) |
| RU000A0ZYM54 | ЦЕНТРАЛЬНАЯ ППК-П01-БО-01 | No text layer (.docx) |
| RU000A0JXGV0 | АКБ ПЕРЕСВЕТ-С01 | No text layer (.zip) |
| RU000A0JUT85 | АКБ ПЕРЕСВЕТ-БО-02 | No text layer (.zip) |
| RU000A0JVM32 | АКБ ПЕРЕСВЕТ-БО-03 | No text layer (.zip) |
| RU000A10B8X7 | ДАРС-ДЕВЕЛОПМЕНТ-001Р-03 | No text layer (scan) |
| RU000A1078Y6 | ЭКОНОМЛИЗИНГ-001Р-06 | Failed to download |

## Program Parsing Analysis (NEXT STEP)
### needs_program_check=True: 46 ISIN total
| Type | Count | Description | Action |
|------|-------|-------------|--------|
| A — "Возможность не предусмотрена" | 24 | First lines say not provided, program ref is supplementary | **Skip** |
| B — "Дополнительные не предусмотрены" | 1 | МВ ФИНАНС-001Р-06: all covenants in program only | **Need program** |
| C — Has covenants + program ref | 21 | Decision has covenants, program may have more | **Need program** |

### TYPE C ISINs (21):
- 5× РОЛЬФ-001Р (-03/-06/-07/-08/-09): 2 covenants each (делистинг + нераскрытие)
- 5× ЭНЕРГОТЕХСЕРВИС-001Р (-06/-07/-08/-09/-10): 1 covenant each
- 2× РОДЕЛЕН-001Р (-03/-04): 1 covenant each
- 2× ЭКОНОМЛИЗИНГ-001Р (-07/-08): 1 covenant each
- 1× ТАЛАН-ФИНАНС-001P-04: 2 covenants
- 1× ПКО ФИЛБЕРТ-БО-01: 1 covenant
- 1× ИННОВАЦИОННЫЕ СИСТЕМЫ ПОЖ: 1 covenant
- 1× ММЦБ-БО-П01-02: 1 covenant
- 2× СЛАВЯНСК ЭКО-001Р (-01/-04): 1 covenant each
- 1× ЦИФРА БРОКЕР-П01-02: 1 covenant

### TYPE B (1):
- МВ ФИНАНС-001Р-06: "Дополнительные к случаям... не предусмотрены" → all in program

### Program section: 9.5.1 (not 5.6.1)
- Decision references "п. 9.5.1 Программы"
- Program has section 9.5.1 with covenant events
- Pilot script: `pilot_programs.py` — downloads 4 program PDFs, parses 9.5.1

### Pilot ISINs:
1. RU000A109LC8 РОЛЬФ-001Р-03 (2 covenants in decision, check for more)
2. RU000A10ADJ3 ЭНЕРГОТЕХСЕРВИС-001Р-06 (1 covenant, check for more)
3. RU000A105M59 РОДЕЛЕН-001Р-03 (1 covenant, check for more)
4. RU000A10BFP3 МВ ФИНАНС-001Р-06 (Type B, 0 in decision, all in program)

## Pending Tasks
1. **Run pilot**: `python pilot_programs.py` from PowerShell (needs Playwright, can't run in sandbox)
2. **After pilot**: Scale program parsing to all 22 ISINs
3. **Update parser.py**: Save `program_url` to results.json
4. **Future**: PaddleOCR for 6 scanned PDFs
5. **Future**: Expand beyond section 5.6.1
6. **GitHub**: Repo at https://github.com/vvv1kt2-ai/covenant-base (push manually from PS)

## Git Commits (on main)
- `9568195` — initial
- `5d90123` — code review
- `1a543ff` — fix review findings
- `9efc9a9` — docs: add README.md
- `d2b60bd` — fix: filter disclosure items + plain-text triggers
- `b128f80` — fix: catch single bullets (РОЛЬФ fix)

## Workspace Path Note
DSH maps `D:\парсинг эмиссионки сфинам` but actual disk path is `D:\парсинг эмиссионки с финам` (with space).
To get correct path in PowerShell:
```powershell
$dir = (Get-ChildItem "D:\" -Directory | Where-Object { $_.Name -like "*парсинг*" })[0].FullName
```
Python scripts using this path work fine. File operations via DSH write tool may fail due to sandbox path mapping.

## Run Commands From
```powershell
D:\data-scraping\venv\Scripts\Activate.ps1
python reparse_missing.py       # reparse all from cached PDFs
python export_excel.py          # export results.json → covarianants.xlsx
python pilot_programs.py        # PILOT: download + parse program PDFs
```
