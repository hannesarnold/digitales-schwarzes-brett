from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

NEWS_OVERVIEW = "https://shorturl.appack.de/sundern_Application_1765195867222"
COMPONENT_ID = "sundern_Application_1765195867222"
OUTPUT = Path("latest-news.json")

def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()

def main():
    checked_at = datetime.now(timezone.utc).isoformat()
    news_entries = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1400, "height": 2200},
            locale="de-DE",
        )

        def on_response(response):
            if response.url != "https://api.appack.de/graphql":
                return

            ctype = (response.headers.get("content-type") or "").lower()
            if "application/json" not in ctype:
                return

            try:
                payload = response.json()
            except Exception:
                return

            if not isinstance(payload, dict):
                return

            data = payload.get("data")
            if not isinstance(data, dict):
                return

            feed = data.get("newsFeed")
            if not isinstance(feed, list):
                return

            for item in feed:
                if isinstance(item, dict):
                    news_entries.append(item)

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

        browser.close()

    if not news_entries:
        raise RuntimeError(
            "Keine News-Einträge aus der Appack-GraphQL-Antwort gefunden."
        )

    # Doppelte Einträge entfernen, falls dieselbe GraphQL-Antwort mehrfach kam.
    unique = {}
    for item in news_entries:
        news_id = clean_text(item.get("id") or item.get("guid"))
        if news_id:
            unique[news_id] = item

    items = list(unique.values())

    def sort_key(item):
        return clean_text(item.get("publishedDate"))

    items.sort(key=sort_key, reverse=True)

    latest = items[0]

    news_id = clean_text(latest.get("id") or latest.get("guid"))
    title = clean_text(latest.get("title"))
    subtitle = clean_text(latest.get("subtitle"))
    published = clean_text(latest.get("publishedDate"))

    shared_url = (
        f"https://application.appack.de/news/de/shared/{news_id}"
        f"?component={COMPONENT_ID}"
    )

    # Optional Vorschaubild suchen.
    image_url = ""

    media_refs = latest.get("mediaRefs")
    if isinstance(media_refs, list):
        for media in media_refs:
            if not isinstance(media, dict):
                continue
            for key in ("thumbnailUrl", "url", "src"):
                candidate = clean_text(media.get(key))
                if candidate:
                    image_url = candidate
                    break
            if image_url:
                break

    result = {
        "status": "ok",
        "checked_at": checked_at,
        "id": news_id,
        "title": title,
        "subtitle": subtitle,
        "publishedDate": published,
        "url": shared_url,
        "image": image_url,
    }

    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
