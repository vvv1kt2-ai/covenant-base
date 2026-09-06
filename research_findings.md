# Research: bonds.finam.ru - Bond Issuance Document Retrieval

## 1. Bond Card URL Pattern

The URL pattern for bond card pages is:
```
https://bonds.finam.ru/issue/details{INTERNAL_CODE}/default.asp
```
or equivalently:
```
https://bonds.finam.ru/issue/details{INTERNAL_CODE}/
```

**The INTERNAL_CODE is a hexadecimal-like identifier (5 chars)**, NOT the ISIN. Examples:
- `details048A2` → for ISIN RU000A1089A3 (user-provided example)
- `details00007` → for bond "АRIES-01" (OMZZ)
- `details02D17` → for "ABH Financial-2023"
- `details003BF` → for "ARIES-2007"

The code appears to be an internal database primary key in hexadecimal format. It is sequentially assigned and has no mathematical relationship to the ISIN.

### Sub-pages (for the same bond):
```
https://bonds.finam.ru/issue/details{CODE}00001/default.asp  ← Эмиссии (Issuances)
https://bonds.finam.ru/issue/details{CODE}00002/default.asp  ← Купоны (Coupons)
https://bonds.finam.ru/issue/details{CODE}00003/default.asp  ← Выплаты (Payments)
https://bonds.finam.ru/issue/details{CODE}00004/default.asp  ← Дополнительные эмиссии (Additional issuances)
https://bonds.finam.ru/issue/details{CODE}00005/default.asp  ← Дата дохода (Income date)
https://bonds.finam.ru/issue/details{CODE}00006/default.asp  ← Прочее (Misc)
https://bonds.finam.ru/issue/details{CODE}00007/default.asp  ← Данные эмитента (Emitter data)
https://bonds.finam.ru/issue/details{CODE}00008/default.asp  ← Динамика цен (Price dynamics)
https://bonds.finam.ru/issue/details{CODE}00009/default.asp  ← YTM Chart
```

---

## 2. Search by ISIN — How It Actually Works

### There is NO direct ISIN search endpoint!

The search page (`/issue/search/default.asp`) has a **quick search form** (`srchForm`) with a single text field:

```html
<form name="srchForm" action="/issue/search/default.asp" method="get">
  <input type="text" name="emitterCustomName" id="emitterCustomName" 
         style="width:170px" 
         placeholder="Эмитент, тикер, ИНН, ...">
  <input type="submit" class="button" value="Найти"/>
</form>
```

The placeholder says **"Эмитент, тикер, ИНН, ..."** (Emitter, ticker, INN, ...) — there's no explicit mention of ISIN in the placeholder.

### How ISIN search works in practice:

The `emitterCustomName` parameter accepts **emitter name, ticker, INN, or ISIN** as a text search. The server does a LIKE search across these fields. So you can pass an ISIN like `RU000A1089A3` and the server will search for it.

**URL for searching by ISIN:**
```
https://bonds.finam.ru/issue/search/default.asp?emitterCustomName=RU000A1089A3
```

This returns a results page (table) with links to `/issue/details{CODE}/default.asp` pages. The user then clicks the matching result to go to the bond card.

### Advanced search form (`hiddenForm`):

The hidden form has these parameters (all submitted via GET):
- `emitterCustomName` — emitter name / ISIN text search
- `status` — bond status filter
- `sectorId` / `FieldId` — sector/field filter
- `placementFrom` / `placementTo` — placement date range
- `paymentFrom` / `paymentTo` — payment date range  
- `registrationDateFrom` / `registrationDateTo`
- `couponRateFrom` / `couponRateTo`
- `couponDateFrom` / `couponDateTo`
- `offerExecDateFrom` / `offerExecDateTo`
- `currencyId` — currency filter
- `volumeFrom` / `volumeTo`
- `faceValue` / `faceValueSign`
- `operatorId` / `operatorTypeId`
- `amortization`
- `regNumber`
- `govRegBody`
- `placementMethod`
- `quoteType`
- `YTMFrom` / `YTMTo`
- `liquidRange` / `liquidFrom` / `liquidTo`
- `rating`
- `orderby` / `page`

---

## 3. PDF/Document Links on the Bond Card Page

On the bond card page (`/issue/details{CODE}/default.asp`), document links are in a `<div class="emission">` section, within a `<tr>` containing "Документы:" (Documents):

```html
<tr>
    <td colspan="3" style="white-space:normal;">Документы:
        <a href="http://st.finam.ru/ipo/decision\{ID}_{TICKER}_decision.zip" target="_blank">
            Решение о выпуске
        </a>;&nbsp;
        <a href="http://st.finam.ru/ipo/{ID}_{TICKER}_prospect.zip" target="_blank">
            Программа облигаций
        </a>;&nbsp;
    </td>
</tr>
```

### Document URL patterns on st.finam.ru:

**Two different URL formats exist (old vs new):**

**Old format** (for bonds registered ~2000-2010):
```
http://st.finam.ru/ipo/decision\{NUM_ID}_{TICKER}_decision.zip    ← Решение о выпуске
http://st.finam.ru/ipo/{NUM_ID}_{TICKER}_prospect.zip              ← Программа облигаций
```
Example: `http://st.finam.ru/ipo/decision\7_UMAS1_decision.zip`

**New format** (for bonds registered ~2010+):
```
http://st.finam.ru/ipo/{NUM_ID}_0_Проспект.pdf                     ← Проспект эмиссии
http://st.finam.ru/ipo/{NUM_ID}_0_Проспект_001Р.pdf               ← Проспект эмиссии (variant)
http://st.finam.ru/ipo/{NUM_ID}_0_Проект_решения_о_выпуске.pdf    ← Решение о выпуске (variant)
```
Example: `http://st.finam.ru/ipo/10262_0_Проспект.pdf`

**Even newer format** (for the most recent bonds):
```
https://st.finam.ru/ipo/{NUM_ID}_0_Проспект.pdf                   ← HTTPS version
```

The `{NUM_ID}` is a numeric ID (like `7`, `10262`, `10330`, etc.) that appears to be different from the hex code in the URL.

### Note about document links:
The documents are ZIP files or PDFs hosted on `st.finam.ru`. The links are plain `<a href>` tags with `target="_blank"`. There's no AJAX/API call to get them — they're directly embedded in the HTML.

---

## 4. Anti-Bot Measures

### ServicePipe (Active since ~2022-2023)

The site is **entirely protected by ServicePipe** (servicepipe.tech). Every page returns a JavaScript challenge page:

```html
<script src="https://servicepipe.tech/loaders/5f560afbb7f938658a1af64ac290b725.js" 
        integrity="sha256-..." crossorigin="anonymous" async></script>
```

The challenge page includes:
- A JS challenge that must be executed in a real browser
- RSA-encrypted cookie generation (`spsc` cookie)
- Browser fingerprinting (FingerprintJS)
- CAPTCHA capability (controlled by `is_captcha: false/true`)
- A `<noscript>` fallback that redirects to `/exhkqyad`

**Key anti-bot properties:**
```json
{
  "is_captcha": false,          // Can be toggled to require CAPTCHA
  "cookie_domain": "finam.ru",
  "is_partitioned": false
}
```

### Impact on scraping:
- **Simple HTTP requests (curl, Python requests/urllib) will NOT get real content** — they only get the JS challenge page
- **A headless browser (Selenium, Playwright, Puppeteer) with JavaScript execution is required** to bypass the ServicePipe challenge
- The challenge generates cookies (`spsn`, `spid`, `spsc`) that must be sent with subsequent requests
- After solving the JS challenge, the browser gets a redirect to the actual page with proper cookies set on `.finam.ru` domain

### Legacy (pre-ServicePipe):
Before ~2022, the site had **no anti-bot protection** and was directly accessible via HTTP requests. The old ASP pages returned HTML directly.

---

## 5. Complete Flow: ISIN → Bond Documents

1. **Search**: `GET https://bonds.finam.ru/issue/search/default.asp?emitterCustomName={ISIN}`
   - Returns HTML table with matching bonds
   - Each row links to `/issue/details{CODE}/default.asp`

2. **Bond Card**: `GET https://bonds.finam.ru/issue/details{CODE}/default.asp`
   - Contains bond details (name, issuer, dates, volumes)
   - Contains document links (Решение о выпуске, Программа/Проспект облигаций)
   - Documents are on `st.finam.ru/ipo/` as ZIP or PDF files

3. **Documents**: Direct download from `st.finam.ru/ipo/` URLs
   - No anti-bot protection on st.finam.ru (separate from bonds.finam.ru)
   - Files are ZIP or PDF format

---

## 6. Alternative Approach: Direct ISIN-to-URL Mapping

Since there's no way to directly compute the `details{CODE}` URL from an ISIN, the workflow must be:

1. First, search by ISIN on the search page to get the bond code
2. Then navigate to the bond card
3. Then find and download documents

However, there might be a **shortcut**: If you know the `NUM_ID` used in st.finam.ru URLs, you can construct document URLs directly. But this NUM_ID is not the same as the hex code and is only found on the bond card page itself.
