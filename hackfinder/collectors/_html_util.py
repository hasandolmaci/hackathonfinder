"""HTML-only bootstrap readers for rendered listings."""
import json
import re
from datetime import datetime, timezone
from selectolax.lexbor import LexborHTMLParser as HTMLParser


def objects(html):
    """Read JSON and joined Next Flight payloads without executing JavaScript."""
    decoder = json.JSONDecoder()
    def literals(text):
        pos = 0
        while match := re.search(r'[\[{]', text[pos:]):
            pos += match.start()
            try:
                value, size = decoder.raw_decode(text[pos:])
            except ValueError:
                pos += 1
                continue
            yield value
            pos += size
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    chunks = []
    for script in HTMLParser(html).css('script:not([src])'):
        text = script.text()
        for value in literals(text):
            if '__next_f.push' in text and isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
                chunks.append(value[1])
                continue
            # Marko serializes Date fields separately from the event records.
            if isinstance(value, dict) and isinstance(value.get('o'), dict):
                for patch in value.get('$$', []):
                    if patch.get('r', {}).get('type') != 'Date':
                        continue
                    target = value['o']
                    path = patch['l']
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = patch['r']['value']
            yield from walk(value)
    for value in literals(''.join(chunks)):
        yield from walk(value)


def current(start, end):
    now = datetime.now(timezone.utc)
    value = end or start
    if value and value.time() == datetime.min.time():
        return value.date() >= now.date()
    return value is None or value >= now


def load(page, url, selector):
    """Navigation only; extraction belongs to parse(html, base_url)."""
    response = page.goto(url, wait_until='domcontentloaded', timeout=20000)
    if response and response.status >= 400:
        raise RuntimeError(f'HTTP {response.status} at {url}')
    page.wait_for_selector(selector, timeout=12000)
