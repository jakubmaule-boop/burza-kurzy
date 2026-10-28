"""Stahuje kurzy všech titulů hry Burzovní souboj a zapisuje je do prices.json.

Zdroje: Yahoo Finance (chart API) pro světové akcie, indexy, komodity, krypto a měny,
pse.cz pro pražské akcie. Spouští GitHub Actions každých 15 minut.
"""
import json, re, sys, time, unicodedata, html
from datetime import datetime, timezone
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
S = requests.Session(); S.headers.update(UA)
now = datetime.now(timezone.utc)
iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
errors = []

def yahoo(sym):
    for host in ("query1", "query2"):
        r = None
        try:
            r = S.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "5m", "range": "1d"}, timeout=15)
            if r.status_code == 200:
                m = r.json()["chart"]["result"][0]["meta"]
                p, t = m.get("regularMarketPrice"), m.get("regularMarketTime")
                if p:
                    return float(p), iso(t) if t else None
        except Exception as e:
            errors.append(f"{sym}@{host}: {e}")
        else:
            pass
        if r is not None and r.status_code != 200: errors.append(f"{sym}@{host}: HTTP {r.status_code} {r.text[:120]}")
        time.sleep(0.5)
    return None, None

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", s)

def pse(market):
    try:
        r = S.get(f"https://www.pse.cz/en/market-data/shares/{market}-market", timeout=20)
        r.raise_for_status()
    except Exception as e:
        errors.append(f"pse {market}: {e}"); return {}
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        txt = html.unescape(re.sub(r"<[^>]+>", " ", row))
        txt = re.sub(r"\s+", " ", txt).strip()
        m = re.search(r"CZK\s*([\d,]+\.\d+)", txt)
        if not m: continue
        name = txt.split(" CZ")[0] if " CZ" in txt else txt[: m.start()]
        out[norm(name)] = float(m.group(1).replace(",", ""))
    return out

symbols = json.load(open("symbols.json", encoding="utf-8"))

# 1) yfinance hromadně (jeden dotaz na všechny)
YF = {}
def yf_batch(tickers):
    try:
        import yfinance as yf
        df = yf.download(tickers, period="5d", interval="15m", group_by="ticker", progress=False, threads=True, auto_adjust=False, prepost=False)
        for t in tickers:
            try:
                col = df[t]["Close"] if len(tickers) > 1 else df["Close"]
                col = col.dropna()
                if len(col):
                    ts = col.index[-1]
                    YF[t] = (float(col.iloc[-1]), ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"))
            except Exception as e:
                errors.append(f"yf {t}: {e}")
    except Exception as e:
        errors.append(f"yf batch: {e}")

STQ = {}
def stooq(sym):
    try:
        r = S.get("https://stooq.com/q/l/", params={"s": sym, "f": "sd2t2c", "h": "", "e": "csv"}, timeout=15)
        line = r.text.strip().splitlines()[-1].split(",")
        if len(line) >= 4 and line[3] not in ("N/D", ""):
            return float(line[3]), f"{line[1]}T{line[2]}"
        errors.append(f"stooq {sym}: {r.status_code} {r.text[:80]!r}")
    except Exception as e:
        errors.append(f"stooq {sym}: {e}")
    return None, None

STQ_IDX = {"^GSPC": "^spx", "^IXIC": "^ndq", "^DJI": "^dji", "^GDAXI": "^dax", "^STOXX50E": "^stx", "^FTSE": "^ukx", "^N225": "^nkx",
           "GC=F": "gc.f", "SI=F": "si.f", "CL=F": "cl.f", "BZ=F": "cb.f", "NG=F": "ng.f", "HG=F": "hg.f"}
STQ_SUF = {".DE": ".de", ".PA": ".fr", ".AS": ".nl", ".MC": ".es", ".T": ".jp", ".HK": ".hk", ".SW": ".ch", ".L": ".uk", ".KS": ".kr"}
def stooq_sym(y):
    if y in STQ_IDX: return STQ_IDX[y]
    if y.endswith("-USD"): return y[:-4].lower() + "usd"
    for a, b in STQ_SUF.items():
        if y.endswith(a):
            base = y[: -len(a)]
            if a == ".HK": base = base.lstrip("0")
            return base.lower() + b
    return y.lower() + ".us"

FXT = ["CZK=X"] + [f"{c}=X" for c in ("EUR", "GBP", "JPY", "CHF", "HKD", "KRW")]
yf_batch([e["y"] for e in symbols if "y" in e] + FXT)

quotes, fx = {}, {}
fails = 0

# Měny: X/CZK = (USD/CZK) / (USD/X)
usdczk, at = YF.get("CZK=X") or yahoo("CZK=X")
if usdczk:
    fx["USD"] = {"p": usdczk, "at": at}
    for cur in ("EUR", "GBP", "JPY", "CHF", "HKD", "KRW"):
        v, a = YF.get(f"{cur}=X") or yahoo(f"{cur}=X")
        if v: fx[cur] = {"p": usdczk / v, "at": a}

# Pražská burza
pse_px = {}
for mkt in ("prime", "standard", "start"):
    pse_px[mkt] = pse(mkt)
pse_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

for e in symbols:
    if "pse" in e:
        p = pse_px.get(e["m"], {}).get(norm(e["pse"]))
        if p is None:  # zkus podle začátku názvu
            k = norm(e["pse"])
            p = next((v for n, v in pse_px.get(e["m"], {}).items() if n.startswith(k) or k.startswith(n) and len(n) > 3), None)
        if p is not None:
            quotes[e["s"]] = {"p": p, "at": pse_at, "src": "pse"}
        else:
            errors.append(f"pse missing {e['s']}")
    else:
        p, a = YF.get(e["y"], (None, None))
        if p is None and fails < 8: p, a = yahoo(e["y"])
        if p is None: p, a = stooq(stooq_sym(e["y"]))
        fails = 0 if p is not None else fails + 1
        if p is not None:
            quotes[e["s"]] = {"p": p, "at": a or pse_at, "src": "yahoo"}
        else:
            errors.append(f"yahoo missing {e['s']} ({e['y']})")
        time.sleep(0.15)

res = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(quotes), "total": len(symbols),
       "quotes": quotes, "fx": fx, "errors": errors[:40] + errors[-40:]}
json.dump(res, open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
# Širší seznam (extra.json) jednou za hodinu nebo při ručním spuštění
import os
try:
    old_all = json.load(open("all.json"))
except Exception:
    old_all = {}
if os.path.exists("extra.json") and (now.minute < 15 or os.environ.get("FORCE_EXTRA") or not old_all.get("byg")):
    extra = json.load(open("extra.json"))
    ys = [e["y"] for e in extra]
    YF.clear()
    for i in range(0, len(ys), 200):
        yf_batch(ys[i:i + 200]); time.sleep(2)
    byg = {}
    for e in extra:
        if e["y"] in YF:
            p, a = YF[e["y"]]
            byg[e["g"]] = {"p": round(p, 6), "at": a}
    json.dump({"at": res["at"], "count": len(byg), "total": len(extra), "byg": byg}, open("all.json", "w"), sort_keys=True)
    print(f"extra: {len(byg)}/{len(extra)}")

game = {"at": res["at"], "fx": fx,
        "quotes": {k: {"p": v["p"], "at": v["at"], "t": ("PSE" if v["src"] == "pse" else "Yahoo") + " " + v["at"][:16].replace("T", " ") + " UTC"} for k, v in quotes.items()}}
json.dump(game, open("game_update.json", "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True)
print(f"{len(quotes)}/{len(symbols)} quotes, {len(fx)} fx, {len(errors)} errors")
