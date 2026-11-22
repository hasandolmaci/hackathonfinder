"""Offline parser regressions. Run: .venv\\Scripts\\python tests\\test_parsers.py

Set HF_PARSER_PAGES to relocate the browser snapshots. Counts describe these
snapshots on 2026-11-22; date filtering deliberately uses the real UTC clock.
"""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from hackfinder.collectors import ctftime, ethglobal, kaggle, hackathoncom, lablab, luma, meetup

PAGES = Path(os.environ.get('HF_PARSER_PAGES', r'C:\Users\hasan\AppData\Local\Temp\claude\98baf456b77d57f6\ddcb85d0-6bf3-4dc9-b896-1d6cb647e0cd\scratchpad\pages'))


def check_fields(events):
    assert len({e.url for e in events}) == len(events)
    for e in events:
        assert e.title.strip() and e.url.startswith('https://')
        for value in (e.start, e.end, e.registration_deadline):
            assert value is None or value.utcoffset() == timedelta(0)
        if e.start and e.end:
            assert e.start <= e.end
        if e.end:
            assert e.end.date() >= datetime.now(timezone.utc).date()
        if e.format == 'online':
            assert e.location is None


def test_snapshots():
    parsed = {}
    for module in (ethglobal, kaggle, hackathoncom, lablab):
        name = module.SOURCE['id']
        html = (PAGES / (name + '.html')).read_text(encoding='utf-8')
        events = module.parse(html, getattr(module, 'LISTING', module.SOURCE['url']))
        check_fields(events)
        parsed[name] = events
        print(f'{name}: {len(events)} events')
    eth = {e.title: e for e in parsed['ethglobal']}
    assert len(eth) == 5
    assert all(e.kind == 'hackathon' and e.classified_by == 'source' for e in eth.values())
    assert eth['Agentic Markets'].start == datetime(2026, 12, 3, 5, tzinfo=timezone.utc)
    assert eth['Agentic Markets'].end == datetime(2026, 12, 10, 5, tzinfo=timezone.utc)
    assert eth['Agentic Markets'].format == 'online'
    assert eth['ETHGlobal Cannes 2027'].location == 'Cannes, France'
    assert not any('Pragma' in title or 'ETHConf' in title for title in eth)
    kg = {e.source_id: e for e in parsed['kaggle']}
    assert len(kg) == 25
    assert all(e.kind == 'coding_competition' and e.format == 'online' for e in kg.values())
    assert kg['nfl-big-data-bowl-2027'].prize == '$100,000'
    assert kg['nfl-big-data-bowl-2027'].organizer == 'The National Football League'
    assert 'arc-prize-2026-arc-agi-2' not in kg
    # This snapshot contains relative labels only, not exact deadlines.
    assert all(e.start is None and e.end is None for e in kg.values())
    hc = {e.title: e for e in parsed['hackathoncom']}
    assert len(hc) == 2  # The saved online listing explicitly says 2 out of 2.
    assert hc['AI Builders Challenge - North America'].end == datetime(2026, 12, 2, tzinfo=timezone.utc)
    assert hc['AI Builders Challenge - North America'].prize_usd == 15000
    assert hc['UiPath Free Virtual Community Sessions'].kind == 'unknown'
    assert hc['UiPath Free Virtual Community Sessions'].classified_by == 'none'
    assert parsed['lablab'] == []
    # The paged Active list uses plain li rows rather than role=listitem cards.
    active = PAGES / 'kaggle_active1.html'
    if active.exists():
        rows = kaggle.parse(active.read_text(encoding='utf-8'), kaggle.ACTIVE)
        check_fields(rows)
        assert len(rows) == 20 and rows[0].title == 'Santa 2026 - The Elf Calculator'
        assert rows[0].prize_usd == 50000 and rows[0].url.endswith('/competitions/santa-2026')


def test_future_and_past_records():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rows = [{'type': 'hackathon', 'slug': 'future', 'name': 'Future Hack', 'medium': 'virtual', 'startTime': future, 'endTime': future},
            {'type': 'hackathon', 'slug': 'past', 'name': 'Past Hack', 'endTime': past},
            {'type': 'conference', 'slug': 'conference', 'name': 'Conference', 'endTime': future}]
    # Next Flight records can be split between scripts in the middle of JSON.
    flight = '1:' + json.dumps({'events': rows})
    split = flight.index('future') + 3
    html = ''.join('<script>self.__next_f.push(' + json.dumps([1, part]) + ')</script>' for part in [flight[:split], flight[split:]])
    assert [e.title for e in ethglobal.parse(html, 'https://ethglobal.com/events')] == ['Future Hack']
    schema = {'@type': 'Event', 'name': 'Future AI Hackathon', 'url': '/ai-hackathons/future', 'startDate': future,
              'endDate': future, 'eventAttendanceMode': 'https://schema.org/OnlineEventAttendanceMode'}
    html = '<script type="application/ld+json">' + json.dumps([schema, dict(schema, name='Past', endDate=past)]) + '</script>'
    events = lablab.parse(html, lablab.LISTING)
    assert len(events) == 1 and events[0].format == 'online'
    assert events[0].url == 'https://starfieldlabs.ai/ai-hackathons/future'
    # Real Marko shape: Date fields are replacements outside the main object.
    record = {'name': 'Future Hackathon', 'slug': 'future-123', 'online': True}
    payload = {'o': {'events': [record]}, '$$': [
        {'l': ['events', 0, key], 'r': {'type': 'Date', 'value': int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()*1000)}}
        for key in ['date_start', 'date_end']]}
    events = hackathoncom.parse('<script>$MC=(window.$MC||[]).concat(' + json.dumps(payload) + ')</script>', 'https://www.hackathon.com')
    assert len(events) == 1 and events[0].kind == 'hackathon'
    assert events[0].start is not None and events[0].end is not None
    check_fields(events)


def test_luma_scopes(monkeypatch=None):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    def entry(i, name, city):
        return {'api_id': 'evt-%d' % i, 'event': {'api_id': 'evt-%d' % i, 'name': name, 'url': 'e%d' % i, 'start_at': future,
                'location_type': 'offline', 'geo_address_info': {'city': city, 'country': 'Poland', 'localized': {'pl': {'city': city}}}}}
    rows = [entry(1, 'City Hackathon', 'Krakow'), entry(2, 'Brunch', 'Krakow'), entry(3, 'Elsewhere Hackathon', 'Warsaw'),
            entry(4, 'Game Jam Night', 'Kraków'), entry(1, 'City Hackathon', 'Krakow')]
    seen = []
    def fake(c, params):
        seen.append(dict(params))
        return {'entries': rows}
    original, luma._get, luma._places['sf'] = luma._get, fake, 'discplace-sf'
    luma._categories['tech'] = 'cat-tech'
    try:
        assert [e.title for e in luma.collect_scope('city:Krakow')] == ['City Hackathon', 'Game Jam Night']
        assert seen[-1]['query'] == 'hackathon Krakow'
        assert len(luma.collect_scope('place:sf:datathon')) == 3  # Deduped by api_id, relevance only.
        assert seen[-1]['discover_place_api_id'] == 'discplace-sf' and seen[-1]['query'] == 'datathon'
        luma.collect_scope('online:game jam')
        assert seen[-1]['query'] == 'online game jam' and 'discover_place_api_id' not in seen[-1]
        luma.collect_scope('cat:tech:hack')
        assert seen[-1]['query'] == 'hack' and seen[-1]['discover_category_api_id'] == 'cat-tech'
        assert 'discover_place_api_id' not in seen[-1]
    finally:
        luma._get = original
    quick = luma.scopes('quick')
    assert 'global:hackathon' in quick and 'place:sf:hackathon' in quick and len(quick) == 10
    assert all(s.split(':')[0] in ('global', 'online', 'place') for s in quick)


def test_luma_full_scopes():
    luma._places.update({'sf': 'p1', 'denver': 'p2'})
    luma._categories.update({'tech': 'c1', 'ai': 'c2', 'arts': 'c3'})
    full = luma.scopes('full')
    assert len(full) == len(set(full)) and full[-1] == 'calendars' and full.count('calendars') == 1
    assert {x for x in luma.scopes('quick') if not x.startswith('place:')} <= set(full)  # Only 2 places are loaded here.
    assert 'global:hakaton' in full and 'online:\u30cf\u30c3\u30ab\u30bd\u30f3' in full
    assert 'place:sf:ideathon' in full and 'place:denver:hack' in full and 'place:denver:ideathon' not in full
    assert 'cat:tech:hack' in full and 'cat:ai:hackathon' in full and not any(s.startswith('cat:crypto') for s in full)
    assert 'city:Utrecht' in full
    # Place + category is never generated: Luma ignores the category when a place ID is present.
    assert not any(s.startswith('place:') and s.count(':') > 2 and s.split(':')[2] in luma.CATEGORIES for s in full)


def test_luma_calendars():
    future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    def item(i, name, cal, cal_name):
        return {'api_id': 'evt-%d' % i, 'calendar': {'api_id': cal, 'name': cal_name},
                'event': {'api_id': 'evt-%d' % i, 'name': name, 'url': 'c%d' % i, 'start_at': future, 'location_type': 'online'}}
    pages = {None: {'entries': [item(1, 'Spring Hackathon', 'cal-a', 'A'), item(2, 'Social', 'cal-a', 'A')],
                    'has_more': True, 'next_cursor': 'abc'},
             'abc': {'entries': [item(3, 'Build Day', 'cal-a', 'A'), item(1, 'Spring Hackathon', 'cal-a', 'A')], 'has_more': False}}
    calls = []
    def fake(c, params):
        calls.append(dict(params))
        if params['calendar_api_id'] == 'cal-gone':
            raise httpx.HTTPStatusError('gone', request=httpx.Request('GET', 'https://x'), response=httpx.Response(404))
        return pages[params.get('pagination_cursor')] if params['calendar_api_id'] == 'cal-a' else {'entries': [], 'has_more': False}
    original, seeds = (luma._get, luma.seed_calendars), {'cal-a': 'A', 'cal-gone': 'Gone'}
    luma._get, luma.seed_calendars = fake, lambda: seeds
    luma._calendars.clear()
    luma._calendars['cal-seen'] = {'name': 'Seen', 'hits': 2}
    try:
        events = luma.collect_scope('calendars')
    finally:
        luma._get, luma.seed_calendars = original
    assert sorted(e.title for e in events) == ['Build Day', 'Spring Hackathon']  # Cursor followed, deduped, relevance only.
    assert [c['calendar_api_id'] for c in calls] == ['cal-a', 'cal-a', 'cal-gone', 'cal-seen']  # 404 skipped, seen crawled.
    assert calls[0]['period'] == 'future' and 'pagination_cursor' not in calls[0] and calls[1]['pagination_cursor'] == 'abc'
    assert luma._calendars['cal-a']['hits'] == 3 and luma._calendars['cal-a']['name'] == 'A'
    luma._calendars.clear()
    seen = {'x': {'name': 'X', 'hits': 1}, 'y': {'name': 'Y', 'hits': 5}, 'cal-a': {'name': 'A', 'hits': 9}}
    assert luma.calendar_order({'cal-a': 'A'}, seen) == [('cal-a', 'A'), ('y', 'Y'), ('x', 'X')]  # Seeds first, busiest next.
    real = luma.seed_calendars()
    assert 'cal-qTA84G1Wwdl14m4' in real and all(k.startswith('cal-') for k in real)  # Cerebral Valley is seeded.


def test_signals():
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    entry = {'api_id': 'e1', 'guest_count': 40, 'calendar': {'api_id': 'cal-z', 'name': 'Zed'},
             'hosts': [{'name': 'Ann'}, {'name': None}], 'featured_guests': [{'name': 'x'}],
             'ticket_info': {'is_free': False, 'price': {'cents': 1250, 'currency': 'eur'}},
             'event': {'api_id': 'e1', 'name': 'X Hackathon', 'url': 'x', 'start_at': future, 'description': 'Build  things'}}
    sig = luma._event(entry).signals
    assert sig == {'guests': 40, 'hosts': ['Ann'], 'calendar_id': 'cal-z', 'calendar_name': 'Zed', 'paid_entry': True,
                   'entry_fee': '12.50 EUR', 'featured': True, 'text': 'Build things'}
    entry.update(guest_count=0, featured_guests=[], ticket_info={'is_free': True, 'price': None})
    entry['event']['hide_rsvp'] = True
    sig = luma._event(entry).signals
    assert 'guests' not in sig and sig['paid_entry'] is False and 'entry_fee' not in sig and 'featured' not in sig
    raw = {'eventUrl': 'https://m/e', 'title': 'Hack Night', 'dateTime': future, 'description': 'Come [link](u) **now**',
           'feeSettings': {'amount': 5.0, 'currency': 'USD'}, 'maxTickets': 0, 'group': {'name': 'Hackers'},
           'rsvps': {'totalCount': 7, 'edges': [{'node': {'isHost': True, 'user': {'name': 'Bo'}}},
                                                {'node': {'isHost': False, 'user': {'name': 'Cy'}}}]}}
    sig = meetup._event(raw, {}).signals
    assert sig == {'rsvps': 7, 'hosts': ['Bo'], 'calendar_name': 'Hackers', 'paid_entry': True, 'entry_fee': '5 USD',
                   'text': 'Come link now'}


def test_ctftime_windows():
    calls = []
    def get(url, params):
        calls.append((params['start'], params['finish']))
        n = 1000 if len(calls) == 1 else 2  # Only the first request looks saturated.
        base = len(calls) * 10
        return httpx.Response(200, json=[{'id': base + i} for i in range(n)], request=httpx.Request('GET', url))
    rows = {}
    ctftime._window(type('C', (), {'get': staticmethod(get)}), datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 31, tzinfo=timezone.utc), rows)
    assert len(calls) == 3 and len(rows) == 4  # Saturated window was split in two halves.
    assert calls[1][0] == calls[0][0] and calls[2][0] > calls[1][0]


def test_meetup_scopes():
    scopes = meetup.scopes('quick')
    assert scopes == meetup.scopes('full') and scopes[:2] == ['global', 'online']
    searches = [i for s in scopes[2:] for i in s.removeprefix('locs:').split('|')]
    assert searches == meetup.searches() and all(s.startswith('locs:') for s in scopes[2:])
    assert all(len(s.split('|')) <= meetup.BATCH for s in scopes[2:])
    assert 'loc:us--ca--San Francisco' in searches and 'kw:hack night@us--ca--San Francisco' in searches
    assert len(meetup.LOCATIONS) >= 60 and len(set(meetup.LOCATIONS)) == len(meetup.LOCATIONS)
    assert all(l.count('--') in (1, 2) and l.split('--')[0].islower() for l in meetup.LOCATIONS)
    assert meetup._items('locs:loc:de--Berlin|loc:fr--Paris') == ['loc:de--Berlin', 'loc:fr--Paris']
    assert meetup._items('global') == ['global']
    assert meetup._url('global') == meetup.BASE and meetup._url('online').endswith('&eventType=online')
    assert meetup._url('loc:us--ca--San Francisco').endswith('&location=us--ca--San%20Francisco')
    url = meetup._url('kw:hack night@us--wa--Seattle')
    assert 'keywords=hack%20night' in url and 'keywords=hackathon' not in url and url.endswith('location=us--wa--Seattle')
    node = {'__typename': 'Event', 'id': '1'}
    assert meetup._ids([{'a': [node, {'eventUrl': 'u', 'dateTime': 'x'}]}]) == {'1', 'u'}
    assert meetup.HACK_RE.search('Berlin Game Jam') and meetup.HACK_RE.search('\u0425\u0430\u043a\u0430\u0442\u043e\u043d')
    assert not meetup.HACK_RE.search('Improv Jam in Person') and not meetup.HACK_RE.search('MUSIC JAM SF')


if __name__ == '__main__':
    test_snapshots()
    test_future_and_past_records()
    test_luma_scopes()
    test_luma_full_scopes()
    test_luma_calendars()
    test_signals()
    test_ctftime_windows()
    test_meetup_scopes()
    print('All parser assertions passed.')
