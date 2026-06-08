from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from toolz import curry, pipe

from reactions.models import RawReactorCandidate, ReactorRecord
from reactions.selectors import extract_profile_id, is_profile_href


def normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


@curry
def normalize_url_with_keys(
    keep_query_keys: tuple[str, ...], base_url: str, url: str | None
) -> str | None:
    """Canonicalize a URL, keeping only an allow-list of query keys.

    Curried with ``keep_query_keys`` first so the profile-url normalizer is just a
    partial application. Profile links keep ``id`` so ``profile.php?id=123``
    survives; everything else (tracking params) is dropped.
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


# Profile-url normalizer: keep only ``id`` (so profile.php?id=123 survives), drop
# all tracking params. A partial application of the curried normalizer above; note
# the argument order is now ``(base_url, url)``.
normalize_profile_url = normalize_url_with_keys(("id",))


def _validate_profile_url(url: str | None) -> str | None:
    """Identity for a real profile URL, else None -- a pipe-friendly guard."""
    return url if url and is_profile_href(url) else None


def parse_reactor(candidate: RawReactorCandidate) -> ReactorRecord | None:
    """Turn a raw reactor row into a normalized, de-dup-keyed record."""
    # normalize -> validate composed as a pipe; the None short-circuit (an invalid
    # or non-profile URL) stays an explicit guard since toolz has no Maybe.
    url = pipe(
        normalize_profile_url(candidate.source_url, candidate.profile_url_hint),
        _validate_profile_url,
    )
    if url is None:
        return None
    profile_id = extract_profile_id(url, candidate.profile_url_hint)
    # Dedup key: prefer the stable profile id, fall back to the (validated) URL.
    return ReactorRecord(
        profile_id=profile_id,
        profile_key=profile_id or url,
        name=normalize_whitespace(candidate.name_hint),
        profile_url=url,
        reaction_type=candidate.reaction_type or "unknown",
        post_url=candidate.source_url,
    )
