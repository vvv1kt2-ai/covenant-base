# -*- coding: utf-8 -*-
"""
Сопоставление выпусков с ПВО и подготовка справочника.

Вход:  tmp/pvo_map.json, tmp/pvo_registry_cbr.json, tmp/pvo_cards.json
Выход: tmp/pvo_final.json  — ISIN -> {pvo, short, site, status, source}
"""
import json
import os
import re
import collections

# Рабочие пути: по умолчанию — каталог данных этого репозитория (publication/data),
# чтобы код и данные не расходились. Переопределяется COVENANT_WS (см. publication/README.md).
_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("COVENANT_WS") or os.path.join(os.path.dirname(_HERE), "data")
WS = WS.replace("\\", "/").rstrip("/") + "/"

# канонические ПВО: ключ поиска в названии из документа -> (краткое имя, полное, сайт, статус)
CANON = [
    ("волста", "Волста", "ООО «Волста»", "https://volsta.ru/", "в списке ЦБ"),
    ("регион финанс", "РЕГИОН Финанс", "ООО «РЕГИОН Финанс»", "http://www.region.ru",
     "деятельность прекращена 11.03.2026"),
    ("первая независимая", "Первая Независимая", "ООО «Первая Независимая»",
     "https://firstindependent.ru/", "исключён из списка ЦБ 20.08.2025"),
    ("защита прав владельцев", "ЗПВО", "ООО «Защита прав владельцев облигаций»",
     "https://zpvo.ru/", "в списке ЦБ"),
    ("лигал кэпитал", "Лигал Кэпитал", "ООО «Лигал Кэпитал Инвестор Сервисез»",
     "https://cbr.ru/finorg/foinfo/?ogrn=1025402483809", "в списке ЦБ"),
    ("центральная трастовая", "Центральная трастовая", "АО «Центральная трастовая компания»",
     "https://www.centrotrust.ru", "в списке ЦБ"),
    ("имплекс", "Имплекс", "ООО НПП «Имплекс»", "https://implex.unimix.ru", "в списке ЦБ"),
    ("юнитек", "Юнитек Сервис", "АО «Юнитек Сервис»", "https://www.unitec-s.ru", "в списке ЦБ"),
    ("юнилайн", "Юнилайн Капитал", "ООО «Юнилайн Капитал Менеджмент»",
     "https://cbr.ru/finorg/foinfo/?ogrn=1165476091098", "в списке ЦБ"),
    ("первоуральскбанк", "Первоуральскбанк", "АО «Первоуральскбанк»",
     "https://cbr.ru/finorg/foinfo/?ogrn=1026600001823", "в списке ЦБ"),
    ("совет", "СОВЕТ-Представитель", "ООО «СОВЕТ-Представитель»", "https://trw-rep.ru",
     "в списке ЦБ"),
    ("альянс", "Альянс-Фининвест", "ООО «Альянс-Фининвест»", "https://afi.expert", "в списке ЦБ"),
    ("фбк", "ФБК Консалтинг", "ООО «ФБК Консалтинг»", "https://www.fbk.ru", "в списке ЦБ"),
    ("квест", "КВЕСТ", "ООО «Юридическая фирма «КВЕСТ»",
     "https://cbr.ru/finorg/foinfo/?ogrn=1052128017864", "в списке ЦБ"),
    ("лп трасти", "ЛП Трасти Сервисез", "ООО «ЛП Трасти Сервисез»",
     "https://cbr.ru/finorg/foinfo/?ogrn=1027739143838", "в списке ЦБ"),
    ("верба", "Верба Лигал", "ООО «Верба Лигал»", "https://verba-legal-cm.ru", "в списке ЦБ"),
]

# выпуски, обслуживаемые ЗПВО по данным zpvo.ru/issuers
ZPVO_ISINS = {
    "RU000A10D3P2", "RU000A10F710", "RU000A10FUB3",          # ЮУЛЦ
    "RU000A10CN62", "RU000A10G6S6",                          # ЮСВ
    "RU000A1089A3", "RU000A10AYB6", "RU000A10FSG6",          # А Спэйс
    "RU000A10B7N0", "RU000A10EQV2",                          # БиоВиtrум
    "RU000A10BP46", "RU000A10FLJ5",                          # Элит Строй
    "RU000A108Y60", "RU000A10FKD0",                          # Первоуральскбанк
    "RU000A104XE0", "RU000A1053H4", "RU000A105RF6", "RU000A105WZ4",
    "RU000A106987", "RU000A106GB6", "RU000A107480", "RU000A107NJ3",
    "RU000A10CU97",                                          # ЛИЗИНГ-ТРЕЙД
    "RU000A104ZU1",                                          # Шевченко
    "RU000A1067T9", "RU000A106R12", "RU000A1078Y6", "RU000A107SX3",
    "RU000A10B081", "RU000A10CDX0", "RU000A10ERA4", "RU000A10FSV5",
    "RU000A10GE69",                                          # ЭкономЛизинг
    "RU000A106FN3", "RU000A10F8G8",                          # СПМК
    "RU000A1089G0", "RU000A10BQF1", "RU000A10C5T0", "RU000A10C5U8",
    "RU000A1026H0",                                          # ГИДРОМАШСЕРВИС
    "RU000A10FKU4",                                          # ЛК АдвансТрак
}


def canon(name):
    s = str(name or "").lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    for key, short, full, site, status in CANON:
        if key in s:
            return {"short": short, "full": full, "site": site, "status": status}
    return None


def main():
    d = json.load(open(WS + "tmp/pvo_map.json", encoding="utf-8"))
    out = {}
    for isin, rec in d.items():
        if isin in ZPVO_ISINS:
            c = canon("защита прав владельцев")
            out[isin] = {**c, "source": "сайт ЗПВО"}
            continue
        if rec.get("pvo"):
            c = canon(rec["pvo"])
            if c:
                out[isin] = {**c, "source": "решение о выпуске"}
            else:
                out[isin] = {"short": rec["pvo"], "full": rec["pvo"], "site": "",
                             "status": "нет в списке ЦБ", "source": "решение о выпуске"}
            continue
        note = rec.get("note") or ""
        out[isin] = {"short": "не определён" if note == "ПВО не определён" else "нет данных",
                     "full": "", "site": "", "status": "",
                     "source": "решение о выпуске" if note == "ПВО не определён" else "документ недоступен"}

    json.dump(out, open(WS + "tmp/pvo_final.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    c = collections.Counter(v["short"] for v in out.values())
    for k, n in c.most_common():
        print(f"{n:4d}  {k}")
    print("всего:", len(out))


if __name__ == "__main__":
    main()
