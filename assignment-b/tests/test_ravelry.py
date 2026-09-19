"""Ravelry client with a fake HTTP session: match, no match, timeout, 401, no key (live test: test_live.py)."""

from __future__ import annotations

import logging

import pytest
import requests

from swatch.config import CONFIG
from swatch.ravelry import ReferencePhoto, fetch_photo, reference_for_stitch, search_reference


class FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


PHOTO_HIT = {
    "patterns": [
        {"name": "No Photo", "permalink": "no-photo", "first_photo": None},
        {"name": "Cable Hat", "permalink": "cable-hat", "first_photo": {"medium_url": "https://img/x.jpg"}},
    ]
}


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("RAVELRY_AUTH", "basic")
    monkeypatch.setenv("RAVELRY_USERNAME", "user")
    monkeypatch.setenv("RAVELRY_PASSWORD", "pass")


def test_match_returns_first_result_with_photo():
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    ref = search_reference("cable", session=session)
    assert ref.pattern_name == "Cable Hat"
    assert ref.photo_url == "https://img/x.jpg"
    assert ref.pattern_url.endswith("/cable-hat")
    assert session.calls[0][1]["auth"] == ("user", "pass")
    assert session.calls[0][1]["params"]["query"] == "cable"


def test_stitch_maps_to_config_query():
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    reference_for_stitch("rib", session=session)
    assert session.calls[0][1]["params"]["query"] == "ribbed"


@pytest.mark.demo
def test_no_match_returns_none_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("zzqx", session=FakeSession(FakeResponse(200, {"patterns": []}))) is None
    assert "RAVELRY status=no_match" in caplog.text


@pytest.mark.parametrize(
    "result,status",
    [
        (requests.Timeout("slow"), "status=timeout"),
        (FakeResponse(401), "status=error code=401"),
        (requests.ConnectionError("down"), "status=error"),
    ],
)
def test_failures_return_none(result, status, caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("cable", session=FakeSession(result)) is None
    assert status in caplog.text


@pytest.mark.parametrize(
    "body,status",
    [([], "status=error"), ({"patterns": None}, "status=error"), ({"patterns": ["x", {"first_photo": "nope"}]}, "status=no_match")],
)
def test_odd_response_shapes_return_none_and_log(body, status, caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("cable", session=FakeSession(FakeResponse(200, body))) is None
    assert status in caplog.text


def test_unexpected_session_error_returns_none_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("cable", session=FakeSession(RuntimeError("boom"))) is None
    assert "status=error reason='RuntimeError'" in caplog.text


def test_missing_credentials_skip_the_call(monkeypatch, caplog):
    monkeypatch.delenv("RAVELRY_USERNAME")
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("cable", session=session) is None
    assert session.calls == []
    assert "status=no_key" in caplog.text


def test_oauth2_uses_bearer_token(monkeypatch):
    monkeypatch.setenv("RAVELRY_AUTH", "oauth2")
    monkeypatch.setenv("RAVELRY_ACCESS_TOKEN", "tok")
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    search_reference("cable", session=session)
    assert session.calls[0][1]["headers"] == {"Authorization": "Bearer tok"}



def test_unknown_stitch_returns_none_and_logs(caplog):
    """A stitch added live that config.yaml does not know must not traceback the notebook."""
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert reference_for_stitch("moss-diamond-brioche", session=FakeSession(FakeResponse(200, PHOTO_HIT))) is None
    assert "status=unknown_stitch" in caplog.text


def test_http_error_without_a_response_returns_none(caplog):
    """requests.HTTPError can carry no .response; reading .status_code used to raise AttributeError."""
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("cable", session=FakeSession(requests.HTTPError("boom"))) is None
    assert "status=error code=?" in caplog.text


def test_unparseable_timeout_env_uses_the_configured_default(monkeypatch, caplog):
    monkeypatch.setenv("RAVELRY_TIMEOUT_S", "abc")
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert search_reference("cable", session=session) is not None
    assert session.calls[0][1]["timeout"] == CONFIG.ravelry.search_timeout_s
    assert "status=bad_timeout_env" in caplog.text


def test_timeout_env_overrides_the_configured_default(monkeypatch):
    monkeypatch.setenv("RAVELRY_TIMEOUT_S", "1.5")
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    search_reference("cable", session=session)
    assert session.calls[0][1]["timeout"] == 1.5


def test_auth_mode_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("RAVELRY_AUTH", "OAuth2")
    monkeypatch.setenv("RAVELRY_ACCESS_TOKEN", "tok")
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    search_reference("cable", session=session)
    assert session.calls[0][1]["headers"] == {"Authorization": "Bearer tok"}


def test_unknown_auth_mode_warns_and_uses_basic(monkeypatch, caplog):
    monkeypatch.setenv("RAVELRY_AUTH", "oauth")
    session = FakeSession(FakeResponse(200, PHOTO_HIT))
    with caplog.at_level(logging.WARNING, logger="swatch"):
        search_reference("cable", session=session)
    assert session.calls[0][1]["auth"] == ("user", "pass")
    assert "status=unknown_auth_mode" in caplog.text


def test_odd_upstream_fields_are_coerced():
    body = {"patterns": [{"name": None, "permalink": None, "first_photo": {"medium_url": "https://img/x.jpg"}}]}
    ref = search_reference("cable", session=FakeSession(FakeResponse(200, body)))
    assert ref.pattern_name == ""
    assert not ref.pattern_url.endswith("None")


REF = ReferencePhoto(query="cable", pattern_name="Cable Hat", pattern_url="https://rav/p", photo_url="https://img/x.jpg", elapsed_ms=1.0)


class PhotoResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def _png_bytes() -> bytes:
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (8, 8), (90, 60, 150)).save(buf, format="PNG")
    return buf.getvalue()


def test_fetch_photo_returns_an_image():
    session = FakeSession(PhotoResponse(_png_bytes()))
    image = fetch_photo(REF, session=session)
    assert image is not None and image.size == (8, 8)
    assert session.calls[0][0] == REF.photo_url
    assert session.calls[0][1]["timeout"] == CONFIG.ravelry.photo_timeout_s


def test_fetch_photo_non_image_bytes_return_none(caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert fetch_photo(REF, session=FakeSession(PhotoResponse(b"<html>not an image</html>"))) is None
    assert "status=photo_error" in caplog.text


@pytest.mark.parametrize("failure", [PhotoResponse(b"", 404), requests.Timeout("slow"), RuntimeError("boom")])
def test_fetch_photo_failures_return_none(failure, caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        assert fetch_photo(REF, session=FakeSession(failure)) is None
    assert "status=photo_error" in caplog.text
