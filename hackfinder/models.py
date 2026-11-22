"""Shared data contract. Every collector returns a list[Event]."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Kind = Literal["hackathon", "game_jam", "ctf", "coding_competition", "ideathon", "other", "unknown"]
Format = Literal["online", "in-person", "hybrid", "unknown"]


class Event(BaseModel):
    # identity
    source: str                      # collector id, e.g. "devpost"
    source_id: Optional[str] = None  # id on the source site if available
    url: str                         # canonical event / registration URL (absolute)

    # content
    title: str
    description: Optional[str] = None  # short plain text, <= ~500 chars
    image: Optional[str] = None

    # when / where (datetimes timezone-aware UTC when known; None if unknown)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    format: Format = "unknown"
    location: Optional[str] = None   # "City, Country" or None for online
    country: Optional[str] = None

    # extras
    prize: Optional[str] = None      # human string as shown, e.g. "$5,000"
    prize_usd: Optional[float] = None
    participants: Optional[int] = None
    organizer: Optional[str] = None
    tags: list[str] = Field(default_factory=list)  # domain tags: ai, web3, student, ...

    # raw source evidence for the Hackfinder Score (DECISIONS.md #4), e.g.
    # {"registrations": 1800, "featured": True, "sponsors": ["Google"], "ctf_weight": 24.5}
    signals: dict[str, Any] = Field(default_factory=dict)

    # classification (filled by collector hint, finalized by classify.py)
    kind: Kind = "unknown"
    confidence: float = 0.0
    classified_by: Literal["source", "keyword", "llm", "manual", "none"] = "none"

    # provenance (filled by pipeline)
    also_on: list[str] = Field(default_factory=list)  # other sources listing the same event
    fetched_at: Optional[datetime] = None
