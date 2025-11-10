import logging
import random
import time
from typing import Any, Dict, Optional

import requests  # type: ignore

logger = logging.getLogger("network")

# A small pool of user-agents so repeated runs look slightly less robotic.
USER_AGENTS = [
    # Modern Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # macOS Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Safari/605.1.15",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
    "Gecko/20100101 Firefox/123.0",
]

def create_http_session() -> requests.Session:
    """
    Create a pre-configured requests.Session with headers tuned for TikTok scraping.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )
    # TikTok may require basic cookies to serve a standard HTML page.
    session.cookies.set("tt_webid_v2", "1")
    return session

def fetch_html(
    url: str,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
    retries: int = 1,
) -> str:
    """
    Fetch raw HTML for a given URL with simple retry logic.

    Returns an empty string if the request fails after all retries.
    """
    if session is None:
        session = create_http_session()

    last_error: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            logger.debug("Fetching URL (attempt %d/%d): %s", attempt, retries, url)
            resp = session.get(url, timeout=timeout)
            if resp.status_code >= 400:
                logger.warning(
                    "Received HTTP %s for %s", resp.status_code, url
                )
            resp.raise_for_status()
            # TikTok returns compressed HTML, but requests handles decompression for us.
            logger.debug(
                "Fetched %d bytes from %s", len(resp.content or b""), url
            )
            return resp.text
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Error fetching %s (attempt %d/%d): %s",
                url,
                attempt,
                retries,
                exc,
            )
            # Basic backoff to be a bit nicer to TikTok.
            time.sleep(min(2 * attempt, 10))

    if last_error:
        logger.error("All retries failed for %s: %s", url, last_error)
    return ""

def build_query_params(base: Dict[str, Any], extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Utility for merging base query params with overrides.
    """
    params = dict(base)
    if extras:
        params.update({k: v for k, v in extras.items() if v is not None})
    return params