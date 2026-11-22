"""Shared browser helper for scraping collectors.

All scraping MUST go through `cdp_page()`: SeleniumBase launches Chrome (CDP mode)
and Playwright attaches to it with `connect_over_cdp`.

    from hackfinder.browser import cdp_page
    with cdp_page() as page:          # playwright.sync_api.Page
        page.goto("https://example.com", wait_until="domcontentloaded")
        html = page.content()

Collectors run in worker threads (never on the asyncio event loop), so the
Playwright *sync* API is safe here. A semaphore caps concurrent browsers.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator

MAX_BROWSERS = int(os.getenv("HF_MAX_BROWSERS", "3"))
HEADLESS = os.getenv("HF_HEADLESS", "1") != "0"
_sem = threading.BoundedSemaphore(MAX_BROWSERS)


@contextmanager
def cdp_page(locale: str = "en") -> Iterator["object"]:
    from playwright.sync_api import sync_playwright
    from seleniumbase import sb_cdp

    with _sem:
        sb = sb_cdp.Chrome(locale=locale, headless=HEADLESS)
        try:
            endpoint = sb.get_endpoint_url()
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(endpoint)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(30_000)
                yield page
        finally:
            try:
                sb.driver.stop()
            except Exception:
                pass
