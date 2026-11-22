"""Recompute scores, coordinates, categories and flags without crawling; print a calibration report."""
from collections import defaultdict
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hackfinder import db, store
from hackfinder.categories import CATEGORIES, unpack


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


def taxonomy_report(conn, sample=15):
    """Category coverage, counts per category and flag, and a random sample of hackathons."""
    import random
    rows = [r for r in conn.fetchall("SELECT title, cats, flags FROM events WHERE status = 'active' AND kind = 'hackathon'")]
    covered = sum(bool(unpack(r["cats"])) for r in rows)
    print(f"\nCategories: {covered}/{len(rows)} active hackathons have >= 1 ({covered / max(1, len(rows)):.0%})")
    for name, counter in (("category", defaultdict(int)), ("flag", defaultdict(int))):
        for row in rows:
            for value in unpack(row["cats" if name == "category" else "flags"]):
                counter[value] += 1
        print(f"By {name}:", ", ".join(f"{k} {v}" for k, v in sorted(counter.items(), key=lambda kv: -kv[1])))
    random.seed(7)
    print("\nRandom hackathons: title | categories | flags")
    for row in random.sample(rows, min(sample, len(rows))):
        print(f"{row['title']} | {','.join(unpack(row['cats'])) or '-'} | {','.join(unpack(row['flags'])) or '-'}")


def region_report(conn):
    """Region and country counts, and the share of in-person/hybrid active events that have a country."""
    rows = conn.fetchall("SELECT country_code, region, format FROM events WHERE status = 'active' AND kind = 'hackathon'")
    physical = [r for r in rows if r["format"] in {"in-person", "hybrid"}]
    covered = sum(r["country_code"] is not None for r in physical)
    print(f"\nCountry coverage: {covered}/{len(physical)} active in-person/hybrid hackathons ({covered / max(1, len(physical)):.0%})")
    for name, field in (("region", "region"), ("country", "country_code")):
        counter = defaultdict(int)
        for row in rows:
            counter[row[field] or "-"] += 1
        print(f"By {name}:", ", ".join(f"{k} {v}" for k, v in sorted(counter.items(), key=lambda kv: -kv[1])[:25]))


def geo_report(conn):
    """Coordinate coverage for in-person/hybrid/unknown-format active events, and the geocode cache."""
    rows = conn.fetchall("SELECT lat, data FROM events WHERE status = 'active' AND format <> 'online'")
    have = sum(r["lat"] is not None for r in rows)
    print(f"\nCoordinates: {have}/{len(rows)} active in-person/hybrid/unknown-format events ({have / max(1, len(rows)):.0%})")
    cache = conn.fetchall("SELECT status, COUNT(*) AS n FROM geocode_cache GROUP BY status")
    print("Geocode cache:", ", ".join(f"{r['status']} {r['n']}" for r in cache) or "empty",
          "(online lookups: HF_GEOCODE_ONLINE=0 turns them off, HF_GEOCODE_MAX caps new ones per run)")
    for r in [r for r in rows if r["lat"] is None][:15]:
        event = db.loads(r["data"])
        print("  no coordinates:", event.get("title", "")[:50], "|", event.get("location"), "|", event.get("country"))


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
        store.remerge(conn)  # reclassifies stored rows, rebuilds events and rescores
        print('\nAFTER')
        report(conn)
        taxonomy_report(conn)
        region_report(conn)
        geo_report(conn)
    db.close()


if __name__ == '__main__':
    main()
