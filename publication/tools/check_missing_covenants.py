# -*- coding: utf-8 -*-
"""
Проверка: у кого из не публиковавших отчётность за 9 мес. 2026 есть
информационные ковенанты (право требования досрочного погашения за
непредоставление/нераскрытие отчётности).

Источники:
  D:/data-scraping/missing.csv                       — список непубликовавших
  D:/data-scraping/data/issuer_registry.json         — company_id -> ИНН (авторитетно)
  D:/API мосбиржи/data/iss-emitters-cache.json       — ИНН -> emitter id
  D:/API мосбиржи/data/iss-issuedate-cache.json      — emitter id -> ISIN
  publication/data/Реестр_ковенантов_*.xlsx              — ковенанты по ISIN

Выход: publication/data/Проверка_непубликовавших_ковенанты.xlsx
"""

import csv
import json
import os
import re
import warnings
import collections
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

warnings.filterwarnings("ignore")

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
# Внешние источники вынесены в COVENANT_SCRAPE и COVENANT_MOEX.
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
BASE = BASE.replace("\\", "/").rstrip("/") + "/"
SCRAPE = os.environ.get("COVENANT_SCRAPE") or "D:/data-scraping/"
SCRAPE = SCRAPE.replace("\\", "/").rstrip("/") + "/"
MOEX = os.environ.get("COVENANT_MOEX") or "D:/API мосбиржи/data/"
MOEX = MOEX.replace("\\", "/").rstrip("/") + "/"

INFO = re.compile(r"Информационный|Раскрытие отчётности", re.I)
# Убираем только общие правовые формы. «ЛК» и «ПКО» оставляем: это разные юрлица
STOP = {"ооо", "ао", "пао", "оао", "зао", "нпп"}
SERIES = re.compile(r"\s*-(?:00\d\s*[РP]|П\d\d|[БB][ОO])(?:-|$)|\s[БB][ОO]-", re.I)


def ikey(s):
    """Точный ключ названия: 'ПКО Защита Онлайн' и 'Защита онлайн' -> 'защита онлайн'."""
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(t for t in s.split() if t not in STOP)


def issuer_from_issue(name):
    """'ВУШ-001Р-03' -> 'ВУШ'."""
    m = SERIES.search(str(name or ""))
    return str(name)[:m.start()].strip(" -") if m else str(name or "")


# -------------------------------------------------- список непубликовавших
missing = list(csv.reader(open(SCRAPE + "missing.csv", encoding="utf-8-sig")))[1:]

# --------------------------------------------------company_id -> ИНН
reg = json.load(open(SCRAPE + "data/issuer_registry.json", encoding="utf-8"))
inn_by_name = {}
for v in reg.values():
    if isinstance(v, dict) and v.get("name") and v.get("inn"):
        inn_by_name[str(v["name"]).strip().lower()] = str(v["inn"]).strip()

# -------------------------------------------------- MOEX: ИНН -> эмитент -> ISIN
emitters = json.load(open(MOEX + "iss-emitters-cache.json", encoding="utf-8"))
by_inn = {}
for eid, v in emitters.items():
    if v.get("INN"):
        by_inn.setdefault(str(v["INN"]).strip(), []).append((str(eid), v.get("SHORT") or v.get("TITLE")))

issued = json.load(open(MOEX + "iss-issuedate-cache.json", encoding="utf-8"))
isin_by_emitter = collections.defaultdict(set)
for k, v in issued.items():
    if k.startswith("_") or not isinstance(v, dict):
        continue
    if v.get("emitter") and v.get("isin"):
        isin_by_emitter[str(v["emitter"])].add(str(v["isin"]))

# -------------------------------------------------- реестры ковенантов
registry = collections.defaultdict(list)   # isin -> [{group, name, cats}]
FILES = [("B", "Реестр_ковенантов B.xlsx"),
         ("BB", "Реестр_ковенантов BB_ИТОГ.xlsx"),
         ("BBB", "Реестр_ковенантов BBB.xlsx")]
for group, f in FILES:
    wb = openpyxl.load_workbook(BASE + f, data_only=True, read_only=True)
    cur_isin, cur_name, cur_issuer, cur_issuer_key = None, None, None, ""
    block = []
    for r in wb.worksheets[0].iter_rows(min_row=2, values_only=True):
        if len(r) < 7:
            continue
        if r[0] and group != "BBB":
            cur_issuer = str(r[0]).strip()
        if r[2]:
            if cur_isin:
                cats = [str(x[6]) for x in block if x[6]]
                registry[cur_isin].append({"group": group, "name": cur_name or "",
                                           "cats": cats, "ikey": cur_issuer_key})
            cur_isin = str(r[2]).strip()
            if group == "BBB":
                cur_name = str(r[1] or "").strip() or str(r[0] or "").strip()
                cur_issuer_key = ikey(issuer_from_issue(cur_name))
            else:
                cur_name = str(r[1] or "").strip()
                cur_issuer_key = ikey(cur_issuer)
            block = []
        if cur_isin:
            block.append(r)
    if cur_isin:
        cats = [str(x[6]) for x in block if x[6]]
        registry[cur_isin].append({"group": group, "name": cur_name or "",
                                   "cats": cats, "ikey": cur_issuer_key})

# новые выпуски: их ISIN нет в кэше MOEX, но ковенанты по ним есть
wb = openpyxl.load_workbook(BASE + "new_issues_covenants.xlsx", data_only=True, read_only=True)
cur_isin, cur_name, cur_rating = None, None, None
nb = []
def flush_new():
    if not cur_isin:
        return
    g = "BBB" if str(cur_rating).upper().startswith("BBB") else (
        "BB" if str(cur_rating).upper().startswith("BB") else "B")
    cats = [str(x[0]) for x in nb if x[0]]
    registry[cur_isin].append({"group": g, "name": str(cur_name or ""),
                               "cats": cats, "ikey": ikey(issuer_from_issue(cur_name))})
for r in wb.worksheets[0].iter_rows(min_row=2, values_only=True):
    if len(r) > 3 and r[2] and str(r[2]).startswith("RU"):
        flush_new()
        cur_isin, cur_name, cur_rating = str(r[2]).strip(), str(r[0] or "").strip(), r[3]
        nb = []
    if len(r) > 6 and r[6]:
        nb.append((r[6], r[7] if len(r) > 7 else ""))
flush_new()

# -------------------------------------------------- сопоставление
# Алиасов нет: «ПРОГРЕСС» в реестрах и «ЛК Прогресс» — разные эмитенты
ALIAS = {}

MANUAL_NOTE = {
    "А спэйс": "ИНН из реестра мониторинга (9724021393) не совпадает с ИНН эмитента "
               "«А Спэйс» в MOEX (9702082272) — совпадение по названию, сверить ИНН",
    "Славянск ЭКО": "в реестре стоит «Иное»: досрочное погашение только по усмотрению "
                    "эмитента, основания не раскрыты — информационный ковенант не подтверждён",
    "ЛК Прогресс": "добавлен по решению Виктора на основании решений о выпуске на Финам; "
                   "группа B; исходные реестры не содержат этого эмитента — в реестрах только "
                   "ЗАО «ПРОГРЕСС» (ИНН 4622004142)",
    "Симпл": "в реестрах есть тёзка АО «СИМПЛ СОЛЮШНЗ КЭПИТЛ» (ИНН 0278202835) — "
             "другая компания",
    "Рестор": "в реестрах есть тёзка ПАО «РОСИНТЕР РЕСТОРАНТС ХОЛДИНГ» — "
              "другая компания; здесь ООО «реСтор», ИНН 7709678550",
}

summary = []
detail = []
for row in missing:
    # новая структура: компания, инн, url, период, год, причина
    company, inn_csv, url, period, year, reason = row
    inn = str(inn_csv or "").strip() or inn_by_name.get(company.strip().lower(), "")
    m_em = by_inn.get(inn, []) if inn else []
    isins = set()
    for eid, _ in m_em:
        isins |= isin_by_emitter.get(eid, set())

    # запасное сопоставление: часть ISIN отсутствует в кэше MOEX,
    # поэтому дополнительно берём выпуски с точным совпадением названия эмитента
    key = ikey(ALIAS.get(company, company))
    by_name = {isin for isin, recs in registry.items()
               if any(r.get("ikey") == key for r in recs)}
    isins |= by_name

    hits, seen = [], set()
    for isin in sorted(isins):
        for rec in registry.get(isin, []):
            info = any(INFO.search(c) for c in rec["cats"])
            k = (isin, rec["group"], rec["name"], tuple(sorted(set(rec["cats"]))))
            if k in seen:
                continue
            seen.add(k)
            hits.append((isin, rec, info))

    info_hits = [h for h in hits if h[2]]
    if info_hits:
        status = "ДА — информационный ковенант есть"
    elif hits:
        status = "НЕТ — в реестре есть, но информационного ковенанта нет"
    elif m_em:
        status = "НЕТ ДАННЫХ — выпуски эмитента не попали в реестры B/BB/BBB"
    else:
        status = "НЕТ ДАННЫХ — эмитент/ИНН не найден в MOEX"

    if company in MANUAL_NOTE:
        status += "; " + MANUAL_NOTE[company]

    grp = "/".join(sorted({h[1]["group"] for h in info_hits}))
    names = ", ".join(sorted({h[1]["name"] for h in info_hits if h[1]["name"]}))
    if not names and hits:
        names = ", ".join(sorted({h[1]["name"] for h in hits if h[1]["name"]}))
    cats = ", ".join(sorted({c for h in hits for c in h[1]["cats"] if INFO.search(c)}))

    summary.append([company, inn, m_em[0][1] if m_em else "", status, grp, names, cats,
                    ", ".join(sorted({h[0] for h in info_hits})), reason])

    if not hits:
        detail.append([company, inn, "", "", "", "", "", "нет выпусков в реестрах ковенантов"])
    for isin, rec, info in hits:
        detail.append([company, inn, isin, rec["group"], rec["name"],
                       "ДА" if info else "нет",
                       " · ".join(sorted(set(rec["cats"]))),
                       "информационный ковенант" if info else "другие основания"])

# -------------------------------------------------- запись
out = openpyxl.Workbook()
HEAD = PatternFill("solid", fgColor="1F4E79")
HF = Font(bold=True, color="FFFFFF", size=11)
TH = Side(style="thin", color="BFBFBF")
BORD = Border(left=TH, right=TH, top=TH, bottom=TH)

sw = out.active
sw.title = "Сводка"
sw["A1"] = "Не публиковали отчётность за 9 мес. 2026 — информационные ковенанты"
sw["A1"].font = Font(bold=True, size=14, color="1F4E79")
hdr = ["Компания (missing.csv)", "ИНН", "Эмитент MOEX", "Результат", "Группа",
       "Выпуск(и) с информационным ковенантом", "Основание", "ISIN", "Причина"]
for i, h in enumerate(hdr, 1):
    c = sw.cell(row=3, column=i, value=h)
    c.fill, c.font, c.border = HEAD, HF, BORD
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
for j, r in enumerate(summary, 4):
    for i, v in enumerate(r, 1):
        c = sw.cell(row=j, column=i, value=v)
        c.border = BORD
        c.alignment = Alignment(vertical="top", wrap_text=True)
    if str(r[3]).startswith("ДА"):
        sw.cell(row=j, column=4).fill = PatternFill("solid", fgColor="E2EFDA")
    elif str(r[3]).startswith("НЕТ —"):
        sw.cell(row=j, column=4).fill = PatternFill("solid", fgColor="FCE4D6")
for col, w in zip("ABCDEFGHI", (24, 14, 30, 52, 10, 46, 44, 42, 34)):
    sw.column_dimensions[col].width = w
sw.freeze_panes = "A4"

dw = out.create_sheet("Детали по выпускам")
for i, h in enumerate(["Компания", "ИНН", "ISIN", "Группа", "Выпуск",
                       "Информационный ковенант", "Все категории в реестре", "Комментарий"], 1):
    c = dw.cell(row=1, column=i, value=h)
    c.fill, c.font, c.border = HEAD, HF, BORD
for j, r in enumerate(detail, 2):
    for i, v in enumerate(r, 1):
        c = dw.cell(row=j, column=i, value=v)
        c.border = BORD
        c.alignment = Alignment(vertical="top", wrap_text=True)
for col, w in zip("ABCDEFGH", (24, 14, 16, 10, 24, 26, 70, 26)):
    dw.column_dimensions[col].width = w
dw.freeze_panes = "A2"

path = BASE + "Проверка_непубликовавших_ковенанты.xlsx"
out.save(path)

# -------------------------------------------------- отчёт в консоль
print("=" * 100)
cnt = collections.Counter(s[3].split(";")[0] for s in summary)
for k, v in cnt.items():
    print(f"{v:3d}  {k}")
print("=" * 100)
for s in summary:
    print(f"{s[0]:24s} | {s[3][:70]}")
    if s[5]:
        print(f"    выпуски: {s[5][:130]}")
print("\nфайл:", path)
