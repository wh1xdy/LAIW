#!/usr/bin/env python3
"""
EUR-Lex Async Text Fetcher
Hämtar HTML-fulltexten för varje CELEX-nummer i eu_legislation_index.json.
Använder asyncio + aiohttp för parallella nedladdningar.

Kör: python3 fetch_eurlex_texts.py [--workers 4]

Output: ~/LAIW/data/raw/eu/texts/{CELEX}.html
"""

import asyncio
import aiohttp
import json
import sys
import logging
import argparse
import time
from pathlib import Path
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR  = Path.home() / "LAIW"
OUT_DIR   = BASE_DIR / "data" / "raw" / "eu"
TEXT_DIR  = OUT_DIR / "texts"
INDEX_FILE = OUT_DIR / "eu_legislation_index.json"
LOG_DIR   = BASE_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)
TEXT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_WORKERS = 1       # Single worker to avoid EUR-Lex rate limits
RATE_SLEEP      = 2.0     # 2s between requests – polite crawl
TIMEOUT_SEC     = 25      # Short timeout – if no reply in 25s, skip
MAX_RETRIES     = 2       # Only 2 retries – most failures are permanent

EURLEX_BASE = "https://eur-lex.europa.eu"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LAIW-Dataset/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv,en;q=0.5",
}

# ─── LOGGING ──────────────────────────────────────────────────────────────────
def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"eurlex_texts_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info(f"Log: {log_file}")
    return log_file


# ─── CONTENT VALIDATION ───────────────────────────────────────────────────────
def is_portal_page(content: str) -> bool:
    """True om svaret är EUR-Lex portalsida, inte lagtext."""
    head = content[:2000]
    return ('class="no-js"' in head or "class='no-js'" in head
            or '<html lang="en"' in head or "<html lang='en'" in head)

def is_valid_swedish(content: str) -> bool:
    """True om innehållet är lagtext på svenska."""
    head = content[:3000]
    if 'lang="SV"' in head or "lang='SV'" in head: return True
    if 'lang="sv"' in head or "lang='sv'" in head: return True
    if "CONVEX" in head and "<?xml" in head: return True
    return False


# ─── ASYNC FETCHER ────────────────────────────────────────────────────────────
async def fetch_one(session: aiohttp.ClientSession, doc: dict,
                    semaphore: asyncio.Semaphore) -> tuple[str, str]:
    """Hämtar ett dokument. Returnerar (celex, status)."""
    celex    = doc["celex"]
    safe     = celex.replace(":", "_").replace("/", "_")
    out_path = TEXT_DIR / f"{safe}.html"

    # Skip if already downloaded and valid
    if out_path.exists() and out_path.stat().st_size > 500:
        try:
            head = out_path.read_text(errors="replace")[:2000]
            if not is_portal_page(head):
                return celex, "skip"
            else:
                out_path.unlink()  # Remove previously saved portal page
        except Exception:
            return celex, "skip"

    url = f"{EURLEX_BASE}/legal-content/SV/TXT/HTML/?uri=CELEX:{celex}"

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
                async with session.get(url, timeout=timeout) as r:
                    if r.status == 404:
                        return celex, "404"
                    if r.status != 200:
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(5)
                            continue
                        return celex, f"http{r.status}"

                    content = await r.text(encoding="utf-8", errors="replace")

                    if is_portal_page(content):
                        return celex, "no_sv"  # EUR-Lex says: no Swedish version

                    if is_valid_swedish(content) and len(content) > 500:
                        out_path.write_text(content, encoding="utf-8")
                        return celex, "ok"

                    # Short / unrecognised – not worth retrying
                    logging.warning(f"  {celex}: unrecognised response {len(content)}b, head={repr(content[:80])}")
                    return celex, "odd"

            except asyncio.TimeoutError:
                logging.warning(f"  {celex}: Timeout attempt {attempt}/{MAX_RETRIES}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RATE_SLEEP * 3)
                    continue
                return celex, "timeout"
            except Exception as e:
                err_type = type(e).__name__
                logging.warning(f"  {celex}: {err_type}: {str(e)[:120]}, attempt {attempt}/{MAX_RETRIES}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RATE_SLEEP * 3)
                    continue
                return celex, f"err:{err_type}"

        await asyncio.sleep(RATE_SLEEP)
        return celex, "fail"


async def run(workers: int):
    setup_logging()
    logging.info("=" * 60)
    logging.info("  EUR-LEX TEXT FETCHER (async)")
    logging.info(f"  Workers: {workers}  Timeout: {TIMEOUT_SEC}s")
    logging.info("=" * 60)

    if not INDEX_FILE.exists():
        logging.error(f"Index saknas: {INDEX_FILE}")
        sys.exit(1)

    docs = json.load(open(INDEX_FILE, encoding="utf-8"))
    total = len(docs)
    logging.info(f"  {total:,} dokument i index")

    semaphore = asyncio.Semaphore(workers)
    connector = aiohttp.TCPConnector(limit=workers, limit_per_host=workers)
    session_timeout = aiohttp.ClientTimeout(total=None)

    counters = {"ok": 0, "skip": 0, "no_sv": 0, "timeout": 0, "err": 0}
    start = time.time()

    async with aiohttp.ClientSession(
        headers=HEADERS, connector=connector, timeout=session_timeout
    ) as session:
        tasks = [fetch_one(session, doc, semaphore) for doc in docs]

        done = 0
        for coro in asyncio.as_completed(tasks):
            celex, status = await coro
            done += 1

            if status == "ok":      counters["ok"]    += 1
            elif status == "skip":  counters["skip"]  += 1
            elif status == "no_sv": counters["no_sv"] += 1
            elif status == "timeout": counters["timeout"] += 1
            else:                   counters["err"]   += 1

            if done % 500 == 0 or done == total:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                pct  = done / total * 100
                eta_min = (total - done) / rate / 60 if rate > 0 else 0
                logging.info(
                    f"  [{done:,}/{total:,}] {pct:.1f}% | "
                    f"OK:{counters['ok']} Skip:{counters['skip']} "
                    f"NoSV:{counters['no_sv']} Timeout:{counters['timeout']} "
                    f"Err:{counters['err']} | {rate:.1f}/s | ETA:{eta_min:.0f}min"
                )
            # Rate limit: sleep a little between requests per worker
            await asyncio.sleep(RATE_SLEEP / workers)

    total_mb = sum(p.stat().st_size for p in TEXT_DIR.glob("*.html")) / 1_048_576
    logging.info(f"\n  KLART!")
    logging.info(f"  OK:{counters['ok']} Skip:{counters['skip']} "
                 f"NoSV:{counters['no_sv']} Timeout:{counters['timeout']} "
                 f"Err:{counters['err']}")
    logging.info(f"  Totalt: {total_mb:.0f} MB i {TEXT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()
    asyncio.run(run(args.workers))
