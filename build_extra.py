"""Sestaví širší seznam titulů (extra.json), aby robot měl kurzy i pro tituly, které Kuba ve hře přidá.

Zdroje: tabulky složení indexů na Wikipedii. Spouští se jednou týdně (a při změně skriptu).
Každá položka: {"y": symbol na Yahoo, "g": klíč ve tvaru Google Finance (US tituly jako TICKER:US)}.
"""
import json, re, io
import requests, pandas as pd

UA = {"User-Agent": "burza-kurzy/1.0 (github.com/jakubmaule-boop/burza-kurzy)"}
YSUF_TO_G = {".DE": "ETR", ".PA": "EPA", ".AS": "AMS", ".MC": "BME", ".L": "LON", ".SW": "SWX", ".MI": "BIT",
             ".T": "TYO", ".HK": "HKG", ".KS": "KRX", ".BR": "EBR", ".HE": "HEL", ".ST": "STO", ".CO": "CPH",
             ".OL": "OSL", ".VI": "VIE", ".WA": "WSE", ".LS": "ELI", ".IR": "ISE", ".AX": "ASX", ".TO": "TSE"}

# (stránka, výchozí přípona Yahoo nebo "" pro USA)
PAGES = [
    ("List_of_S%26P_500_companies", ""), ("List_of_S%26P_400_companies", ""), ("List_of_S%26P_600_companies", ""),
    ("Nasdaq-100", ""), ("DAX", ".DE"), ("MDAX", ".DE"), ("TecDAX", ".DE"), ("CAC_40", ".PA"), ("AEX_index", ".AS"),
    ("IBEX_35", ".MC"), ("FTSE_100_Index", ".L"), ("FTSE_250_Index", ".L"), ("Swiss_Market_Index", ".SW"),
    ("FTSE_MIB", ".MI"), ("Euro_Stoxx_50", ""), ("OMX_Stockholm_30", ".ST"), ("OMX_Copenhagen_25", ".CO"),
    ("OMX_Helsinki_25", ".HE"), ("OBX_Index", ".OL"), ("BEL_20", ".BR"), ("Austrian_Traded_Index", ".VI"),
    ("WIG20", ".WA"), ("Hang_Seng_Index", ".HK"), ("Nikkei_225", ".T"), ("S%26P/ASX_50", ".AX"),
]

ETFS = "SPY QQQ VOO VTI IVV IWM DIA EEM EFA VEA VWO GLD SLV IAU USO UNG BNO CPER PPLT DBA DBC TLT IEF SHY HYG LQD ARKK ARKG XLE XLF XLK XLV XLI XLY XLP XLU XLB XLRE XLC SMH SOXX IBB XBI KWEB FXI MCHI EWJ EWG EWU EWQ EWI EWP EWL EWN EWZ EWY EWT EWA EWC INDA EZU VGK IEMG VNQ JETS ITA PPA URA LIT TAN ICLN GDX GDXJ SIL BITO IBIT FBTC ETHA SCHD JEPI TQQQ SQQQ SOXL UVXY VXX".split()
INDEXES = {"^GSPC": ".INX:INDEXSP", "^IXIC": ".IXIC:INDEXNASDAQ", "^NDX": "NDX:INDEXNASDAQ", "^DJI": ".DJI:INDEXDJX",
           "^RUT": "RUT:INDEXRUSSELL", "^VIX": "VIX:INDEXCBOE", "^GDAXI": "DAX:INDEXDB", "^FCHI": "PX1:INDEXEURO",
           "^STOXX50E": "SX5E:INDEXSTOXX", "^STOXX": "SXXP:INDEXSTOXX", "^FTSE": "UKX:INDEXFTSE", "^N225": "NI225:INDEXNIKKEI",
           "^HSI": "HSI:INDEXHANGSENG", "^AEX": "AEX:INDEXEURO", "^SSMI": "SMI:INDEXSWX", "^IBEX": "IB:INDEXBME",
           "^KS11": "KOSPI:KRX", "FTSEMIB.MI": "FTSEMIB:INDEXFTSE", "000001.SS": "000001:SHA", "^BSESN": "SENSEX:INDEXBOM",
           "^NSEI": "NIFTY_50:INDEXNSE", "^AXJO": "XJO:INDEXASX", "^GSPTSE": "OSPTX:INDEXTSI", "^BVSP": "IBOV:INDEXBVMF"}
COMMOD = {"GC=F": "GCW00:COMEX", "SI=F": "SIW00:COMEX", "HG=F": "HGW00:COMEX", "PL=F": "PLW00:NYMEX", "PA=F": "PAW00:NYMEX",
          "CL=F": "CLW00:NYMEX", "BZ=F": "BZW00:NYMEX", "NG=F": "NGW00:NYMEX", "RB=F": "RBW00:NYMEX", "HO=F": "HOW00:NYMEX",
          "ZC=F": "ZCW00:CBOT", "ZW=F": "ZWW00:CBOT", "ZS=F": "ZSW00:CBOT", "KC=F": "KCW00:NYBOT", "CC=F": "CCW00:NYBOT",
          "SB=F": "SBW00:NYBOT", "CT=F": "CTW00:NYBOT", "LE=F": "LEW00:CME"}
CRYPTO = "BTC ETH SOL XRP DOGE ADA BNB TRX AVAX LINK DOT LTC BCH XLM SHIB TON SUI NEAR APT UNI ATOM ETC HBAR ICP FIL ARB OP PEPE AAVE XMR ALGO VET INJ RNDR".split()

def g_from_y(y):
    for suf, ex in YSUF_TO_G.items():
        if y.endswith(suf):
            t = y[: -len(suf)]
            return f"{t}:{ex}"
    return y.replace("-", ".") + ":US"

def clean(v, suf):
    v = str(v).strip().upper()
    v = re.sub(r"\[.*?\]", "", v).strip()
    if not v or v in ("NAN", "-") or " " in v or len(v) > 14:
        return None
    m = re.match(r"^([A-Z]+):\s*([A-Z0-9.\-]+)$", v)  # např. "NYSE: XYZ"
    if m:
        v = m.group(2)
    if suf == "":
        if "." in v and v.rsplit(".", 1)[1] in [s[1:] for s in YSUF_TO_G]:
            return v
        return v.replace(".", "-")
    if suf == ".HK":
        v = re.sub(r"\D", "", v)
        return v.zfill(4) + ".HK" if v else None
    if suf == ".T":
        v = re.sub(r"\D", "", v)
        return v + ".T" if len(v) == 4 else None
    if "." in v and ("." + v.rsplit(".", 1)[1]) in YSUF_TO_G:
        return v
    return v.replace(".", "-") + suf

out, log = {}, []
for page, suf in PAGES:
    try:
        r = requests.get(f"https://en.wikipedia.org/wiki/{page}", headers=UA, timeout=30)
        tables = pd.read_html(io.StringIO(r.text))
    except Exception as e:
        log.append(f"{page}: {e}"); continue
    n = 0
    for t in tables:
        cols = [c for c in t.columns if re.search(r"ticker|symbol|code|ric", str(c), re.I)]
        if not cols or len(t) < 10:
            continue
        for v in t[cols[0]].tolist():
            y = clean(v, suf)
            if y:
                out[y] = g_from_y(y); n += 1
        if n:
            break
    log.append(f"{page}: {n}")
for e in ETFS: out[e] = e + ":US"
out.update(INDEXES); out.update(COMMOD)
for c in CRYPTO: out[f"{c}-USD"] = f"{c}-USD"
json.dump([{"y": y, "g": g} for y, g in sorted(out.items())], open("extra.json", "w"), indent=0)
json.dump(log, open("extra_log.json", "w"), indent=1)
print(len(out), log)
