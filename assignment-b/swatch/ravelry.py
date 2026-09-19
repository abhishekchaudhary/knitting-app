"""Ravelry reference photo: search patterns by stitch keyword, return the first result with a photo.

Never raises. No credentials, timeout, HTTP error or no match all return None
and log one `RAVELRY status=...` line, so the notebook shows the generated
swatch on its own.

Example: reference_for_stitch("cable") -> ReferencePhoto(pattern_name=..., photo_url=...) or None.
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from PIL import Image

from swatch.config import CONFIG

logger = logging.getLogger("swatch")

# RAVELRY_AUTH values we understand (DECISIONS D7: basic is the default).
_AUTH_MODES = ("basic", "oauth2")
# Where a pattern's permalink lives on the Ravelry website.
_PATTERN_PAGE_URL = "https://www.ravelry.com/patterns/library/{permalink}"


@dataclass(frozen=True)
class ReferencePhoto:
    """A Ravelry pattern that matched the stitch search, and the URL of its photo."""

    query: str
    pattern_name: str
    pattern_url: str
    photo_url: str
    elapsed_ms: float


def search_reference(
    query: str, timeout_s: float | None = None, session: requests.Session | None = None
) -> ReferencePhoto | None:
    """First pattern for `query` that has a photo, or None."""
    auth = _auth()
    if auth is None:
        logger.warning("RAVELRY status=no_key query=%r", query)
        return None
    timeout_s = _timeout(timeout_s)
    http = session or requests
    start = time.perf_counter()
    patterns = _search_patterns(query, auth, timeout_s, http)
    if patterns is None:
        return None
    elapsed = round((time.perf_counter() - start) * 1000, 1)
    return _first_with_photo(patterns, query, elapsed)


def reference_for_stitch(stitch_type: str, **kwargs: Any) -> ReferencePhoto | None:
    """Reference photo for a configured stitch. A stitch with no config entry returns None
    (a new stitch added live must not traceback the notebook)."""
    try:
        query = CONFIG.stitch(stitch_type).ravelry_query
    except ValueError:
        logger.warning("RAVELRY status=unknown_stitch stitch=%r", stitch_type)
        return None
    return search_reference(query, **kwargs)


def fetch_photo(ref: ReferencePhoto, session: requests.Session | None = None) -> Image.Image | None:
    """Download the reference photo, or None (never raises). `session` is injectable for tests."""
    http = session or requests
    try:
        response = http.get(ref.photo_url, timeout=CONFIG.ravelry.photo_timeout_s)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as exc:  # HTTP error, timeout, non-image bytes: the reference is optional
        logger.warning("RAVELRY status=photo_error reason=%r", type(exc).__name__)
        return None


# --- Private helpers, in the order they are used above ---


def _auth() -> dict[str, Any] | None:
    """kwargs for requests: Basic Auth (default, DECISIONS D7) or an OAuth2 bearer token.

    RAVELRY_AUTH is case-insensitive; an unknown value warns and falls back to Basic, so a typo
    on the live-edit path is visible in the log instead of silently changing the auth mode.
    """
    mode = (os.environ.get("RAVELRY_AUTH") or "basic").strip().casefold()
    if mode not in _AUTH_MODES:
        logger.warning("RAVELRY status=unknown_auth_mode mode=%r (using basic; known: %s)", mode, list(_AUTH_MODES))
        mode = "basic"
    if mode == "oauth2":
        token = os.environ.get("RAVELRY_ACCESS_TOKEN")
        return {"headers": {"Authorization": f"Bearer {token}"}} if token else None
    username = os.environ.get("RAVELRY_USERNAME")
    password = os.environ.get("RAVELRY_PASSWORD")
    return {"auth": (username, password)} if username and password else None


def _timeout(timeout_s: float | None) -> float:
    """Explicit argument, else RAVELRY_TIMEOUT_S, else config.yaml ravelry.search_timeout_s.
    An unparseable env var warns and uses the configured default rather than raising."""
    if timeout_s is not None:
        return float(timeout_s)
    env_value = os.environ.get("RAVELRY_TIMEOUT_S")
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            logger.warning("RAVELRY status=bad_timeout_env value=%r (using %s)", env_value, CONFIG.ravelry.search_timeout_s)
    return CONFIG.ravelry.search_timeout_s


def _search_patterns(query: str, auth: dict[str, Any], timeout_s: float, http: Any) -> list | None:
    """The `patterns` list from Ravelry's search, or None (logged) on timeout, HTTP error or an odd response."""
    settings = CONFIG.ravelry
    try:
        response = http.get(
            settings.base_url + settings.search_path,
            params={"query": query, "page_size": settings.page_size},
            timeout=timeout_s,
            **auth,
        )
        response.raise_for_status()
        body = response.json()
        patterns = body.get("patterns") if isinstance(body, dict) else None
        if not isinstance(patterns, list):
            raise ValueError("unexpected response shape")
    except requests.Timeout:
        logger.warning("RAVELRY status=timeout query=%r timeout_s=%s", query, timeout_s)
        return None
    except requests.HTTPError as exc:
        error_response = getattr(exc, "response", None)
        status_code = getattr(error_response, "status_code", "?")
        logger.warning("RAVELRY status=error code=%s query=%r", status_code, query)
        return None
    except Exception as exc:  # anything else (bad JSON, odd session): the reference is optional
        logger.warning("RAVELRY status=error reason=%r query=%r", type(exc).__name__, query)
        return None
    return patterns


def _first_with_photo(patterns: list, query: str, elapsed: float) -> ReferencePhoto | None:
    """The first well-formed pattern that has a photo URL, or None (logged as no_match)."""
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        photo = pattern.get("first_photo") if isinstance(pattern.get("first_photo"), dict) else {}
        photo_url = photo.get("medium2_url") or photo.get("medium_url")
        if photo_url:
            logger.info(
                "RAVELRY status=match query=%r pattern=%r elapsed_ms=%.0f", query, pattern.get("name"), elapsed
            )
            name = pattern.get("name") or ""
            permalink = pattern.get("permalink") or ""
            return ReferencePhoto(
                query=query,
                pattern_name=str(name),
                pattern_url=_PATTERN_PAGE_URL.format(permalink=permalink),
                photo_url=photo_url,
                elapsed_ms=elapsed,
            )
    logger.warning("RAVELRY status=no_match query=%r results=%d elapsed_ms=%.0f", query, len(patterns), elapsed)
    return None
