"""C2 organizer parsers: small public-source excerpts moved to 2099; no network."""
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).parent / 'fixtures'
IDS = 'hackbarna hackculture hackonvibe hackrice hackspain shenicest indehub loops stormhacks dubhacks hackmeridian hackmty sye makefun hackuk circuitfeed'.split()
FILES = {'hackculture': 'events.json', 'shenicest': 'events.json', 'makefun': 'events.json',
         'circuitfeed': 'event.json', 'hackmty': 'edition.js'}


def fixture(cid):
    return (ROOT / cid / FILES.get(cid, 'event.html')).read_text(encoding='utf-8')


def parse(cid, text):
    module = importlib.import_module('hackfinder.collectors.' + cid)
    data = json.loads(text) if cid in ('hackculture', 'shenicest', 'makefun', 'circuitfeed') else text
    if cid == 'makefun':
        data = data['items']
    if cid == 'hackuk':
        return module.parse(data, 'https://www.hackuk.network/events/hack4health')
    return module.parse(data)


def test_all_future_editions():
    for cid in IDS:
        events = parse(cid, fixture(cid))
        assert len(events) == 1, (cid, [e.title for e in events])
        e = events[0]
        assert e.source == cid and e.start.year == 2099, cid
        assert e.start.utcoffset().total_seconds() == 0 and e.end.utcoffset().total_seconds() == 0, cid
        assert e.url.startswith('https://') and e.organizer, cid
        assert e.format in ('online', 'in-person', 'hybrid'), cid
        assert len(e.signals.get('text', '')) <= 3000, cid
        if e.format != 'online':
            assert e.location and e.country, cid


def test_all_past_editions():
    for cid in IDS:
        assert parse(cid, fixture(cid).replace('2099', '2001')) == [], cid


def test_no_year_inference_from_copyright():
    for cid in ('hackrice', 'dubhacks', 'stormhacks', 'hackmty'):
        assert parse(cid, fixture(cid).replace('2099', 'TBD')) == [], cid


def test_original_urls_and_kinds():
    for cid, host in [('hackbarna', 'luma.com'), ('sye', 'luma.com'), ('dubhacks', 'apply.dubhacks.co'),
                      ('hackculture', 'example.devpost.com'), ('shenicest', 'example.typeform.com'),
                      ('hackmty', 'experience.hackmty.com')]:
        e = parse(cid, fixture(cid))[0]
        assert host in e.url, (cid, e.url)
    for cid in IDS:
        e = parse(cid, fixture(cid))[0]
        mixed = cid in ('hackculture', 'shenicest', 'makefun', 'hackuk', 'circuitfeed')
        assert e.kind == ('unknown' if mixed else 'hackathon'), cid
        assert e.confidence == (0 if mixed else .9), cid


def test_she_timezone_capacity_and_nonhackathon():
    e = parse('shenicest', fixture('shenicest'))[0]
    assert e.start.hour == 1  # 09:00 China is 01:00 UTC.
    assert e.participants is None
    d = json.loads(fixture('shenicest'))
    d['events'][0]['title'] = 'Community Meetup'
    assert parse('shenicest', json.dumps(d)) == []
    d['events'][0]['title'] = 'Test Hackathon'
    d['events'][0]['status'] = 'closed'
    assert parse('shenicest', json.dumps(d)) == []


def test_loops_signals():
    e = parse('loops', fixture('loops'))[0]
    assert e.participants == e.signals['registrations'] == 107
    assert e.prize_usd == e.signals['prize_amount'] == 5000
    assert e.signals['prize_currency'] == 'USD' and len(e.signals['sponsors']) == 4
    assert e.registration_deadline == e.end
    from hackfinder.collectors.loops import listings
    rows = listings((ROOT / 'loops/listing.html').read_text(encoding='utf-8'))
    assert 'agents-open-for-business' in rows


def test_hackrice_source_sponsors_and_tracks():
    e = parse('hackrice', fixture('hackrice'))[0]
    assert 'Capital One' in e.signals['sponsors']
    assert e.signals['themes'] == ['Healthcare', 'Games & Gamification', 'Finance', 'Work & Productivity']
    assert e.participants is None


def test_circuitfeed_credits_are_not_cash():
    e = parse('circuitfeed', fixture('circuitfeed'))[0]
    assert e.participants == 60 and e.signals['prize_noncash'] is True
    assert e.prize_usd is None and 'prize_amount' not in e.signals
    assert e.signals['sponsors'] == ['UnoRouter', 'Swiftalk']
    assert len(e.signals['themes']) == 4
    assert e.registration_deadline == e.end


def test_makefun_attempts_are_not_people():
    e = parse('makefun', fixture('makefun'))[0]
    assert e.participants is None and e.signals['entries'] > 0
    assert e.signals['prize_amount'] == 500 and e.signals['prize_currency'] == 'USDC'
    d = json.loads(fixture('makefun'))
    d['items'][0]['status'] = 'resolved'
    assert parse('makefun', json.dumps(d)) == []


def test_hackculture_coordinates():
    e = parse('hackculture', fixture('hackculture'))[0]
    assert e.signals['lat'] == 12.9767936 and e.signals['lon'] == 77.590082
    assert e.participants == 7000 and e.country == 'IN'


def test_hackculture_detail_cash_and_credits():
    from hackfinder.collectors.hackculture import parse
    d = json.loads((ROOT / 'hackculture/detail.json').read_text(encoding='utf-8'))
    e = parse([d])[0]
    assert e.signals['prize_amount'] == e.prize_usd == 1000
    assert e.signals['prize_currency'] == 'USD' and e.signals['prize_noncash']
    assert 'Omnidimension' in e.signals['sponsors'] and e.signals['themes']
    assert e.registration_deadline.year == 2099


def test_makefun_pagination_and_stalled_cursor(monkeypatch):
    from hackfinder.collectors import makefun
    d = json.loads(fixture('makefun'))
    calls = []
    def fetch(c, url, **kwargs):
        calls.append(kwargs.get('params'))
        return type('Reply', (), {'json': lambda self: {'items': d['items'], 'next_cursor': 'same'}})()
    monkeypatch.setattr(makefun, 'fetch', fetch)
    monkeypatch.setattr(makefun, 'check_robots', lambda *args: None)
    monkeypatch.setattr('time.sleep', lambda *args: None)
    assert len(makefun.collect()) == 1
    assert calls == [{}, {'cursor': 'same'}]


def test_explicit_prize_totals_and_coordinates():
    e = parse('hackmeridian', fixture('hackmeridian'))[0]
    assert e.prize_usd == 30000
    e = parse('sye', fixture('sye'))[0]
    assert e.signals['prize_amount'] == 150000 and e.signals['prize_currency'] == 'SEK'
    assert e.signals['prize_noncash'] and e.prize_usd is None
    e = parse('hackspain', fixture('hackspain'))[0]
    assert e.signals['prize_amount'] == 10000 and e.signals['prize_currency'] == 'EUR'
    e = parse('hackmty', fixture('hackmty'))[0]
    assert e.signals['lat'] == 25.6515 and e.signals['lon'] == -100.2899


def test_hackuk_capacity_and_login_url():
    e = parse('hackuk', fixture('hackuk') + '<a href="/portal">Sign in to register</a>')[0]
    assert e.signals['capacity'] == 150 and e.participants is None
    assert e.url.endswith('/events/hack4health')


def test_schema_cancellation_and_undated():
    from hackfinder.collectors.hackonvibe import parse
    h = fixture('hackonvibe')
    assert parse(h.replace('EventScheduled', 'EventCancelled')) == []
    assert parse('<script type="application/ld+json">{"@type":"Event","name":"TBD"}</script>') == []


def test_fixture_sizes():
    for cid in IDS:
        for p in (ROOT / cid).iterdir():
            if p.suffix != '.tmp':
                assert p.stat().st_size < 100_000, p
