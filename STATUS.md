# Project Status: bonds.finam.ru Bond Covenant Parser

## Architecture
- **Pipeline**: bonds.finam.ru (Playwright) → st.finam.ru (PDF download) → pdfplumber → JSON → Excel
- **Venv**: `D:\data-scraping\venv`
- **Working dir**: `D:\парсинг эмиссионки сфинам` (note: disk path has space before "сфинам", DSH maps without space)

## Results (updated with program parsing)
- **192 ISIN** total (from BBB.csv)
- **185** successfully parsed, **7** errors, **25** skipped (no PDF / broken)
- **69 ISIN** with covenants → **131 covenant events** total
- **116 ISIN** without covenants
- **7 ISIN** with errors — marked "Требует ручной проверки" in Excel
- **+6 new covenants** from program parsing (section 9.5.1)

## Program Parsing Results
### Stats: 46 ISIN checked, 13 programs found, 6 new covenants
| Status | Count |
|--------|-------|
| Program found + parsed | 13 |
| No program URL on Finam | 31 |
| Not found on Finam | 2 |

### New covenants from programs (6):
| ISIN | Issuer | Covenant |
|------|--------|----------|
| RU000A109LC8 | РОЛЬФ-001Р-03 | Досрочное погашение при ликвидации |
| RU000A105M59 | РОДЕЛЕН-001Р-03 | Досрочное погашение при делистинге |
| RU000A105SK4 | РОДЕЛЕН-001Р-04 | Досрочное погашение при делистинге |
| RU000A105054 | ММЦБ-БО-П01-02 | Досрочное погашение при делистинге |
| RU000A107SX3 | ЭКОНОМЛИЗИНГ-001Р-07 | Досрочное погашение при делистинге |
| RU000A1040E8 | ЦИФРА БРОКЕР-П01-02 | Досрочное погашение при делистинге |

### Why 31 ISINs have no program URL:
Finam bond cards don't always link to program PDFs. CRKI/ЦРКИ approach was investigated (via D:\data-scraping) — no alternative method exists to find program URLs without the Finam card page. The NUM_ID needed for direct URL construction is only available on the card page itself.

## Key Files
| File | Purpose |
|------|---------|
| `parser.py` | CLI entry: `--input`, `--isin`, `--limit`, `--resume`, `--retry-errors`, `--no-headless` |
| `finam_client.py` | Playwright client for bonds.finam.ru (anti-bot, ServicePipe, search by ISIN/name) |
| `pdf_parser.py` | PDF section 5.6.1 extraction with 5 patterns + disclosure filter |
| `export_excel.py` | JSON → Excel export (covarianants.xlsx) with yellow error + green program highlights |
| `config.py` | Delays (20-45s for anti-bot), timeouts, block detection, browser settings |
| `reparse_missing.py` | Re-pars all ISINs from cached PDFs |
| `pilot_programs.py` | Pilot: download + parse 4 program PDFs (section 9.5.1) |
| `parse_programs.py` | Scale: parse programs for all 46 ISINs with needs_program_check=True |
| `merge_programs.py` | Merge program covenants from results_programs.json into results.json |
| `BBB.csv` | 192 ISINs, one per line, no header |

## Covenant Parser Logic (pdf_parser.py — 5 patterns)
Section 5.6.1 "Досрочное погашение по требованию владельцев":

1. **is_provided check**: First 5 lines → `не предусмотрена/установлена/предоставлена` → 0 covenants
2. **Event extraction** (5 patterns, priority order):
   - Pattern 1: `Событие досрочного погашения ... – N:` (formal, ≥2 matches)
   - Pattern 2: `Событие N:` at line start (nominative case, ≥2 matches)
   - Pattern 3: Numbered list `N) ...` or `N). ...` (≥50% event-keyword match, ≥2 items)
   - Pattern 4: Bullet items `✓/-/–/—/•/◆/▪/\uf0fc` (≥2 items, filtered for disclosure)
   - Pattern 5: Plain-text triggers `в случае делистинга/нарушения/etc.`
   - Single-bullet scan: lone bullets with event keywords (merged with Pattern 5)
3. **Disclosure filter** (`_is_disclosure_or_procedural`): removes "В Ленте новостей", "Порядок раскрытия", etc.
4. **Fallback**: `is_provided=True` + no events → single CovenantEvent from section text
5. **Deduplication**: by event number across all patterns
6. Federal law references NOT counted as covenants
7. Program references flagged with `needs_program_check=True`

## Program Parser Logic
- Section **9.5.1** in programs (not 5.6.1 as in decisions)
- Same PDF parser patterns applied to section 9.5.1
- Programs downloaded via Playwright from bonds.finam.ru → st.finam.ru
- `search_by_isin()` enhanced with issuer_name matching (Finam shows bond name, not ISIN, in search results)

## Key Fixes Applied
### Commit d2b60bd: Disclosure filter + plain-text triggers
- Added `_is_disclosure_or_procedural()` — filters "в Ленте новостей" disclosure items
- Added Pattern 5: plain-text triggers ("в случае делистинга/нарушения/снижения")
- Added merge logic: Pattern 4 single events + Pattern 5 triggers
- **Fixed**: ФИЛБЕРТ 3→1, ТАЛК 03P-01 3→1, ТД РКС-004 3→1

### Commit b128f80: Single-bullet scan
- After Pattern 5, scan for lone bullets with event keywords
- **Fixed**: РОЛЬФ-001Р-03/-06/-07/-08 now correctly show 2 covenants
- Total covenants: 121 → 125

### Program parsing (this session):
- Fixed `search_by_isin` — Finam shows bond name, not ISIN, in search results
- Added `issuer_name` matching + `search_by_name()` fallback + row context extraction
- Added Method 3: full-page ISIN text search
- Scale: 46 ISINs processed via `parse_programs.py` (20-45s delays)
- 6 new covenants merged into results.json
- Excel export updated: green tint for program-sourced covenants

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

## Pending Tasks
1. ~~Run pilot~~ ✅ Done — 4 pilot ISINs tested
2. ~~Scale program parsing~~ ✅ Done — 46 ISINs, 6 new covenants
3. **Future**: PaddleOCR for 6 scanned PDFs without text layer
4. **Future**: Expand beyond section 5.6.1
5. **GitHub**: Repo at https://github.com/vvv1kt2-ai/covenant-base (push manually from PS)

## Git Commits (on main)
- `9568195` — initial
- `5d90123` — code review
- `1a543ff` — fix review findings
- `9efc9a9` — docs: add README.md
- `d2b60bd` — fix: filter disclosure items + plain-text triggers
- `b128f80` — fix: catch single bullets (РОЛЬФ fix)
- `9add047` — docs: add pilot_programs.py + STATUS.md

## Workspace Path Note
DSH maps `D:\парсинг эмиссионки сфинам` but actual disk path is `D:\парсинг эмиссионки сфинам` (with space).
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
python parse_programs.py        # parse program PDFs (20-45s delays, --resume)
python merge_programs.py        # merge program covenants into results.json
```
