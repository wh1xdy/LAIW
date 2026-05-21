#!/usr/bin/env python3
"""
SAOB Scraper — Svenska Akademiens Ordbok
Källa: saob.se (WordPress med custom AJAX-API)

Strategi:
  1. Autocomplete-API: hämta alla ord per bokstav (A-Ö)
  2. Per ord: fetch artikel-HTML och extrahera definition
  3. Spara som strukturerad JSON

Output:
  ~/LAIW/data/raw/saob/word_index.json    ← komplett ordlista med URLs
  ~/LAIW/data/raw/saob/articles/          ← råHTML per ord
  ~/LAIW/data/raw/saob/saob_complete.json ← slutlig strukturerad data

Kör: python3 download_saob.py [--words-only] [--batch A-F]

Obs: ~500,000 ord × 0.3 sek ≈ 40 timmar. Kör med nohup eller i delar.
"""

import json, time, sys, os, re, logging, argparse
from pathlib import Path
from datetime import datetime
import urllib.request, urllib.parse, urllib.error

BASE_DIR   = Path.home() / "LAIW"
OUT_DIR    = BASE_DIR / "data" / "raw" / "saob"
LOG_DIR    = BASE_DIR / "logs"
ART_DIR    = OUT_DIR / "articles"
PROG_FILE  = OUT_DIR / ".progress_saob.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
ART_DIR.mkdir(parents=True, exist_ok=True)

AJAX_URL  = "https://www.saob.se/wp-admin/admin-ajax.php"
BASE_URL  = "https://www.saob.se"
SLEEP_AC  = 0.3   # autocomplete
SLEEP_ART = 0.4   # article fetch
MAX_RETRY = 4

# Svenska bokstäver (inkl digrafer och vanliga kombinationer)
LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ")
# Vanliga 2-bokstavskombinationer för bättre täckning
PREFIXES_2 = [
    f"{a}{b}" for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ"
    for b in "AEIOUÅÄÖ"
]

def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lf = LOG_DIR / f"saob_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf), logging.StreamHandler(sys.stdout)],
    )
    logging.info(f"Log: {lf}")

def fetch_autocomplete(term: str) -> list[dict]:
    """Hämta ordlista för ett sökterm via AJAX autocomplete."""
    params = urllib.parse.urlencode({
        "callback": "x",
        "action": "myprefix_autocompletesearch",
        "term": term,
    })
    url = AJAX_URL + "?" + params
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; LAIW/1.0)",
        "Referer": "https://www.saob.se/",
    })
    for attempt in range(1, MAX_RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", errors="replace")
            # Rensa JSONP-wrapper: x([...]) eller ?([...])
            body = re.sub(r"^[^(\[]*\(?", "", body.strip())
            body = re.sub(r"\)?;?\s*$", "", body)
            if not body or body == "false" or body == "null":
                return []
            return json.loads(body) if body.startswith("[") else []
        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(3 * attempt)
    return []

def fetch_article_html(seek: str) -> str | None:
    """Hämta artikel-HTML för ett ord."""
    params = urllib.parse.urlencode({"seek": seek, "pz": "2"})
    url = f"{BASE_URL}/artikel/?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; LAIW/1.0)",
        "Referer": "https://www.saob.se/",
    })
    for attempt in range(1, MAX_RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt < MAX_RETRY:
                time.sleep(3 * attempt)
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(3 * attempt)
    return None

def extract_article_text(html: str, word: str) -> dict:
    """Extrahera artikel-data från SAOB HTML."""
    def strip(s):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()

    result = {"word": word, "sections": [], "raw_length": len(html)}

    # Titlar (ordformer med ordklass)
    titles = re.findall(r'class="titlez"[^>]*>(.*?)</a>', html, re.DOTALL)
    result["titles"] = [strip(t) for t in titles]

    # Ordklasser
    cases = re.findall(r'class="casez?"[^>]*>(.*?)</span>', html, re.DOTALL)
    result["word_classes"] = list(set(strip(c) for c in cases if strip(c)))

    # Artikeltext — leta efter div.skroll och div.noskroll (innehåller definitionen)
    for cls in ["skroll", "noskroll", "smal passiv", "smal"]:
        pattern = rf'class="{re.escape(cls)}"[^>]*>(.*?)</div>'
        blocks = re.findall(pattern, html, re.DOTALL)
        for block in blocks:
            text = strip(block)
            if len(text) > 50:
                result["sections"].append(text)

    # Fallback: hämta allt innehåll mellan body-taggar
    if not result["sections"]:
        body_match = re.search(r'<div[^>]+id="content"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
        if body_match:
            result["sections"].append(strip(body_match.group(1))[:2000])

    return result

def load_progress() -> dict:
    if PROG_FILE.exists():
        try:
            return json.loads(PROG_FILE.read_text())
        except:
            pass
    return {"completed_prefixes": [], "total_words": 0}

def save_progress(prog: dict):
    PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False))

def build_word_index(batch_filter: str | None = None) -> list[dict]:
    """Bygg ordindex via autocomplete för alla prefix."""
    logging.info("  Bygger ordindex via SAOB autocomplete...")
    index_file = OUT_DIR / "word_index.json"
    all_words: dict[str, dict] = {}

    # Ladda befintligt index
    if index_file.exists():
        existing = json.loads(index_file.read_text())
        all_words = {w["label"]: w for w in existing}
        logging.info(f"  Laddade {len(all_words):,} befintliga ord")

    prog = load_progress()
    done_prefixes = set(prog.get("completed_prefixes", []))

    prefixes = LETTERS + PREFIXES_2

    # Filtrera batch om angivet (t.ex. "A-F")
    if batch_filter and "-" in batch_filter:
        start, end = batch_filter.upper().split("-")
        prefixes = [p for p in prefixes if start <= p[0] <= end]
        logging.info(f"  Batch {batch_filter}: {len(prefixes)} prefix")

    for i, prefix in enumerate(prefixes):
        if prefix in done_prefixes:
            continue
        words = fetch_autocomplete(prefix)
        new_count = 0
        for w in words:
            label = w.get("label", "")
            if label and label not in all_words:
                all_words[label] = w
                new_count += 1

        if new_count > 0 or i % 50 == 0:
            logging.info(
                f"  Prefix '{prefix}': +{new_count} ord "
                f"| Totalt: {len(all_words):,}"
            )

        done_prefixes.add(prefix)
        prog["completed_prefixes"] = list(done_prefixes)
        prog["total_words"] = len(all_words)

        # Spara index var 100:e prefix
        if i % 100 == 0:
            result = list(all_words.values())
            json.dump(result, open(index_file, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
            save_progress(prog)

        time.sleep(SLEEP_AC)

    # Slutspar
    result = list(all_words.values())
    json.dump(result, open(index_file, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    save_progress(prog)
    logging.info(f"\n  Ordindex klart: {len(result):,} unika ord")
    return result

def fetch_all_articles(words_only: bool = False):
    """Hämta alla artiklar baserat på ordindex."""
    index_file = OUT_DIR / "word_index.json"
    if not index_file.exists():
        logging.error("  Kör med --words-only först för att bygga ordindex!")
        return

    word_list = json.loads(index_file.read_text())
    logging.info(f"  Hämtar artiklar för {len(word_list):,} ord...")

    all_articles = []
    out_file = OUT_DIR / "saob_complete.json"

    ok = skip = fail = 0
    for i, entry in enumerate(word_list, 1):
        label = entry.get("label", "")
        link  = entry.get("link", "")
        if not label:
            continue

        # Artikel-fil för cache
        safe = re.sub(r'[^\w\-]', '_', label)[:80]
        art_path = ART_DIR / f"{safe}.json"
        if art_path.exists():
            skip += 1
            try:
                all_articles.append(json.loads(art_path.read_text()))
            except:
                pass
            continue

        # Extrahera seek-term från länk
        seek_match = re.search(r'seek=([^&]+)', link)
        seek = urllib.parse.unquote(seek_match.group(1)) if seek_match else label

        html = fetch_article_html(seek)
        if html:
            article = extract_article_text(html, label)
            article["link"] = link
            art_path.write_text(json.dumps(article, ensure_ascii=False))
            all_articles.append(article)
            ok += 1
        else:
            fail += 1

        if i % 500 == 0:
            eta_h = ((len(word_list) - i) * SLEEP_ART) / 3600
            logging.info(
                f"  [{i}/{len(word_list)}] OK:{ok} Skip:{skip} Fail:{fail} "
                f"| ETA: {eta_h:.1f}h"
            )
            # Checkpoint
            json.dump(all_articles, open(out_file, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))

        time.sleep(SLEEP_ART)

    # Slutspar
    json.dump(all_articles, open(out_file, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    size_mb = out_file.stat().st_size / 1_048_576
    logging.info(f"\n  KLART: {ok:,} hämtade, {skip:,} cachade, {fail:,} fel")
    logging.info(f"  Output: {out_file} ({size_mb:.0f} MB)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAOB Scraper")
    parser.add_argument("--words-only", action="store_true",
                        help="Bygg bara ordindex, hämta inte artiklar")
    parser.add_argument("--batch", default=None,
                        help="Begränsa till bokstavsintervall, t.ex. A-F")
    args = parser.parse_args()

    setup_logging()
    logging.info("=" * 60)
    logging.info("  SAOB SCRAPER")
    logging.info("=" * 60)

    words = build_word_index(batch_filter=args.batch)

    if not args.words_only and words:
        fetch_all_articles()
