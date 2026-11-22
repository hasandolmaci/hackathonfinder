"""Offline score, geocoding and API checks: python tests/test_score.py."""
from datetime import timedelta
import importlib
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HF_GEOCODE_ONLINE", "0")  # no network in tests
os.environ.pop('DATABASE_URL', None)
from fastapi.testclient import TestClient
from hackfinder import db, store
from hackfinder.dedupe import dedupe
from hackfinder.geo import geocode
from hackfinder.models import Event
from hackfinder.score import Context, WEIGHTS, extract, prize_usd, score_event


def event(**kwargs):
    return Event(**{'source': 'devpost', 'title': 'Build together', 'url': 'https://example.com/build',
                    'kind': 'hackathon', **kwargs})


def test_score():
    assert all(sum(w.values()) == 100 for w in WEIGHTS.values())
    empty = score_event(event())
    assert empty['score'] is None and 'Not enough info' in empty['score_detail']['reasons']
    full = event(source='ethglobal', organizer='ETHGlobal', participants=5000, prize_usd=250000,
                 start=store.utcnow(), end=store.utcnow() + timedelta(days=2), format='hybrid',
                 description='Build with fellow developers. ' * 10,
                 signals={'sponsors': ['Google', 'OpenAI', 'NVIDIA'], 'travel_support': True,
                          'mentors': True, 'hiring': True, 'food_swag': True, 'paid_entry': False})
    assert score_event(full)['score'] >= 85, score_event(full)
    mlh = full.model_copy(update={'source': 'mlh', 'organizer': 'Local university', 'prize_usd': 100000,
                                  'signals': {**full.signals, 'mlh_member': True, 'registrations': 2000}})
    assert score_event(mlh)['score'] >= 80, score_event(mlh)
    spam = event(source='eventbrite', kind='other', title='Networking meetup', description='Buy tickets!')
    assert score_event(spam)['score'] is None or score_event(spam)['score'] < 40
    context = Context([full, mlh])
    for context_value in (None, context):
        for field in ('prize_usd', 'participants'):
            scores = [score_event(full.model_copy(update={field: n}), context_value)['score']
                      for n in (0, 1, 10, 100, 1000, 10000, 100000)]
            assert scores == sorted(scores), (field, scores)
        scores = [score_event(full.model_copy(update={'participants': None, 'signals': {'registrations': n}}), context_value)['score']
                  for n in (0, 1, 10, 100, 1000, 10000)]
        assert scores == sorted(scores), scores
    member = event(signals={'mlh_member': True, 'registrations': 5000}, prize_usd=250000)
    assert score_event(member)['score'] >= 80, score_event(member)
    assert prize_usd(event(signals={'prize_amount': 100, 'prize_currency': 'EUR'}), {'EUR': 1, 'USD': 1.2}) == 120
    assert prize_usd(event(signals={'prize_amount': 100, 'prize_currency': 'XXX'})) is None
    older = full.model_copy(update={'url': 'https://example.com/old', 'start': full.start - timedelta(days=365)})
    assert Context(history=[older, older]).editions(full) == 1
    halo_context = Context([full, mlh])
    assert all(halo_context.prior(full, d, True) >= halo_context.prior(full, d, False) for d in WEIGHTS['hackathon'])
    print('PASS weights, golden cases, monotonicity, FX, recurrence and halo')



def test_real_data_golden():
    # Scoring fields from the 2026-11-22 crawl; no database or network dependency.
    fixtures = [{'source': 'devpost',
      'title': 'Kiroween 2026',
      'image': 'https://example.com/banner.png',
      'start': '2026-10-30T00:00:00Z',
      'end': '2026-12-04T00:00:00Z',
      'format': 'online',
      'prize_usd': 100000.0,
      'participants': 18363,
      'organizer': 'Kiro',
      'tags': ['Beginner Friendly', 'Machine Learning/AI', 'Open Ended'],
      'signals': {'featured': False,
                  'invite_only': False,
                  'official': True,
                  'prize_amount': 100000.0,
                  'prize_currency': 'USD',
                  'registrations': {'devpost': 18363},
                  'themes': ['Beginner Friendly', 'Machine Learning/AI', 'Open Ended']},
      'kind': 'hackathon'},
     {'source': 'devpost',
      'title': 'Codegeist 2026: Build with context. Ship with confidence.',
      'image': 'https://example.com/banner.png',
      'start': '2026-10-27T00:00:00Z',
      'end': '2026-12-22T00:00:00Z',
      'format': 'online',
      'prize_usd': 120000.0,
      'participants': 4841,
      'organizer': 'Atlassian',
      'tags': ['Machine Learning/AI', 'Enterprise', 'Productivity'],
      'signals': {'featured': False,
                  'invite_only': False,
                  'official': True,
                  'prize_amount': 120000.0,
                  'prize_currency': 'USD',
                  'registrations': {'devpost': 4841},
                  'themes': ['Machine Learning/AI', 'Enterprise', 'Productivity']},
      'kind': 'hackathon'},
     {'source': 'devpost',
      'title': 'Hack Western 13',
      'image': 'https://example.com/banner.png',
      'start': '2026-11-20T00:00:00Z',
      'end': '2026-11-22T00:00:00Z',
      'format': 'in-person',
      'location': 'Ronald D. Schmeichel Building',
      'participants': 299,
      'organizer': 'Hack Western',
      'tags': ['Beginner Friendly', 'Open Ended'],
      'signals': {'participants': {'devpost': 299}},
      'kind': 'hackathon'},
     {'source': 'ethglobal',
      'title': 'ETHGlobal Lisbon 2027',
      'image': 'https://example.com/banner.png',
      'start': '2027-10-14T10:24:00Z',
      'end': '2027-10-16T10:24:00Z',
      'format': 'in-person',
      'location': 'Lisbon, Portugal',
      'organizer': 'ETHGlobal',
      'tags': ['web3'],
      'signals': {'hosts': ['ETHGlobal']},
      'kind': 'hackathon'},
     {'source': 'luma',
      'title': 'Agentic AI Hackathon 2.0 - SF',
      'image': 'https://example.com/banner.png',
      'start': '2026-12-15T17:30:00Z',
      'end': '2026-12-16T02:30:00Z',
      'format': 'in-person',
      'location': 'San Francisco, United States',
      'participants': 93,
      'organizer': 'Aviral, AWS Builder Loft, Lizzie @ Entire',
      'tags': ['ai'],
      'signals': {'calendar_id': 'cal-3XyuS65JPasgZ5y',
                  'calendar_name': 'Devnovate',
                  'featured': True,
                  'guests': {'luma': 93},
                  'hosts': ['Aviral', 'AWS Builder Loft', 'Lizzie @ Entire'],
                  'paid_entry': False},
      'kind': 'hackathon'},
     {'source': 'mlh',
      'title': 'Hack Western 13',
      'image': 'https://example.com/banner.png',
      'start': '2026-11-20T23:00:00Z',
      'end': '2026-11-22T20:00:00Z',
      'format': 'in-person',
      'location': 'London, Ontario',
      'tags': ['student', 'software', 'hardware'],
      'signals': {'mlh_member': True},
      'kind': 'hackathon'},
     {'source': 'hackquest',
      'title': 'Arbitrum Open House São Paulo: Online Buildathon',
      'description': "Build what's next",
      'image': 'https://example.com/banner.png',
      'start': '2027-02-08T03:01:00Z',
      'end': '2027-03-01T02:59:00Z',
      'format': 'online',
      'prize_usd': 100000.0,
      'participants': 37,
      'organizer': 'Arbitrum Foundation',
      'tags': ['web3', 'Solidity', 'Rust', 'ecosystem:Arbitrum', 'projects:1'],
      'signals': {'entries': {'hackquest': 1},
                  'judges': 3,
                  'mentors': True,
                  'prize_amount': 100000.0,
                  'prize_currency': 'USDC',
                  'registrations': {'hackquest': 37},
                  'text': 'Arbitrum Open House São Paulo — Buildathon São Paulo is where ambitious startups, '
                          'global capital, and Latin America’s rapidly growing onchain ecosystem converge. '
                          'Arbitrum provides infrastructure trusted by institutions and used by millions. It’s '
                          'time to connect the two. The Open House São Paulo Buildathon brings three weeks of '
                          'intensive building with the same technology that companies such as BlackRock and '
                          'Robinhood have chosen to build on. Three weeks to build something that matters. DeFi. '
                          'Gaming. Social applications. DePIN. Something entirely new? That’s up to you. Build '
                          'with Stylus in familiar programming languages or use Solidity. Deploy on Arbitrum One '
                          'or launch a custom Arbitrum chain. Bring an existing project or start from scratch. '
                          'No compromises. No limits. Just build. And there’s plenty to play for. The top three '
                          'teams will each earn a place at the in-person Founder House in São Paulo: three days '
                          'of intensive work alongside Arbitrum’s technical team, experienced mentors, and '
                          'successful ecosystem founders. Real mentorship, valuable connections, and a tangible '
                          'path from an early idea to a fundable product. We’ve built the infrastructure. You '
                          'bring the vision. Let’s see what happens next. Agenda & Google Calendar Get access to '
                          'the workshops & feedback sessions by navigating to the "Workshops & Sessions" tab . '
                          'Find the Buildathon schedule below.'},
      'kind': 'hackathon'}]
    rows = [event(**fields) for fields in fixtures]
    cohort = [event(participants=n, prize_usd=prize, organizer='Independent', format='online')
              for n in (0, 1, 5, 20, 50, 100, 250, 500, 1000, 5000)
              for prize in (0, 1000, 10000, 100000)]
    context = Context([*cohort, *rows])
    for ctx in (None, context):
        results = {e.title: score_event(e, ctx) for e in rows}
        for title, result in results.items():
            value = result['score']
            if title.startswith(('Kiroween', 'Codegeist')):
                assert value >= 85, (title, result)
            elif title.startswith('ETHGlobal'):
                assert 80 <= value <= 88, result
                assert result['score_confidence'] != 'high'
                assert set(result['score_detail']['missing']) >= {'community', 'rewards', 'support'}
            elif title.startswith('Arbitrum'):
                assert 64 <= value <= 72, result
            elif title.startswith('Agentic AI'):
                assert 45 <= value <= 60, result
            elif title.startswith('Hack Western'):
                assert 55 <= value <= 65, result
        kiro = results['Kiroween 2026']['score_detail']
        assert '18,363 registrations on Devpost' in kiro['reasons']
        assert '$100,000 prize pool' in kiro['reasons']
        assert kiro['effective_weights']['support'] == 3
    for currency in ('USDC', 'USDT'):
        assert prize_usd(event(signals={'prize_amount': 100000, 'prize_currency': currency}), {'EUR': 1}) == 100000
    for source, key, n, reason in [('luma', 'guests', 93, '93 guests on Luma'),
                                  ('ctftime', 'teams', 120, '120 teams on CTFtime'),
                                  ('itchio', 'joined', 435, '435 joined on itch.io')]:
        result = score_event(event(source=source, format='online', start=store.utcnow(), signals={key: {source: n}}))
        assert reason in result['score_detail']['reasons'], result
    eth = next(e for e in rows if e.source == 'ethglobal')
    assert context.prior(eth, 'community', True) > context.prior(eth, 'community', False)
    assert score_event(eth, context)['score_confidence'] == score_event(eth)['score_confidence']
    thin = next(e for e in rows if e.source == 'mlh')
    flagship = thin.model_copy(update={'participants': 3000, 'prize_usd': 100000,
                                      'signals': {'mlh_member': True, 'travel_support': True,
                                                  'mentors': True, 'sponsors': ['Google', 'NVIDIA']}})
    assert score_event(flagship, context)['score'] >= 80
    # Evidence beats a halo, and increasing counts/prizes stays monotone in fixed cohorts.
    eth = next(e for e in rows if e.source == 'ethglobal')
    weak = eth.model_copy(update={'participants': 1, 'prize_usd': 0})
    assert score_event(weak, context)['score'] < score_event(eth, context)['score']
    for original in rows:
        for field in ('participants', 'prize_usd'):
            # Luma zero is an undisclosed count, not an observed zero.
            counts = (0, 1, 10, 100, 1000, 10000, 100000)
            if original.source == 'luma' and field == 'participants':
                counts = counts[1:]
            values = [score_event(original.model_copy(update={field: n, 'signals': {}}), context)['score']
                      for n in counts]
            assert values == sorted(values), (original.title, field, values)
    print('PASS real-data goldens, count reasons, stablecoins, missing weight and monotonicity')

def test_extract():
    s = extract(event(description='No travel reimbursement. Not hiring. No mentors. We use Google APIs.'))
    assert s['travel_support'] is False and s['hiring'] is False and s['mentors'] is False
    assert not s.get('sponsors')
    s = extract(event(description='Sponsored by Google and AWS. Travel support. Free meals. API credits. Only for students.'))
    assert set(s['sponsors']) == {'Google', 'Amazon'} and s['travel_support'] and s['food_swag']
    assert s['prize_noncash'] and s['students_only']
    assert extract(event(description='Open only to residents of the Netherlands.'))['region_locked']
    assert not extract(event(organizer='Metaverse workshop')).get('sponsors')
    a = event(signals={'registrations': 20, 'sponsors': ['Google']})
    b = event(source='luma', signals={'guests': 40, 'sponsors': ['NVIDIA']})
    merged = dedupe([a, b])[0]
    assert merged.signals['registrations'] == {'devpost': 20}
    assert merged.signals['guests'] == {'luma': 40} and len(merged.signals['sponsors']) == 2
    print('PASS extraction, negation, sponsor context and per-source counts')


def test_geo_api():
    ams = geocode('Amsterdam, Netherlands')
    assert 52 < ams[0] < 53 and 4 < ams[1] < 5
    assert 51 < geocode('Eindhoven, NL')[0] < 52
    assert geocode('Online') == (None, None)
    assert geocode('Amsterdam', format='online') == (None, None)
    app = importlib.import_module('hackfinder.app')
    with tempfile.TemporaryDirectory() as directory:
        os.environ['HF_DB_PATH'] = str(Path(directory) / 'test.db')
        db.init(places=True)
        db.init(places=True)
        now = store.utcnow()
        rows = [event(title='Amsterdam hackathon', start=now + timedelta(days=1), location='Amsterdam, Netherlands',
                      format='in-person', participants=100, prize_usd=10000, signals={'text': 'Private extraction text'}),
                event(url='https://example.com/eindhoven', title='Eindhoven hackathon', start=now + timedelta(days=2),
                      location='Eindhoven, NL', format='in-person', participants=10, prize_usd=100),
                event(url='https://example.com/empty')]
        with db.connect() as conn:
            store.upsert_sources(conn, 'devpost', '*', [(e, e) for e in rows], now)
            store.remerge(conn)
        app.clear_cache()
        with TestClient(app.app) as client:
            result = client.get('/api/hackathons?sort=score').json()['events']
            assert result[0]['score'] >= result[1]['score'] and result[-1]['score'] is None
            assert 'text' not in result[0]['signals']
            threshold = result[0]['score']
            assert all(e['score'] >= threshold for e in client.get(f'/api/hackathons?min_score={threshold}').json()['events'])
            result = client.get(f'/api/hackathons?lat={ams[0]}&lon={ams[1]}&radius_km=25').json()
            assert result['total'] == 1 and result['events'][0]['distance_km'] < 1
            assert client.get('/api/hackathons?lat=52').status_code == 422
            assert client.get('/api/hackathons?sort=distance').status_code == 422
            assert client.get('/api/hackathons?radius_km=2001').status_code == 422
            places = client.get('/api/places?q=ams')
            assert places.json()[0]['name'] == 'Amsterdam' and 'cache-control' in places.headers
            assert client.get('/api/places?q=São').json() == client.get('/api/places?q=sao').json()
            assert len(client.get('/api/methodology').json()['dimensions']) == 5
            assert client.get('/api/hackathons?sort=new').status_code == 200
            assert client.get('/near').status_code == 200
            assert client.get('/methodology').status_code == 200
    print('PASS offline geocoding, idempotent schema, score/distance API, places and methodology')


if __name__ == '__main__':
    test_score()
    test_real_data_golden()
    test_extract()
    test_geo_api()
    print('All score tests passed (offline).')
