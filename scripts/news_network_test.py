from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

NEWS_OVERVIEW = "https://shorturl.appack.de/sundern_Application_1765195867222"

KNOWN_IDS = [
    "6aba4304544591ab405b0c9a",
    "6ab913bf89f46c99873f45eb",
]

OUT = Path("news-network-debug.json")
HEX24_RE = re.compile(r"\b[a-fA-F0-9]{24}\b")

def snippet(text: str, needle: str, radius: int = 350) -> str:
    pos = text.find(needle)
    if pos == -1:
        return ""
    start = max(0, pos - radius)
    end = min(len(text), pos + len(needle) + radius)
    return text[start:end]

def main():
    checked_at = datetime.now(timezone.utc).isoformat()
    matches = []
    all_api_like = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1400, "height": 2200},
            locale="de-DE",
        )

        def on_response(response):
            url = response.url
            ctype = (response.headers.get("content-type") or "").lower()

            interesting_type = any(
                token in ctype
                for token in ("json", "javascript", "text", "html")
            )

            interesting_url = any(
                token in url.lower()
                for token in ("api", "news", "graphql", "application", "appack")
            )

            if interesting_url:
                all_api_like.append({
                    "status": response.status,
                    "content_type": ctype,
                    "url": url,
                })

            if not interesting_type:
                return

            try:
                body = response.text()
            except Exception:
                return

            known_found = [kid for kid in KNOWN_IDS if kid in body]

            if known_found:
                matches.append({
                    "status": response.status,
                    "content_type": ctype,
                    "url": url,
                    "known_ids_found": known_found,
                    "snippets": {
                        kid: snippet(body, kid)
                        for kid in known_found
                    },
                    "hex24_sample": list(dict.fromkeys(HEX24_RE.findall(body)))[:50],
                })

        page.on("response", on_response)

        page.goto(
            NEWS_OVERVIEW,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(15000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        result = {
            "checked_at": checked_at,
            "overview_url": NEWS_OVERVIEW,
            "final_url": page.url,
            "page_title": page.title(),
            "known_ids": KNOWN_IDS,
            "matching_responses": matches,
            "api_like_responses": all_api_like[:200],
        }

        if matches:
            result["status"] = "known_news_ids_found_in_network"
            result["message"] = (
                "Mindestens eine Netzwerk-Antwort enthält bekannte News-IDs. "
                "Damit können wir sehr wahrscheinlich die Datenquelle für die "
                "automatische neueste Meldung direkt verwenden."
            )
        else:
            result["status"] = "known_news_ids_not_found"
            result["message"] = (
                "Die bekannten News-IDs wurden noch nicht in den gelesenen "
                "Netzwerk-Antworten gefunden. Dann prüfen wir im nächsten Schritt "
                "gezielt Klicks auf den ersten Beitrag."
            )

        OUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()

if __name__ == "__main__":
    main()
