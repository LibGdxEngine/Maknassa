from __future__ import annotations

from functools import partial

import pytest

from reactions.selectors import (
    BLOCK_MENU_LABELS,
    MORE_BUTTON_LABELS,
    extract_profile_id,
    is_profile_href,
    matches_any,
    reaction_type_from_label,
    to_int,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("٤٢", 42),  # Arabic-Indic digits (live reaction tab badge)
        ("5", 5),
        ("١٬٢٣٤", 1234),  # Arabic thousands separator
        ("Haha ٣", 3),
        ("", 0),
        (None, 0),
    ],
)
def test_to_int(text, expected):
    assert to_int(text) == expected


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Like", "like"),
        ("أعجبني", "like"),
        ("Love", "love"),
        ("أحبه", "love"),
        ("Care", "care"),
        ("يهمني", "care"),
        ("Haha", "haha"),
        ("هاها", "haha"),
        ("Wow", "wow"),
        ("واو", "wow"),
        ("Sad", "sad"),
        ("حزين", "sad"),
        ("Angry", "angry"),
        ("غاضب", "angry"),
        ("Angry: 12", "angry"),  # tab labels often include the count
        ("All", None),
        ("", None),
        (None, None),
    ],
)
def test_reaction_type_from_label(label, expected):
    assert reaction_type_from_label(label) == expected


@pytest.mark.parametrize(
    "href,expected",
    [
        ("https://www.facebook.com/profile.php?id=100012345", True),
        ("https://www.facebook.com/john.doe.5", True),
        ("https://www.facebook.com/people/Some-One/100064/", True),
        ("https://www.facebook.com/groups/123456", False),
        ("https://www.facebook.com/story.php?story_fbid=1/posts/2", False),
        ("https://www.facebook.com/somepage/posts/123", False),
        ("https://www.facebook.com/login", False),
        ("", False),
        (None, False),
    ],
)
def test_is_profile_href(href, expected):
    assert is_profile_href(href) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.facebook.com/profile.php?id=100012345&__tn__=x", "100012345"),
        ("https://www.facebook.com/people/Some-One/100064/", "100064"),
        ("https://www.facebook.com/john.doe.5", "john.doe.5"),
        ("https://www.facebook.com/JohN.DoE", "john.doe"),
    ],
)
def test_extract_profile_id(url, expected):
    assert extract_profile_id(url) == expected


def test_localized_action_labels_match_both_languages():
    # Signature is (patterns, value); named predicates are functools.partial.
    is_more = partial(matches_any, MORE_BUTTON_LABELS)
    is_block = partial(matches_any, BLOCK_MENU_LABELS)
    assert is_more("More")
    assert is_more("المزيد")
    assert is_block("Block")
    assert is_block("حظر")
    assert not is_block("Message")
