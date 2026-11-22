"""Non-hackathon events are labelled (talk, meetup, workshop, info_session), not hidden."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hackfinder.classify import classify
from hackfinder.models import Event

MIXED = {"id": "eventbrite", "default_kind": "mixed"}


def kind(title, description="", source="eventbrite", meta=None, **extra):
    event = Event(source=source, url="https://example.com/e", title=title, description=description, **extra)
    return classify(event, meta or {"id": source, "default_kind": "mixed"}).kind


def test_live_examples():
    assert kind("Pre-Hackathon: OneGov #3 | Leer de challenges kennen & vind je team") == "info_session"
    assert kind("Leiden.dev • Running your own hackathon • HTTP Query method", source="meetup") == "talk"


def test_true_hackathons_stay():
    for title in ["Benelux Robotics Hackathon", "WTC BUILDATHON - Feb 11", "Hackathon for Good: AI by Women, for Women",
                  "Social Impact Hackathon 2026", "OneGov AI Hackathon Series - Editie #3", "AI Hackathon 2026"]:
        assert kind(title) == "hackathon", title
    assert kind("Winter Game Jam 2026") == "game_jam"


def test_hackathon_with_talk_extras_stays():
    assert kind("One-Person Unicorn Hackathon + Fireside + Pitch @ NASDAQ") == "hackathon"
    assert kind("TALK-N-OPS AI-BUILDATHON") == "hackathon"
    assert kind("Keynote + Mini Hackathon") == "hackathon"
    assert kind("kickoff(): hack, demo, play") == "unknown"


def test_hack_night():
    assert kind("Hack Night") == "meetup"
    assert kind("Hack Night: build an app and win prizes", "Teams build a working project, judges pick winners") == "hackathon"


def test_pre_event_beats_hackathon_keyword():
    for title in ["Hackathon Kick-off", "Hackathon info session", "Find your team for the AI Hackathon",
                  "Hackathon Demo Day", "Hackathon Award Ceremony", "Hackathon Finale", "Team formation - Spring Hackathon"]:
        assert kind(title) == "info_session", title


def test_talks_meetups_workshops():
    assert kind("Panel: the future of hackathons") == "talk"
    assert kind("Lecture on hackathon design") == "talk"
    assert kind("Hackathon Meetup") == "meetup"
    assert kind("Hackathon networking drinks") == "meetup"
    assert kind("Hackathon workshop: Intro to LLM agents") == "workshop"
    assert kind("Masterclass for hackathon teams") == "workshop"
    assert kind("Python bootcamp for the hackathon") == "workshop"


def test_dutch():
    assert kind("Informatiesessie Hackathon Gemeente") == "info_session"
    assert kind("Kennismaking hackathon") == "info_session"
    assert kind("Hackathon borrel") == "meetup"
    assert kind("Lezing over hackathons") == "talk"
    assert kind("Workshop hackathon voorbereiding") == "workshop"
    assert kind("Meetup: hackathon community") == "meetup"


def test_source_decided_kinds_survive():
    meta = {"id": "devpost", "default_kind": "hackathon"}
    event = Event(source="devpost", url="https://x.dev/e", title="Cool Workshop Hackathon", kind="hackathon",
                  confidence=0.9, classified_by="source")
    assert classify(event, meta).kind == "hackathon"
    pre = event.model_copy(update=dict(title="Pre-Hackathon info session"))
    assert classify(pre, meta).kind == "info_session"
    assert classify(Event(source="devpost", url="https://x.dev/f", title="Panel Hackathon"), meta).kind == "hackathon"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
