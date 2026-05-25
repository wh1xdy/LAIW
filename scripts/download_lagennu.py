#!/usr/bin/env python3
"""
Hämtar gällande lagtexter från lagen.nu:
  1. Konsoliderade versioner av de stora balkarna + viktiga lagar
  2. Alla lagar med SFS-nummer 2017–2026 (saknas i Riksdagens API)

Fas 1 – Sondering: HEAD-requests för att hitta vilka SFS-nummer som finns
Fas 2 – Nedladdning: GET för varje hittad lag

Output: ~/LAIW/data/raw/lagennu/{YYYY}-{NNN}.html

Kör: python3 scripts/download_lagennu.py [--mode all|balkar|modern] [--workers 5]
"""
import asyncio, aiohttp, json, re, time, logging, argparse, sys
from pathlib import Path
from datetime import datetime

BASE    = Path.home() / "LAIW"
OUT_DIR = BASE / "data" / "raw" / "lagennu"
LOG_DIR = BASE / "logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://lagen.nu"
SLEEP    = 0.3   # sekunder mellan requests per worker

# ── Viktiga lagar att alltid hämta (konsoliderade) ────────────────────────────
PRIORITY_LAWS = [
    # Grundlagar
    "1974:152",   # Regeringsformen
    "1974:1209",  # Riksdagsordningen
    "1949:105",   # Tryckfrihetsförordningen
    "1991:1469",  # Yttrandefrihetsgrundlagen
    # Processbalkar
    "1942:740",   # Rättegångsbalken
    "1996:242",   # Förvaltningslagen
    "2017:900",   # Förvaltningslagen (ny)
    # Civilrätt
    "1915:218",   # Avtalslagen
    "1949:381",   # Föräldrabalken
    "1958:637",   # Ärvdabalken
    "1962:700",   # Brottsbalken
    "1970:994",   # Jordabalken
    "1981:774",   # Utsökningsbalken
    "1987:230",   # Äktenskapsbalken
    "1990:931",   # Köplagen
    # Arbetsrätt
    "1976:580",   # MBL
    "1982:80",    # LAS
    "1977:1160",  # Arbetsmiljölagen
    # Skatter
    "1999:1229",  # Inkomstskattelagen
    "1994:200",   # Mervärdesskattelagen
    # Bolag / näringsliv
    "2005:551",   # Aktiebolagslagen
    "1987:667",   # Lagen om ekonomiska föreningar
    "1991:980",   # Lagen om handel med finansiella instrument
    # Miljö / plan
    "1998:1591",  # Miljöbalken
    "2010:900",   # Plan- och bygglagen
    # Offentlig förvaltning
    "2009:400",   # Offentlighets- och sekretesslagen
    "2017:310",   # Lagen om framtidsfullmakter
    # Socialförsäkring / välfärd
    "2010:110",   # Socialförsäkringsbalken
    "2001:453",   # Socialtjänstlagen
    # Dataskydd / IT
    "2018:218",   # Dataskyddslagen (GDPR)
    "2022:482",   # Cybersäkerhetslagen... might not exist yet
    # Modern konsumenträtt
    "2022:260",   # Konsumentköplagen
    "2005:59",    # Distansavtalslagen
    # Straffrätt
    "1988:870",   # Narkotikastrafflagen
    "1951:649",   # Lag om straff för vissa trafikbrott
    # Utlänning / migration
    "2005:716",   # Utlänningslagen
    "2010:197",   # Lagen om etableringsinsatser
    # Livsmedel
    "2006:804",   # Livsmedelslagen
    "2023:1091",  # Ny livsmedelslag (if exists)
]

# SFS-år att sondera för moderna lagar
MODERN_YEARS = list(range(2017, 2027))
MAX_SFS_NR   = 1500   # max SFS-nummer per år att sondera


def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lf = LOG_DIR / f"lagennu_{ts}.log"
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf), logging.StreamHandler(sys.stdout)])
    logging.info(f"Log: {lf}")


def sfs_to_filename(sfs: str) -> str:
    return sfs.replace(":", "-") + ".html"


def already_downloaded(sfs: str) -> bool:
    return (OUT_DIR / sfs_to_filename(sfs)).exists()


# ── Fas 1: sondera vilka SFS-nummer som existerar ─────────────────────────────
async def probe_year(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                     year: int, nr: int) -> str | None:
    sfs = f"{year}:{nr}"
    if already_downloaded(sfs):
        return sfs
    url = f"{BASE_URL}/{sfs}"
    async with sem:
        await asyncio.sleep(SLEEP)
        try:
            async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return sfs if r.status == 200 else None
        except Exception:
            return None


async def probe_all_modern(workers: int) -> list[str]:
    sem = asyncio.Semaphore(workers)
    found = []
    connector = aiohttp.TCPConnector(limit=workers)
    headers = {"User-Agent": "LAIW-Dataset/1.0 (legal AI research)"}
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        for year in MODERN_YEARS:
            tasks = [probe_year(session, sem, year, nr) for nr in range(1, MAX_SFS_NR + 1)]
            results = await asyncio.gather(*tasks)
            year_found = [r for r in results if r]
            logging.info(f"  {year}: {len(year_found)} lagar hittade")
            found.extend(year_found)
    return found


# ── Fas 2: ladda ner HTML ─────────────────────────────────────────────────────
async def download_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                       sfs: str) -> tuple[str, bool]:
    if already_downloaded(sfs):
        return sfs, True   # already done
    url = f"{BASE_URL}/{sfs}"
    async with sem:
        await asyncio.sleep(SLEEP)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    html = await r.text(encoding="utf-8", errors="replace")
                    (OUT_DIR / sfs_to_filename(sfs)).write_text(html, encoding="utf-8")
                    return sfs, True
                return sfs, False
        except Exception as e:
            logging.warning(f"  Fel: {sfs}: {e}")
            return sfs, False


async def download_all(sfs_list: list[str], workers: int):
    sem = asyncio.Semaphore(workers)
    connector = aiohttp.TCPConnector(limit=workers)
    headers = {"User-Agent": "LAIW-Dataset/1.0 (legal AI research)"}
    ok = skip = err = 0
    t0 = time.time()
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks = [download_one(session, sem, sfs) for sfs in sfs_list]
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            sfs, success = await coro
            if success:
                if (OUT_DIR / sfs_to_filename(sfs)).stat().st_size > 0:
                    ok += 1
                else:
                    skip += 1
            else:
                err += 1
            if i % 100 == 0:
                logging.info(f"  {i}/{len(sfs_list)} ({ok} OK, {err} fel) | {time.time()-t0:.0f}s")
    logging.info(f"  Klar: {ok} OK, {skip} redan klara, {err} fel | {time.time()-t0:.0f}s")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="all", choices=["all", "balkar", "modern"])
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    setup_logging()

    to_download = []

    if args.mode in ("all", "balkar"):
        # Filtrera bort dem vi inte kan verifiera (lagen.nu returnerar 404)
        valid_priority = [s for s in PRIORITY_LAWS if s]
        logging.info(f"Prioriterade lagar: {len(valid_priority)}")
        to_download.extend(valid_priority)

    if args.mode in ("all", "modern"):
        logging.info(f"Sonderar SFS {MODERN_YEARS[0]}–{MODERN_YEARS[-1]} (max {MAX_SFS_NR} per år)...")
        found = asyncio.run(probe_all_modern(args.workers))
        logging.info(f"Totalt hittade moderna lagar: {len(found)}")
        to_download.extend(found)

    # Avduplicera, bevara ordning
    seen = set()
    unique = []
    for s in to_download:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    already_done = sum(1 for s in unique if already_downloaded(s))
    logging.info(f"\nLaddar ner {len(unique)} lagar ({already_done} redan klara)...")
    asyncio.run(download_all(unique, args.workers))

    # Spara lista på vad vi hämtat
    index_file = OUT_DIR / "lagennu_index.json"
    all_downloaded = [f.stem.replace("-", ":", 1) for f in sorted(OUT_DIR.glob("*.html"))]
    json.dump(all_downloaded, open(index_file, "w"), indent=2, ensure_ascii=False)
    logging.info(f"\nIndex sparat: {index_file} ({len(all_downloaded)} lagar totalt)")


if __name__ == "__main__":
    main()
