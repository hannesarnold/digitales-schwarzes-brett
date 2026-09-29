from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

NEWS_OVERVIEW = "https://shorturl.appack.de/sundern_Application_1765195867222"
LATEST_FILE = Path("latest-news.json")
DEBUG_FILE = Path("news-debug.json")

SHARED_RE = re.compile(
    r"https?://application\.appack\.de/news/de/shared/[A-Za-z0-9]+(?:\?[^\"'<>\s]*)?",
    re.I,
)

def uniq(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out

def main():
    checked_at = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1400, "height": 2200},
            locale="de-DE",
        )

        page.goto(
            NEWS_OVERVIEW,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Appack lädt Inhalte dynamisch nach.
        page.wait_for_timeout(12000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        final_url = page.url
        title = page.title()
        html = page.content()

        # Alle sichtbaren/gerenderten Links sammeln.
        hrefs = page.locator("a").evaluate_all(
            """els => els.map(a => a.href || a.getAttribute('href') || '')"""
        )
        hrefs = uniq(hrefs)

        # Auch typische URL-Attribute prüfen, falls Appack keine normalen <a>-Links nutzt.
        attrs = page.locator("[href], [data-href], [data-url], [onclick]").evaluate_all(
            """els => els.map(el => ({
                text: (el.innerText || '').trim().slice(0, 200),
                href: el.getAttribute('href') || '',
                dataHref: el.getAttribute('data-href') || '',
                dataUrl: el.getAttribute('data-url') || '',
                onclick: el.getAttribute('onclick') || ''
            }))"""
        )

        candidates = []

        # 1. Direkte Links aus <a>
        for href in hrefs:
            if "/news/" in href or "application.appack.de" in href:
                candidates.append(href)

        # 2. Shared-Links direkt aus komplett gerendertem HTML
        candidates.extend(SHARED_RE.findall(html))

        # 3. URLs aus data-Attributen / onclick
        for item in attrs:
            for key in ("href", "dataHref", "dataUrl", "onclick"):
                value = item.get(key, "")
                if not value:
                    continue
                for found in SHARED_RE.findall(value):
                    candidates.append(found)

        candidates = uniq(candidates)
        shared = [u for u in candidates if "/news/de/shared/" in u]

        debug = {
            "checked_at": checked_at,
            "overview_url": NEWS_OVERVIEW,
            "final_url": final_url,
            "page_title": title,
            "shared_links_found": shared,
            "interesting_links": candidates[:100],
            "all_links_sample": hrefs[:100],
            "element_sample": attrs[:100],
        }

        latest = {
            "checked_at": checked_at,
            "overview_url": NEWS_OVERVIEW,
        }

        if shared:
            latest["status"] = "ok"
            latest["latest_url"] = shared[0]
            latest["message"] = "Mindestens ein Shared-News-Link wurde nach dem JavaScript-Laden gefunden."
        else:
            latest["status"] = "browser_loaded_but_no_shared_link"
            latest["message"] = (
                "Die News-Seite wurde mit einem echten Browser inklusive JavaScript geladen, "
                "aber es wurde noch kein /news/de/shared/-Link im DOM gefunden. "
                "Dann müssen wir im nächsten Schritt gezielt den ersten News-Eintrag anklicken "
                "oder die von Appack verwendete Datenquelle im Browser-Netzwerk auswerten."
            )

        LATEST_FILE.write_text(
            json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        DEBUG_FILE.write_text(
            json.dumps(debug, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print(json.dumps(latest, ensure_ascii=False, indent=2))
        browser.close()

if __name__ == "__main__":
    main()
