from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


NEWS_OVERVIEW = (
    "https://shorturl.appack.de/"
    "sundern_Application_1765195867222"
)

COMPONENT_ID = "sundern_Application_1765195867222"

OUTPUT = Path("latest-news.json")


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def safe_url_for_log(url):
    """
    Entfernt absichtlich Query-Parameter.
    So wird niemals ein JWT oder anderer temporärer Token
    in den GitHub-Action-Logs ausgegeben.
    """
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except Exception:
        return "(URL nicht lesbar)"


def looks_like_news_item(value):
    if not isinstance(value, dict):
        return False

    news_id = clean_text(
        value.get("id") or value.get("guid")
    )

    title = clean_text(
        value.get("title")
    )

    published = clean_text(
        value.get("publishedDate")
        or value.get("publishedAt")
        or value.get("date")
    )

    return bool(
        news_id
        and title
        and published
    )


def collect_news_items(value, target):
    """
    Durchsucht die komplette JSON-Antwort rekursiv.

    Damit sind wir nicht mehr darauf angewiesen,
    dass Appack die Daten exakt unter:
        data.newsFeed
    zurückgibt.
    """

    if isinstance(value, dict):

        if looks_like_news_item(value):
            target.append(value)

        for child in value.values():
            collect_news_items(child, target)

    elif isinstance(value, list):

        for child in value:
            collect_news_items(child, target)


def get_published_date(item):
    return clean_text(
        item.get("publishedDate")
        or item.get("publishedAt")
        or item.get("date")
    )


def find_image(item):
    """
    Sucht ein Vorschaubild in mehreren möglichen
    Appack-Strukturen.
    """

    # Bisherige Struktur
    media_refs = item.get("mediaRefs")

    if isinstance(media_refs, list):
        for media in media_refs:

            if not isinstance(media, dict):
                continue

            for key in (
                "thumbnailUrl",
                "url",
                "src",
                "imageUrl",
            ):
                candidate = clean_text(
                    media.get(key)
                )

                if candidate:
                    return candidate

    # Mögliche direkte Felder
    for key in (
        "thumbnailUrl",
        "imageUrl",
        "image",
        "picture",
    ):
        candidate = item.get(key)

        if isinstance(candidate, str):
            candidate = clean_text(candidate)

            if candidate.startswith("http"):
                return candidate

        if isinstance(candidate, dict):

            for nested_key in (
                "thumbnailUrl",
                "url",
                "src",
            ):
                nested = clean_text(
                    candidate.get(nested_key)
                )

                if nested:
                    return nested

    return ""


def main():

    checked_at = datetime.now(
        timezone.utc
    ).isoformat()

    news_entries = []

    diagnostics = {
        "json_responses": 0,
        "appack_json_responses": 0,
        "candidate_news_entries": 0,
        "responses": [],
    }

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1400,
                "height": 2200,
            },
            locale="de-DE",
        )

        def on_response(response):

            ctype = (
                response.headers
                .get("content-type", "")
                .lower()
            )

            try:
                hostname = (
                    urlsplit(response.url)
                    .hostname
                    or ""
                ).lower()
            except Exception:
                hostname = ""

            # Alle Appack-Antworten prüfen.
            # Wir verlassen uns absichtlich NICHT mehr darauf,
            # dass Appack den Content-Type korrekt als JSON meldet.
            if not (
                hostname == "appack.de"
                or hostname.endswith(
                    ".appack.de"
                )
            ):
                return

            if (
                "application/json" in ctype
                or "+json" in ctype
            ):
                diagnostics[
                    "json_responses"
                ] += 1

            diagnostics[
                "appack_json_responses"
            ] += 1

            if len(
                diagnostics["responses"]
            ) < 20:
                diagnostics["responses"].append(
                    {
                        "url": safe_url_for_log(
                            response.url
                        ),
                        "status": response.status,
                    }
                )

            try:
                payload = response.json()
            except Exception:
                return

            before = len(news_entries)

            collect_news_items(
                payload,
                news_entries,
            )

            diagnostics[
                "candidate_news_entries"
            ] += (
                len(news_entries) - before
            )

        page.on(
            "response",
            on_response,
        )

        page.goto(
            NEWS_OVERVIEW,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Appack ausreichend Zeit geben.
        page.wait_for_timeout(12000)

        # Manche Webapps laden Inhalte erst beim Scrollen nach.
        try:
            page.evaluate(
                """
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                )
                """
            )
        except Exception:
            pass

        page.wait_for_timeout(5000)

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=10000,
            )
        except Exception:
            pass

        browser.close()

    if not news_entries:

        print(
            "DIAGNOSE (ohne Tokens/JWT):"
        )

        print(
            json.dumps(
                diagnostics,
                ensure_ascii=False,
                indent=2,
            )
        )

        raise RuntimeError(
            "Keine News-Einträge in den "
            "Appack-JSON-Antworten gefunden."
        )

    # Doppelte Einträge entfernen.
    unique = {}

    for item in news_entries:

        news_id = clean_text(
            item.get("id")
            or item.get("guid")
        )

        if news_id:
            unique[news_id] = item

    items = list(
        unique.values()
    )

    # Neueste Meldung zuerst.
    items.sort(
        key=get_published_date,
        reverse=True,
    )

    latest = items[0]

    news_id = clean_text(
        latest.get("id")
        or latest.get("guid")
    )

    title = clean_text(
        latest.get("title")
    )

    subtitle = clean_text(
        latest.get("subtitle")
    )

    published = get_published_date(
        latest
    )

    shared_url = (
        "https://application.appack.de/"
        f"news/de/shared/{news_id}"
        f"?component={COMPONENT_ID}"
    )

    result = {
        "status": "ok",
        "checked_at": checked_at,
        "id": news_id,
        "title": title,
        "subtitle": subtitle,
        "publishedDate": published,
        "url": shared_url,
        "image": find_image(latest),
    }

    OUTPUT.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
