"""Tests for cookie parsing and login state detection utilities."""

from __future__ import annotations

import time

# --- qrcode_auth cookie helpers ---
from data_collection.xhs.mc_api._headers import cookie_header_to_dict
from data_collection.xhs.qrcode_auth import (
    _cookies_to_header,
    _extract_cookie_value,
    _is_cookie_expired,
    _is_logged_in_from_cookies,
)


class TestCookiesToHeader:
    def test_basic(self):
        cookies = [
            {"name": "b", "value": "2"},
            {"name": "a", "value": "1"},
        ]
        # Should be sorted alphabetically
        assert _cookies_to_header(cookies) == "a=1; b=2"

    def test_empty(self):
        assert _cookies_to_header([]) == ""

    def test_skips_non_string(self):
        cookies = [
            {"name": "a", "value": "1"},
            {"name": None, "value": "x"},
            {"name": "c", "value": None},
        ]
        assert _cookies_to_header(cookies) == "a=1"


class TestExtractCookieValue:
    def test_found(self):
        assert _extract_cookie_value("a1=abc123; id_token=xyz", "a1") == "abc123"

    def test_not_found(self):
        assert _extract_cookie_value("a1=abc123", "missing") == ""

    def test_empty_header(self):
        assert _extract_cookie_value("", "a1") == ""

    def test_value_with_equals(self):
        assert _extract_cookie_value("token=a=b=c", "token") == "a=b=c"


class TestIsCookieExpired:
    def test_not_expired(self):
        cookie = {"expires": time.time() + 3600}
        assert not _is_cookie_expired(cookie)

    def test_expired(self):
        cookie = {"expires": time.time() - 100}
        assert _is_cookie_expired(cookie)

    def test_no_expires(self):
        assert not _is_cookie_expired({})

    def test_zero_expires(self):
        assert not _is_cookie_expired({"expires": 0})

    def test_near_expiry(self):
        # Within 30s buffer → considered expired
        cookie = {"expires": time.time() + 10}
        assert _is_cookie_expired(cookie)


class TestIsLoggedInFromCookies:
    def test_logged_in(self):
        cookies = [
            {"name": "a1", "value": "abc"},
            {"name": "id_token", "value": "xyz", "expires": time.time() + 3600},
        ]
        assert _is_logged_in_from_cookies(cookies)

    def test_missing_a1(self):
        cookies = [
            {"name": "id_token", "value": "xyz", "expires": time.time() + 3600},
        ]
        assert not _is_logged_in_from_cookies(cookies)

    def test_missing_id_token(self):
        cookies = [
            {"name": "a1", "value": "abc"},
        ]
        assert not _is_logged_in_from_cookies(cookies)

    def test_expired_id_token(self):
        cookies = [
            {"name": "a1", "value": "abc"},
            {"name": "id_token", "value": "xyz", "expires": time.time() - 100},
        ]
        assert not _is_logged_in_from_cookies(cookies)

    def test_empty_values(self):
        cookies = [
            {"name": "a1", "value": ""},
            {"name": "id_token", "value": "xyz", "expires": time.time() + 3600},
        ]
        assert not _is_logged_in_from_cookies(cookies)


# --- mc_api/_headers.py cookie utilities ---


class TestCookieHeaderToDict:
    def test_basic(self):
        result = cookie_header_to_dict("a=1; b=2; c=3")
        assert result == {"a": "1", "b": "2", "c": "3"}

    def test_empty(self):
        assert cookie_header_to_dict("") == {}

    def test_whitespace(self):
        result = cookie_header_to_dict("  a = 1 ;  b = 2  ")
        assert result == {"a": "1", "b": "2"}

    def test_value_with_equals(self):
        result = cookie_header_to_dict("token=a=b=c")
        assert result == {"token": "a=b=c"}
