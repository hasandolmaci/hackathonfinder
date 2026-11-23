"""Offline tests for sponsor brand detection (the SPONSORS filter)."""
from datetime import datetime, timezone

from hackfinder.categories import sponsors
from hackfinder.models import Event


def event(title="Spring Hackathon", description=None, organizer=None, **signals):
    return Event(source="test", url="https://example.org/e", title=title, description=description,
                 organizer=organizer, start=datetime(2099, 1, 1, tzinfo=timezone.utc), signals=signals)


def test_title_and_products_map_to_maker():
    assert sponsors(event("Build with Claude Hackathon")) == ["anthropic"]
    assert sponsors(event("Gemini API Developer Jam")) == ["google"]
    assert sponsors(event("n8n Automation Hackathon Berlin")) == ["n8n"]


def test_sponsor_phrases_and_lists():
    e = event(description="A weekend of building. Sponsored by OpenAI, ElevenLabs and n8n. Food included.")
    assert sponsors(e) == ["openai", "n8n", "elevenlabs"]
    assert sponsors(event(sponsors=["Anthropic", "Vercel"])) == ["anthropic", "vercel"]
    assert sponsors(event(organizer="Google Developer Groups Munich")) == ["google"]


def test_plain_mentions_and_lookalikes_do_not_count():
    assert sponsors(event(description="Bring a laptop. You may use OpenAI or any other API you like.")) == []
    assert sponsors(event("Meta-learning Intelligence Hackathon")) == []
    assert sponsors(event("cursor positions and polygon meshes jam")) == []


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} sponsor tests passed")
