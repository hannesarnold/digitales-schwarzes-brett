from __future__ import annotations

import json
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

CALENDAR_URL = (
    "https://shorturl.appack.de/"
    "sundern_Application_1663675240711?calendarIds="
)

DATE_KEYS = (
    "start", "end", "date", "time",
    "from", "to", "begin"
)

TITLE_KEYS = (
    "title", "name", "headline", "subject"
)


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def safe_url(url):
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except Exception:
        return "(unlesbar)"


def selected_fields(item):
    result = {}

    for key, value in item.items():
        lower = key.lower()

        if any(x in lower for x in (
            "title", "name", "headline",
            "start", "end", "date",
            "time", "location", "place",
            "id", "guid"
        )):
            if isinstance(value, (str, int, float, bool)) or value is None:
                text = clean(value)
                if len(text) > 240:
                    text = text[:240] + "…"
                result[key] = text

    return result


def collect(value, path, candidates, key_paths):
    if isinstance(value, dict):
        keys = list(value.keys())

        if any(
            any(term in key.lower() for term in (
                "calendar", "event", "appointment",
                "termin", "start", "date"
            ))
            for key in keys
        ):
            key_paths.append({
                "path": path,
                "keys": keys[:40],
            })

        lower_keys = [k.lower() for k in keys]
        has_title = any(
            any(t == k or t in k for t in TITLE_KEYS)
            for k in lower_keys
        )
        has_date = any(
            any(t in k for t in DATE_KEYS)
            for k in lower_keys
        )

        if has_title and has_date:
            fields = selected_fields(value)
            if fields:
                candidates.append({
                    "path": path,
                    "fields": fields,
                })

        for key, child in value.items():
            collect(
                child,
                f"{path}.{key}",
                candidates,
                key_paths,
            )

    elif isinstance(value, list):
        for i, child in enumerate(value[:200]):
            collect(
                child,
                f"{path}[{i}]",
                candidates,
                key_paths,
            )


def main():
    candidates = []
    key_paths = []
    responses = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1400, "height": 2200},
            locale="de-DE",
        )

        def on_response(response):
            try:
                host = (
                    urlsplit(response.url).hostname
                    or ""
                ).lower()
            except Exception:
                host = ""

            if not (
                host == "appack.de"
                or host.endswith(".appack.de")
            ):
                return

            try:
                payload = response.json()
            except Exception:
                return

            responses.append({
                "url": safe_url(response.url),
                "status": response.status,
            })

            collect(
                payload,
                "$",
                candidates,
                key_paths,
            )

        page.on("response", on_response)

        page.goto(
            CALENDAR_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(12000)

        try:
            page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
        except Exception:
            pass

        page.wait_for_timeout(5000)

        browser.close()

    # Deduplizieren, damit Logs übersichtlich bleiben.
    unique_responses = []
    seen = set()
    for item in responses:
        key = (item["url"], item["status"])
        if key not in seen:
            seen.add(key)
            unique_responses.append(item)

    unique_candidates = []
    seen_candidate = set()

    for item in candidates:
        key = json.dumps(
            item["fields"],
            sort_keys=True,
            ensure_ascii=False,
        )
        if key not in seen_candidate:
            seen_candidate.add(key)
            unique_candidates.append(item)

    unique_paths = []
    seen_path = set()
    for item in key_paths:
        key = (
            item["path"],
            tuple(item["keys"]),
        )
        if key not in seen_path:
            seen_path.add(key)
            unique_paths.append(item)

    report = {
        "responses": unique_responses[:30],
        "candidate_count": len(unique_candidates),
        "candidates": unique_candidates[:30],
        "interesting_paths": unique_paths[:40],
    }

    print("KALENDER-DIAGNOSE (ohne Query-Parameter/JWT):")
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not unique_candidates:
        raise RuntimeError(
            "Noch keine Termin-Kandidaten erkannt."
        )


if __name__ == "__main__":
    main()
