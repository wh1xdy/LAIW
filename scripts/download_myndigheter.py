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

import json, time, re, sys, logging, argparse
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import urllib.request, urllib.error, urllib.parse

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
            with urllib.request.urlopen(req, timeout=30) as r:
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
    list_url = f"{base_url}/beslut/?page="
    decisions = dict(existing)
    page = 1

    while True:
        url = list_url + str(page)
        html = fetch(url)
        if not html:
            break
        soup = BeautifulSoup(html, "lxml")

        # Hitta beslutslänkar
        links = soup.find_all("a", href=re.compile(r"/beslut/\d+"))
        if not links:
            logging.info(f"  Inga fler beslut på sida {page}")
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
            title_text = title.get_text(strip=True) if title else ""

            main = detail_soup.find("main") or detail_soup.find("article") or detail_soup.find("div", class_=re.compile("content|main|article"))
            body_text = text_from_html(str(main)) if main else ""

            decisions[full_url] = {
                "url": full_url,
                "title": title_text,
                "text": body_text,
                "source": "jk",
            }
            new_on_page += 1
            time.sleep(SLEEP)

        logging.info(f"  Sida {page}: +{new_on_page} beslut | Totalt: {len(decisions):,}")

        # Kolla om det finns nästa sida
        next_link = soup.find("a", href=re.compile(rf"page={page+1}"))
        if not next_link and new_on_page == 0:
            break
        page += 1
        time.sleep(SLEEP)

    result = list(decisions.values())
    json.dump(result, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size_mb = out_file.stat().st_size / 1e6
    logging.info(f"\n  JK KLART: {len(result):,} beslut ({size_mb:.1f} MB)")
    return len(result)

# ─── DO — Diskrimineringsombudsmannen ─────────────────────────────────────────
def download_do():
    """DO publicerar ärenden på do.se"""
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
    # DO har sökfunktion för ärenden och beslut
    search_url = f"{base_url}/om-do/do-i-medierna/pressmeddelanden-och-nyheter/"
    decisions = dict(existing)
    page = 0

    while True:
        url = search_url + (f"?page={page}" if page > 0 else "")
        html = fetch(url)
        if not html:
            break
        soup = BeautifulSoup(html, "lxml")

        articles = soup.find_all("article") or soup.find_all("div", class_=re.compile("news|article|item|post"))
        if not articles:
            links = soup.find_all("a", href=re.compile(r"/om-do/|/for-den-som-upplever/|/om-diskriminering/"))
            if not links:
                break
            articles = links

        new_on_page = 0
        for art in articles[:50]:
            link = art if art.name == "a" else art.find("a", href=True)
            if not link:
                continue
            href = link.get("href", "")
            full_url = base_url + href if href.startswith("/") else href
            if not full_url.startswith(base_url) or full_url in decisions:
                continue

            detail_html = fetch(full_url)
            if not detail_html:
                continue

            detail_soup = BeautifulSoup(detail_html, "lxml")
            title = detail_soup.find("h1")
            main = detail_soup.find("main") or detail_soup.find("article")
            decisions[full_url] = {
                "url": full_url,
                "title": title.get_text(strip=True) if title else "",
                "text": text_from_html(str(main)) if main else "",
                "source": "do",
            }
            new_on_page += 1
            time.sleep(SLEEP)

        logging.info(f"  Sida {page}: +{new_on_page} ärenden | Totalt: {len(decisions):,}")
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
    """IMY (fd Datainspektionen) publicerar GDPR-beslut på imy.se"""
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
    list_url = f"{base_url}/tillsyn/tillsynsbeslut/"
    decisions = dict(existing)
    page = 0

    while True:
        url = list_url + (f"?page={page}" if page > 0 else "")
        html = fetch(url)
        if not html:
            break
        soup = BeautifulSoup(html, "lxml")

        links = soup.find_all("a", href=re.compile(r"/tillsyn/tillsynsbeslut/\d+"))
        if not links:
            links = soup.find_all("a", href=re.compile(r"beslut|tillsyn"))
        if not links:
            logging.info(f"  Inga fler beslut på sida {page}")
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
            main = detail_soup.find("main") or detail_soup.find("article") or detail_soup.find("div", class_=re.compile("content|main"))
            decisions[full_url] = {
                "url": full_url,
                "title": title.get_text(strip=True) if title else "",
                "text": text_from_html(str(main)) if main else "",
                "source": "imy",
            }
            new_on_page += 1
            time.sleep(SLEEP)

        logging.info(f"  Sida {page}: +{new_on_page} beslut | Totalt: {len(decisions):,}")
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
