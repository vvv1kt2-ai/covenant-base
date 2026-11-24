# -*- coding: utf-8 -*-
"""
Добавление колонок ПВО в реестры ковенантов и формирование справочника ПВО.

Колонки (в конец листа):
  ПВО | Сайт ПВО | Статус ПВО

Вход:  tmp/pvo_final.json
Выход: Реестр_ковенантов B.xlsx, Реестр_ковенантов BB_ИТОГ.xlsx,
       Реестр_ковенантов BBB.xlsx, new_issues_covenants.xlsx,
       ПВО_справочник.xlsx
"""
import json
import os
import re
import shutil
from copy import copy
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
WS = WS.replace("\\", "/").rstrip("/") + "/"
FILES = [
    WS + "Реестр_ковенантов B.xlsx",
    WS + "Реестр_ковенантов BB_ИТОГ.xlsx",
    WS + "Реестр_ковенантов BBB.xlsx",
    WS + "new_issues_covenants.xlsx",
]
BACKUP = WS + "tmp/backup_pvo_" + date.today().isoformat() + "/"

HEADERS = ["ПВО", "Сайт ПВО", "Статус ПВО"]
WIDTHS = [26, 38, 34]

THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def load_map():
    return json.load(open(WS + "tmp/pvo_final.json", encoding="utf-8"))


def value_for(rec):
    short = rec["short"]
    if short == "не определён":
        return "не определён в решении о выпуске", "", ""
    if short == "нет данных":
        return "нет данных", "", ""
    return short, rec.get("site") or "", rec.get("status") or ""


def process(path, mapping):
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
    ncol = ws.max_column
    start_col = ncol + 1

    # заголовки — копируем оформление последней существующей колонки
    src = ws.cell(row=1, column=ncol)
    for i, h in enumerate(HEADERS):
        c = ws.cell(row=1, column=start_col + i, value=h)
        c.font = copy(src.font)
        c.fill = copy(src.fill)
        c.alignment = copy(src.alignment)
        c.border = copy(src.border)
        ws.column_dimensions[get_column_letter(start_col + i)].width = WIDTHS[i]

    # проход по строкам: ПВО относится к блоку выпуска
    cur = None
    filled = 0
    for r in range(2, ws.max_row + 1):
        isin = ws.cell(row=r, column=3).value
        if isin and str(isin).startswith("RU"):
            cur = mapping.get(str(isin).strip())
        if not cur:
            continue
        pvo, site, status = value_for(cur)
        c1 = ws.cell(row=r, column=start_col, value=pvo)
        c1.alignment = Alignment(vertical="top", wrap_text=True)
        c1.border = BORDER
        c2 = ws.cell(row=r, column=start_col + 1, value=site)
        c2.border = BORDER
        if site:
            c2.hyperlink = site
            c2.font = Font(color="0563C1", underline="single", size=9)
        c3 = ws.cell(row=r, column=start_col + 2, value=status)
        c3.alignment = Alignment(vertical="top", wrap_text=True)
        c3.border = BORDER
        if "прекращ" in status or "исключ" in status:
            c3.font = Font(color="C00000", size=9)
        filled += 1

    # автофильтр — на всю ширину
    if ws.auto_filter.ref:
        ws.auto_filter.ref = f"A1:{get_column_letter(start_col + 2)}{ws.max_row}"

    wb.save(path)
    print(f"{os.path.basename(path)}: +3 колонки, заполнено строк {filled}")
    return wb


def build_reference(mapping, wb_bb):
    """Справочник: лист «ПВО» + лист «По выпускам»."""
    # эмитент/выпуск/рейтинг по ISIN
    meta = {}
    for path in FILES:
        ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
        cur_issuer, cur_rating = None, None
        for r in ws.iter_rows(min_row=2, values_only=True):
            if r[0]:
                cur_issuer = str(r[0]).strip()
            if r[2] and str(r[2]).startswith("RU"):
                meta.setdefault(str(r[2]).strip(), {
                    "issuer": cur_issuer,
                    "name": str(r[1] or "").strip(),
                    "rating": str(r[3] or "").strip(),
                })

    out = openpyxl.Workbook()
    out.remove(out.active)

    # --- лист «ПВО»
    ws = out.create_sheet("ПВО")
    ws["A1"] = "Представители владельцев облигаций в реестре ковенантов"
    ws["A1"].font = Font(bold=True, size=13, color="1F4E79")
    ws["A2"] = ("Источники: решения о выпуске (Финам), сайты ПВО, список лиц ПВО Банка России "
                "по состоянию на 24.11.2026.")
    ws["A2"].font = Font(size=9, italic=True, color="595959")

    head = ["ПВО", "Полное наименование", "Сайт", "Статус в списке ЦБ", "Выпусков"]
    fill = PatternFill("solid", fgColor="1F4E79")
    for i, h in enumerate(head, start=1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER

    agg = {}
    for isin, rec in mapping.items():
        if rec["short"] in ("не определён", "нет данных"):
            continue
        a = agg.setdefault(rec["short"], {"full": rec["full"], "site": rec.get("site", ""),
                                          "status": rec.get("status", ""), "n": 0})
        a["n"] += 1

    r = 5
    for short, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        ws.cell(row=r, column=1, value=short).border = BORDER
        ws.cell(row=r, column=2, value=a["full"]).border = BORDER
        c = ws.cell(row=r, column=3, value=a["site"])
        c.border = BORDER
        if a["site"]:
            c.hyperlink = a["site"]
            c.font = Font(color="0563C1", underline="single")
        c4 = ws.cell(row=r, column=4, value=a["status"])
        c4.border = BORDER
        if "прекращ" in a["status"] or "исключ" in a["status"]:
            c4.font = Font(color="C00000")
        ws.cell(row=r, column=5, value=a["n"]).border = BORDER
        ws.cell(row=r, column=5).alignment = Alignment(horizontal="center")
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="Без ПВО").font = Font(bold=True, size=11, color="1F4E79")
    notes = [
        ("не определён в решении о выпуске",
         "В решении о выпуске на дату его подписания представитель не определён; "
         "назначается отдельным решением до начала размещения."),
        ("нет данных",
         "Решение о выпуске недоступно (ссылка не открывается либо документ без текстового слоя)."),
    ]
    for i, (k, v) in enumerate(notes):
        rr = r + 1 + i
        ws.cell(row=rr, column=1, value=k).border = BORDER
        c = ws.cell(row=rr, column=2, value=v)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=rr, start_column=2, end_row=rr, end_column=5)
        ws.row_dimensions[rr].height = 30

    for col, w in zip("ABCDE", (30, 52, 40, 40, 10)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"

    # --- лист «По выпускам»
    ws2 = out.create_sheet("По выпускам")
    head2 = ["ISIN", "Эмитент", "Выпуск", "Рейтинг", "ПВО", "Сайт ПВО", "Статус ПВО", "Источник"]
    for i, h in enumerate(head2, start=1):
        c = ws2.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER

    r = 2
    for isin, rec in sorted(mapping.items(), key=lambda kv: (
            (meta.get(kv[0], {}).get("issuer") or "").lower(), kv[0])):
        m = meta.get(isin, {})
        pvo, site, status = value_for(rec)
        vals = [isin, m.get("issuer", ""), m.get("name", ""), m.get("rating", ""),
                pvo, site, status, rec.get("source", "")]
        for i, v in enumerate(vals, start=1):
            c = ws2.cell(row=r, column=i, value=v)
            c.border = BORDER
            c.alignment = Alignment(vertical="top", wrap_text=(i in (2, 3)))
        if site:
            c = ws2.cell(row=r, column=6)
            c.hyperlink = site
            c.font = Font(color="0563C1", underline="single", size=9)
        if "прекращ" in status or "исключ" in status:
            ws2.cell(row=r, column=7).font = Font(color="C00000", size=9)
        r += 1

    for col, w in zip("ABCDEFGH", (15, 26, 20, 8, 24, 40, 34, 24)):
        ws2.column_dimensions[col].width = w
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = f"A1:H{r-1}"

    # --- лист «Список ЦБ»: все действующие ПВО и их присутствие в реестре
    cbr_path = WS + "tmp/pvo_registry_cbr.json"
    if os.path.exists(cbr_path):
        cbr = json.load(open(cbr_path, encoding="utf-8"))
        def nrm(x):
            x = str(x or "").lower().replace("ё", "е")
            x = re.sub(r"[^a-zа-я0-9]+", " ", x)
            x = re.sub(r"\b(общество с ограниченной ответственностью|акционерное общество|"
                       r"публичное акционерное общество|научно производственное предприятие|"
                       r"ооо|ао|пао|нпп)\b", " ", x)
            return re.sub(r"\s+", " ", x).strip()

        by_full = {nrm(a["full"]): (short, a["n"]) for short, a in agg.items()}
        ws3 = out.create_sheet("Список ЦБ")
        ws3["A1"] = ("Список лиц, осуществляющих деятельность представителей владельцев облигаций, "
                     "по состоянию на 24.11.2026")
        ws3["A1"].font = Font(bold=True, size=13, color="1F4E79")
        ws3["A2"] = "Источник: Банк России. Отмечены ПВО, выпуски которых есть в реестре ковенантов."
        ws3["A2"].font = Font(size=9, italic=True, color="595959")

        head3 = ["№", "Дата включения", "Наименование", "ОГРН", "В реестре ковенантов", "Выпусков"]
        for i, h in enumerate(head3, start=1):
            c = ws3.cell(row=4, column=i, value=h)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = BORDER

        hl = PatternFill("solid", fgColor="E2EFDA")
        rr = 5
        for i, c_ in enumerate(cbr, start=1):
            short, n = by_full.get(nrm(c_["name"]), ("", 0))
            ws3.cell(row=rr, column=1, value=i).border = BORDER
            ws3.cell(row=rr, column=2, value=c_["date"]).border = BORDER
            cc = ws3.cell(row=rr, column=3, value=c_["name"])
            cc.border = BORDER
            cc.alignment = Alignment(wrap_text=True, vertical="top")
            ws3.cell(row=rr, column=4, value=c_["ogrn"]).border = BORDER
            ws3.cell(row=rr, column=5, value=short or "—").border = BORDER
            ws3.cell(row=rr, column=6, value=n if n else "").border = BORDER
            if n:
                for col in range(1, 7):
                    ws3.cell(row=rr, column=col).fill = hl
            rr += 1

        for col, w in zip("ABCDEF", (5, 15, 62, 16, 24, 10)):
            ws3.column_dimensions[col].width = w
        ws3.freeze_panes = "A5"
        ws3.auto_filter.ref = f"A4:F{rr-1}"

    path = WS + "ПВО_справочник.xlsx"
    out.save(path)
    print("справочник:", path, "строк:", r - 2)


def main():
    os.makedirs(BACKUP, exist_ok=True)
    for p in FILES:
        shutil.copy2(p, BACKUP + os.path.basename(p))
    print("резервная копия:", BACKUP)

    mapping = load_map()
    for p in FILES:
        process(p, mapping)
    build_reference(mapping, None)


if __name__ == "__main__":
    main()
