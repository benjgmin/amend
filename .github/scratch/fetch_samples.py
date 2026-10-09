# temporary: pulls real changed plates (old + new edition) so the plate-number diff can be built
# against real files. lives only on the working branch; removed before merge.
import os, random, sys, urllib.request, xml.etree.ElementTree as ET
SKIP = {"DAB", "DED", "OMN", "EVB"}
def get(url, path):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "amend"}), timeout=60) as r:
            b = r.read()
    except Exception as e:
        print("miss", url, e); return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b); return True
for new, old, n in (("2611", "2610", 220), ("2610", "2609", 40)):
    meta = f"out/meta_{new}.xml"
    if not get(f"https://aeronav.faa.gov/d-tpp/{new}/xml_data/d-tpp_Metafile.xml", meta):
        continue
    recs, apt = [], None
    for ev, el in ET.iterparse(meta, events=("start", "end")):
        if ev == "start" and el.tag == "airport_name":
            apt = el.get("apt_ident")
        elif ev == "end" and el.tag == "record":
            g = lambda k: (el.findtext(k) or "").strip()
            if g("useraction") == "C" and apt not in SKIP and g("pdf_name") and "CONT" not in g("chart_name"):
                recs.append((g("chart_code"), apt, g("pdf_name")))
            el.clear()
    print(new, "changed first pages:", len(recs))
    random.seed(7)
    by = {}
    for r in recs:
        by.setdefault(r[0], []).append(r)
    pick = []
    for code, rr in by.items():
        k = n if code == "IAP" else max(6, n // 8)
        pick += random.sample(rr, min(k, len(rr)))
    for code, apt, pdf in pick:
        for ed in (old, new):
            get(f"https://aeronav.faa.gov/d-tpp/{ed}/{pdf}", f"out/{new}/{ed}/{code}_{apt}_{pdf}")
