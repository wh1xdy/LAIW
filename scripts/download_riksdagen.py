#!/usr/bin/env python3
"""
Riksdagen API Downloader - SFS, Prop, Bet, SOU
Resumable, rate-limited, with full error handling.
Output: ~/LAIW/data/raw/riksdagen/{doctype}_all.json
"""

import json
import time
import logging
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

import urllib.request
import urllib.error

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR   = Path.home() / "LAIW"
RAW_DIR    = BASE_DIR / "data" / "raw" / "riksdagen"
LOG_DIR    = BASE_DIR / "logs"
PROG_DIR   = BASE_DIR / "data" / "raw" / "riksdagen" / ".progress"

RAW_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROG_DIR.mkdir(parents=True, exist_ok=True)

API_BASE   = "https://data.riksdagen.se/dokumentlista/"
PAGE_SIZE  = 500
SLEEP_SEC  = 1.2   # polite rate limit
MAX_RETRIES = 5
RETRY_SLEEP = 10

DOC_TYPES = {
    "sfs":  "sfs_all.json",
    "prop": "prop_all.json",
    "bet":  "bet_all.json",
    "sou":  "sou_all.json",
    "ds":   "ds_all.json",
    "prot": "prot_all.json",
    "mot":  "mot_all.json",   # Motioner (257k docs)
    "fr":   "fr_all.json",    # Skriftliga frågor (44k docs)
    "ip":   "ip_all.json",    # Interpellationer (15k docs)
    "dir":  "dir_all.json",   # Kommittédirektiv (6k docs)
}

# ─── LOGGING ──────────────────────────────────────────────────────────────────
def setup_logging(doctype: str):
    log_file = LOG_DIR / f"riksdagen_{doctype}_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info(f"Log: {log_file}")

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def fetch_page(doctype: str, page: int) -> dict | None:
    url = (
        f"{API_BASE}?doktyp={doctype}"
        f"&utformat=json&sz={PAGE_SIZE}&p={page}"
        f"&sort=datum&sortorder=asc"
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LAIW-Dataset/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            logging.warning(f"  HTTP {e.code} on page {page}, attempt {attempt}/{MAX_RETRIES}")
        except Exception as e:
            logging.warning(f"  Error on page {page}: {e}, attempt {attempt}/{MAX_RETRIES}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_SLEEP * attempt)
    logging.error(f"  Failed to fetch page {page} after {MAX_RETRIES} attempts")
    return None


def extract_docs(data: dict) -> list:
    """Pull document list from API response."""
    try:
        dl = data.get("dokumentlista", {})
        docs = dl.get("dokument", [])
        if isinstance(docs, list):
            return docs
        if isinstance(docs, dict):
            return [docs]
    except Exception:
        pass
    return []

def get_total_pages(data: dict) -> int:
    """Parse total pages from API response."""
    try:
        dl = data.get("dokumentlista", {})
        total = int(dl.get("@traffar", 0))
        pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        return max(pages, 1)
    except Exception:
        return 999

def load_progress(doctype: str) -> int:
    """Return last successfully saved page (0 = not started)."""
    prog_file = PROG_DIR / f"{doctype}_progress.txt"
    if prog_file.exists():
        try:
            return int(prog_file.read_text().strip())
        except Exception:
            pass
    return 0

def save_progress(doctype: str, page: int):
    prog_file = PROG_DIR / f"{doctype}_progress.txt"
    prog_file.write_text(str(page))

def load_existing_docs(out_path: Path) -> list:
    """Load already-downloaded documents."""
    if out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                logging.info(f"  Loaded {len(data):,} existing docs from {out_path.name}")
                return data
        except Exception as e:
            logging.warning(f"  Could not load existing file: {e}")
    return []

def save_docs(docs: list, out_path: Path):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=None, separators=(",", ":"))

# ─── MAIN DOWNLOAD LOGIC ──────────────────────────────────────────────────────
def download_doctype(doctype: str, force_restart: bool = False):
    setup_logging(doctype)
    out_path = RAW_DIR / DOC_TYPES[doctype]

    logging.info(f"{'='*60}")
    logging.info(f"  Doktyp: {doctype.upper()} → {out_path}")
    logging.info(f"{'='*60}")

    # Determine start page
    if force_restart:
        start_page = 1
        all_docs = []
    else:
        start_page = load_progress(doctype) + 1
        all_docs = load_existing_docs(out_path)

    # Dedup existing docs by dok_id to avoid duplicates on resume
    if all_docs:
        seen = {}
        for d in all_docs:
            key = d.get("dok_id") or d.get("id") or str(id(d))
            seen[key] = d
        all_docs = list(seen.values())
        logging.info(f"  After dedup: {len(all_docs):,} unique docs")

    # Probe first page for totals
    logging.info(f"  Probing API for total document count...")
    first = fetch_page(doctype, 1)
    if not first:
        logging.error("  Could not reach API. Aborting.")
        return
    total_docs = int(first.get("dokumentlista", {}).get("@traffar", 0))
    # Använd faktiskt antal returnerade per sida (API kan ignorera sz)
    first_docs = extract_docs(first)
    actual_page_size = len(first_docs) if first_docs else PAGE_SIZE
    if actual_page_size < 1:
        actual_page_size = PAGE_SIZE
    total_pages = (total_docs + actual_page_size - 1) // actual_page_size
    logging.info(f"  Total documents: {total_docs:,} | Actual page size: {actual_page_size} | Total pages: {total_pages}")
    logging.info(f"  Already have: {len(all_docs):,} docs, resuming from page {start_page}")

    if start_page > total_pages:
        logging.info("  Already complete!")
        return

    # Download pages
    for page in range(start_page, total_pages + 1):
        logging.info(f"  Page {page}/{total_pages} ...")
        data = fetch_page(doctype, page)
        if data is None:
            logging.error(f"  Skipping page {page} due to repeated failures")
            continue

        docs = extract_docs(data)
        if not docs:
            logging.warning(f"  No documents on page {page}, possibly last page")
            save_progress(doctype, page)
            break

        all_docs.extend(docs)
        save_progress(doctype, page)

        # Save every 10 pages
        if page % 10 == 0 or page == total_pages:
            logging.info(f"  Saving checkpoint: {len(all_docs):,} docs total")
            save_docs(all_docs, out_path)

        time.sleep(SLEEP_SEC)

    # Final save
    save_docs(all_docs, out_path)
    size_mb = out_path.stat().st_size / 1_048_576
    logging.info(f"\n  DONE: {len(all_docs):,} docs saved to {out_path} ({size_mb:.1f} MB)")

# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Riksdagen documents")
    parser.add_argument("doctypes", nargs="*", default=list(DOC_TYPES.keys()),
                        help=f"Document types to download: {list(DOC_TYPES.keys())}")
    parser.add_argument("--restart", action="store_true",
                        help="Ignore progress and restart from page 1")
    args = parser.parse_args()

    for dt in args.doctypes:
        if dt not in DOC_TYPES:
            print(f"Unknown doctype: {dt}. Valid: {list(DOC_TYPES.keys())}")
            continue
        download_doctype(dt, force_restart=args.restart)
        print(f"\n✓ {dt.upper()} complete\n")
