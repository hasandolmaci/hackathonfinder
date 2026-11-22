"""Recompute scores and coordinates without crawling; print a calibration report."""
from collections import defaultdict
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hackfinder import db, store


def report(conn):
    rows = conn.fetchall("SELECT source, kind, title, score, score_conf, score_detail, data, status, lat FROM events")
    active = [r for r in rows if r["status"] == "active"]
    print(f"Stored: {len(rows)}; active: {len(active)}; geocoded: {sum(r['lat'] is not None for r in active)}")
    for field in ("source", "kind"):
        groups = defaultdict(list)
        for row in active:
            groups[row[field]].append(row["score"])
        print(f"\nBy {field}: name | total | unknown | <40 | 40-59 | 60-79 | 80+ | median")
        for name, values in sorted(groups.items()):
            known = [v for v in values if v is not None]
            buckets = [sum(lo <= v <= hi for v in known) for lo, hi in [(0, 39), (40, 59), (60, 79), (80, 100)]]
            print(name, len(values), len(values) - len(known), *buckets, median(known) if known else 'n/a', sep=' | ')
    known = sorted((r for r in active if r['kind'] == 'hackathon' and r['score'] is not None),
                   key=lambda r: (-r['score'], r['title']))
    bottom = sorted(known, key=lambda r: (r['score'], r['title']))[:15]
    for label, examples in [('Top 20 hackathons', known[:20]), ('Bottom 15 hackathons', bottom)]:
        print('\n' + label)
        for row in examples:
            print_row(row)
    print('\nGolden rows (including thin MLH listings)')
    for row in active:
        event = db.loads(row['data'])
        if (any(name in row['title'] for name in ('Kiroween', 'Codegeist', 'Arbitrum Open House')) or
                row['source'] in {'ethglobal', 'mlh'} or
                (row['source'] == 'luma' and event.get('participants') == 93)):
            print_row(row)


def print_row(row):
    detail = db.loads(row['score_detail']) if row['score_detail'] else {}
    reasons = '; '.join(detail.get('reasons', []))
    print(f"{str(row['score']):>3} | {row['score_conf']} | {row['source']} | {row['title']} | {reasons}")


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    db.init(places=True)
    with db.connect() as conn:
        print('BEFORE')
        report(conn)
        store.rescore(conn)
        print('\nAFTER')
        report(conn)
    db.close()


if __name__ == '__main__':
    main()
