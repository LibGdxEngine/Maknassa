from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class CommentRecord(BaseModel):
    comment_id: str | None
    parent_comment_id: str | None
    depth: int = Field(ge=0)
    author_name: str | None
    author_profile_url: str | None
    author_thumbnail_url: str | None
    text: str | None
    timestamp_text: str | None
    permalink: str | None


@dataclass(slots=True)
class RawCommentCandidate:
    node_key: str
    outer_html: str
    depth_hint: int
    parent_comment_id_hint: str | None
    permalink_hint: str | None
    source_url: str
    author_name_hint: str | None = None
    author_profile_url_hint: str | None = None
    author_thumbnail_url_hint: str | None = None
    text_hint: str | None = None
    timestamp_text_hint: str | None = None
    page_locale: str | None = None


@dataclass(slots=True)
class SessionStats:
    discovered_nodes: int = 0
    stored_comments: int = 0
    duplicate_comments: int = 0
    failures: int = 0
    expansion_clicks: int = 0
    visible_comment_anchors: int = 0
    unmatched_expand_controls: int = 0
