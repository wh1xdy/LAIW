#!/usr/bin/env python3
"""
EUR-Lex Downloader — EU-förordningar och direktiv på svenska
Källa: EUR-Lex CELLAR SPARQL + Content API

Strategi:
  1. SPARQL: hämta alla CELEX-nummer för förordningar/direktiv på svenska (2000–2026)
  2. Content API: hämta HTML-text för varje dokument

Output:
  ~/LAIW/data/raw/eu/eu_legislation_index.json   ← metadata + CELEX-nummer
  ~/LAIW/data/raw/eu/texts/{CELEX}.html          ← fulltext per dokument

Kör: python3 download_eurlex.py [--type reg|dir|both]
"""

import json, time, sys, os, logging, argparse, re
from pathlib import Path
from datetime import datetime
import urllib.request, urllib.parse, urllib.error

BASE_DIR  = Path.home() / "LAIW"
OUT_DIR   = BASE_DIR / "data" / "raw" / "eu"
LOG_DIR   = BASE_DIR / "logs"
TEXT_DIR  = OUT_DIR / "texts"
PROG_FILE = OUT_DIR / ".progress_eu.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
TEXT_DIR.mkdir(parents=True, exist_ok=True)

SPARQL_URL  = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX_BASE = "https://eur-lex.europa.eu"
CELLAR_BASE = "https://publications.europa.eu/resource/cellar"
SLEEP_SPARQL = 1.0
SLEEP_TEXT   = 2.0   # slower = fewer rate-limit resets
MAX_RETRIES  = 5

# Resurstypskoder i CDM-ontologin
RESOURCE_TYPES = {
    "reg": "http://publications.europa.eu/resource/authority/resource-type/REG",
    "dir": "http://publications.europa.eu/resource/authority/resource-type/DIR",
}

def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lf = LOG_DIR / f"eurlex_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf), logging.StreamHandler(sys.stdout)],
    )
    logging.info(f"Log: {lf}")

def sparql_query(query: str) -> list[dict]:
    """Kör SPARQL-fråga mot EUR-Lex och returnera bindings."""
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    url = SPARQL_URL + "?" + params
    req = urllib.request.Request(url, headers={
        "User-Agent": "LAIW-Dataset/1.0",
        "Accept": "application/sparql-results+json",
    })
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
                return data.get("results", {}).get("bindings", [])
        except Exception as e:
            logging.warning(f"  SPARQL attempt {attempt}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return []

def get_all_celex(resource_type_uri: str, year_start=1995, year_end=2026) -> list[dict]:
    """Hämta CELEX-nummer för dokument som FAKTISKT finns på svenska.
    Sverige gick med i EU 1995 — äldre dokument saknar i regel svensk version."""
    logging.info(f"  Hämtar CELEX-nummer för {resource_type_uri.split('/')[-1]} (SV, {year_start}–{year_end})...")
    results = []
    for year in range(year_start, year_end + 1):
        query = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?work ?celex ?date ?title
WHERE {{
  ?work cdm:work_has_resource-type <{resource_type_uri}> .
  ?work cdm:work_date_document ?date .
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language
        <http://publications.europa.eu/resource/authority/language/SWE> .
  ?expr cdm:expression_title ?title .
  FILTER(YEAR(?date) = {year})
}}
LIMIT 2000
"""
        bindings = sparql_query(query)
        for b in bindings:
            results.append({
                "celex":  b.get("celex", {}).get("value", ""),
                "date":   b.get("date",  {}).get("value", "")[:10],
                "title":  b.get("title", {}).get("value", ""),
                "work":   b.get("work",  {}).get("value", ""),
                "year":   year,
            })
        if bindings:
            logging.info(f"    {year}: {len(bindings)} dokument")
        time.sleep(SLEEP_SPARQL)
    return results

def is_portal_page(content: str) -> bool:
    """Returnerar True om svaret är EUR-Lex portalsida (ej svensk lagtext)."""
    # Portal page has lang="en" in <html> tag and no-js class
    head = content[:2000]
    if 'class="no-js"' in head or "class='no-js'" in head:
        return True
    # Generic English portal pages have <html lang="en"
    if '<html lang="en"' in head or "<html lang='en'" in head:
        return True
    return False

def is_swedish_content(content: str) -> bool:
    """Returnerar True om innehållet verkar vara lagtext på svenska."""
    head = content[:3000]
    # Explicit Swedish lang attribute
    if 'lang="SV"' in head or "lang='SV'" in head:
        return True
    if 'lang="sv"' in head or "lang='sv'" in head:
        return True
    # Old XHTML format from EUR-Lex (CONVEX converter) – always Swedish when fetched via SV URL
    if "CONVEX" in head and "<?xml" in head:
        return True
    return False

def fetch_text(celex: str, work_uri: str = "") -> str | None:
    """Hämta HTML-text för ett CELEX-nummer.
    Försöker EUR-Lex HTML-URL direkt."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LAIW-Dataset/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sv,en;q=0.5",
    }
    url = f"{EURLEX_BASE}/legal-content/SV/TXT/HTML/?uri=CELEX:{celex}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                if r.status == 200:
                    content = r.read().decode("utf-8", errors="replace")
                    if is_portal_page(content):
                        # EUR-Lex returned English portal = no Swedish version exists
                        return None
                    if is_swedish_content(content) and len(content) > 500:
                        return content
                    # Short or unrecognised response – retry
                    logging.warning(f"  {celex}: unrecognised response ({len(content)}b), attempt {attempt}")
        except urllib.error.HTTPError as e:
            if e.code in (404, 406):
                return None  # Explicit "not found" – skip immediately
            logging.warning(f"  {celex}: HTTP {e.code}, attempt {attempt}")
        except Exception as e:
            logging.warning(f"  {celex}: {type(e).__name__}: {e}, attempt {attempt}")
        if attempt < MAX_RETRIES:
            wait = min(10 * (2 ** (attempt - 1)), 60)  # 10, 20, 40, 60 max
            logging.info(f"  Väntar {wait}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)

    return None

def download_all(doc_types=("reg", "dir"), skip_sparql=False):
    setup_logging()
    logging.info("=" * 60)
    logging.info("  EUR-LEX NEDLADDNING")
    logging.info(f"  Dokumenttyper: {', '.join(doc_types)}")
    logging.info(f"  Skip SPARQL: {skip_sparql}")
    logging.info("=" * 60)

    index_file = OUT_DIR / "eu_legislation_index.json"
    all_docs = []

    # Steg 1: Bygg index via SPARQL (eller ladda befintligt)
    if skip_sparql and index_file.exists():
        logging.info(f"  Laddar befintligt index: {index_file}")
        with open(index_file, encoding="utf-8") as f:
            all_docs = json.load(f)
        logging.info(f"  Laddat {len(all_docs):,} dokument från index")
    else:
        for dt in doc_types:
            uri = RESOURCE_TYPES.get(dt)
            if not uri:
                continue
            docs = get_all_celex(uri)
            for d in docs:
                d["type"] = dt
            all_docs.extend(docs)
            logging.info(f"  {dt.upper()}: {len(docs):,} dokument hittade")

        # Deduplicera på CELEX
        seen = set()
        unique = []
        for d in all_docs:
            if d["celex"] and d["celex"] not in seen:
                seen.add(d["celex"])
                unique.append(d)
        all_docs = unique
        logging.info(f"\n  Totalt unika dokument: {len(all_docs):,}")

        # Spara index
        json.dump(all_docs, open(index_file, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        logging.info(f"  Index sparat: {index_file}")

    # Steg 2: Hämta fulltext
    logging.info(f"\n  Hämtar fulltext för {len(all_docs):,} dokument...")
    ok = skip = fail = 0
    consecutive_fails = 0
    for i, doc in enumerate(all_docs, 1):
        celex = doc["celex"]
        if not celex:
            continue
        safe = celex.replace(":", "_").replace("/", "_")
        out_path = TEXT_DIR / f"{safe}.html"
        if out_path.exists() and out_path.stat().st_size > 500:
            # Quick sanity: make sure it's not a saved portal page
            try:
                head = out_path.read_text(errors="replace")[:2000]
                if not is_portal_page(head):
                    skip += 1
                    consecutive_fails = 0
                    continue
                else:
                    out_path.unlink()  # Remove incorrectly saved portal page
            except Exception:
                skip += 1
                continue

        work_uri = doc.get("work", "")
        text = fetch_text(celex, work_uri)
        if text:
            out_path.write_text(text, encoding="utf-8")
            ok += 1
            consecutive_fails = 0
        else:
            fail += 1
            consecutive_fails += 1
            # If many consecutive failures, slow down significantly
            if consecutive_fails >= 10:
                logging.warning(f"  {consecutive_fails} failures i rad – pausar 60s")
                time.sleep(60)
                consecutive_fails = 0

        if i % 100 == 0:
            pct = (ok + skip) / max(i, 1) * 100
            logging.info(
                f"  [{i}/{len(all_docs)}] OK:{ok} Skip:{skip} Fail:{fail} ({pct:.0f}% framgång)"
            )
        time.sleep(SLEEP_TEXT)

    total_mb = sum(p.stat().st_size for p in TEXT_DIR.glob("*.html")) / 1_048_576
    logging.info(f"\n  KLART: {ok:,} hämtade, {skip:,} hoppade, {fail:,} fel")
    logging.info(f"  Totalt: {total_mb:.0f} MB i {TEXT_DIR}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["reg", "dir", "both"], default="both")
    parser.add_argument("--skip-sparql", action="store_true",
                        help="Hoppa SPARQL-steget och använd befintligt index")
    args = parser.parse_args()
    types = ("reg", "dir") if args.type == "both" else (args.type,)
    download_all(types, skip_sparql=args.skip_sparql)
