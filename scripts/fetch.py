"""Gold desk data refresh. Free public sources only, no keys. Writes data/live.json.
Each source is fetched independently; on failure the last good value is kept and marked stale.
Same pattern as STTIE (github.com/cakashoza-cmyk/sttie)."""
import json, re, ssl, html, sys, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "live.json"
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Gold desk data refresh; github.com/cakashoza-cmyk/gold)"}
NOW = datetime.now(IST)
OZ = 31.1034768  # grams per troy ounce


def get(url, headers=None, timeout=45):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def check(v, lo, hi, name):
    if v is None or not (lo <= v <= hi):
        raise ValueError(f"{name}={v} outside sanity range {lo}-{hi}")
    return v


def merge_hist(old, new):
    d = {a: b for a, b in (old or [])}
    d.update({a: b for a, b in new})
    return [[k, d[k]] for k in sorted(d)]


# ---------- sources ----------
def ibja(prev):
    """IBJA published gold rates (India Bullion & Jewellers Association), public website ibjarates.com.
    Per 10 g, without 3% GST and making charges. AM = opening, PM = closing."""
    url = "https://ibjarates.com/"
    t = get(url, timeout=60).decode("utf-8", "ignore")
    out = {}
    # 1. ~84-day closing history (chart data) for 999 and 916
    m = re.search(r'id="HdnGold" value="([^"]*)"', t)
    ch = json.loads(html.unescape(m.group(1)))
    iso = lambda s: datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    h999 = [[iso(d), float(v)] for d, v in zip(ch["labels"], ch["purity999"])]
    h916 = [[iso(d), float(v)] for d, v in zip(ch["labels"], ch["purity916"])]
    # 2. previous-dates table: AM block then PM block, 7 numbers per row (999,995,916,750,585, silver, platinum)
    def block(tab):
        i = t.find(f'id="{tab}"'); j = t.find("</table>", i)
        s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t[i:j])))
        return [[iso(r[0])] + [float(x) for x in r[1:]] for r in re.findall(r"(\d\d/\d\d/\d{4})" + r"\s+(\d+(?:\.\d+)?)" * 7, s)]
    am, pm = block("tab-am"), block("tab-pm")
    # 3. today's table (filled during the day: rows Purity | AM | PM)
    i = t.find('id="TodayRatesTableDataNo"'); j = t.find("</table>", i)
    today_rows = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t[i:j], re.S):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 2 and re.fullmatch(r"(999|995|916|750|585)\b.*", cells[0] or ""):
            nums = [float(x.replace(",", "")) if re.fullmatch(r"[\d,]+(\.\d+)?", x) else None for x in cells[1:3]]
            today_rows[cells[0][:3]] = nums + [None] * (2 - len(nums))
    last_pm = h999[-1][1]
    td = NOW.strftime("%Y-%m-%d")
    sessions = []  # (date, session, {purity: rate})
    for r in am:
        sessions.append((r[0], "AM", dict(zip(["999", "995", "916", "750", "585"], r[1:6]))))
    for r in pm:
        sessions.append((r[0], "PM", dict(zip(["999", "995", "916", "750", "585"], r[1:6]))))
    for k, s in ((0, "AM"), (1, "PM")):
        vals = {p: v[k] for p, v in today_rows.items() if v[k]}
        if vals.get("999") and abs(vals["999"] / last_pm - 1) < 0.10 and td > h999[-1][0]:
            sessions.append((td, s, vals))
        elif vals.get("999") and abs(vals["999"] / last_pm - 1) < 0.10 and td == h999[-1][0] and s == "AM":
            sessions.append((td, s, vals))
    sessions.sort(key=lambda x: (x[0], x[1]))
    ld, ls, lv = sessions[-1]
    pm_hist = merge_hist(prev.get("ibja999", {}).get("history"), h999 + [[d, v["999"]] for d, s, v in sessions if s == "PM"])
    am_hist = merge_hist(prev.get("ibja999_am", {}).get("history"), [[d, v["999"]] for d, s, v in sessions if s == "AM"])
    h916m = merge_hist(prev.get("ibja916", {}).get("history"), h916 + [[d, v["916"]] for d, s, v in sessions if s == "PM" and v.get("916")])
    common = dict(source="IBJA published rates (ibjarates.com public page)", source_url=url, status="live",
                  unit="₹ per 10 g (excl. 3% GST, making)")
    note = ("India Bullion & Jewellers Association benchmark rate (used by RBI for SGB and gold-loan valuation). Without 3% GST and making charges. "
            "Read from IBJA's public web page; IBJA asks commercial users to subscribe to its official API.")
    out["ibja999"] = dict(label="IBJA gold 999 (24K), latest", value=check(lv["999"], 30000, 400000, "ibja999"), as_of=f"{ld} {ls}",
                          note=note, history=pm_hist, latest_session=ls, latest_date=ld, **common)
    out["ibja999_am"] = dict(label="IBJA gold 999, opening (AM) rate", value=am_hist[-1][1], as_of=am_hist[-1][0], note="Opening rate history (accumulates from each refresh).", history=am_hist, **common)
    out["ibja999_pm"] = dict(label="IBJA gold 999, closing (PM) rate", value=pm_hist[-1][1], as_of=pm_hist[-1][0], note="Closing rate; this series is what predictions are scored on.", history=pm_hist, **common)
    for p, lab in (("995", "995"), ("916", "916 (22K)"), ("750", "750 (18K)")):
        if lv.get(p):
            extra = {"history": h916m} if p == "916" else {}
            out["ibja" + p] = dict(label=f"IBJA gold {lab}, latest", value=check(lv[p], 20000, 400000, p), as_of=f"{ld} {ls}", note=note, **extra, **common)
    out["ibja999"]["sessions"] = [[d, s, v.get("999"), v.get("916")] for d, s, v in sessions][-12:]
    return out


def comex():
    ref = {"Referer": "https://finance.sina.com.cn/"}
    raw = get("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=GC", ref).decode()
    arr = json.loads(raw[raw.index("(") + 1: raw.rindex(")")])
    hist = [[r["date"], float(r["close"])] for r in arr if float(r["close"]) > 0]
    hl = [[r["date"], float(r["high"]), float(r["low"])] for r in arr if float(r["close"]) > 0 and float(r["high"]) >= float(r["low"]) > 0]
    d, v = hist[-1]
    asof = d
    try:
        q = get("https://hq.sinajs.cn/list=hf_GC", ref).decode("gbk", "ignore")
        f = q.split('"')[1].split(",")
        last, qd, qt = float(f[0]), f[12], f[6]
        if last > 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", qd) and qd >= d:
            ist = (datetime.strptime(qd + " " + qt, "%Y-%m-%d %H:%M:%S") - timedelta(hours=2, minutes=30)).strftime("%Y-%m-%d %H:%M IST")
            v, asof = last, ist
            if hist[-1][0] == qd:
                hist[-1][1] = last
            else:
                hist.append([qd, last])
    except Exception:
        pass
    return dict(label="COMEX gold futures (continuous)", value=check(v, 500, 10000, "comex"), unit="US$ per troy oz", as_of=asof,
                source="CME COMEX gold futures via Sina Finance public quote feed (unofficial)", source_url="https://finance.sina.com.cn/futures/quotes/GC.shtml",
                status="unofficial", note="Not an official CME feed. Front-month continuous contract; small jumps at contract rolls. Latest point can be intraday.", history=hist[-2700:],
                hl=hl[-2700:])


def rbi():
    t = get("https://www.rbi.org.in/", timeout=60).decode("utf-8", "ignore")
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    repo = float(re.search(r"Policy Repo Rate\s*:\s*([\d.]+)\s*%", t).group(1))
    usd = float(re.search(r"INR\s*/\s*1 USD\s*:\s*([\d.]+)", t).group(1))
    m = re.search(r"\(As at [^)]*? of (\w+ \d{1,2}, \d{4})\)", t)
    fx_date = datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d") if m else NOW.strftime("%Y-%m-%d")
    return {
        "repo": dict(label="RBI policy repo rate", value=check(repo, 2, 12, "repo"), unit="% p.a.", as_of=NOW.strftime("%Y-%m-%d"),
                     source="Reserve Bank of India homepage, 'Current Rates'", source_url="https://www.rbi.org.in/",
                     status="official", note="Date shown is the date we read it from the RBI site."),
        "usdinr": dict(label="USD/INR reference rate", value=check(usd, 60, 140, "usdinr"), unit="₹ per US$", as_of=fx_date,
                       source="FBIL reference rate, as shown on RBI homepage", source_url="https://www.fbil.org.in/",
                       status="official", note="Set once a day around 1:30 pm IST. Customs uses its own notified rate (CBIC), which can differ slightly."),
    }


def ecb():
    start = (NOW - timedelta(days=3900)).strftime("%Y-%m-%d")
    j = json.loads(get(f"https://api.frankfurter.dev/v1/{start}..?base=USD&symbols=INR"))
    days = sorted(j["rates"])
    inr = [[d, j["rates"][d]["INR"]] for d in days]
    return {"usdinr_ecb": dict(label="USD/INR (ECB cross rate)", value=check(inr[-1][1], 40, 140, "inr"), unit="₹ per US$", as_of=inr[-1][0],
                               source="European Central Bank reference rates via Frankfurter API", source_url="https://www.frankfurter.app/", status="live",
                               note="Used for history and back-tests; the FBIL rate is used for today's figures.", history=inr)}


FRED = {"real10": ("DFII10", "US 10-year real yield (TIPS)", "% p.a.", -3, 6),
        "dollar": ("DTWEXBGS", "US dollar index (broad, trade-weighted)", "index Jan 2006 = 100", 60, 200),
        "fedfunds": ("DFF", "US fed funds effective rate", "% p.a.", 0, 15)}


def fred(key):
    sid, label, unit, lo, hi = FRED[key]
    rows = [l.split(",") for l in get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60).decode().strip().splitlines()[1:]]
    hist = [[d, float(v)] for d, v in rows if v not in (".", "")][-2800:]
    d, v = hist[-1]
    return dict(label=label, value=check(v, lo, hi, key), unit=unit, as_of=d, source=f"Federal Reserve via FRED (series {sid})",
                source_url=f"https://fred.stlouisfed.org/series/{sid}", status="official", note="Official US data, published with a 1-3 day lag.", history=hist)


def headlines():
    q = "gold price India (rate OR duty OR import OR jewellers) when:30d"
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-IN&gl=IN&ceid=IN:en"
    root = ET.fromstring(get(url))
    items = []
    for it in root.iter("item"):
        t = (it.findtext("title") or "").lstrip("| ").strip()
        if not re.search(r"\bgold\b", t, re.I) or any(x["title"] == t for x in items):
            continue
        d = datetime.strptime(it.findtext("pubDate"), "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).astimezone(IST)
        items.append({"title": t, "date": d.strftime("%Y-%m-%d"), "url": it.findtext("link")})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:15]


def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {"items": {}}
    items, errors = {}, {}
    groups = {}

    def run(name, fn, keys=None):
        try:
            r = fn()
            r = r if keys is None else {keys: r}
            for k in r:
                groups[k] = name
            items.update(r)
        except Exception as e:  # noqa: BLE001
            errors[name] = f"{type(e).__name__}: {e}"[:300]
            for k, old in prev["items"].items():
                if old.get("group") == name and k not in items:
                    old = dict(old); old["status"] = "stale"; old["stale_reason"] = errors[name]
                    items[k] = old

    run("ibja", lambda: ibja(prev["items"]))
    run("comex", comex, "comex")
    run("rbi", rbi)
    run("ecb", ecb)
    for k in FRED:
        run("fred_" + k, lambda k=k: fred(k), k)
    for k, v in items.items():
        v.setdefault("group", groups.get(k, v.get("group", "")))
        if k in groups:
            v["group"] = groups[k]
    try:
        news = headlines()
    except Exception as e:  # noqa: BLE001
        errors["news"] = str(e)[:300]; news = prev.get("headlines", [])
    out = {"generated_ist": NOW.strftime("%Y-%m-%d %H:%M IST"), "items": items, "errors": errors, "headlines": news,
           "headlines_source": "Google News RSS search (public). Headlines only; never used in a number. A duty-cut headline can only make the call more cautious."}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("items:", len(items), "| errors:", json.dumps(errors))
    for k, v in items.items():
        print(f"  {k:12s} {v['value']:>12} {v['unit']:34s} as of {v['as_of']}  [{v['status']}]  hist={len(v.get('history', []))}")
    if "ibja999" not in items or len(items) < 5:
        sys.exit(2)


if __name__ == "__main__":
    main()
