#!/usr/bin/env python3
"""
LAIW Preprocessing Pipeline
Konverterar rådata (XML, HTML, JSON) → ren text → JSONL träningsdataset

Output: ~/LAIW/data/processed/
  {source}.jsonl        ett dokument per rad: {"text":"...","source":"...","meta":{}}
  dataset.jsonl         alla källor sammanslagna
  dataset_stats.json    statistik

Kör: python3 preprocess.py [--source all|sfs|prop|bet|sou|eu|domstol]
"""
import json, re, sys, argparse, logging, time
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from lxml import etree

BASE    = Path.home() / "LAIW"
RAW     = BASE / "data" / "raw"
OUT_DIR = BASE / "data" / "processed"
LOG_DIR = BASE / "logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

MIN_CHARS = 200
MAX_CHARS = 2_000_000

def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lf = LOG_DIR / f"preprocess_{ts}.log"
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf), logging.StreamHandler(sys.stdout)])
    logging.info(f"Log: {lf}")

# ── text extraction ────────────────────────────────────────────────────────────
def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script","style","head","meta","link"]): tag.decompose()
    return clean_text(soup.get_text(separator="\n"))

def xml_to_text(raw: bytes) -> str:
    try:
        root = etree.fromstring(raw)
        for elem in root.iter():
            if elem.tag == "html":
                # riksdagen motioner/fr/ip/dir store HTML as text content inside <html>
                html_str = (elem.text or "").strip()
                if html_str and html_str.startswith("<"):
                    return html_to_text(html_str)
                html_str = etree.tostring(elem, encoding="unicode", method="html")
                if html_str.strip():
                    return html_to_text(html_str)
            elif elem.tag in ("text", "body"):
                t = etree.tostring(elem, encoding="unicode", method="text")
                if t.strip(): return clean_text(t)
        return clean_text(etree.tostring(root, encoding="unicode", method="text"))
    except Exception:
        return html_to_text(raw.decode("utf-8", errors="replace"))

def clean_text(t: str) -> str:
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', t)
    t = t.replace('\xa0', ' ')                          # non-breaking space → vanligt mellanslag
    t = re.sub(r'\n{3,}', '\n\n', t)
    t = "\n".join(re.sub(r' {3,}', '  ', l) for l in t.split('\n'))
    return t.strip()

def clean_prot(t: str) -> str:
    """Extra rensning för protokoll: ta bort OCR-brus (falska vinkelparentes-fragment)."""
    # Tar bort mönster som <blah !}blah> som är OCR-artefakter, ej riktig HTML
    t = re.sub(r'<[^<>\n]{1,60}>', ' ', t)
    return clean_text(t)

def trunc(t: str) -> str:
    return t[:MAX_CHARS] + "\n[TRUNKERAT]" if len(t) > MAX_CHARS else t

# ── sources ────────────────────────────────────────────────────────────────────
def process_riksdagen(doctype, subdirs):
    out = OUT_DIR / f"{doctype}.jsonl"
    ok = skip = err = 0
    t0 = time.time()
    files = []
    for s in subdirs:
        d = RAW / "riksdagen" / "texts" / s
        if d.exists(): files.extend(d.glob("*.xml"))
    logging.info(f"  {doctype.upper()}: {len(files):,} XML-filer")
    seen = set()
    with open(out, "w", encoding="utf-8") as f:
        for p in files:
            did = p.stem.upper()
            if did in seen: skip += 1; continue
            seen.add(did)
            try:
                text = xml_to_text(p.read_bytes())
                if doctype == "prot":
                    text = clean_prot(text)
                if len(text) < MIN_CHARS: skip += 1; continue
                f.write(json.dumps({"text": trunc(text), "source": doctype,
                    "meta": {"dok_id": did}}, ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                err += 1
                if err <= 3: logging.warning(f"  {p.name}: {e}")
    mb = out.stat().st_size / 1e6
    logging.info(f"  {doctype.upper()} klar: {ok:,} OK, {skip:,} skip, {err} fel | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": doctype, "docs": ok, "size_mb": mb}

def process_eu():
    out = OUT_DIR / "eu.jsonl"
    meta_map = {}
    idx = RAW / "eu" / "eu_legislation_index.json"
    if idx.exists():
        for d in json.load(open(idx)): meta_map[d.get("celex","")] = d
    files = list((RAW / "eu" / "texts").glob("*.html"))
    logging.info(f"  EU: {len(files):,} HTML-filer")
    ok = skip = err = 0; t0 = time.time()
    with open(out, "w", encoding="utf-8") as f:
        for p in files:
            try:
                text = html_to_text(p.read_text(encoding="utf-8", errors="replace"))
                if len(text) < MIN_CHARS: skip += 1; continue
                m = meta_map.get(p.stem, {})
                f.write(json.dumps({"text": trunc(text), "source": "eu",
                    "meta": {"celex": p.stem, "title": m.get("title",""),
                             "date": m.get("date",""), "type": m.get("type","")}},
                    ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                err += 1
    mb = out.stat().st_size / 1e6
    logging.info(f"  EU klar: {ok:,} OK, {skip} skip, {err} fel | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": "eu", "docs": ok, "size_mb": mb}

def process_domstol():
    out = OUT_DIR / "domstol.jsonl"
    ok = skip = err = 0; t0 = time.time()
    with open(out, "w", encoding="utf-8") as f:
        # Vägledande – fulltext HTML
        vag = RAW / "domstolar" / "vagledande_all.json"
        if vag.exists():
            cases = json.load(open(vag))
            logging.info(f"  Domstol vägledande: {len(cases):,} fall")
            for c in cases:
                html = c.get("innehall","")
                if not html or len(html) < MIN_CHARS: skip += 1; continue
                try:
                    text = html_to_text(html)
                    if len(text) < MIN_CHARS: skip += 1; continue
                    f.write(json.dumps({"text": trunc(text), "source": "domstol_vagledande",
                        "meta": {"id": c.get("id",""), "domstol": c.get("domstol",{}).get("domstolNamn",""),
                                 "datum": c.get("avgorandedatum",""),
                                 "rattsomrade": c.get("rattsomradeLista",[])}},
                        ensure_ascii=False) + "\n")
                    ok += 1
                except: err += 1
        # Övriga – sammanfattning
        ovr = RAW / "domstolar" / "ovriga_all.json"
        if ovr.exists():
            cases = json.load(open(ovr))
            logging.info(f"  Domstol övriga: {len(cases):,} fall")
            for c in cases:
                text = c.get("sammanfattning","").strip()
                if len(text) < MIN_CHARS: skip += 1; continue
                f.write(json.dumps({"text": text, "source": "domstol_ovriga",
                    "meta": {"id": c.get("id",""), "domstol": c.get("domstol",{}).get("domstolNamn",""),
                             "datum": c.get("avgorandedatum","")}},
                    ensure_ascii=False) + "\n")
                ok += 1
    mb = out.stat().st_size / 1e6
    logging.info(f"  Domstol klar: {ok:,} OK, {skip} skip, {err} fel | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": "domstol", "docs": ok, "size_mb": mb}

def merge_all():
    out = OUT_DIR / "dataset.jsonl"
    total = 0
    logging.info(f"\n  Slår ihop → dataset.jsonl")
    with open(out, "w", encoding="utf-8") as fout:
        for src in sorted(OUT_DIR.glob("*.jsonl")):
            if src.name == "dataset.jsonl": continue
            n = sum(1 for line in open(src, encoding="utf-8")
                    if fout.write(line) or True)
            logging.info(f"    {src.name}: {n:,}")
            total += n
    gb = out.stat().st_size / 1e9
    logging.info(f"  dataset.jsonl: {total:,} dokument, {gb:.2f} GB")
    return total, gb

def _extract_article_text(html: str) -> str:
    """Extract text from <article> or <main>, stripping nav/header/footer."""
    soup = BeautifulSoup(html, "lxml")
    container = soup.find("article") or soup.find("main") or soup
    for tag in container(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return clean_text(container.get_text(separator="\n"))


def process_mfs():
    out = OUT_DIR / "mfs.jsonl"
    src_dir = BASE / "data" / "raw" / "mfs"
    if not src_dir.exists():
        logging.warning("  mfs: raw-katalog saknas, kör download_mfs.py först")
        return {"source": "mfs", "docs": 0, "size_mb": 0}
    files = list(src_dir.glob("*.html"))
    logging.info(f"  MFS: {len(files):,} HTML-filer")
    ok = skip = err = 0; t0 = time.time()
    soft404 = ("kan inte hittas", "sidan kunde inte", "page not found", "404")
    with open(out, "w", encoding="utf-8") as f:
        for p in files:
            try:
                raw_html = p.read_text(encoding="utf-8", errors="replace")
                # Filter soft-404 pages (e.g. SSM returns HTTP 200 for missing regs)
                raw_lower = raw_html.lower()
                if any(s in raw_lower for s in soft404):
                    skip += 1; continue
                text = _extract_article_text(raw_html)
                # Strip PDF page markers inserted by lagen.nu (page001, page002, ...)
                text = re.sub(r'\bpage\d{3}\b\s*\n*\s*Original\s*\n*', '\n', text)
                text = re.sub(r'\bpage\d{3}\b', '', text)
                text = re.sub(r'\n{3,}', '\n\n', text).strip()
                if len(text) < MIN_CHARS:
                    skip += 1; continue
                m = re.match(r"([a-z\-]+)-(\d{4})-(\d+)", p.stem)
                if m:
                    prefix, year, nr = m.group(1), m.group(2), m.group(3)
                    beteckning = f"{prefix.upper()} {year}:{nr}"
                else:
                    beteckning = p.stem
                f.write(json.dumps({"text": trunc(text), "source": "mfs",
                    "meta": {"beteckning": beteckning, "fil": p.name}},
                    ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                err += 1
                if err <= 3: logging.warning(f"  {p.name}: {e}")
    mb = out.stat().st_size / 1e6
    logging.info(f"  MFS klar: {ok:,} OK, {skip} skip, {err} fel | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": "mfs", "docs": ok, "size_mb": mb}


def process_lagennu():
    out = OUT_DIR / "lagennu.jsonl"
    src_dir = BASE / "data" / "raw" / "lagennu"
    if not src_dir.exists():
        logging.warning("  lagennu: raw-katalog saknas, kör download_lagennu.py först")
        return {"source": "lagennu", "docs": 0, "size_mb": 0}
    files = list(src_dir.glob("*.html"))
    logging.info(f"  lagen.nu: {len(files):,} HTML-filer")
    ok = skip = err = 0; t0 = time.time()
    with open(out, "w", encoding="utf-8") as f:
        for p in files:
            sfs = p.stem.replace("-", ":", 1)   # "1962-700" → "1962:700"
            try:
                text = _extract_article_text(p.read_text(encoding="utf-8", errors="replace"))
                if len(text) < MIN_CHARS:
                    skip += 1; continue
                f.write(json.dumps({"text": trunc(text), "source": "lagennu",
                    "meta": {"sfs": sfs}}, ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                err += 1
                if err <= 3: logging.warning(f"  {p.name}: {e}")
    mb = out.stat().st_size / 1e6
    logging.info(f"  lagen.nu klar: {ok:,} OK, {skip} skip, {err} fel | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": "lagennu", "docs": ok, "size_mb": mb}


def process_myndigheter():
    out = OUT_DIR / "myndigheter.jsonl"
    ok = skip = err = 0; t0 = time.time()
    sources = {
        "jo": RAW / "myndigheter" / "jo_decisions.json",
        "jk": RAW / "myndigheter" / "jk_decisions.json",
        "do": RAW / "myndigheter" / "do_decisions.json",
        "di": RAW / "myndigheter" / "di_decisions.json",
    }
    with open(out, "w", encoding="utf-8") as f:
        for src_name, path in sources.items():
            if not path.exists():
                continue
            decisions = json.load(open(path))
            logging.info(f"  Myndigheter {src_name}: {len(decisions):,} beslut")
            for d in decisions:
                text = d.get("text", "").strip()
                if len(text) < MIN_CHARS:
                    skip += 1; continue
                try:
                    f.write(json.dumps({"text": trunc(text), "source": f"myndighet_{src_name}",
                        "meta": {"url": d.get("url",""), "title": d.get("title",""),
                                 "diarienummer": d.get("diarienummer","")}},
                        ensure_ascii=False) + "\n")
                    ok += 1
                except Exception as e:
                    err += 1
    mb = out.stat().st_size / 1e6
    logging.info(f"  Myndigheter klar: {ok:,} OK, {skip} skip, {err} fel | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": "myndigheter", "docs": ok, "size_mb": mb}

def clean_saob_section(s: str) -> str:
    """Rensa SAOB-sektionstext: ta bort webbskräp och normalisera."""
    import html as html_module
    s = html_module.unescape(re.sub(r"<[^>]+>", "", s))
    s = re.sub(r'Publicerad\s+\d{4}\s*', '', s)   # "Publicerad 1893"
    s = re.sub(r'Lämna synpunkter\s*', '', s)      # UI-knapp
    s = s.replace('\xa0', ' ')
    return re.sub(r' {2,}', ' ', s).strip()

def process_saob():
    out = OUT_DIR / "saob.jsonl"
    ok = skip = 0; t0 = time.time()
    src = BASE / "data" / "raw" / "saob" / "saob_complete.json"
    if not src.exists():
        logging.warning("  saob_complete.json saknas")
        return {"source": "saob", "docs": 0, "size_mb": 0}
    entries = json.load(open(src, encoding="utf-8"))
    logging.info(f"  SAOB: {len(entries):,} artiklar")
    with open(out, "w", encoding="utf-8") as f:
        for e in entries:
            word = e.get("word", "").strip()
            sections = e.get("sections", [])
            if not word or not sections:
                skip += 1; continue
            cleaned = [clean_saob_section(s) for s in sections if s]
            cleaned = [s for s in cleaned if s]
            if not cleaned:
                skip += 1; continue
            text = clean_text(f"{word}\n\n" + "\n\n".join(cleaned))
            if len(text) < MIN_CHARS:
                skip += 1; continue
            f.write(json.dumps({"text": trunc(text), "source": "saob",
                "meta": {"word": word, "titles": e.get("titles", [])}},
                ensure_ascii=False) + "\n")
            ok += 1
    mb = out.stat().st_size / 1e6
    logging.info(f"  SAOB klar: {ok:,} OK, {skip:,} skip | {mb:.0f} MB | {time.time()-t0:.0f}s")
    return {"source": "saob", "docs": ok, "size_mb": mb}

SOURCE_MAP = {
    "mfs":         process_mfs,
    "lagennu":     process_lagennu,
    "sfs":         lambda: process_riksdagen("sfs",  ["sfs"]),
    "prop":        lambda: process_riksdagen("prop", ["prop"]),
    "bet":         lambda: process_riksdagen("bet",  ["bet"]),
    "sou":         lambda: process_riksdagen("sou",  ["sou"]),
    "ds":          lambda: process_riksdagen("ds",   ["ds"]),
    "prot":        lambda: process_riksdagen("prot", ["prot"]),
    "mot":         lambda: process_riksdagen("mot",  ["mot"]),
    "fr":          lambda: process_riksdagen("fr",   ["fr"]),
    "ip":          lambda: process_riksdagen("ip",   ["ip"]),
    "dir":         lambda: process_riksdagen("dir",  ["dir"]),
    "yttr":        lambda: process_riksdagen("yttr", ["yttr"]),
    "saob":        process_saob,
    "eu":          process_eu,
    "domstol":     process_domstol,
    "myndigheter": process_myndigheter,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="all",
        choices=["all"]+list(SOURCE_MAP.keys()))
    parser.add_argument("--no-merge", action="store_true")
    args = parser.parse_args()
    setup_logging()
    logging.info("="*60)
    logging.info("  LAIW PREPROCESSING PIPELINE")
    logging.info("="*60)
    sources = list(SOURCE_MAP.keys()) if args.source=="all" else [args.source]
    stats = [SOURCE_MAP[s]() for s in sources]
    if not args.no_merge and args.source=="all":
        total, gb = merge_all()
        stats.append({"source":"TOTAL","docs":total,"size_mb":gb*1000})
    json.dump(stats, open(OUT_DIR/"dataset_stats.json","w"), indent=2, ensure_ascii=False)
    logging.info("\n"+"="*60+"  KLART")
    for s in stats:
        logging.info(f"  {s['source']:15s} {s['docs']:>8,} dok  {s['size_mb']:>8.0f} MB")
