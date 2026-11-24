# -*- coding: utf-8 -*-
"""Таблица «Компания — ПВО» для не публиковавших отчётность за 9 мес. 2026."""
import csv
import json
import os
import re
import collections
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
WS = WS.replace("\\", "/").rstrip("/") + "/"
MOEX = os.environ.get("COVENANT_MOEX") or "D:/API мосбиржи/data/"
MOEX = MOEX.replace("\\", "/").rstrip("/") + "/"

STOP = {"ооо", "ао", "пао", "оао", "зао", "нпп"}
SERIES = re.compile(r"\s*-(?:00\d\s*[РP]|П\d\d|[БB][ОO])(?:-|$)|\s[БB][ОO]-", re.I)


def ikey(s):
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(t for t in s.split() if t not in STOP)


def issuer_from_issue(name):
    m = SERIES.search(str(name or ""))
    return str(name)[:m.start()].strip(" -") if m else str(name or "")


# -------------------------------------------------- справочник ПВО
wb = openpyxl.load_workbook(WS + "ПВО_справочник.xlsx", data_only=True)
ws = wb["По выпускам"]
pvo_by_isin = {}
pvo_by_name = collections.defaultdict(set)
for r in ws.iter_rows(min_row=2, values_only=True):
    if not r[0]:
        continue
    isin = str(r[0]).strip()
    pvo = str(r[4] or "").strip()
    issuer = str(r[1] or "").strip()
    if pvo:
        pvo_by_isin[isin] = pvo
    if issuer and pvo:
        pvo_by_name[ikey(issuer)].add(pvo)
        pvo_by_name[ikey(issuer_from_issue(issuer))].add(pvo)

# запасной источник — колонка ПВО в самих реестрах
for f, ci in [("Реестр_ковенантов B.xlsx", 13),
              ("Реестр_ковенантов BBB.xlsx", 14),
              ("Реестр_ковенантов BB_ИТОГ.xlsx", 16)]:
    w = openpyxl.load_workbook(WS + f, data_only=True, read_only=True)
    for r in w.worksheets[0].iter_rows(min_row=2, values_only=True):
        if len(r) > ci and r[2] and r[ci]:
            pvo_by_isin.setdefault(str(r[2]).strip(), str(r[ci]).strip())

# -------------------------------------------------- MOEX: ИНН -> ISIN
emitters = json.load(open(MOEX + "iss-emitters-cache.json", encoding="utf-8"))
by_inn = {}
for eid, v in emitters.items():
    if v.get("INN"):
        by_inn.setdefault(str(v["INN"]).strip(), []).append(str(eid))

issued = json.load(open(MOEX + "iss-issuedate-cache.json", encoding="utf-8"))
isin_by_emitter = collections.defaultdict(set)
for k, v in issued.items():
    if k.startswith("_") or not isinstance(v, dict):
        continue
    if v.get("emitter") and v.get("isin"):
        isin_by_emitter[str(v["emitter"])].add(str(v["isin"]))

# -------------------------------------------------- список непубликовавших
missing = list(csv.reader(open("D:/data-scraping/missing.csv", encoding="utf-8-sig")))[1:]

rows = []
for company, inn, url, period, year, reason in missing:
    inn = str(inn or "").strip()
    isins = set()
    for eid in by_inn.get(inn, []):
        isins |= isin_by_emitter.get(eid, set())
    found = []
    for isin in sorted(isins):
        p = pvo_by_isin.get(isin)
        if p and p not in found:
            found.append(p)
    if not found:
        for p in sorted(pvo_by_name.get(ikey(company), set())):
            found.append(p)
    placeholders = {"нет данных", "не определён в решении о выпуске", "—"}
    real = [p for p in found if p not in placeholders]
    value = ", ".join(real) if real else ", ".join(found)
    rows.append([company, value or "—"])

# -------------------------------------------------- запись
out = openpyxl.Workbook()
ws = out.active
ws.title = "Непубликовавшие — ПВО"
ws["A1"] = "Не публиковали отчётность за 9 мес. 2026 — представитель владельцев облигаций"
ws["A1"].font = Font(bold=True, size=13, color="1F4E79")
for i, h in enumerate(["Компания", "ПВО"], 1):
    c = ws.cell(row=3, column=i, value=h)
    c.fill = PatternFill("solid", fgColor="1F4E79")
    c.font = Font(bold=True, color="FFFFFF", size=11)
    c.alignment = Alignment(horizontal="center")
    c.border = Border(*[Side(style="thin", color="BFBFBF")] * 4)
for j, r in enumerate(rows, 4):
    for i, v in enumerate(r, 1):
        c = ws.cell(row=j, column=i, value=v)
        c.border = Border(*[Side(style="thin", color="BFBFBF")] * 4)
        c.alignment = Alignment(vertical="top", wrap_text=True)
    if r[1] == "—":
        ws.cell(row=j, column=2).fill = PatternFill("solid", fgColor="FCE4D6")
ws.column_dimensions["A"].width = 34
ws.column_dimensions["B"].width = 62
ws.freeze_panes = "A4"

path = WS + "Непубликовавшие_ПВО.xlsx"
out.save(path)
print("строк:", len(rows))
for r in rows:
    print(f"  {r[0]:24s} | {r[1]}")
print("\nфайл:", path)
