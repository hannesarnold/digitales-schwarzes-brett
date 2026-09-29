from __future__ import annotations

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NEWS_OVERVIEW = "https://shorturl.appack.de/sundern_Application_1765195867222"
OUTPUT_FILE = Path("latest-news.json")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

# Appack Shared-News-Links sehen z. B. so aus:
# https://application.appack.de/news/de/shared/6aba4304544591ab405b0c9a
SHARED_LINK_RE = re.compile(
    r'https?://application\.appack\.de/news/de/shared/[A-Za-z0-9]+'
    r'(?:\?[^"\'<>\s\\]*)?',
    re.IGNORECASE,
)

RELATIVE_SHARED_RE = re.compile(
    r'(?:"|\')(/news/de/shared/[A-Za-z0-9]+(?:\?[^"\'<>\s\\]*)?)(?:"|\')',
    re.IGNORECASE,
)

META_RE = re.compile(
    r'<meta\s+[^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\'][^>]*>',
    re.IGNORECASE,
)

META_RE_REVERSED = re.compile(
    r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)


def fetch(url: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        final_url = response.geturl()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), final_url


def normalize_page_source(source: str) -> str:
    # Manche JavaScript-Blöcke enthalten URLs escaped als https:\/\/...
    return (
        source.replace(r"\/", "/")
        .replace(r"\u002F", "/")
        .replace(r"\u002f", "/")
        .replace("&amp;", "&")
    )


def find_shared_links(source: str) -> list[str]:
    source = normalize_page_source(source)
    found: list[str] = []

    for match in SHARED_LINK_RE.findall(source):
        clean = html.unescape(match)
        if clean not in found:
            found.append(clean)

    for relative in RELATIVE_SHARED_RE.findall(source):
        absolute = urllib.parse.urljoin("https://application.appack.de", html.unescape(relative))
        if absolute not in found:
            found.append(absolute)

    return found


def read_meta(source: str) -> dict[str, str]:
    meta: dict[str, str] = {}

    for key, value in META_RE.findall(source):
        meta[key.lower()] = html.unescape(value).strip()

    for value, key in META_RE_REVERSED.findall(source):
        meta[key.lower()] = html.unescape(value).strip()

    return meta


def extract_title(source: str, meta: dict[str, str]) -> str:
    for key in ("og:title", "twitter:title"):
        if meta.get(key):
            return meta[key]

    match = re.search(r"<title[^>]*>(.*?)</title>", source, re.I | re.S)
    if match:
        title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
        return title

    return ""


def extract_date(meta: dict[str, str], source: str) -> str:
    for key in (
        "article:published_time",
        "date",
        "datepublished",
        "publish-date",
    ):
        if meta.get(key):
            return meta[key]

    # Häufig in JSON-LD / eingebetteten Daten
    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"publishedAt"\s*:\s*"([^"]+)"',
        r'"createdAt"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, source, re.I)
        if match:
            return html.unescape(match.group(1))

    return ""


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()

    try:
        overview_html, final_overview_url = fetch(NEWS_OVERVIEW)
    except Exception as exc:
        print(f"FEHLER: News-Übersicht konnte nicht geladen werden: {exc}", file=sys.stderr)
        return 1

    links = find_shared_links(overview_html)

    result = {
        "checked_at": now,
        "overview_url": NEWS_OVERVIEW,
        "overview_final_url": final_overview_url,
        "status": "ok" if links else "no_shared_link_found",
        "shared_links_found": len(links),
    }

    if not links:
        # Für den ersten Test besonders wichtig:
        # Wir schreiben trotzdem eine JSON-Datei, damit man sieht,
        # dass der Workflow gelaufen ist und wo das Problem liegt.
        result["message"] = (
            "Die Appack-News-Seite wurde geladen, aber im ausgelieferten HTML "
            "wurde kein /news/de/shared/-Link gefunden. Wahrscheinlich werden "
            "die Beiträge erst per JavaScript nachgeladen."
        )
        OUTPUT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(result["message"])
        return 0

    latest_url = links[0]

    try:
        article_html, final_article_url = fetch(latest_url)
        meta = read_meta(article_html)

        result.update(
            {
                "latest_url": final_article_url,
                "title": extract_title(article_html, meta),
                "image": meta.get("og:image", ""),
                "description": meta.get("og:description", "")
                or meta.get("description", ""),
                "published_at": extract_date(meta, article_html),
            }
        )
    except Exception as exc:
        # Der Link selbst ist schon wertvoll, selbst wenn das Auslesen
        # des Artikels einmal scheitert.
        result.update(
            {
                "latest_url": latest_url,
                "article_read_error": str(exc),
            }
        )

    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
