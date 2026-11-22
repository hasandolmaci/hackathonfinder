"""Deterministic source hints and multilingual keyword classification."""
from __future__ import annotations

import re
import unicodedata
from .models import Event


def _text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


# Pre-event, talk, meetup and workshop cues (English, Dutch, German, French, Spanish). Matched on the casefolded title.
PRE_STRONG = (r"\b(?:pre[- ]?(hackathon|event|jam|buildathon|datathon)|info(?:rmation)?[- ]?(session|evening|meeting)|informatie(?:sessie|avond|bijeenkomst)|"
              r"kick[- ]?off(?!\()|team[- ]?(formation|matching)|find your (team|teammates?)|vind je (team|teamgenoten)|teamvorming|"
              r"kennismaking|leer de challenges|(award|prize|closing|opening) ceremony|prijsuitreiking|demo[- ]?day|"
              r"infoabend|infoveranstaltung|s[ée]ance d.information|sesi[óo]n informativa)")
PRE_EVENT = PRE_STRONG + r"|\bfinale\b|\bfinal pitch(?:es)?\b|\bbriefing\b|\borientation\b|\bq ?& ?a\b"
TALK = (r"\b(talks?|speakers?|panel|lectures?|lezing|fireside|keynote|webinar|seminar|symposium|presentation|"
        r"praatje|vortrag|conf[é]rence|charla|ponencia)\b")
TALK_STRONG = (r"(running|organi[sz]ing|hosting|planning|starting) (?:your|a|an) (?:own )?hackathons?|how to (?:run|organi[sz]e|host|win) (?:a |your )?hackathons?|"
               r"(?:what|why) (?:is|are) (?:a )?hackathons?|\bintro(?:duction)? to hackathons?")
WORKSHOP = r"\b(workshops?|master ?class(?:es)?|boot ?camp|tutorial|crash course|cursus|atelier|taller|hands-on (?:lab|session))\b"
MEETUP = (r"\b(meet-?ups?|socials|social (?:night|club|hour|evening|gathering|mixer)|drinks|borrel|netwerkborrel|networking|"
          r"mixer|happy hour|community (?:night|evening|meetup|hangout|call)|bijeenkomst|inloop\w*|stammtisch|encuentro|rencontre)\b")
# A build-event noun, or "talk + hackathon", means the hackathon is the main event: talk/meetup/workshop cues are ignored.
BUILD_EVENT = (r"\b(build[ -]?athon|datathon|makeathon|game jam)\b|[+&] ?(?:a |the )?(?:mini[- ]?)?(?:hackathon|buildathon)\b|"
               r"\b(?:hackathon|buildathon) ?[+&]")
HACK_NIGHT = r"\bhack[ -]?nights?\b"


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
    title = _text(event.title)
    pre = re.search(PRE_EVENT, title)
    if event.classified_by == "source" and event.kind != "unknown":
        if pre and re.search(PRE_STRONG, title):
            return event.model_copy(update=dict(kind="info_session", confidence=0.85, classified_by="keyword"))
        return event
    default = source_meta.get("default_kind")
    if event.kind == "unknown" and default in {
        "hackathon", "game_jam", "ctf", "coding_competition", "ideathon", "other"
    }:
        if pre and re.search(PRE_STRONG, title):
            return event.model_copy(update=dict(kind="info_session", confidence=0.85, classified_by="keyword"))
        return event.model_copy(update=dict(kind=default, confidence=0.9, classified_by="source"))
    build = r"\b(build|prototype|create|develop|ship)\s+(?:a |an |your |our |working |new )?(?:project|prototype|app|game|product|solution|together)\b"
    compete = r"\b(prizes?|judg(?:es|ing)|compete|competition|winners?|teams? of|submit(?:ted)? (?:a |your )?project|\d+ ?(?:h|hrs?|hours)\b)"
    building = re.search(build, text) or re.search(compete, text)
    kind, confidence = "unknown", 0.0
    cue = "" if re.search(BUILD_EVENT, title) else title
    if pre:
        kind, confidence = "info_session", 0.9
    elif (re.search(TALK, cue) and not re.search(build, text)) or re.search(TALK_STRONG, cue) or (
            source_meta.get("id") == "meetup" and len(re.findall(r" [•·|] ", cue)) >= 2 and not re.search(build, text)):
        kind, confidence = "talk", 0.85
    elif re.search(WORKSHOP, cue) and not re.search(build, text):
        kind, confidence = "workshop", 0.85
    elif re.search(MEETUP, cue) and not re.search(build, text):
        kind, confidence = "meetup", 0.85
    elif re.search(r"\b(conference|summit|congres|expo|intro(?:duction)? to)\b", cue) and not building:
        kind, confidence = "other", 0.9
    elif re.search(HACK_NIGHT, title) and not building:
        kind, confidence = "meetup", 0.8
    else:
        rules = [
            ("game_jam", r"\b(game[ -]?jam|ludum dare|global game jam|jam)\b|ゲームジャム"),
            ("ctf", r"\b(ctf|capture[ -]the[ -]flag)\b"),
            ("ideathon", r"\b(ideathon|idea[ -]thon)\b"),
            ("hackathon", r"\b(hackathons?|hack[ -]?(day|night)|build[ -]?(athon|day|night)|datathon|makeathon|hackaton|hakaton|hackat[oó]n|hakat[oó]n)\b|ハッカソン|해커톤|黑客松|駭客松|хакатон|هاكاثون"),
            ("coding_competition", r"\b(coding competition|programming contest|algorithmic contest|kaggle competition)\b"),
        ]
        for candidate, pattern in rules:
            if re.search(pattern, text):
                kind, confidence = candidate, 0.85
                break
        if kind == "unknown" and re.search(build, text):
            kind, confidence = "hackathon", 0.75
    return event.model_copy(update=dict(kind=kind, confidence=confidence,
                                        classified_by="keyword" if kind != "unknown" else "none"))
