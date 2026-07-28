import json, re, urllib.request

EVENT = "Earthquake-Myanmar-March-2025"   # or "Brazil-Flooding-May24"
BASE = "https://maxar-opendata.s3.amazonaws.com"

def ls(prefix, delim="/"):
    url = f"{BASE}/?list-type=2&prefix={prefix}&delimiter={delim}"
    xml = urllib.request.urlopen(url, timeout=30).read().decode()
    return (re.findall(r"<Prefix>([^<]+)</Prefix>", xml)[1:],
            re.findall(r"<Key>([^<]+)</Key>", xml))

zones, _ = ls(f"events/{EVENT}/ard/")
for zone in [z for z in zones if re.search(r"/ard/\d+/$", z)]:
    quads, _ = ls(zone)
    for quad in quads:
        dates, _ = ls(quad)
        _, keys = ls(dates[0], delim="")
        item = next((k for k in keys if k.endswith(".json")), None)
        if not item:
            continue
        meta = json.load(urllib.request.urlopen(f"{BASE}/{item}", timeout=30))
        b = meta.get("bbox", ["?"] * 4)
        cloud = meta.get("properties", {}).get("tile:clouds_percent", "?")
        print(f"{quad.split('/')[-2]}  lon {b[0]:.3f}..{b[2]:.3f}  lat {b[1]:.3f}..{b[3]:.3f}  "
          f"cloud {cloud}%  dates: {', '.join(d.rstrip('/').split('/')[-1] for d in dates)}")