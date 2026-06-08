from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from reactions.models import RawReactorCandidate, ReactorRecord
from reactions.selectors import extract_profile_id, is_profile_href


def normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def normalize_url_with_keys(
    url: str | None, base_url: str, keep_query_keys: tuple[str, ...] = ()
) -> str | None:
    """Canonicalize a URL, keeping only an allow-list of query keys.

    Ported verbatim from the old scraper -- profile links keep ``id`` so that
    ``profile.php?id=123`` survives, everything else (tracking params) is dropped.
    """
    if not url:
        return None
    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    normalized_query = []
    for key in keep_query_keys:
        for value in query.get(key, []):
            normalized_query.append((key, value))
    query_string = "&".join(f"{key}={value}" for key, value in normalized_query)
    return urlunparse((scheme, netloc, path.rstrip("/") or "/", "", query_string, ""))


def normalize_profile_url(url: str | None, base_url: str) -> str | None:
    return normalize_url_with_keys(url, base_url, keep_query_keys=("id",))


def parse_reactor(candidate: RawReactorCandidate) -> ReactorRecord | None:
    """Turn a raw reactor row into a normalized, de-dup-keyed record."""
    profile_url = normalize_profile_url(candidate.profile_url_hint, candidate.source_url)
    if not profile_url or not is_profile_href(profile_url):
        return None
    name = normalize_whitespace(candidate.name_hint)
    profile_id = extract_profile_id(profile_url, candidate.profile_url_hint)
    # Dedup key: prefer the stable profile id, fall back to the normalized URL.
    profile_key = profile_id or profile_url
    if not profile_key:
        return None
    return ReactorRecord(
        profile_id=profile_id,
        profile_key=profile_key,
        name=name,
        profile_url=profile_url,
        reaction_type=candidate.reaction_type or "unknown",
        post_url=candidate.source_url,
    )
