"""Duplicates that aggregators write differently, and events you can no longer join."""
from datetime import datetime, timedelta, timezone

from hackfinder.dedupe import _same
from hackfinder.models import Event
from hackfinder.store import _closed, day_start


def E(t, s, e=None, loc=None, **kw):
    d = lambda x: datetime.fromisoformat(x).replace(tzinfo=timezone.utc) if x else None
    return Event(source='x', url=f'https://x.org/{t}/{s}/{loc}', title=t, start=d(s), end=d(e), location=loc, **kw)


def test_dedupe_real_pairs():
    same = [
        (E('Hoya Hacks', '2027-01-22', loc='Washington, DC'), E('Hoya Hacks 2027', '2027-01-23', loc='Washington, United States')),
        (E('K-Dub Hacks', '2026-11-27', loc='Spur Innovation Centre'), E('K-DUB Hacks', '2026-11-27', loc='Waterloo, Canada')),
        (E('Inceptrix 3.0', '2026-11-05', loc='Bengaluru, India'), E('Inceptrix 3.0', '2026-10-31', loc='Bangalore, Karnataka')),
        (E('Applied AI Hackathon Tokyo', '2026-12-12', loc='Tokyo, JP'), E('Applied AI Hackathon Tokyo', '2026-12-12', loc='Shinjuku City, Japan')),
        (E('Hack Peel', '2026-12-12'), E('hack::peel 2026', '2026-12-12')),
        (E('hackaTUM 2026', '2026-11-26', loc='Munich, Germany'), E('hackaTUM 2026', '2026-11-27', loc='Garching bei München, Germany')),
        (E('Hacksprint 3.0', '2027-02-05'), E('Hacksprint 3.0', '2026-10-25', '2027-02-01')),
    ]
    different = [
        (E('HackwithBay 4.0', '2026-11-24'), E('HackwithBay 5.0', '2026-12-08')),
        (E('Lovable Build Day - RJ', '2026-12-09'), E('Lovable Build Day - RJ', '2027-01-23')),
        (E('Flushing Tech Bi-Weekly Hackathon', '2026-11-28'), E('Flushing Tech Bi-Weekly Hackathon', '2026-12-12')),
        (E('AI Hackathon', '2026-12-03', loc='Lakeland, United States'), E('AI Hackathon', '2026-12-04', loc='Taipei, Taiwan')),
        (E('Claude Code Build Day', '2026-11-30', loc='Hamburg, Germany'), E('Claude Code Build Day', '2026-11-30', loc='Berlin, Germany')),
        (E('Hack Week 2027', '2027-03-01'), E('Hack Week 2028', '2027-03-01')),
    ]
    assert all(_same(a, b) for a, b in same), [(a.title, b.title) for a, b in same if not _same(a, b)]
    assert not any(_same(a, b) for a, b in different), [(a.title, b.title) for a, b in different if _same(a, b)]


def test_closed_means_not_joinable():
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    cut = day_start(now)
    yesterday, later = '2026-11-22', '2026-12-20'
    assert _closed(E('Started in person', yesterday, later, format='in-person'), now, cut)
    assert _closed(E('Started hybrid', yesterday, later, format='hybrid'), now, cut)
    assert not _closed(E('Online submissions', yesterday, later, format='online'), now, cut)
    assert _closed(E('Registration over', '2026-12-01', format='online', registration_deadline=now - timedelta(hours=1)), now, cut)
    assert not _closed(E('Multi-round, registration open', '2026-10-25', later, format='in-person',
                         registration_deadline=now + timedelta(days=3)), now, cut)
    assert not _closed(E('Starts today', '2026-11-23', format='in-person'), now, cut)
    assert not _closed(E('Future', '2026-12-01', format='in-person'), now, cut)


if __name__ == '__main__':
    test_dedupe_real_pairs(); test_closed_means_not_joinable(); print('cleanup tests passed')
