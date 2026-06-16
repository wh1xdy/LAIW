#!/usr/bin/env python3
"""
Domstolspraxis Downloader
Källa: rattspraxis.etjanst.domstol.se/api/v1
Totalt: ~17,500 avgöranden

- Vägledande avgöranden: full HTML-text i 'innehall' (hämtas direkt från JSON)
- Övriga avgöranden: sammanfattning + PDF-bilaga (hämtas separat)

Output:
  ~/LAIW/data/raw/domstolar/vagledande_all.json   ← alla vägledande, med fulltext
  ~/LAIW/data/raw/domstolar/ovriga_all.json        ← övriga, med sammanfattning
  ~/LAIW/data/raw/domstolar/pdfs/{fillagringId}.pdf ← domstolsavgöranden som PDF

Kör: python3 download_domstolar.py [--skip-pdfs]
"""

import json, time, sys, os, argparse, logging, asyncio
from pathlib import Path
from datetime import datetime
import urllib.request, urllib.error

BASE_DIR   = Path.home() / "LAIW"
OUT_DIR    = BASE_DIR / "data" / "raw" / "domstolar"
LOG_DIR    = BASE_DIR / "logs"
PDF_DIR    = OUT_DIR / "pdfs"
PROG_FILE  = OUT_DIR / ".progress_domstolar.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

API_BASE   = "https://rattspraxis.etjanst.domstol.se"
PAGE_SIZE  = 10   # API returnerar max 10 per sida
SLEEP_SEC  = 0.8
MAX_RETRIES = 4

# Courts we want (all precedent-setting, any court)
TARGET_COURTS = ["HDO", "HFD", "AD", "MMOD", "HOR", "KamR"]  # tom = alla

def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"domstolar_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    logging.info(f"Log: {log_file}")

def load_progress() -> dict:
    if PROG_FILE.exists():
        try:
            return json.loads(PROG_FILE.read_text())
        except:
            pass
    return {"last_page": 0, "total_fetched": 0}

def save_progress(page: int, total: int):
    PROG_FILE.write_text(json.dumps({"last_page": page, "total_fetched": total}))

def get_publiceringar(page: int, size: int = PAGE_SIZE) -> dict | None:
    """GET /api/v1/publiceringar med paginering — returnerar x-total-count i header."""
    url = f"{API_BASE}/api/v1/publiceringar?page={page}&size={size}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "LAIW-Dataset/1.0",
        "Accept": "application/json",
    })
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                total_count = int(r.headers.get("x-total-count", 0))
                pubs = json.loads(r.read())
                return {"publiceringLista": pubs, "_total_count": total_count}
        except Exception as e:
            logging.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed for page {page}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return None

# Keep alias for backward compat
def post_sok(page: int, size: int = PAGE_SIZE) -> dict | None:
    return get_publiceringar(page, size)

def download_pdf(fillagring_id: str) -> bool:
    """Ladda ner PDF-bilaga."""
    out = PDF_DIR / f"{fillagring_id.replace('/', '_')}.pdf"
    if out.exists() and out.stat().st_size > 500:
        return True
    url = f"{API_BASE}/api/v1/bilagor/{fillagring_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "LAIW-Dataset/1.0"})
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out.write_bytes(r.read())
            return True
        except Exception as e:
            logging.warning(f"  PDF fail {fillagring_id}: {e}")
            if attempt < 3:
                time.sleep(3 * attempt)
    return False

def download_all(skip_pdfs: bool = False):
    setup_logging()
    logging.info("=" * 60)
    logging.info("  DOMSTOLSPRAXIS NEDLADDNING")
    logging.info("=" * 60)

    progress = load_progress()
    start_page = progress["last_page"] + 1
    vagledande = []
    ovriga = []

    # Load existing files if present
    vag_file = OUT_DIR / "vagledande_all.json"
    ovr_file = OUT_DIR / "ovriga_all.json"
    if vag_file.exists() and start_page > 1:
        vagledande = json.loads(vag_file.read_text())
        logging.info(f"  Loaded {len(vagledande):,} existing vägledande")
    if ovr_file.exists() and start_page > 1:
        ovriga = json.loads(ovr_file.read_text())
        logging.info(f"  Loaded {len(ovriga):,} existing övriga")

    # Probe the first page for the total count
    probe = post_sok(1, size=PAGE_SIZE)
    if probe:
        total_count = probe.get("_total_count", 0)
        actual_page_size = len(probe.get("publiceringLista", [])) or PAGE_SIZE
        if total_count == 0:
            total_count = 20000
            logging.warning(f"  x-total-count saknades, använder fallback {total_count:,}")
    else:
        total_count = 20000
        actual_page_size = PAGE_SIZE
    total_pages = (total_count + actual_page_size - 1) // actual_page_size
    logging.info(f"  Totalt: {total_count:,} avgöranden, {total_pages} sidor (actual_page_size={actual_page_size})")
    logging.info(f"  Startar från sida {start_page}")

    pdf_queue = []

    for page in range(start_page, total_pages + 1):
        logging.info(f"  Sida {page}/{total_pages} ...")
        result = post_sok(page)
        if result is None:
            logging.error(f"  Hoppar över sida {page}")
            continue

        pubs = result.get("publiceringLista", [])
        if not pubs:
            logging.info("  Tom sida, klart!")
            save_progress(page, len(vagledande) + len(ovriga))
            break

        for pub in pubs:
            is_vag = pub.get("arVagledande", False)
            # Collect PDF storage IDs for the rest
            if not is_vag:
                for bil in pub.get("bilagaLista", []):
                    fid = bil.get("fillagringId", "")
                    if fid:
                        pdf_queue.append(fid)
                ovriga.append(pub)
            else:
                vagledande.append(pub)

        save_progress(page, len(vagledande) + len(ovriga))

        # Checkpoint var 10:e sida
        if page % 10 == 0:
            logging.info(f"  Checkpoint: {len(vagledande):,} vägledande, {len(ovriga):,} övriga")
            json.dump(vagledande, open(vag_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            json.dump(ovriga, open(ovr_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

        time.sleep(SLEEP_SEC)

    # Slutspar
    json.dump(vagledande, open(vag_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(ovriga, open(ovr_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    logging.info(f"\n  Metadata klar: {len(vagledande):,} vägledande, {len(ovriga):,} övriga")

    # PDF-nedladdning
    if not skip_pdfs and pdf_queue:
        logging.info(f"\n  Laddar ner {len(pdf_queue):,} PDF:er...")
        ok = fail = 0
        for i, fid in enumerate(pdf_queue, 1):
            if download_pdf(fid):
                ok += 1
            else:
                fail += 1
            if i % 100 == 0:
                logging.info(f"  PDF: {i}/{len(pdf_queue)} | OK:{ok} Fail:{fail}")
            time.sleep(0.5)
        logging.info(f"  PDF-nedladdning klar: {ok:,} OK, {fail:,} fail")
    elif skip_pdfs:
        logging.info("  PDF-nedladdning hoppas över (--skip-pdfs)")

    total_mb = sum(p.stat().st_size for p in OUT_DIR.glob("*.json")) / 1_048_576
    logging.info(f"\n  KLART. JSON: {total_mb:.1f} MB i {OUT_DIR}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pdfs", action="store_true",
                        help="Hoppa över PDF-nedladdning (spara tid)")
    args = parser.parse_args()
    download_all(skip_pdfs=args.skip_pdfs)
