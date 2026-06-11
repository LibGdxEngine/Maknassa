"""Single source of truth for Facebook DOM selection.

Facebook ships obfuscated, randomized CSS class names (``x1i10hfl`` ...) that
change between sessions and A/B buckets, so class selectors are useless. Every
selector here matches a *stable semantic signal* instead, in priority order:

1. ``href`` shape          -> profile links (numeric id / username / people path)
2. ARIA ``role``           -> dialog / tab / tabpanel / menu / menuitem / button
3. ``aria-label`` text     -> localized (EN + AR), e.g. "More" / "المزيد"
4. visible text / emoji alt -> localized reaction + action labels
5. structural position     -> last-resort tie-breaker only

When Facebook changes its wording, you only edit the tuples in this file and
re-run ``inspect`` mode to capture the live strings for your account/locale.
"""

from __future__ import annotations

import re
from functools import partial

# --------------------------------------------------------------------------- #
# Reaction types: canonical key -> localized labels (English + Arabic).
# These appear as the reaction-tab aria-label/text and as emoji `alt` text.
# --------------------------------------------------------------------------- #
#
# Arabic labels are the *verb* form Facebook uses in the reaction dialog's tab
# aria-label ('... تفاعلوا باستخدام "أحببته"'). Confirmed live: Love is "أحببته"
# (not "أحبه") and Haha is "هاهاها". Older/short forms are kept as fallbacks.
REACTION_LABELS: dict[str, tuple[str, ...]] = {
    "like": ("Like", "أعجبني"),
    "love": ("Love", "أحببته", "أحبه"),
    # The Care reaction localizes as "Support" / "أدعمه" on some posts.
    "care": ("Care", "Support", "أهتم", "يهمني", "أدعمه"),
    "haha": ("Haha", "هاهاها", "هاها"),
    # "واااو" is the elongated live spelling of Wow (the short "واو" never matches it).
    "wow": ("Wow", "أدهشني", "واااو", "واو"),
    "sad": ("Sad", "Sorry", "أحزنني", "حزين"),
    "angry": ("Angry", "أغضبني", "غاضب"),
}

# The "All reactions" tab — collected for completeness but type is left unknown.
ALL_REACTIONS_LABELS: tuple[str, ...] = ("All", "الكل", "All reactions", "كل التفاعلات")

# Words that mark the clickable reaction-summary element under a post. Confirmed
# live, the Arabic aria-label reads:
#   'NaN من التفاعلات؛ تعرف على الأشخاص الذين تفاعلوا مع هذا'
# (Facebook renders the count as "NaN" in the label; the real count is the
# element's visible text, which the opener parses to pick the right post.)
REACTION_SUMMARY_LABELS: tuple[str, ...] = (
    "reactions",
    "people who reacted",
    "see who reacted",
    "who reacted to this",
    "تفاعلوا مع هذا",
    "الذين تفاعلوا",
    "من التفاعلات",
    "الأشخاص الذين أبدوا إعجابهم",
)

# Profile action-bar overflow ("...") trigger.
MORE_BUTTON_LABELS: tuple[str, ...] = (
    "More",
    "More options",
    "See options",
    "المزيد",
    "المزيد من الخيارات",
    "خيارات",
)

# "Block" entry inside the profile's "..." menu.
BLOCK_MENU_LABELS: tuple[str, ...] = ("Block", "حظر")

# "Report" entry — always present in a profile's actions menu, so it (with Block/
# Unblock) is used as a fingerprint to tell the real "..." menu apart from the
# page's other "More" buttons (footer links, "see more comments", etc.).
REPORT_LABELS: tuple[str, ...] = ("Report", "الإبلاغ", "إبلاغ")

# Terms that mark a "More" button we must NOT treat as the profile actions menu.
MORE_DISTRACTOR_TERMS: tuple[str, ...] = (
    "comment",
    "تعليق",
    "footer",
    "تذييل",
    "reply",
    "رد",
)

# Final confirm button inside the block confirmation dialog. Confirmed live the
# Arabic dialog's confirm button is "تأكيد" (Confirm) -- NOT "حظر": the Cancel
# button's aria-label is "إلغاء حظر <name>" (contains حظر), so a naive "حظر"
# match clicks Cancel. Match these exactly and avoid BLOCK_CANCEL_LABELS.
BLOCK_CONFIRM_LABELS: tuple[str, ...] = ("Confirm", "تأكيد", "Block")

# Cancel / close controls to never click during the block confirmation.
BLOCK_CANCEL_LABELS: tuple[str, ...] = ("Cancel", "إلغاء", "Close", "إغلاق")

# Menu entry shown once someone is already blocked -- used to verify a block took
# effect ("إلغاء الحظر" / "الغاء الحظر" = Unblock).
UNBLOCK_LABELS: tuple[str, ...] = ("Unblock", "إلغاء الحظر", "الغاء الحظر")

# Confirm button inside the unblock confirmation dialog.
UNBLOCK_CONFIRM_LABELS: tuple[str, ...] = ("Confirm", "تأكيد", "Unblock", "إلغاء الحظر")

# Login / checkpoint wall detection (reused from the old scraper).
LOGIN_TEXT_PATTERNS: tuple[str, ...] = ("log in", "login", "تسجيل الدخول")

# The persistent Notifications flyout is also a [role="dialog"] and carries its
# own "تأكيد" (Confirm) buttons -- we must skip it when locating the block dialog.
NOTIFICATION_DIALOG_LABELS: tuple[str, ...] = ("الإشعارات", "Notifications")

# --------------------------------------------------------------------------- #
# href-based profile detection.
# --------------------------------------------------------------------------- #
PROFILE_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[?&]id=(\d+)"),
    re.compile(r"/people/[^/]+/(?:pfbid)?([0-9A-Za-z]+)"),
    re.compile(r"/profile/(\d+)"),
)

# Path segments that are NOT user profiles (groups, pages UI, post permalinks…).
NON_PROFILE_PATH_TOKENS: tuple[str, ...] = (
    "/login",
    "/posts/",
    "/permalink/",
    "/photo",
    "/groups/",
    "/watch",
    "/events/",
    "/marketplace/",
    "/stories/",
    "/reel/",
    "/hashtag/",
    "/help",
    "/policies",
    "/privacy",
    "/settings",
)

# A username path is a single segment of allowed chars, e.g. /john.doe.5
_USERNAME_PATH_RE = re.compile(r"^/([A-Za-z0-9.]{3,})/?$")

# A group post links a reactor as /groups/<gid>/user/<uid>/ -- a real user, not
# the group itself. Captures <uid> (numeric or pfbid) for canonicalization.
GROUP_MEMBER_PATH = re.compile(r"/groups/\d+/user/([A-Za-z0-9]+)")


_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def to_int(text: str | None) -> int:
    """Parse an integer from text containing ASCII or Arabic-Indic digits.

    Facebook reaction tabs label their count in the local digit set (e.g. "٤٢").
    Returns 0 when no digits are present.
    """
    if not text:
        return 0
    ascii_text = "".join(
        str(_ARABIC_INDIC_DIGITS.index(ch)) if ch in _ARABIC_INDIC_DIGITS else ch for ch in text
    )
    digits = re.sub(r"[^0-9]", "", ascii_text)
    return int(digits) if digits else 0


def normalize_control_text(value: str | None) -> str:
    """Collapse whitespace / bidi marks and casefold (ported from old scraper)."""
    if not value:
        return ""
    normalized = re.sub(r"[‌-‏﻿]+", " ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return normalized


def matches_any(patterns: tuple[str, ...], value: str | None) -> bool:
    """True if any localized pattern is contained in ``value`` (case-insensitive).

    ``patterns`` comes first so a named predicate is a ``functools.partial``,
    e.g. ``is_block = partial(matches_any, BLOCK_MENU_LABELS)``.
    """
    normalized = normalize_control_text(value)
    if not normalized:
        return False
    return any(normalize_control_text(pattern) in normalized for pattern in patterns)


def reaction_type_from_label(value: str | None) -> str | None:
    """Map a tab's aria-label/text/emoji-alt to a canonical reaction key.

    Checks the more specific labels first so that, e.g., "love" is not shadowed
    by a substring match. Returns ``None`` when nothing matches.
    """
    normalized = normalize_control_text(value)
    if not normalized:
        return None
    # Longest labels first to avoid substring collisions.
    ranked = sorted(
        ((key, label) for key, labels in REACTION_LABELS.items() for label in labels),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )
    for key, label in ranked:
        if normalize_control_text(label) in normalized:
            return key
    return None


# A login/checkpoint-wall detector, built by partially applying ``matches_any``
# to the login text patterns.
is_login_wall = partial(matches_any, LOGIN_TEXT_PATTERNS)


def is_profile_href(href: str | None) -> bool:
    """True when an href points at a user profile (not a post/photo/group/etc.)."""
    if not href:
        return False
    lowered = href.lower()
    if "facebook.com" not in lowered and not href.startswith("/"):
        return False
    if any(token in lowered for token in NON_PROFILE_PATH_TOKENS):
        return False
    if "profile.php" in lowered and "id=" in lowered:
        return True
    if "/people/" in lowered:
        return True
    # Bare username path: strip the origin then test the path shape.
    path = re.sub(r"^https?://[^/]+", "", href)
    path = path.split("?", 1)[0].split("#", 1)[0]
    return bool(_USERNAME_PATH_RE.match(path))


def extract_profile_id(*values: str | None) -> str | None:
    """Numeric / pfbid profile id from a URL, else the bare username slug."""
    for value in values:
        if not value:
            continue
        for pattern in PROFILE_ID_PATTERNS:
            match = pattern.search(value)
            if match:
                return match.group(1)
    # Fall back to the username slug.
    for value in values:
        if not value:
            continue
        path = re.sub(r"^https?://[^/]+", "", value)
        path = path.split("?", 1)[0].split("#", 1)[0]
        match = _USERNAME_PATH_RE.match(path)
        if match:
            return match.group(1).lower()
    return None
