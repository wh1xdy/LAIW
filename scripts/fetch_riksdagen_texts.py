#!/usr/bin/env python3
"""
Riksdagen Full-Text Fetcher
Hämtar fulltexten (XML) för varje dokument i metadata-JSON-filerna.
Använder asyncio + aiohttp för parallella nedladdningar.

Kör: python3 fetch_riksdagen_texts.py [--doctype prop] [--workers 8]

Output: ~/LAIW/data/raw/riksdagen/texts/{doctype}/{DOK_ID}.xml
"""

import asyncio
import aiohttp
import json
import sys
import os
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR    = Path.home() / "LAIW"
RAW_DIR     = BASE_DIR / "data" / "raw" / "riksdagen"
LOG_DIR     = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_WORKERS  = 8      # concurrent requests
RATE_LIMIT_SLEEP = 0.15   # seconds between requests per worker
MAX_RETRIES      = 4
TIMEOUT_SEC      = 90

META_FILES = {
    "prop":         RAW_DIR / "prop_all.json",
    "prop_modern":  RAW_DIR / "prop_modern.json",
    "sfs":          RAW_DIR / "sfs_all.json",
    "bet":          RAW_DIR / "bet_all.json",
    "bet_modern":   RAW_DIR / "bet_modern.json",
    "sou":          RAW_DIR / "sou_all.json",
    "ds":           RAW_DIR / "ds_all.json",
    "prot":         RAW_DIR / "prot_all.json",
    "mot":          RAW_DIR / "mot_all.json",
    "fr":           RAW_DIR / "fr_all.json",
    "ip":           RAW_DIR / "ip_all.json",
    "dir":          RAW_DIR / "dir_all.json",
}

# ─── LOGGING ──────────────────────────────────────────────────────────────────
def setup_logging(doctype: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"texts_{doctype}_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def load_doc_ids(doctype: str) -> list[tuple[str, str]]:
    """Returns list of (dok_id, text_url) tuples."""
    meta_file = META_FILES[doctype]
    if not meta_file.exists():
        logging.error(f"Metadata file not found: {meta_file}")
        logging.error(f"Run download_riksdagen.py {doctype} first!")
        return []
    with open(meta_file, encoding="utf-8") as f:
        docs = json.load(f)
    result = []
    for doc in docs:
        dok_id = doc.get("dok_id") or doc.get("id", "")
        url_rel = doc.get("dokument_url_text", "")
        if not dok_id or not url_rel:
            continue
        url = ("https:" + url_rel) if url_rel.startswith("//") else url_rel
        result.append((dok_id.upper(), url))
    logging.info(f"  Found {len(result):,} document IDs in {meta_file.name}")
    return result

def get_output_dir(doctype: str) -> Path:
    # prop_modern and bet_modern share output dirs with prop/bet
    base = doctype.replace("_modern", "")
    d = RAW_DIR / "texts" / base
    d.mkdir(parents=True, exist_ok=True)
    return d

def already_fetched(out_dir: Path, dok_id: str) -> bool:
    p = out_dir / f"{dok_id}.xml"
    return p.exists() and p.stat().st_size > 100


# ─── ASYNC FETCHER ────────────────────────────────────────────────────────────
async def fetch_one(session: aiohttp.ClientSession, dok_id: str, url: str,
                    out_dir: Path, semaphore: asyncio.Semaphore,
                    stats: dict) -> bool:
    out_path = out_dir / f"{dok_id}.xml"
    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        out_path.write_bytes(content)
                        stats["success"] += 1
                        await asyncio.sleep(RATE_LIMIT_SLEEP)
                        return True
                    elif resp.status == 404:
                        logging.warning(f"  404 for {dok_id}: {url}")
                        stats["not_found"] += 1
                        return False
                    else:
                        logging.warning(f"  HTTP {resp.status} for {dok_id}")
            except asyncio.TimeoutError:
                logging.warning(f"  Timeout for {dok_id} (attempt {attempt})")
            except Exception as e:
                logging.warning(f"  Error for {dok_id}: {e} (attempt {attempt})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(5 * attempt)
        stats["failed"] += 1
        stats["failed_ids"].append(dok_id)
        return False

async def fetch_all(doctype: str, workers: int):
    log_file = setup_logging(doctype)
    logging.info(f"{'='*60}")
    logging.info(f"  Fetching full texts for: {doctype.upper()}")
    logging.info(f"  Workers: {workers}")
    logging.info(f"{'='*60}")

    doc_ids = load_doc_ids(doctype)
    if not doc_ids:
        return

    out_dir = get_output_dir(doctype)

    # Skip already downloaded
    pending = [(did, url) for did, url in doc_ids if not already_fetched(out_dir, did)]
    skipped = len(doc_ids) - len(pending)
    logging.info(f"  Skipping {skipped:,} already fetched, downloading {len(pending):,}")

    if not pending:
        logging.info("  All documents already fetched!")
        return

    stats = {"success": 0, "failed": 0, "not_found": 0, "failed_ids": []}
    semaphore = asyncio.Semaphore(workers)

    headers = {"User-Agent": "LAIW-Dataset/1.0 (Swedish Legal AI Research)"}
    connector = aiohttp.TCPConnector(limit=workers, ssl=False)

    start = time.time()
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = [fetch_one(session, did, url, out_dir, semaphore, stats)
                 for did, url in pending]

        # Progress logging every 100 completions
        completed = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            completed += 1
            if completed % 100 == 0 or completed == len(pending):
                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = (len(pending) - completed) / rate if rate > 0 else 0
                logging.info(
                    f"  Progress: {completed:,}/{len(pending):,} "
                    f"({100*completed/len(pending):.1f}%) "
                    f"| OK: {stats['success']:,} "
                    f"| Fail: {stats['failed']:,} "
                    f"| {rate:.1f} docs/sec "
                    f"| ETA: {remaining/60:.0f} min"
                )

    # Save failed IDs for retry
    if stats["failed_ids"]:
        fail_log = LOG_DIR / f"failed_{doctype}_{datetime.now():%Y%m%d_%H%M%S}.txt"
        fail_log.write_text("\n".join(stats["failed_ids"]))
        logging.warning(f"  {len(stats['failed_ids']):,} failed IDs saved to {fail_log}")

    total_size = sum(p.stat().st_size for p in out_dir.glob("*.xml")) / 1_048_576
    elapsed = time.time() - start
    logging.info(f"\n  DONE in {elapsed/60:.1f} min")
    logging.info(f"  Success: {stats['success']:,}, Failed: {stats['failed']:,}, 404: {stats['not_found']:,}")
    logging.info(f"  Total size: {total_size:.0f} MB in {out_dir}")

# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch full texts from Riksdagen")
    parser.add_argument("doctypes", nargs="*", default=["prop", "sfs", "bet", "sou"],
                        help="Document types to fetch")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Concurrent workers (default: {DEFAULT_WORKERS})")
    args = parser.parse_args()

    # Install aiohttp if needed
    try:
        import aiohttp
    except ImportError:
        print("Installing aiohttp...")
        os.system("pip3 install aiohttp --break-system-packages -q")
        import aiohttp

    for dt in args.doctypes:
        if dt not in META_FILES:
            print(f"Unknown: {dt}")
            continue
        asyncio.run(fetch_all(dt, args.workers))
