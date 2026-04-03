from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from lxml import html

from scraper.models import CommentRecord, RawCommentCandidate

COMMENT_ID_PATTERNS = (
    re.compile(r"[?&]comment_id=(\d+)"),
    re.compile(r"/posts/[^/?#]+[/?].*comment_id=(\d+)"),
    re.compile(r"/permalink/(\d+)"),
    re.compile(r"/comment/(\d+)"),
    re.compile(r'"commentID":"(\d+)"'),
    re.compile(r'"comment_id":"(\d+)"'),
    re.compile(r'data-commentid="(\d+)"'),
)


def normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def normalize_url(url: str | None, base_url: str) -> str | None:
    return normalize_url_with_keys(url, base_url, keep_query_keys=("comment_id", "reply_comment_id", "story_fbid", "id"))


def normalize_url_with_keys(url: str | None, base_url: str, keep_query_keys: tuple[str, ...] = ()) -> str | None:
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


def extract_comment_id(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        for pattern in COMMENT_ID_PATTERNS:
            match = pattern.search(value)
            if match:
                return match.group(1)
    return None


def _first_text(doc: html.HtmlElement, xpaths: list[str]) -> str | None:
    for xpath in xpaths:
        for item in doc.xpath(xpath):
            text = item if isinstance(item, str) else item.text_content()
            normalized = normalize_whitespace(text)
            if normalized:
                return normalized
    return None


def _first_attr(doc: html.HtmlElement, xpaths: list[str], base_url: str) -> str | None:
    for xpath in xpaths:
        try:
            values = doc.xpath(xpath)
        except Exception:
            continue
        for value in values:
            normalized = normalize_url(str(value), base_url)
            if normalized:
                return normalized
    return None


def parse_comment(candidate: RawCommentCandidate) -> CommentRecord | None:
    if not candidate.outer_html.strip():
        return None
    doc = html.fromstring(candidate.outer_html)
    permalink = normalize_url(
        candidate.permalink_hint,
        candidate.source_url,
    ) or _first_attr(
        doc,
        [
            './/a[contains(@href, "comment_id=")]/@href',
            './/a[contains(@href, "/permalink/")]/@href',
            './/a[contains(@href, "/comment/")]/@href',
        ],
        candidate.source_url,
    )
    comment_id = extract_comment_id(
        permalink,
        candidate.outer_html,
        doc.get("id"),
        doc.get("data-commentid"),
    )
    author_profile_url = normalize_url_with_keys(
        candidate.author_profile_url_hint,
        candidate.source_url,
        keep_query_keys=(),
    ) or _first_attr(
        doc,
        [
            './/a[@role="link" and not(contains(@href, "comment_id=")) and normalize-space(text())][1]/@href',
            './/h3//a[1]/@href',
            './/strong//a[1]/@href',
            './/a[1]/@href',
        ],
        candidate.source_url,
    )
    if author_profile_url:
        author_profile_url = normalize_url_with_keys(author_profile_url, candidate.source_url, keep_query_keys=())
    author_name = normalize_whitespace(candidate.author_name_hint) or _first_text(
        doc,
        [
            './/h3//a[1]/text()',
            './/strong//a[1]/text()',
            './/a[@role="link" and normalize-space(text())][1]/text()',
        ],
    )
    author_thumbnail_url = normalize_url_with_keys(
        candidate.author_thumbnail_url_hint,
        candidate.source_url,
        keep_query_keys=(),
    ) or _first_attr(
        doc,
        [
            ".//img[1]/@src",
            ".//image/@href",
            ".//image/@xlink:href",
        ],
        candidate.source_url,
    )
    if not author_thumbnail_url:
        style_value = _first_text(doc, [".//*[contains(@style, 'background-image')][1]/@style"])
        if style_value:
            extracted = re.search(r"url\(['\"]?(.*?)['\"]?\)", style_value)
            if extracted:
                author_thumbnail_url = normalize_url_with_keys(extracted.group(1), candidate.source_url, keep_query_keys=())
    timestamp_text = normalize_whitespace(candidate.timestamp_text_hint) or _first_text(
        doc,
        [
            './/a[contains(@href, "comment_id=")]//text()',
            './/abbr//text()',
            './/time//text()',
        ],
    )
    text = normalize_whitespace(candidate.text_hint) or _first_text(
        doc,
        [
            './/*[@data-ad-preview="message"]//text()',
            './/*[contains(@class, "xdj266r")]//text()',
            './/div[@dir="auto" and not(descendant::a[contains(@href, "comment_id=")])]//text()',
            './/span[@dir="auto"]//text()',
        ],
    )
    if text:
        ignored_texts = {author_name, timestamp_text}
        if text in ignored_texts:
            text = None
    if not any((comment_id, author_name, text, timestamp_text)):
        return None
    parent_comment_id = candidate.parent_comment_id_hint
    depth = max(candidate.depth_hint, 0)
    return CommentRecord(
        comment_id=comment_id,
        parent_comment_id=parent_comment_id,
        depth=depth,
        author_name=author_name,
        author_profile_url=author_profile_url,
        author_thumbnail_url=author_thumbnail_url,
        text=text,
        timestamp_text=timestamp_text,
        permalink=normalize_url(permalink, candidate.source_url),
    )
