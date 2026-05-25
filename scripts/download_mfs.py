#!/usr/bin/env python3
"""
Hämtar myndighetsföreskrifter (MFS) från två källor:

  Källa 1 — lagen.nu (async, ingen JS):
    afs, fffs, nfs, sjvfs, kvfs, pmfs, skvfs, eifs, msb-fs
    Sonderar 1985–2026, nummer 1–100 per år

  Källa 2 — Playwright (JS-renderade myndighetssidor):
    Livsmedelsverket        (LIVSFS)
    Boverket                (BFS)
    Socialstyrelsen         (SOSFS + HSLF-FS)
    Läkemedelsverket        (LVFS)
    Transportstyrelsen      (TSFS)
    Strålsäkerhetsmyndigh.  (SSMFS)
    Post och telestyrelsen  (PTSFS)

Output: ~/LAIW/data/raw/mfs/{prefix}-{year}-{nr}.html

Kör: python3 scripts/download_mfs.py [--source lagennu|playwright|all]
"""
import asyncio, aiohttp, json, re, time, logging, argparse, sys
from pathlib import Path
from datetime import datetime

BASE    = Path.home() / "LAIW"
OUT_DIR = BASE / "data" / "raw" / "mfs"
LOG_DIR = BASE / "logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SLEEP_LAGENNU   = 0.25
SLEEP_PLAYWRIGHT = 1.5
WORKERS_LAGENNU  = 6

MFS_PREFIXES = ["afs", "fffs", "nfs", "sjvfs", "kvfs", "pmfs", "skvfs", "eifs", "msb-fs"]
YEAR_START   = 1985
YEAR_END     = 2026
MAX_NR       = 100


def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lf = LOG_DIR / f"mfs_{ts}.log"
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf), logging.StreamHandler(sys.stdout)])
    logging.info(f"Log: {lf}")


def mfs_filename(prefix: str, year: int, nr: int) -> Path:
    return OUT_DIR / f"{prefix}-{year}-{nr}.html"


# ── Källa 1: lagen.nu ─────────────────────────────────────────────────────────
async def probe_and_download_lagennu(workers: int):
    sem = asyncio.Semaphore(workers)
    hdrs = {"User-Agent": "LAIW-Dataset/1.0 (legal AI research)"}
    total_ok = 0

    async def fetch_one(session, prefix, year, nr):
        fname = mfs_filename(prefix, year, nr)
        if fname.exists():
            return True
        url = f"https://lagen.nu/{prefix}/{year}:{nr}"
        async with sem:
            await asyncio.sleep(SLEEP_LAGENNU)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        html = await r.text(encoding="utf-8", errors="replace")
                        if len(html) > 500:
                            fname.write_text(html, encoding="utf-8")
                            return True
                return False
            except Exception:
                return False

    connector = aiohttp.TCPConnector(limit=workers)
    async with aiohttp.ClientSession(connector=connector, headers=hdrs) as session:
        for prefix in MFS_PREFIXES:
            tasks = [
                fetch_one(session, prefix, year, nr)
                for year in range(YEAR_START, YEAR_END + 1)
                for nr in range(1, MAX_NR + 1)
            ]
            results = await asyncio.gather(*tasks)
            ok = sum(results)
            total_ok += ok
            logging.info(f"  {prefix}: {ok} föreskrifter hämtade")

    logging.info(f"  lagen.nu MFS totalt: {total_ok} föreskrifter")


# ── Källa 2: Playwright ───────────────────────────────────────────────────────
# Myndigheter med direkta URL-mönster (ingen Playwright behövs)
DIRECT_URL_SOURCES = {
    "ssmfs": "https://www.ssm.se/regler-och-tillstand/foreskrifter/ssmfs-{yr}-{nr}/",
    "ptsfs": "https://www.pts.se/sv/reglering/regler/ptsfs-{yr}-{nr}/",
}

PLAYWRIGHT_SOURCES = {
    "livsfs": {
        "name": "Livsmedelsverket",
        "list_url": "https://www.livsmedelsverket.se/foretagande-regler-kontroll/lagstiftning/foreskrifter",
        "list_selector": "a[href*='livsfs'], a[href*='LIVSFS']",
        "base_url": "https://www.livsmedelsverket.se",
    },
    "bfs": {
        "name": "Boverket",
        "list_url": "https://www.boverket.se/sv/lag--ratt/foreskrifter/",
        "list_selector": "a[href*='bfs'], a[href*='BFS']",
        "base_url": "https://www.boverket.se",
    },
    "sosfs": {
        "name": "Socialstyrelsen",
        "list_url": "https://www.socialstyrelsen.se/regler-och-riktlinjer/foreskrifter-och-allmanna-rad/",
        "list_selector": "a[href*='sosfs'], a[href*='SOSFS'], a[href*='hslf']",
        "base_url": "https://www.socialstyrelsen.se",
    },
    "lvfs": {
        "name": "Läkemedelsverket",
        "list_url": "https://www.lakemedelsverket.se/sv/regler-och-lagar/lakemedelsverkets-foreskrifter/",
        "list_selector": "a[href*='lvfs'], a[href*='LVFS']",
        "base_url": "https://www.lakemedelsverket.se",
    },
    "tsfs": {
        "name": "Transportstyrelsen",
        "list_url": "https://www.transportstyrelsen.se/sv/regler/Regler-for-vag/Foreskrifter/",
        "list_selector": "a[href*='tsfs'], a[href*='TSFS']",
        "base_url": "https://www.transportstyrelsen.se",
    },
    "ssmfs": {
        "name": "Strålsäkerhetsmyndigheten",
        "list_url": "https://www.ssm.se/regler-och-tillstand/foreskrifter/",
        "list_selector": "a[href*='ssmfs'], a[href*='SSMFS']",
        "base_url": "https://www.ssm.se",
    },
    "ptsfs": {
        "name": "Post och telestyrelsen",
        "list_url": "https://www.pts.se/sv/reglering/regler/",
        "list_selector": "a[href*='ptsfs'], a[href*='PTSFS']",
        "base_url": "https://www.pts.se",
    },
}


def run_playwright_source(prefix: str, cfg: dict) -> int:
    from playwright.sync_api import sync_playwright

    ok = 0
    logging.info(f"  Playwright: {cfg['name']} ({prefix})")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent="LAIW-Dataset/1.0 (legal AI research)")
        page = ctx.new_page()

        try:
            page.goto(cfg["list_url"], wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Samla alla föreskriftslänkar
            links = page.eval_on_selector_all(
                "a[href]",
                """els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"""
            )

            # Filtrera på relevanta länktexter (föreskrift-mönster)
            pattern = re.compile(
                r'(' + re.escape(prefix) + r'|' + prefix.upper() + r'|hslf-fs|HSLF-FS)',
                re.IGNORECASE
            )
            relevant = []
            seen_urls = set()
            for lnk in links:
                href = lnk.get("href", "")
                text = lnk.get("text", "")
                if (pattern.search(href) or pattern.search(text)) and href not in seen_urls:
                    if href.startswith("http"):
                        relevant.append(href)
                        seen_urls.add(href)

            logging.info(f"    {len(relevant)} länkar hittade")

            for url in relevant:
                # Generera ett filnamn från URL:en
                slug = re.sub(r'[^\w\-]', '_', url.split('//')[1] if '//' in url else url)[:80]
                fname = OUT_DIR / f"{prefix}_{slug}.html"
                if fname.exists():
                    ok += 1
                    continue
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(SLEEP_PLAYWRIGHT)
                    html = page.content()
                    if len(html) > 1000:
                        fname.write_text(html, encoding="utf-8")
                        ok += 1
                except Exception as e:
                    logging.warning(f"    Fel: {url}: {e}")

        except Exception as e:
            logging.warning(f"  Fel för {cfg['name']}: {e}")
        finally:
            browser.close()

    logging.info(f"  {cfg['name']}: {ok} sidor sparade")
    return ok


def run_playwright_all():
    total = 0
    for prefix, cfg in PLAYWRIGHT_SOURCES.items():
        total += run_playwright_source(prefix, cfg)
    logging.info(f"  Playwright totalt: {total} sidor")


# ── Main ──────────────────────────────────────────────────────────────────────
async def probe_and_download_direct(workers: int):
    """Hämtar från myndigheter med kända URL-mönster (ingen Playwright)."""
    sem = asyncio.Semaphore(workers)
    hdrs = {"User-Agent": "LAIW-Dataset/1.0 (legal AI research)"}

    async def fetch_one(session, pfx, yr, nr, tmpl):
        fname = mfs_filename(pfx, yr, nr)
        if fname.exists():
            return True
        url = tmpl.format(yr=yr, nr=nr)
        async with sem:
            await asyncio.sleep(0.4)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        html = await r.text(encoding="utf-8", errors="replace")
                        if len(html) > 1000:
                            fname.write_text(html, encoding="utf-8")
                            return True
                return False
            except Exception:
                return False

    connector = aiohttp.TCPConnector(limit=workers)
    async with aiohttp.ClientSession(connector=connector, headers=hdrs) as session:
        for pfx, tmpl in DIRECT_URL_SOURCES.items():
            tasks = [
                fetch_one(session, pfx, yr, nr, tmpl)
                for yr in range(1995, YEAR_END + 1)
                for nr in range(1, 60)
            ]
            ok = sum(await asyncio.gather(*tasks))
            logging.info(f"  {pfx}: {ok} föreskrifter hämtade")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="all", choices=["all", "lagennu", "direct", "playwright"])
    parser.add_argument("--workers", type=int, default=WORKERS_LAGENNU)
    args = parser.parse_args()
    setup_logging()

    if args.source in ("all", "lagennu"):
        logging.info(f"Sonderar + laddar ner lagen.nu MFS ({', '.join(MFS_PREFIXES)})...")
        asyncio.run(probe_and_download_lagennu(args.workers))

    if args.source in ("all", "direct"):
        logging.info(f"Hämtar direkt-URL-källor (ssmfs, ptsfs)...")
        asyncio.run(probe_and_download_direct(args.workers))

    if args.source in ("all", "playwright"):
        logging.info("Kör Playwright-skrapning av JS-renderade myndighetssidor...")
        run_playwright_all()

    # Sammanfattning
    files = list(OUT_DIR.glob("*.html"))
    mb = sum(f.stat().st_size for f in files) / 1e6
    logging.info(f"\nTotalt: {len(files):,} MFS-filer, {mb:.0f} MB")

    index = sorted(f.stem for f in files)
    json.dump(index, open(OUT_DIR / "mfs_index.json", "w"), indent=2, ensure_ascii=False)
    logging.info(f"Index sparat: mfs_index.json")


if __name__ == "__main__":
    main()
