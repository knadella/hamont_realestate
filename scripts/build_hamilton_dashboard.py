#!/usr/bin/env python3
"""
Build the Hamilton real-estate market-dynamics dashboard from HouseSigma's
public market-trends API. Self-contained (Python stdlib only) so it can run
headless in a cloud agent without a browser or login.

Pipeline:
  1. Mint a short-lived access token (no auth required).
  2. Fetch the 15-year monthly trend chart for all types + detached/semi/condo.
  3. Write hamilton_market_trends.csv (all types, full months).
  4. Render hamilton_dynamics.html from scripts/dashboard_template.html.

Run:  python3 scripts/build_hamilton_dashboard.py
"""
import json, csv, os, sys, ssl, urllib.request
from collections import defaultdict


def _ssl_context():
    """Verified TLS where possible; fall back gracefully so this runs across
    environments (some Python installs ship without a usable CA bundle). The
    endpoint serves public, non-sensitive market data."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


SSL_CTX = _ssl_context()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html")

# Hamilton = municipality 10134. house_type codes: all / D. / S. / C.
MUNI = "10134"
TYPES = [("all", "all"), ("det", "D."), ("semi", "S."), ("condo", "C.")]
HDR = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "HS-Client-Type": "desktop_v7",
    "HS-Client-Version": "7.22.32",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def post(url, body, tok=None):
    h = dict(HDR)
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
            j = json.loads(r.read().decode())
    except urllib.error.URLError as e:
        # Last-resort fallback if the environment can't verify the cert chain.
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            print("WARN: TLS verification failed, retrying unverified (public data)", file=sys.stderr)
            with urllib.request.urlopen(req, timeout=60, context=ssl._create_unverified_context()) as r:
                j = json.loads(r.read().decode())
        else:
            raise
    if not j.get("status"):
        raise RuntimeError("API error for %s: %s" % (url, j.get("error")))
    return j


def get_token():
    return post("https://housesigma.com/bkv2/api/init/accesstoken/new", {})["data"]["access_token"]


def fetch(tok, house_type):
    j = post(
        "https://housesigma.com/bkv2/api/stats/trend/chart",
        {"lang": "en_US", "province": "ON", "municipality": MUNI,
         "community": "all", "house_type": house_type, "period_num": 180},
        tok,
    )
    rows = []
    for r in j["data"]["chart"]:
        rows.append([r["period"], int(r["list_count"]), int(r["list_active"]), int(r["sold_count"]),
                     int(r["list_days"]), int(r["property_listing_dom"]), int(r["price_sold"])])
    rows.sort(key=lambda x: x[0])
    return rows


def rowdict(rows):
    return {r[0]: {"nl": r[1], "ac": r[2], "sd": r[3], "dom": r[4], "pdom": r[5], "price": r[6]} for r in rows}


def sma(vals, w=3):
    return [sum(vals[max(0, i - w + 1):i + 1]) / len(vals[max(0, i - w + 1):i + 1]) for i in range(len(vals))]


def main():
    tok = get_token()
    series = {name: fetch(tok, ht) for name, ht in TYPES}
    # sanity: all four should return the same set of periods
    n = {name: len(rows) for name, rows in series.items()}
    if len(set(n.values())) != 1:
        print("WARN: period counts differ across types:", n, file=sys.stderr)

    # Drop the partial current month (the last period) for all full-month math.
    full = {name: rows[:-1] for name, rows in series.items()}
    allf = full["all"]
    if not allf:
        raise RuntimeError("no data returned")

    # ---- CSV (all types, every full month) ----
    csv_path = os.path.join(REPO, "hamilton_market_trends.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "new_listings", "active_listings", "total_sold",
                    "days_on_market", "property_days_on_market", "median_sold_price"])
        w.writerows(allf)

    AD, DD, SD, CD = (rowdict(full[k]) for k in ("all", "det", "semi", "condo"))

    # ---- monthly series for the all-types charts (2016+) ----
    data = [{"p": r[0], "nl": r[1], "ac": r[2], "sd": r[3], "dom": r[4], "pdom": r[5], "price": r[6]}
            for r in allf if r[0] >= "2016-01"]

    # ---- annual averages (2019+) ----
    yr = defaultdict(list)
    for r in allf:
        yr[r[0][:4]].append(r)
    annual = []
    for y in sorted(yr):
        if y < "2019":
            continue
        rs = yr[y]
        m = len(rs)
        av = lambda i: sum(x[i] for x in rs) / m
        annual.append({"y": y, "n": m, "nl": round(av(1)), "ac": round(av(2)), "sd": round(av(3)),
                       "dom": round(av(4), 1), "pdom": round(av(5), 1),
                       "moi": round(sum(x[2] / x[3] for x in rs if x[3]) / m, 1),
                       "snlr": round(sum(x[3] / x[1] * 100 for x in rs if x[1]) / m), "price": round(av(6))})

    # ---- by-type smoothed series (3-mo avg), 2019-01 onward ----
    periods = [r["p"] for r in data if r["p"] >= "2019-01"]
    moicol = lambda d: [d[p]["ac"] / d[p]["sd"] if d[p]["sd"] else 0 for p in periods]
    prcol = lambda d: [d[p]["price"] for p in periods]
    dm, sm, cm = sma(moicol(DD)), sma(moicol(SD)), sma(moicol(CD))
    dp, sp, cp = sma(prcol(DD)), sma(prcol(SD)), sma(prcol(CD))
    TS = [{"p": periods[i], "dm": round(dm[i], 2), "sm": round(sm[i], 2), "cm": round(cm[i], 2),
           "dp": round(dp[i]), "sp": round(sp[i]), "cp": round(cp[i])} for i in range(len(periods))]

    # ---- property-type comparison (latest full month + YoY + YTD) ----
    latest = allf[-1][0]
    y, mo = latest.split("-")
    prev = "%d-%s" % (int(y) - 1, mo)
    curyear = y

    def build_row(label, d):
        l = d[latest]
        pa = d.get(prev)
        snlr = l["sd"] / l["nl"] * 100 if l["nl"] else 0
        moi = l["ac"] / l["sd"] if l["sd"] else 0
        pyoy = (l["price"] - pa["price"]) / pa["price"] * 100 if pa and pa["price"] else 0
        ytd = [p for p in d if p[:4] == curyear]
        snlr_ytd = sum(d[p]["sd"] / d[p]["nl"] * 100 for p in ytd if d[p]["nl"]) / len(ytd)
        moi_ytd = sum(d[p]["ac"] / d[p]["sd"] for p in ytd if d[p]["sd"]) / len(ytd)
        return {"label": label, "nl": l["nl"], "ac": l["ac"], "sd": l["sd"], "dom": l["dom"], "pdom": l["pdom"],
                "snlr": round(snlr), "moi": round(moi, 1), "price": l["price"], "pyoy": round(pyoy, 1),
                "snlr_ytd": round(snlr_ytd), "moi_ytd": round(moi_ytd, 1)}

    TT = [build_row("All types", AD), build_row("Detached", DD),
          build_row("Semi-detached", SD), build_row("Condo apt", CD)]

    payload = {"data": data, "annual": annual, "ts": TS, "tt": TT,
               "latest": latest, "prev": prev, "curyear": curyear}

    with open(TMPL) as f:
        html = f.read()
    html = html.replace("__PAYLOAD__", json.dumps(payload))
    out_path = os.path.join(REPO, "hamilton_dynamics.html")
    with open(out_path, "w") as f:
        f.write(html)

    print("Built dashboard. latest full month=%s  months=%d  type-series=%d" % (latest, len(data), len(TS)))
    print("Wrote %s and %s" % (csv_path, out_path))


if __name__ == "__main__":
    main()
