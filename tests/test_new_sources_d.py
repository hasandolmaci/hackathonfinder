"""Offline plain-assert coverage for group B; public fragments use 2099 event dates."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hackfinder.collectors import (aanmelder, bayerninnovativ, brainport, eurodefense, hackatum,
    starthack, startupamsterdam, techeurope, tudelft, vu, yesdelft, zukunftgesundheit)
from hackfinder.collectors import _ecosystem_util as util

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(cid, name='event.html'):
    return (FIXTURES / cid / name).read_text(encoding='utf-8')


def valid(e, kind='unknown'):
    assert e.start and e.start.utcoffset() == timedelta(0)
    assert e.url.startswith('https://')
    assert e.kind == kind
    assert e.confidence == (0 if kind == 'unknown' else .9)
    assert e.classified_by == ('none' if kind == 'unknown' else 'source')
    assert len(e.signals.get('text', '')) <= 3000


def test_hackatum_edition_and_expiry():
    html = fixture('hackatum', 'edition.html')
    e, = hackatum.parse(html)
    valid(e, 'hackathon')
    assert e.start == datetime(2099, 11, 26, 23, tzinfo=timezone.utc)
    assert e.end == datetime(2099, 11, 28, 23, tzinfo=timezone.utc)
    assert e.country == 'Germany' and e.organizer == 'Technical University of Munich'
    assert hackatum.parse(html.replace('2099', '2000')) == []


def test_techeurope_original_registration_and_prize():
    html = fixture('techeurope')
    e, = techeurope.parse(html, 'https://hackathons.techeurope.io/events/big-berlin-hack')
    valid(e, 'hackathon')
    assert e.url == 'https://luma.com/bbh'
    assert e.start == datetime(2099, 11, 28, 8, 30, tzinfo=timezone.utc)
    assert e.signals['prize_amount'] == 10000 and e.signals['prize_currency'] == 'EUR'
    assert 'Aikido' in e.signals['sponsors'] and 'AIAikido' not in e.signals['sponsors']
    assert e.country == 'Germany' and e.location == 'Berlin, Germany'
    assert techeurope.parse(html.replace('2099', '2000'), e.url) == []


def test_eurodefense_bootstrap_no_execution():
    html = fixture('eurodefense', 'bootstrap.html')
    e, = eurodefense.parse(html)
    valid(e)
    assert e.url == 'https://events.eurodefense.tech/berlin-2099'
    assert e.organizer == 'European Defense Tech Hub'
    assert e.participants == 184 and e.signals['registrations'] == 184
    assert 52 < e.signals['lat'] < 53 and 13 < e.signals['lon'] < 14
    assert eurodefense.parse(html.replace('2099', '2000')) == []
    assert eurodefense.parse(html.replace('Hackathon', 'Summit')) == []
    assert eurodefense.parse(html.replace('status:"upcoming"', 'status:"cancelled"').replace('status:"running"', 'status:"cancelled"').replace('status:"waiting"', 'status:"cancelled"')) == []


def test_bayern_detail_and_general_kind():
    e, = bayerninnovativ.parse(fixture('bayerninnovativ'), 'https://www.bayern-innovativ.de/events-termine/detail/healthcare/')
    valid(e)
    assert e.url == 'https://forms.office.com/e/DTztzcTfpz'
    assert 'München' in e.location and e.country == 'Germany'
    assert e.start.year == 2099 and e.end > e.start
    assert bayerninnovativ.parse(fixture('bayerninnovativ').replace('2099', '2000'), e.url) == []


def test_aanmelder_sitemap_deduplicates_event_roots():
    urls = aanmelder.event_urls(fixture('aanmelder', 'sitemap.xml'))
    assert urls == ['https://www.aanmelder.nl/hack-the-power-grid-2099', 'https://www.aanmelder.nl/whatthehack']


def test_aanmelder_microdata_and_unknown_venue():
    html = fixture('aanmelder')
    e, = aanmelder.parse(html, 'https://www.aanmelder.nl/hack-the-power-grid-2099')
    valid(e)
    assert e.url.endswith('/hack-the-power-grid-2099/subscribe')
    assert e.signals['paid_entry'] is False and e.location is None
    assert e.organizer == 'Hack the Power Grid 2099'
    assert aanmelder.parse(html.replace('2099', '2000'), e.url) == []
    assert aanmelder.parse(html.replace('EventScheduled', 'EventCancelled'), e.url) == []


def test_start_global_and_tour_cards():
    e, = starthack.parse(fixture('starthack'))
    valid(e, 'hackathon')
    assert e.country == 'Switzerland' and e.url == 'https://starthack.eu/#/register'
    events = starthack.tours(fixture('starthack', 'tours.html'))
    assert len(events) >= 4
    flagship = next(e for e in events if e.title == 'START Hack 2099')
    assert flagship.prize == '10000 CHF' and flagship.signals['prize_amount'] == 10000
    assert starthack.tours(fixture('starthack', 'tours.html').replace('2099', '2000')) == []


def test_start_munich_registration_links():
    events = starthack.munich(fixture('starthack', 'munich.html'))
    assert len(events) == 2
    for e in events:
        valid(e, 'hackathon')
        assert e.organizer == 'START Munich' and e.country == 'Germany'
    assert any(e.url == 'https://luma.com/start-7spj' for e in events)


def test_tudelft_nested_schema_and_keyword_filter():
    html = fixture('tudelft')
    e, = tudelft.parse(html, 'https://www.tudelft.nl/en/events/2099/ctf')
    valid(e)
    assert e.title == 'TU Delft CTF 2099' and e.organizer == 'TU Delft'
    assert e.start.hour == 13 and e.format == 'in-person'
    assert tudelft.parse(html.replace('CTF', 'BioDay'), e.url) == []


def test_vu_public_search_wall_time_and_registration():
    row, = json.loads(fixture('vu', 'search.json'))['value']
    e = vu.parse(row, fixture('vu'))
    valid(e)
    assert e.start == datetime(2099, 11, 24, 15, tzinfo=timezone.utc)
    assert e.url == 'https://libcal.vu.nl/event/4621445' and e.organizer == 'Charlie Greene'
    assert e.country == 'Netherlands'
    assert vu.parse(dict(row, Title='Library workshop', IntroText='Pizza')) is None
    assert vu.parse(dict(row, SubTitle=row['SubTitle'].replace('2099', '2000'))) is None


def test_yesdelft_event_info_fields():
    e, = yesdelft.parse(fixture('yesdelft'), 'https://yesdelft.com/events/energy-hackathon/')
    valid(e)
    assert e.url == 'https://newenergychallenge.com/'
    assert e.start.year == 2099 and e.registration_deadline.year == 2099
    assert e.location is None and e.organizer == 'YES!Delft'


def test_startupamsterdam_original_luma_url():
    e, = startupamsterdam.parse(fixture('startupamsterdam'), 'https://www.iamsterdam.com/en/business/calendar/events/all/wtc-buildathon')
    valid(e)
    assert e.url == 'https://luma.com/ams-feb11' and e.country == 'NL'


def test_future_health_schema_partners_and_tickets():
    html = fixture('zukunftgesundheit')
    e, = zukunftgesundheit.parse(html)
    valid(e, 'hackathon')
    assert e.url == 'https://pretix.eu/zukunftgesundheit/hackathon/'
    assert e.start.hour == 17 and e.country == 'DE'
    assert 'Roboyo' in e.signals['sponsors'] and 'agentic AI' in e.signals['themes']
    assert 'AOK Neckar-Fils' in e.organizer and 'HfWU' in e.organizer
    assert zukunftgesundheit.parse(html.replace('EventScheduled', 'EventCancelled')) == []


def test_strict_multilingual_keywords():
    for name in ('Hack the Power Grid', 'hackathon', 'hakaton', 'CTF', 'NWERC', 'programming contest',
                 'Programmierwettbewerb', 'programmeerwedstrijd', 'game jam', 'buildathon', 'datathon', 'ideathon'):
        assert util.HACK.search(name)
    for name in ('Networking drinks', 'AI conference', 'Pitch contest', 'startup dinner'):
        assert not util.HACK.search(name)


def test_schema_signals_and_no_price_as_prize():
    raw = {'@type': 'Event', 'name': 'Datathon', 'startDate': '2099-01-01T10:00:00+01:00',
        'endDate': '2099-01-02T17:00:00+01:00', 'description': 'x' * 4000, 'attendeeCount': 42,
        'location': {'@type': 'Place', 'name': 'Delft', 'geo': {'latitude': 52, 'longitude': 4.3}},
        'sponsor': [{'name': 'Partner'}], 'offers': {'url': '/register', 'price': 250, 'priceCurrency': 'EUR'}}
    html = '<script type="application/ld+json">' + json.dumps(raw) + '</script>'
    e, = util.parse_schema(html, 'test', 'https://example.org/event')
    valid(e)
    assert e.url == 'https://example.org/register'
    assert e.participants == 42 and e.signals['lat'] == 52 and e.signals['sponsors'] == ['Partner']
    assert e.prize is None and 'prize_amount' not in e.signals
    assert len(e.signals['text']) == 3000


def test_listing_exhausts_pagination_and_prefilters_details():
    source = dict(startupamsterdam.SOURCE, url='https://example.org/list')
    docs = {'https://example.org/list': '<a class="event" href="/talk">Networking</a><div aria-label="Pagination"><a href="/list?page=2">Next</a></div>',
        'https://example.org/list?page=2': '<a class="event" href="/hack">Game jam</a><div aria-label="Pagination"><a href="/list?page=3">Next</a></div>',
        'https://example.org/list?page=3': '<a class="event" href="/dinner">Dinner</a>',
        'https://example.org/hack': fixture('startupamsterdam')}
    requested = []
    def fetch(c, url):
        requested.append(url)
        return SimpleNamespace(text=docs[url])
    with patch.object(util, 'robots'), patch.object(util, 'get', fetch):
        events = util.listing(source, 'a.event')
    assert len(events) == 1
    assert sorted(requested) == sorted(docs)  # same pages fetched; detail may come before the last page
    assert 'https://example.org/talk' not in requested and 'https://example.org/dinner' not in requested


def test_listing_safety_limit_warns():
    html = '<a class="event" href="/talk">Networking</a><div aria-label="Pagination"><a href="/page2">Next</a></div>'
    with patch.object(util, 'MAX_PAGES', 1), patch.object(util, 'robots'), patch.object(util, 'get', return_value=SimpleNamespace(text=html)), patch.object(util, 'warn_limit') as warn:
        assert util.listing({'id': 'test', 'url': 'https://example.org/'}, 'a.event') == []
        warn.assert_called_once()


def test_listing_fixtures_remain_parseable():
    selectors = {'yesdelft': 'a[href*="yesdelft.com/events/"]', 'startupamsterdam': 'a[href*="/business/calendar/events/"]',
        'brainport': '.media-overview-item--event a.media-overview-item__inner', 'tudelft': 'a[href*="/en/events/"]'}
    for cid, selector in selectors.items():
        assert util.HTMLParser(fixture(cid, 'listing.html')).css(selector)
    assert all(p.stat().st_size < 100_000 for cid in selectors for p in (FIXTURES / cid).iterdir())


if __name__ == '__main__':
    tests = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]
    for test in tests:
        test()
        print(f'PASS {test.__name__}')
    print(f'{len(tests)} offline tests passed')
