# temporary: which old d-TPP editions does the FAA still serve? prints only.
import urllib.request
for ed in ("2605", "2606", "2607", "2608", "2609"):
    for path in ("xml_data/d-tpp_Metafile.xml", "00110IL7L.PDF", "05103AD.PDF"):
        url = f"https://aeronav.faa.gov/d-tpp/{ed}/{path}"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "amend"})
            with urllib.request.urlopen(req, timeout=30) as r:
                print(ed, path, r.status, r.headers.get("Content-Length"), r.headers.get("Last-Modified"))
        except Exception as e:
            print(ed, path, "ERR", e)
