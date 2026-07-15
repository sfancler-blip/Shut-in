from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RawScreening:
    """Adapter output. starts_at_local is NAIVE theater wall-clock - no tz math in adapters."""

    film_title: str
    starts_at_local: datetime
    description: str | None = None
    poster_url: str | None = None
    ticket_url: str | None = None
    runtime_minutes: int | None = None
    format: str | None = None
    event_note: str | None = None
    film_url: str | None = None


class Adapter(Protocol):
    def fetch(self, config: dict) -> Any: ...
    def parse(self, payload: Any) -> list[RawScreening]: ...
