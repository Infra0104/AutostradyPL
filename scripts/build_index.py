#!/usr/bin/env python3
"""
ik-herby – Verzeichnis amtlicher Gemeindewappen aus den Ratsbeschlüssen (Polen)

Quelle: offizielle ELI-Schnittstelle des Sejm (api.sejm.gov.pl/eli), Beschlüsse
"w sprawie ustanowienia herbu …" aus den Amtsblättern der Woiwodschaften.
Zuordnung zu Gemeinden über Wikidata (TERC-Kennung), damit das Übersichtsplan-Tool
die Einträge direkt über die Wikidata-ID findet.

Aufruf:  python scripts/build_index.py --voiv malopolskie [--discover] [--limit N]
Ergebnis: data/index.json, data/img/<QID>.png, data/report.md
"""
import argparse, datetime, io, json, os, re, sys, time, urllib.parse, urllib.robotparser
import requests
try:
    import pymupdf as fitz
except ImportError:
    import fitz
from PIL import Image, ImageChops

API = "https://api.sejm.gov.pl/eli"
WDQS = "https://query.wikidata.org/sparql"
CONTACT = os.environ.get("CONTACT", "https://github.com/Infra0104/ik-herby")
UA = f"ik-herby/1.0 (+{CONTACT}) Infrakit map tool, monthly run"
VOIV = {  # TERC-Präfix und Suchbegriffe für das Amtsblatt
    "malopolskie": {"terc": "12", "names": ["małopolsk"]},
}
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
S = requests.Session(); S.headers["User-Agent"] = UA
_robots = {}
PAUSE = float(os.environ.get("PAUSE", "1.0"))


def allowed(url):
    """robots.txt der Zielseite respektieren."""
    p = urllib.parse.urlparse(url); base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser(); rp.set_url(base + "/robots.txt")
        try: rp.read()
        except Exception: rp = None
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(UA, url)


def get(url, **kw):
    if not allowed(url):
        raise PermissionError(f"robots.txt verbietet: {url}")
    for attempt in range(4):
        r = S.get(url, timeout=60, **kw)
        if r.status_code in (429, 502, 503, 504):
            time.sleep(5 * (attempt + 1)); continue
        r.raise_for_status(); time.sleep(PAUSE); return r
    r.raise_for_status()


# ---------- 1. Amtsblatt in der ELI-Schnittstelle finden ----------
def find_publishers(voiv):
    pubs = get(API + "/acts", headers={"Accept": "application/json"}).json()
    keys = VOIV[voiv]["names"]
    hits = [p for p in pubs if any(k in (p.get("name", "") + " " + p.get("shortName", "")).lower() for k in keys)]
    return pubs, hits


# ---------- 2. Wappenbeschlüsse suchen ----------
TITLE_OK = re.compile(r"herb", re.I)
TITLE_KIND = re.compile(r"ustanowieni|przyjęci|wzor|zmian|uchyl|symbol|insygni", re.I)
TITLE_ABOUT = re.compile(r"w\s+sprawie[^.;]{0,60}?\bherb", re.I)
TITLE_SKIP = re.compile(r"nadani[ae] prawa|wyrażeni[ae] zgody|zgody na używanie|honorow|odznak|medal", re.I)


def is_crest_act(t):
    if not TITLE_OK.search(t): return False
    if TITLE_SKIP.search(t) and not re.search(r"ustanowieni", t, re.I): return False
    return bool(TITLE_ABOUT.search(t) or TITLE_KIND.search(t))
ORGAN = re.compile(r"Rad[ay]\s+(?P<typ>Gminy|Miejskiej(?:\s+w)?|Miasta(?:\s+i\s+Gminy)?|Powiatu|Dzielnicy)\s+(?P<name>[A-ZŁŚŻŹĆŃÓĘĄ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\-]*(?:[\s\-][A-ZŁŚŻŹĆŃÓĘĄ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\-]*)*)", re.U)
DATE = re.compile(r"z\s+dnia\s+(\d{1,2})\s+(\w+)\s+(\d{4})", re.I)
MONTHS = {m: i + 1 for i, m in enumerate("stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia".split())}


def search_acts(publisher, limit=None):
    out, offset = [], 0
    while True:
        q = {"publisher": publisher, "title": "herb", "limit": 200, "offset": offset}
        d = get(API + "/acts/search?" + urllib.parse.urlencode(q), headers={"Accept": "application/json"}).json()
        items = d.get("items", [])
        out += [i for i in items if is_crest_act(i.get("title", ""))]
        offset += len(items)
        if not items or offset >= d.get("totalCount", 0) or (limit and len(out) >= limit): break
    return out[:limit] if limit else out


def parse_title(t):
    m = ORGAN.search(t); d = DATE.search(t)
    date = None
    if d and d.group(2).lower() in MONTHS:
        date = f"{int(d.group(3)):04d}-{MONTHS[d.group(2).lower()]:02d}-{int(d.group(1)):02d}"
    revoke = bool(re.search(r"uchyleni|stwierdzeni[ae] nieważności", t, re.I)) and not re.search(r"ustanowieni", t, re.I)
    return {"organ_typ": m.group("typ") if m else None, "organ_name": m.group("name").strip() if m else None,
            "date": date, "revoke": revoke, "powiat": bool(m and m.group("typ") == "Powiatu")}


# ---------- 3. Gemeinden aus Wikidata (mit TERC und Wikidata-ID) ----------
def wikidata_units(terc_prefix):
    q = f"""SELECT ?u ?uLabel ?terc ?seatLabel WHERE {{
      ?u wdt:P1653 ?terc . FILTER(STRSTARTS(?terc, "{terc_prefix}") && (STRLEN(?terc)=7 || STRLEN(?terc)=4))
      OPTIONAL {{ ?u wdt:P36 ?seat }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pl". }} }}"""
    r = get(WDQS + "?" + urllib.parse.urlencode({"query": q, "format": "json"}), headers={"Accept": "application/sparql-results+json"})
    units = {}
    for b in r.json()["results"]["bindings"]:
        qid = b["u"]["value"].rsplit("/", 1)[-1]
        u = units.setdefault(qid, {"qid": qid, "label": b["uLabel"]["value"], "terc": b["terc"]["value"], "seats": set()})
        if "seatLabel" in b: u["seats"].add(b["seatLabel"]["value"])
    for u in units.values(): u["seats"] = sorted(u["seats"])
    return list(units.values())


def core(label):
    return re.sub(r"^(gmina miejsko-wiejska|gmina miejska|gmina wiejska|gmina|powiat|miasto)\s+", "", label, flags=re.I).strip()


def stem(s, keep=3):
    s = s.lower(); return s[:max(4, len(s) - keep)]


def match_unit(info, units):
    """Ordnet „Rady Gminy Chełmiec“ / „Rady Miejskiej w Wieliczce“ / „Rady Powiatu Gorlickiego“ einer Einheit zu."""
    name = info["organ_name"]
    if not name: return None, "kein Organ im Titel"
    pool = [u for u in units if (len(u["terc"]) == 4) == info["powiat"]]
    exact = [u for u in pool if core(u["label"]).lower() == name.lower()]
    if len(exact) == 1: return exact[0], "exakt"
    st = stem(name)
    cand = [u for u in pool if core(u["label"]).lower().startswith(st) or any(s.lower().startswith(st) for s in u["seats"])]
    # Gleichnamige Einheiten (Landgemeinde, Stadtgemeinde, Stadt-Land-Gemeinde): die TERC-Typziffer entscheidet
    # 1 = gmina miejska, 2 = gmina wiejska, 3 = gmina miejsko-wiejska, 4 = Stadt in Stadt-Land-Gemeinde, 5 = Landteil
    if len(cand) > 1 and info["organ_typ"]:
        t = info["organ_typ"]
        pref = ["2", "3"] if t.startswith("Gminy") else ["3", "1"] if (t.startswith("Miejskiej") or "Gminy" in t) else ["1", "3"]
        for p in pref:
            c2 = [u for u in cand if len(u["terc"]) == 7 and u["terc"][-1] == p]
            if len(c2) == 1: return c2[0], "TERC-Typ"
    if len(cand) == 1: return cand[0], "Wortstamm"
    return None, f"mehrdeutig ({len(cand)})" if cand else "nicht gefunden"


# ---------- 4. Wappen aus der Anlage des Beschlusses ----------
def trim(img, pad=6):
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img.convert("RGB"), bg.convert("RGB")).convert("L").point(lambda v: 255 if v > 18 else 0)
    box = diff.getbbox()
    if not box: return None
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def extract_crest(pdf_bytes):
    """Sucht die Anlage „Herb“ und schneidet das Wappenbild aus. Rückgabe: (PNG-Bytes, Hinweis) oder (None, Grund)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    best = None
    for pno, page in enumerate(doc):
        txt = page.get_text().lower()
        is_annex = "załącznik" in txt or "zalacznik" in txt
        score = (3 if is_annex else 0) + (3 if re.search(r"\bherb", txt) else 0) - (2 if "flag" in txt and "herb" not in txt else 0)
        rects = []
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                if r.width > 40 and r.height > 40: rects.append(r)
        draw = [d["rect"] for d in page.get_drawings() if d["rect"].width > 30 and d["rect"].height > 30 and d["rect"].width < page.rect.width * 0.95]
        if draw:
            u = draw[0]
            for r in draw[1:]: u = u | r
            rects.append(u)
        if not rects: continue
        r = max(rects, key=lambda r: r.width * r.height)
        cand = (score + min(4, r.width * r.height / 20000), pno, r)
        if not best or cand[0] > best[0]: best = cand
    if not best or best[0] < 3: return None, "keine Wappen-Anlage erkannt"
    _, pno, r = best
    pix = doc[pno].get_pixmap(clip=r, dpi=200, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    img = trim(img)
    if img is None or img.width < 40 or img.height < 40: return None, "Bild zu klein"
    img.thumbnail((400, 480))
    b = io.BytesIO(); img.save(b, "PNG", optimize=True)
    return b.getvalue(), f"Seite {pno + 1}"


# ---------- Hauptlauf ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voiv", default="malopolskie", choices=sorted(VOIV))
    ap.add_argument("--discover", action="store_true", help="nur prüfen, welche Amtsblätter die Schnittstelle kennt")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
    report = [f"# Lauf {datetime.datetime.utcnow():%Y-%m-%d %H:%M} UTC – {a.voiv}", ""]

    pubs, hits = find_publishers(a.voiv)
    report.append("Amtsblätter in der ELI-Schnittstelle: " + ", ".join(f"{p.get('code')} ({p.get('name')})" for p in pubs))
    if not hits:
        report += ["", f"**Das Amtsblatt der Woiwodschaft {a.voiv} ist in api.sejm.gov.pl nicht enthalten.**",
                   "Nächster Schritt: Nutzung der ELI-Schnittstelle des e-Dziennik-Portals mit dem Urząd Wojewódzki klären (robots.txt verbietet automatische Zugriffe)."]
        open(os.path.join(OUT, "report.md"), "w").write("\n".join(report)); print("\n".join(report)); return 2
    report.append("Verwendet: " + ", ".join(h["code"] for h in hits))
    if a.discover:
        open(os.path.join(OUT, "report.md"), "w").write("\n".join(report)); print("\n".join(report)); return 0

    units = wikidata_units(VOIV[a.voiv]["terc"])
    report.append(f"Gemeinden und Kreise aus Wikidata: {len(units)}")
    idx_path = os.path.join(OUT, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else {"items": {}}
    acts = []
    for h in hits: acts += search_acts(h["code"], a.limit)
    report.append(f"Gefundene Wappenbeschlüsse: {len(acts)}"); report.append("")
    unmatched, problems, per_unit = [], [], {}
    for act in acts:
        info = parse_title(act["title"])
        unit, how = match_unit(info, units)
        if not unit: unmatched.append((act["ELI"], act["title"], how)); continue
        per_unit.setdefault(unit["qid"], []).append((act, info, unit))
    for qid, lst in per_unit.items():
        lst.sort(key=lambda x: (x[1]["date"] or x[0].get("announcementDate") or ""), reverse=True)
        chosen = None
        for act, info, unit in lst:
            if info["revoke"]: continue
            try: det = get(f"{API}/acts/{act['ELI']}", headers={"Accept": "application/json"}).json()
            except Exception as e: problems.append((act["ELI"], f"Details: {e}")); continue
            if det.get("inForce") == "NOT_IN_FORCE" or det.get("repealDate"): continue
            chosen = (act, info, unit, det); break
        if not chosen: problems.append((qid, "kein gültiger Beschluss (alle aufgehoben oder Fehler)")); continue
        act, info, unit, det = chosen
        prev = index["items"].get(qid)
        entry = {"label": unit["label"], "terc": unit["terc"], "eli": act["ELI"], "title": act["title"],
                 "date": info["date"] or act.get("announcementDate"), "entryIntoForce": det.get("entryIntoForce"),
                 "displayAddress": act.get("displayAddress"), "pdf": f"{API}/acts/{act['ELI']}/text.pdf",
                 "eliUrl": f"https://eli.gov.pl/eli/{act['ELI']}/ogl", "older": [x[0]["ELI"] for x in lst if x[0] is not act],
                 "checked": datetime.date.today().isoformat()}
        if prev and prev.get("eli") == act["ELI"] and prev.get("image"):
            entry["image"], entry["imageNote"] = prev["image"], prev.get("imageNote")
        else:
            try:
                pdf = get(entry["pdf"], headers={"Accept": "application/pdf"}).content
                png, note = extract_crest(pdf)
            except Exception as e:
                png, note = None, f"PDF: {e}"
            if png:
                rel = f"img/{qid}.png"; open(os.path.join(OUT, rel), "wb").write(png)
                entry["image"], entry["imageNote"] = rel, note
            else:
                entry["image"], entry["imageNote"] = None, note; problems.append((qid, f"{unit['label']}: {note}"))
        index["items"][qid] = entry
    index.update({"generated": datetime.datetime.utcnow().isoformat() + "Z", "source": "api.sejm.gov.pl/eli",
                  "voivodeships": sorted(set(index.get("voivodeships", [])) | {a.voiv})})
    json.dump(index, open(idx_path, "w"), ensure_ascii=False, indent=1)
    report.append(f"Im Verzeichnis: {len(index['items'])} Einheiten, davon mit Bild: {sum(1 for v in index['items'].values() if v.get('image'))}")
    report += ["", "## Nicht zugeordnet (bitte prüfen)"] + ([f"- {e} – {t} ({w})" for e, t, w in unmatched] or ["- keine"])
    report += ["", "## Probleme"] + ([f"- {k}: {v}" for k, v in problems] or ["- keine"])
    open(os.path.join(OUT, "report.md"), "w").write("\n".join(report)); print("\n".join(report[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
