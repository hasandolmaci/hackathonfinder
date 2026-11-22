"""Deterministic source hints and multilingual keyword classification."""
from __future__ import annotations

import re
import unicodedata
from .models import Event


def _text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def classify(event: Event, source_meta: dict) -> Event:
    event = event.model_copy(deep=True)
    text = _text(f"{event.title} {event.description or ''}")
    if not event.tags:
        rules = {
            "ai": r"\b(ai|artificial intelligence|machine learning|llm|generative)\b",
            "web3": r"\b(web3|blockchain|ethereum|crypto|solidity)\b",
            "student": r"\b(student|university|college|high.school|campus)\b",
            "gov": r"\b(government|civic|public sector|govtech)\b",
            "hardware": r"\b(hardware|robotics|iot|arduino|raspberry pi)\b",
            "climate": r"\b(climate|sustainability|cleantech)\b",
            "health": r"\b(health|medical|biotech)\b",
        }
        event.tags = [tag for tag, pattern in rules.items() if re.search(pattern, text)]
    if event.classified_by == "source" and event.kind != "unknown":
        return event
    default = source_meta.get("default_kind")
    if event.kind == "unknown" and default in {
        "hackathon", "game_jam", "ctf", "coding_competition", "ideathon", "other"
    }:
        return event.model_copy(update=dict(kind=default, confidence=0.9, classified_by="source"))
    title = _text(event.title)
    support = r"\b(info(?:rmation)? session|workshop|meetup|talk|webinar|panel|conference|intro(?:duction)?)\b"
    about = r"\b(info(?:rmation)? session|webinar|talk|panel)\b.*\b(about|for|on|hackathon)\b"
    build = r"\b(build|prototype|create|develop|ship)\s+(?:a |an |your |our |working |new )?(?:project|prototype|app|game|product|solution|together)\b"
    if re.search(about, title) or (re.search(support, title) and not re.search(build, text)):
        kind, confidence = "other", 0.9
    else:
        rules = [
            ("game_jam", r"\b(game[ -]?jam|ludum dare|global game jam|jam)\b|ゲームジャム"),
            ("ctf", r"\b(ctf|capture[ -]the[ -]flag)\b"),
            ("ideathon", r"\b(ideathon|idea[ -]thon)\b"),
            ("hackathon", r"\b(hackathons?|hack[ -]?(day|night)|build[ -]?(athon|day|night)|datathon|makeathon|hackaton|hakaton|hackat[oó]n|hakat[oó]n)\b|ハッカソン|해커톤|黑客松|駭客松|хакатон|هاكاثون"),
            ("coding_competition", r"\b(coding competition|programming contest|algorithmic contest|kaggle competition)\b"),
        ]
        kind, confidence = "unknown", 0.0
        for candidate, pattern in rules:
            if re.search(pattern, text):
                kind, confidence = candidate, 0.85
                break
        if kind == "unknown" and re.search(build, text):
            kind, confidence = "hackathon", 0.75
    return event.model_copy(update=dict(kind=kind, confidence=confidence,
                                        classified_by="keyword" if kind != "unknown" else "none"))
