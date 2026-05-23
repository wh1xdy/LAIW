"""
LAIW Legal Search Tools
Search functions for Swedish and EU legal sources, callable by the model at inference time.

Usage:
    from tools import search_sfs, get_law, search_riksdagen, search_domstol, search_eurlex

Tool definitions (for function-calling):
    See TOOL_DEFINITIONS below — pass these to the model's tool_use parameter.
"""

import json
import re
import urllib.request
import urllib.parse

_HEADERS = {"User-Agent": "LAIW/1.0 (Swedish Legal AI; research)"}
_TIMEOUT = 15


def _get(url: str) -> dict | list | None:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _get_html(url: str) -> str | None:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# ── Tool 1: search_sfs ────────────────────────────────────────────────────────

def search_sfs(query: str, max_results: int = 5) -> list[dict]:
    """
    Search Swedish statutes (SFS) by keyword or SFS number.

    Args:
        query: keyword or SFS number (e.g. "avtalslagen" or "1915:218")
        max_results: max number of results to return (default 5)

    Returns:
        List of dicts with keys: dok_id, titel, datum, url
    """
    url = (
        f"https://data.riksdagen.se/dokumentlista/"
        f"?doktyp=sfs&sok={urllib.parse.quote(query)}"
        f"&utformat=json&sz={max_results}&sort=datum&sortorder=desc"
    )
    data = _get(url)
    if not data:
        return []
    docs = data.get("dokumentlista", {}).get("dokument", [])
    if isinstance(docs, dict):
        docs = [docs]
    return [
        {
            "dok_id": d.get("dok_id", ""),
            "titel": d.get("titel", ""),
            "datum": d.get("datum", ""),
            "url": f"https://www.riksdagen.se/sv/dokument-och-lagar/{d.get('dok_id','').lower()}/",
        }
        for d in docs[:max_results]
    ]


# ── Tool 2: get_law ───────────────────────────────────────────────────────────

def get_law(dok_id: str) -> dict:
    """
    Fetch the full text of a Swedish law by its document ID (dok_id).

    Args:
        dok_id: Riksdagen document ID, e.g. "SFS-1915-218" or from search_sfs result

    Returns:
        Dict with keys: dok_id, titel, text (full plain text of the law)
    """
    url = f"https://data.riksdagen.se/dokument/{dok_id.lower()}.json"
    data = _get(url)
    if not data:
        return {"dok_id": dok_id, "titel": "", "text": ""}
    doc = data.get("dokumentstatus", {}).get("dokument", {})
    titel = doc.get("titel", "")
    text_url = doc.get("dokument_url_text", "")
    if text_url:
        if text_url.startswith("//"):
            text_url = "https:" + text_url
        html = _get_html(text_url)
        text = _strip_html(html) if html else ""
    else:
        text = _strip_html(doc.get("text", ""))
    return {"dok_id": dok_id, "titel": titel, "text": text[:50_000]}


# ── Tool 3: search_riksdagen ──────────────────────────────────────────────────

def search_riksdagen(query: str, doctype: str = "prop", max_results: int = 5) -> list[dict]:
    """
    Search Riksdagen documents (propositioner, betänkanden, motioner, etc.).

    Args:
        query: search keywords
        doctype: document type — one of: prop, bet, sou, mot, dir, fr, ip, prot, sfs
        max_results: max results (default 5)

    Returns:
        List of dicts with keys: dok_id, titel, datum, url
    """
    url = (
        f"https://data.riksdagen.se/dokumentlista/"
        f"?doktyp={doctype}&sok={urllib.parse.quote(query)}"
        f"&utformat=json&sz={max_results}&sort=datum&sortorder=desc"
    )
    data = _get(url)
    if not data:
        return []
    docs = data.get("dokumentlista", {}).get("dokument", [])
    if isinstance(docs, dict):
        docs = [docs]
    return [
        {
            "dok_id": d.get("dok_id", ""),
            "titel": d.get("titel", ""),
            "datum": d.get("datum", ""),
            "url": f"https://www.riksdagen.se/sv/dokument-och-lagar/{d.get('dok_id','').lower()}/",
        }
        for d in docs[:max_results]
    ]


# ── Tool 4: search_domstol ────────────────────────────────────────────────────

def search_domstol(query: str, max_results: int = 5) -> list[dict]:
    """
    Search Swedish court decisions (vägledande avgöranden) from domstol.se.

    Args:
        query: search keywords (e.g. "avtalsbrott skadestånd")
        max_results: max results (default 5)

    Returns:
        List of dicts with keys: id, rubrik, domstol, datum, url
    """
    url = (
        f"https://rattsinfosok.domstol.se/lagrummet/rest/api/1.0/rattsfall"
        f"?fritext={urllib.parse.quote(query)}&maxAntal={max_results}"
        f"&sortering=RELEVANS&vagledande=true"
    )
    data = _get(url)
    if not data:
        return []
    hits = data.get("rattsfall", []) if isinstance(data, dict) else data
    return [
        {
            "id": h.get("id", ""),
            "rubrik": h.get("rubrik", ""),
            "domstol": h.get("domstol", {}).get("domstolNamn", "") if isinstance(h.get("domstol"), dict) else "",
            "datum": h.get("avgorandedatum", ""),
            "url": f"https://www.domstol.se/rattsfall/{h.get('id','')}",
        }
        for h in hits[:max_results]
    ]


# ── Tool 5: search_eurlex ─────────────────────────────────────────────────────

def search_eurlex(query: str, max_results: int = 5) -> list[dict]:
    """
    Search EU legislation via EUR-Lex SPARQL endpoint.

    Args:
        query: search keywords (e.g. "GDPR dataskydd" or "förordning livsmedel")
        max_results: max results (default 5)

    Returns:
        List of dicts with keys: celex, title, date, url
    """
    sparql = f"""
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
    SELECT DISTINCT ?celex ?title ?date WHERE {{
      ?doc cdm:resource_legal_id_celex ?celex ;
           cdm:work_date_document ?date .
      OPTIONAL {{ ?doc cdm:expression_title ?title .
                 FILTER(LANG(?title) IN ("sv","en")) }}
      FILTER(CONTAINS(LCASE(STR(?title)), LCASE("{query.split()[0]}")))
    }} ORDER BY DESC(?date) LIMIT {max_results}
    """
    url = (
        "https://publications.europa.eu/webapi/rdf/sparql"
        f"?query={urllib.parse.quote(sparql)}&format=application%2Fsparql-results%2Bjson"
    )
    data = _get(url)
    if not data:
        return []
    results = []
    for b in data.get("results", {}).get("bindings", [])[:max_results]:
        celex = b.get("celex", {}).get("value", "")
        results.append({
            "celex": celex,
            "title": b.get("title", {}).get("value", ""),
            "date": b.get("date", {}).get("value", ""),
            "url": f"https://eur-lex.europa.eu/legal-content/SV/TXT/?uri=CELEX:{celex}",
        })
    return results


# ── Tool definitions for model function-calling ───────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_sfs",
        "description": "Sök i svenska lagar (SFS) via nyckelord eller SFS-nummer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Sökterm, t.ex. 'avtalslagen' eller '1915:218'"},
                "max_results": {"type": "integer", "description": "Max antal resultat (standard 5)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_law",
        "description": "Hämta fulltext för en svensk lag via dess dok_id (från search_sfs).",
        "input_schema": {
            "type": "object",
            "properties": {
                "dok_id": {"type": "string", "description": "Riksdagens dok_id, t.ex. 'SFS-1915-218'"},
            },
            "required": ["dok_id"],
        },
    },
    {
        "name": "search_riksdagen",
        "description": "Sök riksdagsdokument (propositioner, betänkanden, motioner m.m.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Sökterm"},
                "doctype": {
                    "type": "string",
                    "description": "Dokumenttyp: prop, bet, sou, mot, dir, fr, ip, prot, sfs",
                    "default": "prop",
                },
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_domstol",
        "description": "Sök vägledande domstolsavgöranden från svenska domstolar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Sökterm, t.ex. 'skadestånd avtalsbrott'"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_eurlex",
        "description": "Sök EU-lagstiftning via EUR-Lex (förordningar, direktiv m.m.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Sökterm, t.ex. 'GDPR dataskydd'"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
]

TOOL_DISPATCH = {
    "search_sfs": search_sfs,
    "get_law": get_law,
    "search_riksdagen": search_riksdagen,
    "search_domstol": search_domstol,
    "search_eurlex": search_eurlex,
}
