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
        try:
            r = S.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "5m", "range": "1d"}, timeout=15)
            if r.status_code == 200:
                m = r.json()["chart"]["result"][0]["meta"]
                p, t = m.get("regularMarketPrice"), m.get("regularMarketTime")
                if p:
                    return float(p), iso(t) if t else None
        except Exception as e:
            errors.append(f"{sym}@{host}: {e}")
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
quotes, fx = {}, {}

# Měny: X/CZK = (USD/CZK) / (USD/X)
usdczk, at = yahoo("CZK=X")
if usdczk:
    fx["USD"] = {"p": usdczk, "at": at}
    for cur in ("EUR", "GBP", "JPY", "CHF", "HKD", "KRW"):
        v, a = yahoo(f"{cur}=X")
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
        p, a = yahoo(e["y"])
        if p is not None:
            quotes[e["s"]] = {"p": p, "at": a or pse_at, "src": "yahoo"}
        else:
            errors.append(f"yahoo missing {e['s']} ({e['y']})")
        time.sleep(0.15)

res = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(quotes), "total": len(symbols),
       "quotes": quotes, "fx": fx, "errors": errors[-60:]}
json.dump(res, open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
print(f"{len(quotes)}/{len(symbols)} quotes, {len(fx)} fx, {len(errors)} errors")
if len(quotes) < len(symbols) // 2:
    sys.exit(1)
