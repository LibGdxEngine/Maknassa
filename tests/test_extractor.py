from __future__ import annotations

from reactions.extractor import normalize_profile_url, normalize_whitespace, parse_reactor
from reactions.models import RawReactorCandidate

POST_URL = "https://www.facebook.com/some.page/posts/123456789"


def _candidate(profile_url: str | None, name: str | None, reaction: str = "angry"):
    return RawReactorCandidate(
        name_hint=name,
        profile_url_hint=profile_url,
        reaction_type=reaction,
        source_url=POST_URL,
    )


def test_parse_reactor_numeric_profile():
    record = parse_reactor(
        _candidate("https://www.facebook.com/profile.php?id=100012345&__tn__=R", "Ahmed Fathy")
    )
    assert record is not None
    assert record.profile_id == "100012345"
    assert record.profile_key == "100012345"
    assert record.name == "Ahmed Fathy"
    assert record.reaction_type == "angry"
    assert record.profile_url == "https://www.facebook.com/profile.php?id=100012345"


def test_parse_reactor_username_profile():
    record = parse_reactor(_candidate("https://www.facebook.com/john.doe.5", "John Doe", "haha"))
    assert record is not None
    assert record.profile_id == "john.doe.5"
    assert record.profile_url == "https://www.facebook.com/john.doe.5"
    assert record.reaction_type == "haha"


def test_parse_reactor_rejects_non_profile_links():
    assert parse_reactor(_candidate("https://www.facebook.com/groups/999", "Group")) is None
    assert parse_reactor(_candidate("https://www.facebook.com/some.page/posts/1", "Post")) is None
    assert parse_reactor(_candidate(None, "No URL")) is None


def test_parse_reactor_group_member_numeric():
    """A group post links reactors as /groups/<gid>/user/<uid>/ -- a real user.

    The link must canonicalize to the blockable profile, keyed by the user id,
    not be rejected for containing /groups/.
    """
    record = parse_reactor(
        _candidate("https://www.facebook.com/groups/123456/user/100012345/", "Sara M")
    )
    assert record is not None
    assert record.profile_id == "100012345"
    assert record.profile_key == "100012345"
    assert record.name == "Sara M"
    assert record.profile_url == "https://www.facebook.com/profile.php?id=100012345"


def test_parse_reactor_group_member_pfbid_keeps_distinct_key():
    """A pfbid user id stays the dedup key (not collapsed to 'profile.php')."""
    record = parse_reactor(
        _candidate("https://www.facebook.com/groups/123456/user/pfbid0ABCdef/", "Karim")
    )
    assert record is not None
    assert record.profile_key == "pfbid0ABCdef"
    assert record.profile_url == "https://www.facebook.com/profile.php?id=pfbid0ABCdef"


def test_normalize_whitespace_collapses_and_nulls_empty():
    assert normalize_whitespace("  Ahmed   Fathy ") == "Ahmed Fathy"
    assert normalize_whitespace("\tA\nB\r C ") == "A B C"
    assert normalize_whitespace("   ") is None
    assert normalize_whitespace("") is None
    assert normalize_whitespace(None) is None


def test_parse_reactor_normalizes_unicode_name():
    record = parse_reactor(
        _candidate("https://www.facebook.com/profile.php?id=42", "  أحمد   فتحي  ", "love")
    )
    assert record is not None
    assert record.name == "أحمد فتحي"
    assert record.reaction_type == "love"
    assert record.profile_key == "42"


def test_parse_reactor_blank_reaction_defaults_to_unknown():
    record = parse_reactor(_candidate("https://www.facebook.com/john.doe.5", "John", reaction=""))
    assert record is not None
    assert record.reaction_type == "unknown"


def test_normalize_profile_url_keeps_id_drops_tracking():
    # Curried signature is now (base_url, url).
    assert (
        normalize_profile_url(
            POST_URL, "https://www.facebook.com/profile.php?id=42&__cft__[0]=abc&__tn__=R"
        )
        == "https://www.facebook.com/profile.php?id=42"
    )
    assert (
        normalize_profile_url(POST_URL, "https://www.facebook.com/john.doe.5?ref=tag")
        == "https://www.facebook.com/john.doe.5"
    )
