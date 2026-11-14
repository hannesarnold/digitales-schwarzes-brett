from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


CALENDAR_URL = (
    "https://shorturl.appack.de/"
    "sundern_Application_1663675240711?calendarIds="
)

OUTPUT = Path("next-events.json")
MAX_EVENTS = 5


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def parse_iso(value):
    value = clean(value)

    if not value:
        return None

    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def find_image(item):
    """
    Appack kann iconImage unterschiedlich liefern.
    Wir übernehmen nur eine normale http(s)-URL.
    """

    value = item.get("iconImage")

    if isinstance(value, str):
        value = clean(value)
        if value.startswith("http://") or value.startswith("https://"):
            return value

    if isinstance(value, dict):
        for key in (
            "url",
            "src",
            "thumbnailUrl",
            "imageUrl",
        ):
            candidate = clean(value.get(key))

            if (
                candidate.startswith("http://")
                or candidate.startswith("https://")
            ):
                return candidate

    return ""


def clean_location(value):
    if isinstance(value, str):
        return clean(value)

    if isinstance(value, dict):
        parts = []

        for key in (
            "name",
            "title",
            "street",
            "zip",
            "city",
        ):
            item = clean(value.get(key))
            if item and item not in parts:
                parts.append(item)

        return ", ".join(parts)

    return ""


def event_to_output(item):
    return {
        "id": clean(item.get("id")),
        "calendarId": clean(item.get("calendarId")),
        "title": clean(item.get("title")),
        "subtitle": clean(
            item.get("subTitle")
            or item.get("subtitle")
        ),
        "dateStart": clean(item.get("dateStart")),
        "dateEnd": clean(item.get("dateEnd")),
        "allDay": bool(item.get("allDay")),
        "location": clean_location(
            item.get("location")
        ),
        "detailLink": clean(
            item.get("detailLink")
        ),
    }


def main():
    checked_at = datetime.now(
        timezone.utc
    )

    events = []

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
            try:
                host = (
                    urlsplit(response.url)
                    .hostname
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

            data = payload.get("data")

            if not isinstance(data, dict):
                return

            found = data.get(
                "findCalendarEvents"
            )

            if not isinstance(found, list):
                return

            for item in found:
                if isinstance(item, dict):
                    events.append(item)

        page.on(
            "response",
            on_response,
        )

        page.goto(
            CALENDAR_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(12000)

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

        browser.close()

    if not events:
        raise RuntimeError(
            "Keine Kalendertermine in "
            "data.findCalendarEvents gefunden."
        )

    unique = {}

    for item in events:
        event_id = clean(item.get("id"))

        if event_id:
            unique[event_id] = item

    upcoming = []

    for item in unique.values():

        start = parse_iso(
            item.get("dateStart")
        )

        end = parse_iso(
            item.get("dateEnd")
        )

        # Laufende Termine behalten,
        # vergangene Termine entfernen.
        relevant_until = end or start

        if relevant_until is None:
            continue

        if relevant_until < checked_at:
            continue

        upcoming.append(
            (
                start or relevant_until,
                item,
            )
        )

    upcoming.sort(
        key=lambda pair: pair[0]
    )

    selected = [
        event_to_output(item)
        for _, item in upcoming[:MAX_EVENTS]
    ]

    result = {
        "status": "ok",
        "checked_at": checked_at.isoformat(),
        "count": len(selected),
        "events": selected,
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
