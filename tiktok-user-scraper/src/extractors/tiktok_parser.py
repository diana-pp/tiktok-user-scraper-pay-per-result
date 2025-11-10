import json
import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup  # type: ignore

from extractors.utils_network import fetch_html  # type: ignore

logger = logging.getLogger("tiktok_parser")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(\+?\d[\d\s\-]{7,}\d)"
)  # naive pattern; enough for detecting presence

@dataclass
class TikTokUser:
    id: str = ""
    url: str = ""
    username: str = ""
    nickname: str = ""
    bio: str = ""
    followers: int = 0
    following: int = 0
    likes: int = 0
    videos: int = 0
    verified: bool = False
    avatar: str = ""
    region: str = ""
    language: str = ""
    hasEmail: bool = False
    hasPhone: bool = False
    coverImage: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Merge "extra" fields into the top-level dictionary
        extra = data.pop("extra", {}) or {}
        data.update(extra)
        return data

def _extract_username_from_url(url: str) -> str:
    """
    Extracts username from TikTok profile or video URL.

    Examples:
    - https://www.tiktok.com/@username -> username
    - https://www.tiktok.com/@username/video/123456 -> username
    """
    # Normalize URL
    url = url.strip()
    if not url:
        return ""

    # Remove query params and fragments
    url = url.split("?", 1)[0].split("#", 1)[0]

    # Look for @username segment
    match = re.search(r"/@([^/]+)/?", url)
    if match:
        return match.group(1)

    return ""

def _detect_contacts(bio: str) -> Tuple[bool, bool]:
    if not bio:
        return False, False
    has_email = EMAIL_RE.search(bio) is not None
    has_phone = PHONE_RE.search(bio) is not None
    return has_email, has_phone

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            # Remove commas and other formatting
            cleaned = re.sub(r"[^\d]", "", value)
            return int(cleaned) if cleaned else default
        return default
    except Exception:
        return default

def _deep_get(data: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node

def _parse_from_sigi_state(html: str) -> Dict[str, Any]:
    """
    TikTok embeds structured data in a script tag with id="SIGI_STATE".
    This helper returns that JSON object if present.
    """
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="SIGI_STATE")
    if not script or not script.string:
        return {}

    try:
        return json.loads(script.string)
    except Exception as exc:
        logger.debug("Failed to parse SIGI_STATE JSON: %s", exc)
        return {}

def _select_primary_user(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given a parsed SIGI_STATE-like dict, try to pick the most relevant user dictionary.
    """
    # Newer TikTok layouts often expose user data under UserModule.users
    users = _deep_get(data, ["UserModule", "users"], {})
    if isinstance(users, dict) and users:
        # Pick the first user entry
        first_key = next(iter(users))
        user = users.get(first_key, {})
        stats = _deep_get(data, ["UserModule", "stats", first_key], {})
        merged = dict(user)
        if isinstance(stats, dict):
            merged.setdefault("stats", stats)
        return merged

    # Fallback: try UserPage.userInfo
    user_info = _deep_get(data, ["UserPage", "userInfo"], {})
    if isinstance(user_info, dict):
        return user_info

    return {}

def _parse_user_from_structured_json(url: str, html: str) -> Optional[TikTokUser]:
    sigi_state = _parse_from_sigi_state(html)
    if not sigi_state:
        return None

    user_data = _select_primary_user(sigi_state)
    if not user_data:
        return None

    # Two common layouts:
    # 1) {"id": "...", "uniqueId": "...", "nickname": "...", "avatarLarger": "...", ...}
    # 2) {"user": {...}, "stats": {...}}
    if "user" in user_data and "stats" in user_data:
        user_info = user_data.get("user", {}) or {}
        stats = user_data.get("stats", {}) or {}
    else:
        user_info = user_data
        stats = user_data.get("stats", {}) or {}

    username = user_info.get("uniqueId") or _extract_username_from_url(url)
    nickname = user_info.get("nickname", "")
    bio = user_info.get("signature", "")
    avatar = (
        user_info.get("avatarLarger")
        or user_info.get("avatarThumb")
        or user_info.get("avatarMedium")
        or ""
    )
    region = user_info.get("region", "") or user_info.get("country", "")
    language = user_info.get("language", "")
    cover_image = user_info.get("coverImage", "")

    followers = _safe_int(
        stats.get("followerCount")
        or stats.get("fans")
        or stats.get("followers")
        or stats.get("follower")
    )
    following = _safe_int(
        stats.get("followingCount")
        or stats.get("following")
        or stats.get("followings")
    )
    likes = _safe_int(
        stats.get("heartCount")
        or stats.get("heart")
        or stats.get("totalFavorited")
        or stats.get("likes")
    )
    videos = _safe_int(
        stats.get("videoCount")
        or stats.get("videos")
        or stats.get("video")
    )

    uid = str(
        user_info.get("id")
        or user_info.get("uid")
        or _deep_get(sigi_state, ["UserPage", "uniqueId"], "")
    )

    verified = bool(user_info.get("verified") or user_info.get("badgeVerification"))

    has_email, has_phone = _detect_contacts(bio)

    return TikTokUser(
        id=uid,
        url=url,
        username=username,
        nickname=nickname,
        bio=bio,
        followers=followers,
        following=following,
        likes=likes,
        videos=videos,
        verified=verified,
        avatar=avatar,
        region=region,
        language=language,
        hasEmail=has_email,
        hasPhone=has_phone,
        coverImage=cover_image,
    )

def _parse_from_open_graph(url: str, html: str) -> Optional[TikTokUser]:
    """
    Basic fallback using OpenGraph meta tags and title when structured JSON is unavailable.
    """
    soup = BeautifulSoup(html, "html.parser")

    def og(name: str) -> str:
        tag = soup.find("meta", attrs={"property": f"og:{name}"})
        if tag and tag.get("content"):
            return str(tag["content"])
        return ""

    title = og("title")
    description = og("description")
    image = og("image")

    # Often the title looks like: "nickname (@username) | TikTok"
    username = _extract_username_from_url(url)
    nickname = ""
    if title:
        m = re.match(r"(.+?)\s+\(@(.+?)\)", title)
        if m:
            nickname = m.group(1).strip()
            if not username:
                username = m.group(2).strip()
        else:
            nickname = title.replace("| TikTok", "").strip()

    bio = description or ""
    has_email, has_phone = _detect_contacts(bio)

    return TikTokUser(
        id="",
        url=url,
        username=username,
        nickname=nickname,
        bio=bio,
        avatar=image,
        hasEmail=has_email,
        hasPhone=has_phone,
    )

def parse_user_from_url(
    url: str,
    session: Any,
    timeout: int = 10,
    retries: int = 1,
) -> Optional[TikTokUser]:
    """
    High-level API used by the runner.

    Attempts to fetch a TikTok profile or video URL, extract the author's profile,
    and return a TikTokUser object. It is resilient and will fall back to
    minimal parsing when full structured data isn't available.
    """
    logger.info("Processing URL: %s", url)

    html = fetch_html(
        url=url,
        session=session,
        timeout=timeout,
        retries=retries,
    )

    if not html:
        logger.warning("No HTML returned for %s", url)
        # Best-effort minimal object using just URL and username
        username = _extract_username_from_url(url)
        return TikTokUser(id="", url=url, username=username)

    # First try to parse the embedded JSON state
    user = _parse_from_sigi_state(html)
    if isinstance(user, TikTokUser):
        return user

    structured_user = _parse_user_from_structured_json(url, html)
    if structured_user:
        return structured_user

    # Fallback: OpenGraph meta tags
    og_user = _parse_from_open_graph(url, html)
    if og_user:
        return og_user

    # Final fallback: very minimal user object
    username = _extract_username_from_url(url)
    logger.debug("Falling back to minimal user for %s", url)
    return TikTokUser(id="", url=url, username=username)