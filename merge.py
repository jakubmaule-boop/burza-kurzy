"""Doplní do /tmp/gu.json kurzy vlastních titulů hry (config.custom) z /tmp/all.json.
Použití: python3 merge.py /tmp/custom.json   (custom.json = pole config.custom z databáze hry)"""
import json, sys
US = {"NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "BATS", "NYSEMKT", "OTCMKTS", "US"}
def key(q):
    q = q.strip().upper()
    if ":" not in q:
        return q
    t, ex = q.split(":", 1)
    return f"{t}:US" if ex in US else f"{t}:{ex}"
gu = json.load(open("/tmp/gu.json"))
allq = json.load(open("/tmp/all.json")).get("byg", {})
custom = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
hit, miss = [], []
for c in custom:
    s, q = c.get("s"), c.get("q", "")
    if not s or s in gu["quotes"]:
        continue
    v = allq.get(key(q))
    if v:
        gu["quotes"][s] = {"p": v["p"], "at": v["at"], "t": "Yahoo " + v["at"][:16].replace("T", " ") + " UTC"}
        hit.append(s)
    else:
        miss.append(f"{s} ({q})")
json.dump(gu, open("/tmp/gu.json", "w"), ensure_ascii=False)
print("doplneno:", hit, "| bez kurzu:", miss)
