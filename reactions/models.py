from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


class ReactorRecord(BaseModel):
    """A single person who reacted to the post, with their reaction type."""

    profile_id: str | None
    profile_key: str  # dedup key: numeric id / username slug / normalized url
    name: str | None
    profile_url: str | None
    reaction_type: str  # like / love / care / haha / wow / sad / angry / unknown
    post_url: str
    blocked: bool = False


@dataclass(slots=True)
class RawReactorCandidate:
    """Raw reactor row collected from the live DOM before normalization."""

    name_hint: str | None
    profile_url_hint: str | None
    reaction_type: str
    source_url: str
    page_locale: str | None = None


@dataclass(slots=True)
class SessionStats:
    discovered_rows: int = 0
    stored_reactors: int = 0
    duplicate_reactors: int = 0
    failures: int = 0
    per_type_counts: dict[str, int] = field(default_factory=dict)  # captured (linkable)
    per_type_expected: dict[str, int] = field(default_factory=dict)  # Facebook's tab badge


@dataclass(slots=True)
class BlockOutcome:
    profile_key: str
    name: str | None
    profile_url: str | None
    status: str  # blocked / skipped / failed / dry_run
    detail: str | None = None
