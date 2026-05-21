#!/usr/bin/env python3
"""
SAOB djup ordindex - hämtar ALLA ord via sekventiell navigering.
Startar från varje bokstav och stegar igenom via scrollist-API:et.
"""
import json, time, re, sys, logging
from pathlib import Path
import urllib.request, urllib.parse

BASE_DIR = Path.home() / "LAIW"
OUT_DIR  = BASE_DIR / "data" / "raw" / "saob"
LOG_DIR  = BASE_DIR / "logs"
AJAX_URL = "https://www.saob.se/wp-admin/admin-ajax.php"
BASE_URL = "https://www.saob.se"
SLEEP    = 0.25
INDEX_FILE = OUT_DIR / "word_index.json"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(LOG_DIR/"saob_deep.log"), logging.StreamHandler(sys.stdout)])

def scrollist_next(unik: str) -> list[dict]:
    """Hämta nästa batch av artiklar via AJAX scrollist."""
    data = urllib.parse.urlencode({"action":"myprefix_scrollist","unik":unik,"dir":"dn"}).encode()
    req = urllib.request.Request(AJAX_URL, data=data,
        headers={"User-Agent":"Mozilla/5.0","Content-Type":"application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8","replace")
        # Extrahera titlar och unik-IDs
        entries = re.findall(r'href="/artikel/\?unik=([^&"]+)[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
        result = []
        for unik_id, label_html in entries:
            label = re.sub(r"<[^>]+>","",label_html).strip()
            if label:
                result.append({"label": label, "unik": unik_id,
                    "link": f"/artikel/?unik={unik_id}&pz=5"})
        # Hitta sista unik-ID för nästa anrop
        all_uniks = re.findall(r'unik="([^"]+)"', html)
        last_unik = all_uniks[-1] if all_uniks else None
        return result, last_unik
    except Exception as e:
        logging.warning(f"Error: {e}")
        return [], None

def get_start_unik(letter: str) -> str | None:
    """Hämta start-unik för en bokstav via söksidan."""
    url = f"{BASE_URL}/artikel/?seek={urllib.parse.quote(letter)}&pz=1"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8","replace")
        # Use href-based extraction to avoid picking up nav button unik= attributes
        hrefs = re.findall(r'href="/artikel/\?unik=([^&"]+)', html)
        return hrefs[0] if hrefs else None
    except:
        return None

if __name__ == "__main__":
    # Ladda befintligt index
    existing = {}
    if INDEX_FILE.exists():
        for w in json.loads(INDEX_FILE.read_text()):
            existing[w.get("label","")] = w

    letters = list("ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ")
    new_words = 0

    for letter in letters:
        logging.info(f"=== Bokstav: {letter} ===")
        start_unik = get_start_unik(letter)
        if not start_unik:
            logging.warning(f"  Ingen start för {letter}")
            continue
        
        current_unik = start_unik
        letter_count = 0
        consecutive_empty = 0

        while True:
            entries, next_unik = scrollist_next(current_unik)
            if not entries:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                time.sleep(1)
                continue
            consecutive_empty = 0

            # Kontrollera om vi lämnat bokstaven (via unik-prefix, ej label som kan börja med bindestreck)
            first_unik = entries[0]["unik"].upper()
            if first_unik and not first_unik.startswith(letter):
                logging.info(f"  Nått slutet av {letter} efter {letter_count} ord")
                break

            for entry in entries:
                lbl = entry["label"]
                if lbl not in existing:
                    existing[lbl] = entry
                    new_words += 1
                    letter_count += 1

            if not next_unik or next_unik == current_unik:
                break
            current_unik = next_unik

            if letter_count % 1000 == 0 and letter_count > 0:
                logging.info(f"  {letter}: {letter_count} ord")
                json.dump(list(existing.values()), open(INDEX_FILE,"w",encoding="utf-8"),
                    ensure_ascii=False, separators=(",",":"))

            time.sleep(SLEEP)

        logging.info(f"  {letter} klar: {letter_count} nya ord")

    json.dump(list(existing.values()), open(INDEX_FILE,"w",encoding="utf-8"),
        ensure_ascii=False, separators=(",",":"))
    logging.info(f"\nTotalt {len(existing):,} ord ({new_words} nya)")
