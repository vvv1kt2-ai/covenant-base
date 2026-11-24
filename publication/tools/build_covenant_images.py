# -*- coding: utf-8 -*-
"""
Растровые изображения материала по ковенантам для публикации.

Вход:  publication/data/Ковенанты_для_публикации.xlsx (листы B, BB, BBB, Легенда)
Выход: publication/img/Ковенанты_B.png
       publication/img/Ковенанты_BB.png
       publication/img/Ковенанты_BBB.png
       publication/img/Ковенанты_все_группы.png
       publication/img/Ковенанты_все_группы.pdf   (растр, без текстового слоя)

Рендер: headless Chrome -> PNG (текстового слоя нет, только пиксели),
лишний фон снизу обрезается по цвету подложки.
"""

import html
import os
import shutil
import subprocess
import tempfile
import openpyxl
from PIL import Image

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
WS = WS.replace("\\", "/").rstrip("/") + "/"
OUT = os.environ.get("COVENANT_IMG_OUT") or (os.path.dirname(WS.rstrip("/")) + "/img/")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# ---------------------------------------------------------------- геометрия

PAGE_W = 1440          # логическая ширина страницы, px
SCALE = 2              # плотность пикселей: 1440 -> 2880 px по ширине
COL = (330, 700, 322)  # Эмитент | Выпуски | Категория ковенант (сумма + padding = PAGE_W)
FONT = 15              # базовый кегль, px
CHIP_FONT = 13

FILL = {
    "Отчётность":     "#DDEBF7",
    "Финковенант":    "#FCE4D6",
    "Кросс-дефолт":   "#E2EFDA",
    "Делистинг":      "#FFF2CC",
    "Смена контроля": "#E4DFEC",
    "Иное":           "#F2F2F2",
}
TAB_COLOR = {"B": "#C55A11", "BB": "#BF9000", "BBB": "#548235"}
PAGE_BG = "#E9EEF3"


# ---------------------------------------------------------------- данные

SRC = os.environ.get("COVENANT_IN", WS + "Ковенанты_для_публикации.xlsx")
wb = openpyxl.load_workbook(SRC)

groups = {}
for g in ("B", "BB", "BBB"):
    rows = []
    for r in wb[g].iter_rows(min_row=5, values_only=True):
        if r[0]:
            rows.append((str(r[0]), str(r[1]), str(r[2])))
    groups[g] = rows

legend = []
for r in wb["Легенда"].iter_rows(min_row=4, values_only=True):
    if r[0] and r[0] in FILL:
        legend.append((str(r[0]), str(r[1])))


# ---------------------------------------------------------------- вёрстка

CSS = f"""
* {{ box-sizing: border-box; }}
body {{ margin:0; background:{PAGE_BG};
        font-family:"Segoe UI",Arial,sans-serif; color:#1A1A1A; }}
.card {{ background:#fff; padding:40px 44px 36px; }}
h1 {{ font-size:30px; line-height:1.2; margin:0 0 6px; letter-spacing:-.2px; }}
.sub {{ font-size:13px; color:#6B7280; margin:0 0 26px; }}
h2 {{ font-size:19px; margin:30px 0 12px; padding:8px 0 8px 14px;
      border-left:5px solid #999; }}
h2 .cnt {{ font-size:13px; font-weight:400; color:#6B7280; }}
table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
col.c1 {{ width:{COL[0]}px }} col.c2 {{ width:{COL[1]}px }} col.c3 {{ width:{COL[2]}px }}
th {{ background:#1F4E79; color:#fff; font-size:13px; font-weight:600;
      text-align:left; padding:11px 14px; letter-spacing:.2px; }}
td {{ font-size:{FONT}px; line-height:1.4; padding:10px 14px;
      vertical-align:top; border-bottom:1px solid #E3E7EC; }}
tr:nth-child(even) td {{ background:#FAFBFC; }}
td.iss {{ font-weight:600; }}
td.issuе {{ }} /* placeholder, не используется */
.chip {{ display:inline-block; font-size:{CHIP_FONT}px; line-height:1.35;
         padding:3px 9px; margin:0 5px 5px 0; border-radius:4px; white-space:nowrap; }}
.legend {{ margin-top:34px; border-top:2px solid #1F4E79; padding-top:20px; }}
.legend h3 {{ font-size:17px; margin:0 0 14px; }}
.lrow {{ display:flex; gap:14px; padding:7px 0; align-items:flex-start; }}
.lname {{ flex:0 0 168px; font-weight:600; font-size:14px; }}
.lname span {{ display:inline-block; padding:2px 9px; border-radius:4px; }}
.ldesc {{ flex:1; font-size:13.5px; line-height:1.45; color:#374151; }}
.foot {{ margin-top:22px; font-size:12px; color:#6B7280; }}
"""


def esc(s):
    return html.escape(str(s))


def table_html(rows):
    out = ['<table><colgroup><col class="c1"><col class="c2"><col class="c3"></colgroup>',
           '<thead><tr><th>Эмитент</th><th>Выпуски</th><th>Категория ковенант</th></tr></thead><tbody>']
    for issuer, names, cats in rows:
        chips = "".join(
            f'<span class="chip" style="background:{FILL.get(c, "#F2F2F2")}">{esc(c)}</span>'
            for c in cats.split(" · "))
        out.append(f'<tr><td class="iss">{esc(issuer)}</td><td>{esc(names)}</td><td>{chips}</td></tr>')
    out.append("</tbody></table>")
    return "\n".join(out)


def legend_html():
    out = ['<div class="legend"><h3>Легенда: что означает категория</h3>']
    for name, text in legend:
        out.append(
            f'<div class="lrow"><div class="lname">'
            f'<span style="background:{FILL.get(name, "#F2F2F2")}">{esc(name)}</span></div>'
            f'<div class="ldesc">{esc(text)}</div></div>')
    out.append("</div>")
    return "\n".join(out)


FOOT = ('Источник: решения о выпуске и программы облигаций. '
        'Категория указана по каждому основанию, при наступлении которого владелец '
        'вправе предъявить выпуск к досрочному погашению. Дата: 06.10.2026.')


def page(title_h2, rows):
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<style>{CSS}</style></head><body><div class="card">
<h1>Выпуски с правом требования досрочного погашения</h1>
<p class="sub">Какие ковенанты дают инвестору право предъявить облигации к досрочному погашению</p>
<h2 style="border-color:{title_h2[1]}">{esc(title_h2[0])}
   <span class="cnt">— {len(rows)} строк</span></h2>
{table_html(rows)}
{legend_html()}
<p class="foot">{esc(FOOT)}</p>
</div></body></html>"""


# ---------------------------------------------------------------- рендер

TMP = os.path.join(tempfile.gettempdir(), "covpub")
os.makedirs(TMP, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
PROF = os.path.join(TMP, "prof")


def render(html_text, png_path, est_h):
    """Рендер HTML в PNG. Высота подбирается так, чтобы низ страницы был фоном."""
    src = os.path.join(TMP, "page.html")
    with open(src, "w", encoding="utf-8") as f:
        f.write(html_text)
    h = est_h
    for attempt in range(3):
        subprocess.run([
            CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            f"--user-data-dir={PROF}", f"--force-device-scale-factor={SCALE}",
            f"--window-size={PAGE_W},{h}", f"--screenshot={png_path}",
            "file:///" + src.replace("\\", "/"),
        ], check=True, capture_output=True)
        im = Image.open(png_path).convert("RGB")
        # ищем снизу первую строку, отличную от цвета подложки
        w, hh = im.size
        bg = im.getpixel((2, hh - 2))
        px = im.load()
        cut = hh
        for y in range(hh - 1, -1, -1):
            row_is_bg = all(px[x, y] == bg for x in range(0, w, 7))
            if not row_is_bg:
                cut = y + 1
                break
        if hh - cut > 8 or attempt == 2:
            im.crop((0, 0, w, min(hh, cut + 8))).save(png_path, "PNG", optimize=True)
            return Image.open(png_path)
        h = int(h * 1.6)   # контент не поместился — рендерим выше
    return im


def est_height(nrows):
    return 420 + nrows * 78 + 460


jobs = []
for g in ("B", "BB", "BBB"):
    jobs.append((f"Ковенанты_{g}.png", f"Рейтинговая группа {g}", groups[g]))

all_rows = groups["B"] + groups["BB"] + groups["BBB"]
# сводная страница: подзаголовки внутри одной таблицы не делаем —
# вместо этого три таблицы подряд
combined_parts = []
for g in ("B", "BB", "BBB"):
    combined_parts.append((f"Рейтинговая группа {g}", TAB_COLOR[g], groups[g]))


def combined_page():
    body = [f'<div class="card"><h1>Выпуски с правом требования досрочного погашения</h1>',
            '<p class="sub">Какие ковенанты дают инвестору право предъявить облигации '
            'к досрочному погашению</p>']
    for name, color, rows in combined_parts:
        body.append(f'<h2 style="border-color:{color}">{esc(name)} '
                    f'<span class="cnt">— {len(rows)} строк</span></h2>')
        body.append(table_html(rows))
    body.append(legend_html())
    body.append(f'<p class="foot">{esc(FOOT)}</p></div>')
    return (f'<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
            f'<style>{CSS}</style></head><body>' + "\n".join(body) + "</body></html>")


results = []
for fname, subtitle, rows in jobs:
    png = OUT + fname
    im = render(page((subtitle, TAB_COLOR[subtitle.split()[-1]]), rows), png, est_height(len(rows)))
    results.append((fname, im.size))
    print(f"{fname}: {im.size[0]}x{im.size[1]} px")

png = OUT + "Ковенанты_все_группы.png"
im = render(combined_page(), png, est_height(len(all_rows)))
results.append(("Ковенанты_все_группы.png", im.size))
print(f"Ковенанты_все_группы.png: {im.size[0]}x{im.size[1]} px")

# растровый PDF из сводной картинки: текстового слоя нет
pdf = OUT + "Ковенанты_все_группы.pdf"
Image.open(png).convert("RGB").save(pdf, "PDF", resolution=144.0)
print("PDF:", pdf, round(os.path.getsize(pdf) / 1024), "КБ")

shutil.rmtree(PROF, ignore_errors=True)
