"""Small classification and date hygiene regressions."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hackfinder.classify import classify
from hackfinder.models import Event
from hackfinder.store import clean


def event(title, **extra):
    return Event(source="eventbrite", url="https://example.com/e", title=title, **extra)


def test_jam_classification():
    meta = {"id": "eventbrite", "default_kind": "mixed"}
    for title in ["Jungle Jam: English Premium Stand-Up Open Mic", "Tiny Desk Maluku Jam Christmas Edition!"]:
        assert classify(event(title), meta).kind == "other", title
    for title in ["Brackeys Game Jam 2027.1", "GGJ27 Leipzig", "Ludum Dare 59", "Mini Jam 200"]:
        assert classify(event(title), meta).kind == "game_jam", title


def test_far_future_date_is_unknown():
    cleaned = clean(event("Hackathon: Open AI", start=datetime(2035, 8, 17, tzinfo=timezone.utc),
                          end=datetime(2035, 8, 18, tzinfo=timezone.utc)))
    assert cleaned.start is None
    assert cleaned.end is None


def test_reversed_dates_are_swapped():
    cleaned = clean(event("Hackathon", start=datetime(2027, 2, 5, tzinfo=timezone.utc),
                          end=datetime(2027, 2, 1, tzinfo=timezone.utc)))
    assert cleaned.start == datetime(2027, 2, 1, tzinfo=timezone.utc)
    assert cleaned.end == datetime(2027, 2, 5, tzinfo=timezone.utc)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
