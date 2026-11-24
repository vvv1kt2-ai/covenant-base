# -*- coding: utf-8 -*-
"""
Сборка публикационного материала по ковенантам.

Вход:
  publication/data/Реестр_ковенантов B.xlsx          -> рейтинговая группа B
  publication/data/Реестр_ковенантов BB_ИТОГ.xlsx    -> рейтинговая группа BB
  publication/data/Реестр_ковенантов BBB.xlsx        -> рейтинговая группа BBB
  publication/data/new_issues_covenants.xlsx         -> новые выпуски (раскладываются по своим группам)
  D:/API мосбиржи/data/covenants/marked/Погашения_до_2026-12-31.xlsx
        лист «Гасятся до 31.12.2026»             -> выпуски, исключаемые по сроку погашения
  D:/API мосбиржи/data/iss-issuedate-cache.json  -> ISIN -> emitter id
  D:/API мосбиржи/data/iss-emitters-cache.json   -> emitter id -> краткое наименование

Выход:
  publication/data/Ковенанты_для_публикации.xlsx
    листы: B, BB, BBB (Эмитент | Выпуски | Категория ковенант), Легенда, Исключения
"""

import json
import os
import re
import collections
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
WS = WS.replace("\\", "/").rstrip("/") + "/"
OUT_XLSX = os.environ.get("COVENANT_OUT", WS + "Ковенанты_для_публикации.xlsx")
OUT_MD = os.environ.get("COVENANT_OUT_MD", WS + "Ковенанты_для_публикации.md")
MOEX = os.environ.get("COVENANT_MOEX") or "D:/API мосбиржи/data/"
MOEX = MOEX.replace("\\", "/").rstrip("/") + "/"
MARKED = MOEX + "covenants/marked/"

# ---------------------------------------------------------------- таксономия

CANON = ["Отчётность", "Финковенант", "Кросс-дефолт", "Делистинг", "Смена контроля", "Иное"]

LEGEND = [
    ("Отчётность",
     "Эмитент не раскрыл отчётность в установленный срок: свою бухгалтерскую (РСБУ), "
     "консолидированную отчётность группы (МСФО) или отчётность поручителя."),
    ("Финковенант",
     "Нарушение числового финансового показателя: превышение долговой нагрузки "
     "(Долг/EBITDA, леверидж), падение выручки ниже порога, займы связанным лицам."),
    ("Кросс-дефолт",
     "Дефолт, просрочка или существенное нарушение по иному долгу эмитента, "
     "поручителя или связанных лиц — в том числе по банковским кредитам."),
    ("Делистинг",
     "Прекращение торгов выпуском, исключение из списка ценных бумаг, "
     "утрата листинга на бирже."),
    ("Смена контроля",
     "Утрата контроля бенефициаром или контролирующим лицом, отчуждение долей "
     "или существенных активов."),
    ("Иное",
     "Прочие основания: реорганизация или ликвидация, дивиденды и распределение прибыли, "
     "утрата кредитного рейтинга, нецелевое использование средств."),
]

FILL = {
    "Отчётность":     "DDEBF7",
    "Финковенант":    "FCE4D6",
    "Кросс-дефолт":   "E2EFDA",
    "Делистинг":      "FFF2CC",
    "Смена контроля": "E4DFEC",
    "Иное":           "F2F2F2",
}

# приведение исходной категории к канонической
MAP = {
    "раскрытие отчётности эмитента":                 "Отчётность",
    "раскрытие отчётности группы / поручителя":      "Отчётность",
    "раскрытие отчётности поручетеля":               "Отчётность",
    "раскрытие отчётности":                          "Отчётность",
    "информационный (отчётность эмитента)":          "Отчётность",
    "информационный (отчётность группы)":            "Отчётность",
    "финансовый ковенант (долговая нагрузка)":       "Финковенант",
    "финансовый ковенант (займы связанных лиц)":     "Финковенант",
    "финансовый ковенант (выручка)":                 "Финковенант",
    "долговая нагрузка":                             "Финковенант",
    "кросс-дефолт":                                  "Кросс-дефолт",
    "делистинг":                                     "Делистинг",
    "смена контроля / бенефициара":                  "Смена контроля",
    "утрата контроля":                               "Смена контроля",
    "реорганизация / ликвидация":                    "Иное",
    "снижение задолженности связанных лиц":          "Иное",
    "выплата дивидендов, распределение прибыли":     "Иное",
    "утрата кредитного рейтинга":                    "Иное",
    "нецелевое использование средств":               "Иное",
    "иное":                                          "Иное",
    "иное основание":                                "Иное",
}

# маркеры «ковенант нет» (в выпуске отсутствует право требования досрочного погашения)
NO_COVENANT_MARKERS = (
    "Положения о досрочном погашении",
    "Право требования досрочного погашения НЕ",
)
# маркеры «разбор не удался»
PARSE_FAIL_MARKERS = (
    "ОШИБКА ПАРСИНГА",
    "ТРЕБУЕТСЯ ПРОВЕРКА ВРУЧНУЮ",
)

# переклассификация строк «Иное» по прочитанной цитате
RECLASS_BY_TEXT = [
    (r"просрочк\w+\s+плат\w+.*кредитн", "Кросс-дефолт"),
    (r"отзыв\s+кредитн\w+\s+рейтингов\w+\s+агентств", "Иное"),
    (r"распределение\s+в\s+течение\s+срока\s+обращения.*чистой\s+прибыли", "Иное"),
    (r"отч[её]т\s+о\s+переоценке", "Отчётность"),
    (r"статус\w*\s+контролирующ", "Смена контроля"),
    (r"предоставлять\s+ПВО\s+отч[её]т", "Отчётность"),
]

# Результаты ручной проверки выпусков, не поддавшихся автоматическому разбору.
# ISIN -> (категории или None, причина исключения если None)
MANUAL = {
    # ковенант нет
    "RU000A101T72": (None, "по результатам ручной проверки: право требования досрочного погашения не предусмотрено"),
    "RU000A10DG52": (None, "по результатам ручной проверки: право требования досрочного погашения не предусмотрено"),
    # эмитент в дефолте
    "RU000A0JXGV0": (None, "эмитент в дефолте — исключено при подготовке публикации"),
    "RU000A0JUT85": (None, "эмитент в дефолте — исключено при подготовке публикации"),
    "RU000A0JVM32": (None, "эмитент в дефолте — исключено при подготовке публикации"),
    # делистинг по Программе облигаций
    "RU000A10ADJ3": (["Делистинг"], None),
    "RU000A10BUM9": (["Делистинг"], None),
    "RU000A10BVT2": (["Делистинг"], None),
    "RU000A10EKX1": (["Делистинг"], None),
    "RU000A10ETM5": (["Делистинг"], None),
    "RU000A0ZYM54": (["Делистинг"], None),
}

RATING_RANK = {"B": 1, "BB": 2, "BBB": 3}

REGISTRIES = [
    ("B",   WS + "Реестр_ковенантов B.xlsx"),
    ("BB",  WS + "Реестр_ковенантов BB_ИТОГ.xlsx"),
    ("BBB", WS + "Реестр_ковенантов BBB.xlsx"),
]


# ---------------------------------------------------------------- helpers

def rating_group(rating):
    """'BB+' -> 'BB', 'B-' -> 'B', 'BBB-' -> 'BBB'."""
    s = str(rating or "").strip().upper()
    if s.startswith("BBB"):
        return "BBB"
    if s.startswith("BB"):
        return "BB"
    if s.startswith("B"):
        return "B"
    return ""


def split_composite(cat):
    """
    'Финансовый ковенант (долговая нагрузка)\\n+ Раскрытие отчётности эмитента; Делистинг'
      -> ['Финансовый ковенант (долговая нагрузка)', 'Раскрытие отчётности эмитента', 'Делистинг']
    Часть после '+' — дополнительные триггеры в том же пункте документа.
    """
    if not cat:
        return []
    parts = [cat]
    if "\n+" in cat:
        base, rest = cat.split("\n+", 1)
        parts = [base] + [p.strip() for p in rest.split(";")]
    return [p.strip() for p in parts if p.strip()]


def canon(part, quote=""):
    """Один исходный триггер -> каноническая категория."""
    key = part.strip().lower()
    if key in ("иное", "иное основание"):
        # «иное» уточняем по цитате — там часто реальный кросс-дефолт или отчётность
        for pattern, target in RECLASS_BY_TEXT:
            if re.search(pattern, str(quote or ""), re.I):
                return target
    if key in MAP:
        return MAP[key]
    return "Иное"


def derive_issuer_from_issue(name):
    """'ИЛОН-001Р-01' -> 'ИЛОН'; 'АПТЕЧНАЯ СЕТЬ 36,6-002P-01' -> 'АПТЕЧНАЯ СЕТЬ 36,6'."""
    s = str(name or "").strip()
    # 'ЭНЕРГОТЕХСЕРВИС-001Р-07' -> 'ЭНЕРГОТЕХСЕРВИС', 'ЦЕНТРАЛЬНАЯ ППК-П01-БО-01' -> 'ЦЕНТРАЛЬНАЯ ППК'
    m = re.search(r"\s*-(?:00\d\s*[РP]|П\d\d|[БB][ОO])|\s[БB][ОO]-", s)
    if m:
        return s[:m.start()].strip(" -")
    return s


# ---------------------------------------------------------------- 1. MOEX

issuedate = json.load(open(MOEX + "iss-issuedate-cache.json", encoding="utf-8"))
emitters = json.load(open(MOEX + "iss-emitters-cache.json", encoding="utf-8"))
sec_by_isin = {}
for k, v in issuedate.items():
    if k.startswith("_") or not isinstance(v, dict):
        continue
    if v.get("isin"):
        sec_by_isin[v["isin"]] = v


def moex_issuer(isin):
    """Краткое наименование эмитента из MOEX ISS. '' если не найдено."""
    sec = sec_by_isin.get(isin)
    if not sec:
        return ""
    em = emitters.get(str(sec.get("emitter")))
    if not em:
        return ""
    return (em.get("SHORT") or em.get("TITLE") or "").strip()


def moex_issue_name(isin):
    sec = sec_by_isin.get(isin)
    if not sec:
        return ""
    return (sec.get("shortname") or sec.get("name") or "").strip()


# ---------------------------------------------------------------- 2. исключения по погашению

wb = openpyxl.load_workbook(MARKED + "Погашения_до_2026-12-31.xlsx", data_only=True)
redeem = set()
for r in wb["Гасятся до 31.12.2026"].iter_rows(min_row=2, values_only=True):
    if r[3]:
        redeem.add(str(r[3]).strip())

# ---------------------------------------------------------------- 2b. ПВО

PVO_REF = WS + "ПВО_справочник.xlsx"


def load_pvo():
    """ISIN -> (краткое имя ПВО, сайт)."""
    if not os.path.exists(PVO_REF):
        return {}
    wb = openpyxl.load_workbook(PVO_REF, data_only=True)
    ws = wb["По выпускам"]
    m = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0]:
            pvo = str(r[4] or "").strip()
            if pvo in ("не определён в решении о выпуске", "нет данных"):
                pvo = "—"
            m[str(r[0]).strip()] = (pvo, str(r[5] or "").strip())
    return m


PVO = load_pvo()

# ---------------------------------------------------------------- 3. чтение реестров

issues = collections.OrderedDict()   # (group, isin) -> record
excluded = []


def add_issue(group, isin, issuer, name, rating, pairs, src):
    """pairs — список (категория, цитата) построчно: цитата нужна для уточнения «Иное»."""
    key = (group, isin)
    rec = issues.setdefault(key, {
        "group": group, "isin": isin, "issuer": issuer, "name": name,
        "rating": rating, "cats": set(), "raw": [], "src": src,
        "pvo": PVO.get(isin, ("—", ""))[0],
    })
    if issuer and not rec["issuer"]:
        rec["issuer"] = issuer
    if name and not rec["name"]:
        rec["name"] = name
    for c, q in pairs:
        rec["raw"].append(c)
        for part in split_composite(c):
            rec["cats"].add(canon(part, q))


for group, path in REGISTRIES:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    pending_issuer, cur_issuer, cur_isin, cur_name, cur_rating = None, None, None, None, None
    block = []          # накопитель строк одного выпуска

    def flush():
        if not cur_isin:
            return
        # ручная проверка имеет приоритет над автоматическим разбором
        if cur_isin in MANUAL:
            cats_m, why = MANUAL[cur_isin]
            if cur_isin in redeem:
                excluded.append({"group": group, "issuer": cur_issuer, "name": cur_name,
                                 "isin": cur_isin, "rating": cur_rating,
                                 "why": "погашение до 31.12.2026"})
            elif cats_m:
                add_issue(group, cur_isin, cur_issuer, cur_name, cur_rating,
                          [(c, "") for c in cats_m], "ручная проверка")
            else:
                excluded.append({"group": group, "issuer": cur_issuer, "name": cur_name,
                                 "isin": cur_isin, "rating": cur_rating, "why": why})
            return

        cats = [r[6] for r in block if r[6]]
        # разбор не удался
        if any(any(m in str(c) for m in PARSE_FAIL_MARKERS) for c in cats):
            excluded.append({
                "group": group, "issuer": cur_issuer, "name": cur_name,
                "isin": cur_isin, "rating": cur_rating,
                "why": "документ — скан без текстового слоя, автоматический разбор невозможен",
            })
            return
        # гасится до конца года
        if cur_isin in redeem:
            excluded.append({
                "group": group, "issuer": cur_issuer, "name": cur_name,
                "isin": cur_isin, "rating": cur_rating,
                "why": "погашение до 31.12.2026",
            })
            return
        # BBB: «Иное» — в реестре это ссылки на Программу облигаций, конкретного события нет
        if group == "BBB" and any(str(row[6] or "").strip() == "Иное" for row in block):
            excluded.append({"group": group, "issuer": cur_issuer, "name": cur_name,
                             "isin": cur_isin, "rating": cur_rating,
                             "why": "формулировка не содержит конкретного события "
                                    "(ссылка на Программу облигаций или на законодательство), "
                                    "требуется ручная проверка"})
            return

        real = [c for c in cats if not any(m in str(c) for m in NO_COVENANT_MARKERS)]
        real = [c for c in real if str(c).strip() not in ("—", "", "None")]
        if not real:
            excluded.append({
                "group": group, "issuer": cur_issuer, "name": cur_name,
                "isin": cur_isin, "rating": cur_rating,
                "why": "право требования досрочного погашения не предусмотрено (ковенант нет)",
            })
            return
        pairs = [(r[6], str(r[12] or "")) for r in block if r[6]]
        add_issue(group, cur_isin, cur_issuer, cur_name, cur_rating, pairs, path)

    for r in rows:
        if r[0]:
            # имя эмитента стоит только в первой строке блока — запоминаем до начала выпуска
            pending_issuer = str(r[0]).strip()
        if r[2]:
            flush()
            block = []
            cur_issuer = pending_issuer
            cur_isin = str(r[2]).strip()
            cur_name = str(r[1] or "").strip()
            cur_rating = str(r[3] or "").strip()
            if not cur_name:
                # BBB: имя выпуска лежит в колонке «Эмитент»
                cur_name = cur_issuer or moex_issue_name(cur_isin)
                cur_issuer = ""
        block.append(r)
    flush()

# ---------------------------------------------------------------- 4. новые выпуски

wb = openpyxl.load_workbook(WS + "new_issues_covenants.xlsx", data_only=True)
ws = wb.worksheets[0]
cur_isin, cur_name, cur_rating = None, None, None
nb = []


def flush_new():
    if not cur_isin or not rating_group(cur_rating):
        return
    if cur_isin in redeem:
        excluded.append({"group": rating_group(cur_rating), "issuer": "", "name": cur_name,
                         "isin": cur_isin, "rating": cur_rating,
                         "why": "погашение до 31.12.2026"})
        return
    cats = [x[0] for x in nb if x[0]]
    cats = [c for c in cats if not any(m in str(c) for m in NO_COVENANT_MARKERS)]
    if not cats:
        excluded.append({"group": rating_group(cur_rating), "issuer": "", "name": cur_name,
                         "isin": cur_isin, "rating": cur_rating,
                         "why": "право требования досрочного погашения не предусмотрено (ковенант нет)"})
        return
    add_issue(rating_group(cur_rating), cur_isin, None, cur_name, cur_rating, nb,
              "new_issues_covenants.xlsx")


for r in ws.iter_rows(min_row=2, values_only=True):
    if r[2] and str(r[2]).startswith("RU"):
        flush_new()
        cur_isin = str(r[2]).strip()
        cur_name = str(r[0] or "").strip()
        cur_rating = str(r[3] or "").strip()
        nb = []
    if r[6]:
        nb.append((r[6], r[12]))
flush_new()

# ---------------------------------------------------------------- 5. имена эмитентов

OPF = re.compile(r"^(?:ООО|ОАО|ЗАО|ПАО|АО|НКО|МФК|МКК|ИК|ЛК|УК|ПК)\s+", re.I)


def clean_issuer(s):
    """'ООО ПКО "Бустер.ру"' -> 'ПКО Бустер.ру'; 'АО "ТАЛК лизинг"' -> 'ТАЛК лизинг'."""
    s = str(s or "").strip()
    for _ in range(2):
        s = OPF.sub("", s).strip()
    s = s.replace("«", " ").replace("»", " ").replace('"', " ")
    return re.sub(r"\s+", " ", s).strip(" -")


def issuer_key(s):
    """Ключ группировки: 'ПКО _Вернем' и 'ПКО Вернём' — один эмитент."""
    s = str(s or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]", "", s)


for (group, isin), rec in issues.items():
    if not rec["issuer"]:
        rec["issuer"] = clean_issuer(moex_issuer(isin)) or derive_issuer_from_issue(rec["name"])
    if not rec["name"]:
        rec["name"] = moex_issue_name(isin) or rec["issuer"]
    # артефакты разметки исходных реестров («ПКО _Вернем») в публикацию не выносятся
    rec["issuer"] = re.sub(r"\s+", " ", re.sub(r"_+", " ", rec["issuer"])).strip(" -")
    rec["key"] = issuer_key(rec["issuer"])

# ---------------------------------------------------------------- 6. дедупликация по рейтингу

by_isin = collections.defaultdict(list)
for (group, isin), rec in issues.items():
    by_isin[isin].append(rec)

deduped = []
dropped_dupes = []
for isin, recs in by_isin.items():
    if len(recs) == 1:
        deduped.append(recs[0])
        continue
    recs.sort(key=lambda x: RATING_RANK.get(x["group"], 9))
    deduped.append(recs[0])
    for r in recs[1:]:
        dropped_dupes.append((isin, r["group"], recs[0]["group"]))

# ---------------------------------------------------------------- 7. группировка

grouped = {"B": collections.OrderedDict(), "BB": collections.OrderedDict(), "BBB": collections.OrderedDict()}
label = {}   # ключ эмитента -> вариант написания для публикации
for rec in deduped:
    k = rec["key"]
    # предпочитаем вариант без артефактов разметки, при прочих равных — более полный
    cand = rec["issuer"]
    if k not in label or ("_" in label[k], -len(label[k])) > ("_" in cand, -len(cand)):
        label[k] = cand
    key = (k, tuple(c for c in CANON if c in rec["cats"]))
    g = grouped.setdefault(rec["group"], collections.OrderedDict())
    g.setdefault(key, []).append((rec["name"], rec.get("pvo") or "—"))

for g in grouped:
    items = sorted(grouped[g].items(),
                   key=lambda kv: (label[kv[0][0]].lower(), -len(kv[0][1]), kv[0][1]))
    grouped[g] = collections.OrderedDict(items)

# ---------------------------------------------------------------- 8. запись

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
TITLE_FONT = Font(bold=True, size=13, color="1F4E79")
HEAD_FONT = Font(bold=True, color="FFFFFF", size=11)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

out = openpyxl.Workbook()
out.remove(out.active)

TAB_COLOR = {"B": "C55A11", "BB": "FFC000", "BBB": "A9D08E"}

for g in ("B", "BB", "BBB"):
    ws = out.create_sheet(g)
    ws.sheet_properties.tabColor = TAB_COLOR[g]
    ws["A1"] = f"Выпуски с правом требования досрочного погашения — рейтинговая группа {g}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("Категория ковенанта указана по каждому основанию, при наступлении которого "
                "владелец вправе предъявить выпуск к досрочному погашению. Раскрытие категорий — на листе «Легенда».")
    ws["A2"].font = Font(size=9, italic=True, color="595959")
    ws.merge_cells("A2:D2")
    ws["A2"].alignment = Alignment(wrap_text=False)

    for i, h in enumerate(["Эмитент", "Выпуски", "Категория ковенант", "ПВО"], start=1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER

    r = 5
    for (issuer, cats), items in grouped[g].items():
        names = [n for n, _ in items]
        pvos = list(dict.fromkeys(p for _, p in items if p and p != "—"))
        ws.cell(row=r, column=1, value=label[issuer]).border = BORDER
        ws.cell(row=r, column=2, value=", ".join(sorted(set(names)))).border = BORDER
        c = ws.cell(row=r, column=3, value=" · ".join(cats))
        c.border = BORDER
        c.fill = PatternFill("solid", fgColor=FILL[cats[0]] if len(cats) == 1 else "FFFFFF")
        if len(cats) == 1:
            c.alignment = Alignment(horizontal="center")
        cp = ws.cell(row=r, column=4, value=", ".join(pvos) if pvos else "—")
        cp.border = BORDER
        for col in (1, 2, 3, 4):
            ws.cell(row=r, column=col).alignment = Alignment(
                vertical="top", wrap_text=(col in (2, 4)),
                horizontal=(ws.cell(row=r, column=col).alignment.horizontal or "left"))
        r += 1

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 32
    ws.column_dimensions["D"].width = 26
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:D{r-1}"
    print(f"лист {g}: строк {r-5}")

# Легенда
lw = out.create_sheet("Легенда")
lw["A1"] = "Категории ковенант"
lw["A1"].font = TITLE_FONT
for i, h in enumerate(["Категория", "Что означает"], start=1):
    c = lw.cell(row=3, column=i, value=h)
    c.font = HEAD_FONT
    c.fill = HEAD_FILL
    c.alignment = Alignment(horizontal="center")
    c.border = BORDER
r = 4
for name, text in LEGEND:
    c1 = lw.cell(row=r, column=1, value=name)
    c1.fill = PatternFill("solid", fgColor=FILL[name])
    c1.border = BORDER
    c1.alignment = Alignment(vertical="top")
    c2 = lw.cell(row=r, column=2, value=text)
    c2.border = BORDER
    c2.alignment = Alignment(vertical="top", wrap_text=True)
    lw.row_dimensions[r].height = 42
    r += 1
r += 1
lw.cell(row=r, column=1, value="Примечания").font = Font(bold=True, size=11, color="1F4E79")
notes = [
    "Если у выпуска несколько оснований, в ячейке они перечислены через « · » в порядке: "
    + " · ".join(CANON) + ".",
    "В таблицу не включены выпуски, у которых право требования досрочного погашения не предусмотрено, "
    "выпуски с погашением до 31.12.2026 и выпуски, эмиссионные документы по которым не поддались "
    "автоматическому разбору — они перечислены на листе «Исключения».",
    "Если один и тот же выпуск встречается в реестрах разных рейтинговых групп, он показан один раз — "
    "в группе с более низким рейтингом.",
    "Колонка «ПВО» — представитель владельцев облигаций по решению о выпуске (сверен со списком лиц ПВО "
    "Банка России на 24.11.2026). «—» означает, что в решении о выпуске представитель не определён "
    "или документ недоступен; расшифровка — на листе «ПВО».",
    "Точные формулировки и пункты эмиссионной документации в публикацию не выносятся; при необходимости "
    "они доступны в исходных реестрах по ссылке на документ.",
]
for i, n in enumerate(notes):
    c = lw.cell(row=r + 1 + i, column=1, value="— " + n)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    lw.merge_cells(start_row=r + 1 + i, start_column=1, end_row=r + 1 + i, end_column=2)
    lw.row_dimensions[r + 1 + i].height = 30
lw.column_dimensions["A"].width = 22
lw.column_dimensions["B"].width = 100

# ПВО
pw = out.create_sheet("ПВО")
pw["A1"] = "Представители владельцев облигаций (ПВО)"
pw["A1"].font = TITLE_FONT
pw["A2"] = ("Источник: решения о выпуске, сайты ПВО; статус — по списку лиц, осуществляющих деятельность "
            "представителей владельцев облигаций, Банка России на 24.11.2026.")
pw["A2"].font = Font(size=9, italic=True, color="595959")

pvo_dir = {}
if os.path.exists(PVO_REF):
    wb_ref = openpyxl.load_workbook(PVO_REF, data_only=True)
    for rr in wb_ref["ПВО"].iter_rows(min_row=5, values_only=True):
        if rr[0] and rr[1]:
            pvo_dir[str(rr[0]).strip()] = (rr[1], rr[2] or "", rr[3] or "")

for i, h in enumerate(["ПВО", "Полное наименование", "Сайт", "Статус в списке ЦБ",
                       "Выпусков в публикации"], start=1):
    c = pw.cell(row=4, column=i, value=h)
    c.font = HEAD_FONT
    c.fill = HEAD_FILL
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border = BORDER

pvo_counts = collections.Counter(r["pvo"] for r in deduped
                                 if r.get("pvo") and r["pvo"] != "—")
r = 5
for short, n in pvo_counts.most_common():
    full, site, status = pvo_dir.get(short, (short, "", ""))
    pw.cell(row=r, column=1, value=short).border = BORDER
    pw.cell(row=r, column=2, value=full).border = BORDER
    cs = pw.cell(row=r, column=3, value=site)
    cs.border = BORDER
    if site:
        cs.hyperlink = site
        cs.font = Font(color="0563C1", underline="single", size=10)
    cst = pw.cell(row=r, column=4, value=status)
    cst.border = BORDER
    if "прекращ" in status or "исключ" in status:
        cst.font = Font(color="C00000", size=10)
    cn = pw.cell(row=r, column=5, value=n)
    cn.border = BORDER
    cn.alignment = Alignment(horizontal="center")
    r += 1

r += 1
pw.cell(row=r, column=1, value="«—» в колонке «ПВО»").font = Font(bold=True, size=11, color="1F4E79")
note_pvo = ("В решении о выпуске представитель владельцев облигаций не определён либо документ недоступен. "
            "Для таких выпусков ПВО назначается отдельным решением; сведения требуют уточнения у эмитента.")
c = pw.cell(row=r + 1, column=1, value=note_pvo)
c.alignment = Alignment(wrap_text=True, vertical="top")
pw.merge_cells(start_row=r + 1, start_column=1, end_row=r + 1, end_column=5)
pw.row_dimensions[r + 1].height = 32

for col, w in zip("ABCDE", (28, 52, 42, 38, 12)):
    pw.column_dimensions[col].width = w
pw.freeze_panes = "A5"

# Исключения
ew = out.create_sheet("Исключения")
ew["A1"] = "Выпуски, не вошедшие в публикацию"
ew["A1"].font = TITLE_FONT
for i, h in enumerate(["Группа", "Эмитент / выпуск", "ISIN", "Рейтинг", "Причина исключения"], start=1):
    c = ew.cell(row=3, column=i, value=h)
    c.font = HEAD_FONT
    c.fill = HEAD_FILL
    c.alignment = Alignment(horizontal="center")
    c.border = BORDER
r = 4
for x in sorted(excluded, key=lambda z: (z["group"], str(z["issuer"] or z["name"]).lower())):
    ew.cell(row=r, column=1, value=x["group"]).border = BORDER
    ew.cell(row=r, column=2, value=x["issuer"] or x["name"] or "").border = BORDER
    ew.cell(row=r, column=3, value=x["isin"]).border = BORDER
    ew.cell(row=r, column=4, value=x["rating"]).border = BORDER
    ew.cell(row=r, column=5, value=x["why"]).border = BORDER
    r += 1
r += 1
ew.cell(row=r, column=1, value="Дубли (выпуск показан в группе с более низким рейтингом)").font = Font(bold=True)
r += 1
for isin, dropped_from, kept_in in sorted(dropped_dupes):
    ew.cell(row=r, column=1, value=dropped_from)
    ew.cell(row=r, column=2, value=f"показан в группе {kept_in}")
    ew.cell(row=r, column=3, value=isin)
    r += 1
for col, w in zip("ABCDE", (10, 40, 16, 10, 62)):
    ew.column_dimensions[col].width = w
ew.freeze_panes = "A4"

# ---------------------------------------------------------------- 9. Markdown-версия

md = ["# Ковенанты: право требования досрочного погашения", "",
      "_Категория ковенанта — основание, при наступлении которого владелец выпуска вправе "
      "предъявить его к досрочному погашению. Полный текст — в эмиссионной документации._", ""]
for name, text in LEGEND:
    md.append(f"* **{name}** — {text}")
md.append("")
for g in ("B", "BB", "BBB"):
    md.append(f"## Рейтинговая группа {g}")
    md.append("")
    md.append("| Эмитент | Выпуски | Категория ковенант | ПВО |")
    md.append("|---|---|---|---|")
    for (issuer, cats), items in grouped[g].items():
        names = [n for n, _ in items]
        pvos = list(dict.fromkeys(p for _, p in items if p and p != "—"))
        md.append(f"| {label[issuer]} | {', '.join(sorted(set(names)))} | {' · '.join(cats)} "
                  f"| {', '.join(pvos) if pvos else '—'} |")
    md.append("")
open(OUT_MD, "w", encoding="utf-8").write("\n".join(md))

out.save(OUT_XLSX)

print(f"\nИсключено: {len(excluded)} (погашение/нет ковенант/скан), дублей: {len(dropped_dupes)}")
print("Строк в публикации:", sum(len(v) for v in grouped.values()))
for g in ("B", "BB", "BBB"):
    n = sum(len(v) for (k, v) in grouped[g].items())
    print(f"  {g}: эмитент+наборов ковенант = {len(grouped[g])}, выпусков = {n}")
