#!/usr/bin/env python3
"""
Myndighets-beslut Downloader — JO, JK, DO, DI
Hämtar beslut och yttranden från svenska tillsynsmyndigheter.

Output:
  ~/LAIW/data/raw/myndigheter/jo_decisions.json
  ~/LAIW/data/raw/myndigheter/jk_decisions.json
  ~/LAIW/data/raw/myndigheter/do_decisions.json
  ~/LAIW/data/raw/myndigheter/di_decisions.json

Kör: python3 download_myndigheter.py [--source jo|jk|do|di|all]
"""

import json, time, re, sys, logging, argparse, ssl
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import urllib.request, urllib.error, urllib.parse

# Bypass SSL verification for Swedish government sites with cert issues
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

BASE_DIR = Path.home() / "LAIW"
OUT_DIR  = BASE_DIR / "data" / "raw" / "myndigheter"
LOG_DIR  = BASE_DIR / "logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SLEEP    = 1.5
MAX_RETRY = 4

def setup_logging(source: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lf = LOG_DIR / f"{source}_{ts}.log"
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf), logging.StreamHandler(sys.stdout)])
    logging.info(f"Log: {lf}")

def fetch(url: str, headers: dict = None) -> str | None:
    h = {"User-Agent": "LAIW-Dataset/1.0 (Swedish Legal AI Research)"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    for attempt in range(1, MAX_RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            logging.warning(f"  HTTP {e.code} {url} (attempt {attempt})")
        except Exception as e:
            logging.warning(f"  {type(e).__name__}: {e} (attempt {attempt})")
        if attempt < MAX_RETRY:
            time.sleep(5 * attempt)
    return None

def text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()

# ─── JO — Justitieombudsmannen ────────────────────────────────────────────────
def download_jo():
    """JO publicerar beslut via WordPress sitemaps på www.jo.se/besluten/"""
    setup_logging("jo")
    logging.info("=" * 60)
    logging.info("  JO - Justitieombudsmannen")
    logging.info("=" * 60)

    out_file = OUT_DIR / "jo_decisions.json"
    existing = {}
    if out_file.exists():
        for d in json.loads(out_file.read_text()):
            existing[d.get("url", "")] = d
        logging.info(f"  Laddat {len(existing):,} befintliga beslut")

    base_url = "https://www.jo.se"

    # Steg 1: Samla alla beslut-URLs från resolve-sitemaps
    decision_urls = set()
    for i in range(1, 25):
        sitemap_url = f"{base_url}/resolve-sitemap{i}.xml"
        xml = fetch(sitemap_url)
        if not xml:
            break
        urls = re.findall(r'<loc>(https://www\.jo\.se/besluten/[^<]+)</loc>', xml)
        # Filtrera bort engelska versioner och index
        sv_urls = [u for u in urls if not u.rstrip("/").endswith("/besluten") and "/en/" not in u]
        decision_urls.update(sv_urls)
        logging.info(f"  Sitemap {i}: {len(sv_urls)} beslut-URLs | Totalt: {len(decision_urls):,}")
        time.sleep(0.3)

    logging.info(f"\n  Totalt {len(decision_urls):,} unika beslut-URLs")

    # Steg 2: Hämta fulltext för varje beslut
    new_count = 0
    for i, url in enumerate(sorted(decision_urls), 1):
        if url in existing:
            continue

        html = fetch(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        title = soup.find("h1")
        # JO-beslut text finns i article eller main
        main = (soup.find("article") or soup.find("main") or
                soup.find("div", class_=re.compile(r"entry-content|post-content|content")))
        body_text = text_from_html(str(main)) if main else ""

        # Extrahera diarienummer om det finns
        dnum = ""
        dnum_match = re.search(r'\b(\d{3,5}-\d{4})\b', body_text)
        if dnum_match:
            dnum = dnum_match.group(1)

        existing[url] = {
            "url": url,
            "title": title.get_text(strip=True) if title else "",
            "text": body_text,
            "diarienummer": dnum,
            "source": "jo",
        }
        new_count += 1

        if i % 100 == 0:
            logging.info(f"  [{i}/{len(decision_urls)}] +{new_count} nya | Totalt: {len(existing):,}")
            json.dump(list(existing.values()), open(out_file, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))

        time.sleep(SLEEP)

    result = list(existing.values())
    json.dump(result, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size_mb = out_file.stat().st_size / 1e6
    logging.info(f"\n  JO KLART: {len(result):,} beslut ({size_mb:.1f} MB)")
    return len(result)

# ─── JK — Justitiekanslern ────────────────────────────────────────────────────
def download_jk():
    """JK publicerar beslut på jk.se — scrapa listpaginator"""
    setup_logging("jk")
    logging.info("=" * 60)
    logging.info("  JK - Justitiekanslern")
    logging.info("=" * 60)

    out_file = OUT_DIR / "jk_decisions.json"
    existing = {}
    if out_file.exists():
        for d in json.loads(out_file.read_text()):
            existing[d.get("url", "")] = d
        logging.info(f"  Laddat {len(existing):,} befintliga beslut")

    base_url = "https://www.jk.se"
    decisions = dict(existing)

    # JK-beslut URL-mönster: /beslut-och-yttranden/{år}/{månad}/{diarienr}/
    # Hämta via kategori-sidor + iterera år/månader
    categories = [
        "/beslut-och-yttranden/?Skadest%C3%A5nd%C3%A4renden",
        "/beslut-och-yttranden/?Ers%C3%A4ttning%20vid%20frihetsinskr%C3%A4nkning",
        "/beslut-och-yttranden/?Tillsyns%C3%A4renden",
        "/beslut-och-yttranden/?Tryck-%20och%20yttrandefrihets%C3%A4renden",
        "/beslut-och-yttranden/?Remissyttranden",
        "/beslut-och-yttranden/",
    ]

    decision_pat = re.compile(r"^/beslut-och-yttranden/\d{4}/")

    all_decision_hrefs = set()
    for cat_path in categories:
        cat_url = base_url + cat_path
        logging.info(f"  Kategori: {cat_path}")
        html = fetch(cat_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("a", href=decision_pat):
            href = link.get("href", "")
            if href and "?" not in href:
                all_decision_hrefs.add(href)
        time.sleep(0.5)

    logging.info(f"  Hittade {len(all_decision_hrefs):,} beslut-URLs från kategorisidor")

    new_count = 0
    for href in sorted(all_decision_hrefs):
        full_url = base_url + href if href.startswith("/") else href
        if full_url in decisions:
            continue

        detail_html = fetch(full_url)
        if not detail_html:
            continue

        detail_soup = BeautifulSoup(detail_html, "lxml")
        title = detail_soup.find("h1")
        main = (detail_soup.find("main") or detail_soup.find("article") or
                detail_soup.find("div", class_=re.compile(r"content|main|article")))
        body_text = text_from_html(str(main)) if main else ""
        if len(body_text) < 100:
            continue

        decisions[full_url] = {
            "url": full_url,
            "title": title.get_text(strip=True) if title else "",
            "text": body_text,
            "source": "jk",
        }
        new_count += 1
        time.sleep(SLEEP)

    logging.info(f"  +{new_count} nya JK-beslut")

    result = list(decisions.values())
    json.dump(result, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size_mb = out_file.stat().st_size / 1e6
    logging.info(f"\n  JK KLART: {len(result):,} beslut ({size_mb:.1f} MB)")
    return len(result)

# ─── DO — Diskrimineringsombudsmannen ─────────────────────────────────────────
def download_do():
    """DO publicerar beslut på do.se/rattsfall-beslut-lagar-stodmaterial/"""
    setup_logging("do")
    logging.info("=" * 60)
    logging.info("  DO - Diskrimineringsombudsmannen")
    logging.info("=" * 60)

    out_file = OUT_DIR / "do_decisions.json"
    existing = {}
    if out_file.exists():
        for d in json.loads(out_file.read_text()):
            existing[d.get("url", "")] = d
        logging.info(f"  Laddat {len(existing):,} befintliga ärenden")

    base_url = "https://www.do.se"
    decisions = dict(existing)

    # DO har beslut under /rattsfall-beslut-lagar-stodmaterial/
    list_pages = [
        f"{base_url}/rattsfall-beslut-lagar-stodmaterial/tvister-domar-tillsynsbeslut/",
        f"{base_url}/rattsfall-beslut-lagar-stodmaterial/",
    ]

    for list_url in list_pages:
        logging.info(f"  Listar: {list_url}")
        page = 0
        while True:
            url = list_url + (f"?page={page}" if page > 0 else "")
            html = fetch(url)
            if not html:
                break
            soup = BeautifulSoup(html, "lxml")

            # DO uses article links
            links = soup.find_all("a", href=re.compile(
                r"/rattsfall-beslut-lagar-stodmaterial/.+|/tillsyn/.+|/yrk.+"
            ))
            if not links:
                break

            new_on_page = 0
            for link in links:
                href = link.get("href", "")
                full_url = base_url + href if href.startswith("/") else href
                if full_url in decisions or full_url in list_pages:
                    continue

                detail_html = fetch(full_url)
                if not detail_html:
                    continue

                detail_soup = BeautifulSoup(detail_html, "lxml")
                title = detail_soup.find("h1")
                main = detail_soup.find("main") or detail_soup.find("article")
                body = text_from_html(str(main)) if main else ""
                if len(body) < 100:
                    continue

                decisions[full_url] = {
                    "url": full_url,
                    "title": title.get_text(strip=True) if title else "",
                    "text": body,
                    "source": "do",
                }
                new_on_page += 1
                time.sleep(SLEEP)

            logging.info(f"  Sida {page}: +{new_on_page} | Totalt: {len(decisions):,}")
            if new_on_page == 0:
                break
            page += 1
            time.sleep(SLEEP)

    result = list(decisions.values())
    json.dump(result, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size_mb = out_file.stat().st_size / 1e6
    logging.info(f"\n  DO KLART: {len(result):,} ärenden ({size_mb:.1f} MB)")
    return len(result)

# ─── DI — Datainspektionen / IMY ──────────────────────────────────────────────
def download_di():
    """IMY publicerar GDPR-tillsynsbeslut på imy.se — hämta via nyheter/tillsyn-sidor"""
    setup_logging("di")
    logging.info("=" * 60)
    logging.info("  IMY/DI - Integritetsskyddsmyndigheten")
    logging.info("=" * 60)

    out_file = OUT_DIR / "di_decisions.json"
    existing = {}
    if out_file.exists():
        for d in json.loads(out_file.read_text()):
            existing[d.get("url", "")] = d
        logging.info(f"  Laddat {len(existing):,} befintliga beslut")

    base_url = "https://www.imy.se"
    decisions = dict(existing)

    # IMY tillsynsbeslut är listade under /nyheter/ och /tillsyn/
    list_urls = [
        f"{base_url}/nyheter/",
        f"{base_url}/tillsyn/",
        f"{base_url}/nyheter/?page=",  # paginerad
    ]

    for base_list in [f"{base_url}/nyheter/", f"{base_url}/tillsyn/"]:
        logging.info(f"  Listar: {base_list}")
        page = 0
        while page < 50:
            url = base_list + (f"?page={page}" if page > 0 else "")
            html = fetch(url)
            if not html:
                break
            soup = BeautifulSoup(html, "lxml")

            # IMY article/news links
            links = soup.find_all("a", href=re.compile(
                r"/nyheter/tillsyn|/tillsyn/|/nyheter/\d"
            ))
            if not links:
                break

            new_on_page = 0
            for link in links:
                href = link.get("href", "")
                full_url = base_url + href if href.startswith("/") else href
                if full_url in decisions:
                    continue

                detail_html = fetch(full_url)
                if not detail_html:
                    continue

                detail_soup = BeautifulSoup(detail_html, "lxml")
                title = detail_soup.find("h1")
                main = (detail_soup.find("main") or detail_soup.find("article") or
                        detail_soup.find("div", class_=re.compile(r"content|article|entry")))
                body = text_from_html(str(main)) if main else ""
                if len(body) < 100:
                    continue

                decisions[full_url] = {
                    "url": full_url,
                    "title": title.get_text(strip=True) if title else "",
                    "text": body,
                    "source": "imy",
                }
                new_on_page += 1
                time.sleep(SLEEP)

            logging.info(f"  Sida {page}: +{new_on_page} | Totalt: {len(decisions):,}")
            if new_on_page == 0:
                break
            page += 1
            time.sleep(SLEEP)

    result = list(decisions.values())
    json.dump(result, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size_mb = out_file.stat().st_size / 1e6
    logging.info(f"\n  IMY/DI KLART: {len(result):,} beslut ({size_mb:.1f} MB)")
    return len(result)

SOURCES = {"jo": download_jo, "jk": download_jk, "do": download_do, "di": download_di}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ladda ner myndighetsbeslut")
    parser.add_argument("--source", choices=list(SOURCES.keys()) + ["all"], default="all")
    args = parser.parse_args()

    sources = list(SOURCES.keys()) if args.source == "all" else [args.source]
    for src in sources:
        try:
            count = SOURCES[src]()
            print(f"\n✅ {src.upper()} KLART: {count:,} beslut\n")
        except Exception as e:
            logging.error(f"  {src} misslyckades: {e}")
