# -*- coding: utf-8 -*-
"""
Сбор ПВО (представителей владельцев облигаций) по каждому выпуску реестров.

1. собирает уникальные ISIN из реестров B / BB / BBB / new_issues
2. качает решение о выпуске с Финама (ссылка из колонки «Источник (Финам)»
   либо собирается из имени файла в колонке «Файл»)
3. извлекает текст через workbuddy-pdf
4. парсит раздел «Сведения о представителе владельцев облигаций»
5. складывает результат в tmp/pvo_map.json

Запуск: python tools/fetch_pvo.py [--limit N]
"""
import collections
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import urllib.parse

import openpyxl

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
WS = WS.replace("\\", "/").rstrip("/") + "/"
TMP = WS + "tmp/"
PDF_DIR = TMP + "pvo_pdf/"
TXT_DIR = TMP + "pvo_txt/"
PDF_CLI = r"C:/Users/1/.workbuddy-ai/external-packages/pdf-cli/workbuddy-pdf.exe"

FILES = [
    ("B", WS + "Реестр_ковенантов B.xlsx"),
    ("BB", WS + "Реестр_ковенантов BB_ИТОГ.xlsx"),
    ("BBB", WS + "Реестр_ковенантов BBB.xlsx"),
    ("NEW", WS + "new_issues_covenants.xlsx"),
]

os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(TXT_DIR, exist_ok=True)


def collect():
    recs = {}
    for g, path in FILES:
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.worksheets[0]
        hdr = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))
        col_url = None
        for i, h in enumerate(hdr):
            if h and "Финам" in str(h):
                col_url = i
        for r in ws.iter_rows(min_row=2, values_only=True):
            isin = r[2]
            if not isin or not str(isin).startswith("RU"):
                continue
            isin = str(isin).strip()
            rec = recs.setdefault(isin, {"isin": isin, "groups": [], "issuer": None,
                                         "name": None, "url": None, "file": None})
            if g not in rec["groups"]:
                rec["groups"].append(g)
            if r[0] and not rec["issuer"]:
                rec["issuer"] = str(r[0]).strip()
            if r[1] and not rec["name"]:
                rec["name"] = str(r[1]).strip()
            if r[11] and not rec["file"]:
                rec["file"] = str(r[11]).strip()
            if col_url is not None and len(r) > col_url and r[col_url]:
                u = str(r[col_url]).strip()
                if u.lower().startswith("http") and not rec["url"]:
                    rec["url"] = u
    # ссылка: явная либо из имени файла
    for rec in recs.values():
        if not rec["url"] and rec["file"]:
            rec["url"] = "https://st.finam.ru/ipo/genconditions/" + rec["file"]
    return recs


def fetch(rec):
    isin = rec["isin"]
    pdf = PDF_DIR + isin + ".pdf"
    txt = TXT_DIR + isin + ".txt"
    if os.path.exists(txt) and os.path.getsize(txt) > 500:
        return isin, "cached"
    if not os.path.exists(pdf) or os.path.getsize(pdf) < 5000:
        if not rec["url"]:
            return isin, "no url"
        q = urllib.parse.quote(rec["url"], safe=":/")
        r = subprocess.run(["curl", "-sL", "--max-time", "90", "-A", "Mozilla/5.0",
                            q, "-o", pdf, "-w", "%{http_code}"],
                           capture_output=True, text=True)
        if r.stdout.strip() != "200":
            return isin, "http " + r.stdout.strip()
    subprocess.run([PDF_CLI, pdf, txt, "--format", "txt"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(txt):
        return isin, "pdf fail"
    return isin, "ok"


LABELS = [
    r"Полное\s+фирменное\s+наименование[^:]{0,200}:",
    r"Полное\s+наименование[^:]{0,150}:",
    r"Наименование\s+представителя[^:]{0,150}:",
]

OPF = (r"(?:Общество\s+с\s+ограниченной\s+ответственностью|"
       r"Акционерное\s+общество|Публичное\s+акционерное\s+общество|"
       r"ООО|АО|ПАО|МКАО)")


def clean(cand):
    cand = re.sub(r"\s*[\(（]\s*далее.*$", "", cand, flags=re.I)
    cand = re.sub(r"\s*[\(（]\s*ранее.*$", "", cand, flags=re.I)
    cand = re.sub(r"\s+\d{1,3}\s+(?=[А-ЯA-Z])", " ", cand)  # номер страницы
    cand = re.sub(r"\s+", " ", cand.replace("\u00ad", ""))
    return cand.strip(" .;:,")


def parse(txt):
    # всё в одну строку — в табличных разделах метки и значения разорваны переводами строк
    t = re.sub(r"\s+", " ", txt.replace("\u00ad", ""))
    res = {"pvo": None, "ogrn": None, "inn": None, "note": None}
    low = t.lower()

    i = low.find("сведения о представителе владельцев облигаций")
    if i < 0:
        res["note"] = "раздел не найден"
        return res
    seg = t[i:i + 1600]

    # ПВО не определён — проверяем внутри раздела, а не по всему документу
    if re.search(r"представител\w*\s+владельцев\s+(?:\w+\s+){0,2}облигаций"
                 r"[^.]{0,120}?\bне\s+(?:определ|назначал|назначен)", seg, re.I):
        res["note"] = "ПВО не определён"
        return res

    name = None
    # 1) обычная форма «метка: значение»
    for pat in LABELS:
        m = re.search(pat, seg, re.I)
        if m:
            tail = seg[m.end():]
            cut = re.split(r"(?:Место\s+нахождения|Адрес|Основной\s+государственный|"
                           r"Идентификационный\s+номер|ОГРН|ИНН|Обязанности)", tail,
                           maxsplit=1, flags=re.I)
            cand = clean(cut[0])
            if len(cand) > 4 and not cand.lower().startswith(("место", "адрес")):
                name = cand
                break
    # 2) табличная форма: ОПФ + название в кавычках где-то в разделе
    if not name:
        m = re.search(r"(" + OPF + r"\s*[«\"].{3,140}?[»\"])", seg)
        if m:
            name = clean(m.group(1))
    res["pvo"] = name

    m = re.search(r"ОГРН[^0-9]{0,60}(\d{13})", seg)
    if m:
        res["ogrn"] = m.group(1)
    m = re.search(r"ИНН[^0-9]{0,60}(\d{10,12})", seg)
    if m:
        res["inn"] = m.group(1)
    return res


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    recs = collect()
    items = list(recs.values())
    if limit:
        items = items[:limit]
    print("выпусков:", len(items))

    status = collections.Counter()
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for isin, st in ex.map(fetch, items):
            status[st.split(":")[0]] += 1
    print("загрузка:", dict(status))

    out = {}
    for rec in items:
        txt_path = TXT_DIR + rec["isin"] + ".txt"
        if not os.path.exists(txt_path):
            rec.update({"pvo": None, "note": "нет текста"})
            out[rec["isin"]] = rec
            continue
        t = open(txt_path, encoding="utf-8", errors="ignore").read()
        rec.update(parse(t))
        out[rec["isin"]] = rec

    json.dump(out, open(TMP + "pvo_map.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    c = collections.Counter((v.get("pvo") or "—") for v in out.values())
    print("\nПВО по выпускам:")
    for k, n in c.most_common():
        print(f"{n:4d}  {k}")
    print("\nбез разбора:", sum(1 for v in out.values() if not v.get("pvo")))


if __name__ == "__main__":
    main()
