# Project Status: bonds.finam.ru Bond Covenant Parser

## Architecture
- **Pipeline**: bonds.finam.ru (Playwright) → st.finam.ru (PDF download) → pdfplumber → JSON → Excel
- **Venv**: `D:\data-scraping\venv`
- **Working dir**: `D:\парсинг эмиссионки с финам`

## Results (latest reparse with fixes)
- **192 ISIN** total (from BBB.csv)
- **185** successfully parsed, **7** errors (scans/ZIP/docx/failed download)
- **69 ISIN** with covenants → **127 covenant events** total
- **116 ISIN** without covenants (put option absent)
- **7 ISIN** with errors — marked "Требует ручной проверки" in Excel

## Key Files
| File | Purpose |
|------|---------|
| `parser.py` | CLI entry: `--input`, `--isin`, `--limit`, `--resume` |
| `finam_client.py` | Playwright client for bonds.finam.ru |
| `pdf_parser.py` | PDF section 5.6.1 extraction with 4 event patterns |
| `export_excel.py` | JSON → Excel export (covarianants.xlsx) |
| `config.py` | Delays, timeouts, block detection |
| `reparse_missing.py` | Re-pars all ISINs from cached PDFs |
| `BBB.csv` | 192 ISINs, one per line |

## Covenant Parser Logic (pdf_parser.py)
Section 5.6.1 "Досрочное погашение по требованию владельцев":

1. **is_provided check**: First 5 lines → `не предусмотрена/установлена/предоставлена` → 0 covenants
2. **Event extraction** (4 patterns, priority order):
   - Pattern 1: `Событие досрочного погашения ... – N:` (formal)
   - Pattern 2: `Событие N:` at line start only (nominative case)
   - Pattern 3: Numbered list `N) ...` or `N). ...` (>=50% event-keyword match)
   - Pattern 4: Bullet items `✓/-/–/—/•/◆/▪` (>=2 items)
3. **Fallback**: `is_provided=True` + no events → single covenant from section text
4. **Deduplication**: by event number across all patterns
5. **Date-definition filter**: skips "является/считается/наступает/возникает" at event start
6. Federal law references NOT counted as covenants
7. Program references flagged for manual review

## Edge Cases Fixed
- `1).` format (dot after paren) — Pattern 3 updated
- `- нераскрытие` dash-bullets — Pattern 4 expanded
- Special char `0xf0fc` bullets — Pattern 4 expanded
- Single-covenant paragraphs (no event list) — fallback creates 1 event
- IP blocking: 3-8s delays, auto-pause after 3 errors, browser restart

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

## Future Work
- PaddleOCR for 6 scanned PDFs
- Expand beyond section 5.6.1
- Parse bond programs (currently skipped)