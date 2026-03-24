"""Tests for browser fingerprint consistency and anti-detection utilities."""

from __future__ import annotations

from data_collection.xhs.browser_fingerprint import (
    CHROME_MAJOR,
    SEC_CH_UA,
    SEC_CH_UA_PLATFORM,
    USER_AGENT,
    get_context_options,
    get_http_headers,
    get_launch_args,
    get_persistent_context_options,
    get_stealth_js,
)


class TestFingerprintConsistency:
    """Verify that UA, sec-ch-ua, and HTTP headers all reference the same Chrome version."""

    def test_ua_contains_chrome_version(self):
        assert f"Chrome/{CHROME_MAJOR}" in USER_AGENT

    def test_sec_ch_ua_contains_chrome_version(self):
        assert f'v="{CHROME_MAJOR}"' in SEC_CH_UA

    def test_ua_matches_real_os(self):
        import platform

        system = platform.system()
        if system == "Windows":
            assert "Windows NT" in USER_AGENT
            assert "Windows" in SEC_CH_UA_PLATFORM
        elif system == "Darwin":
            assert "Macintosh" in USER_AGENT
            assert "macOS" in SEC_CH_UA_PLATFORM
        elif system == "Linux":
            assert "Linux" in USER_AGENT
            assert "Linux" in SEC_CH_UA_PLATFORM

    def test_http_headers_match_ua(self):
        headers = get_http_headers("test=1")
        assert headers["user-agent"] == USER_AGENT
        assert headers["sec-ch-ua"] == SEC_CH_UA
        assert headers["Cookie"] == "test=1"

    def test_context_options_include_anti_detection(self):
        opts = get_context_options()
        assert "--disable-blink-features=AutomationControlled" in opts["args"]

    def test_context_options_headless_flag(self):
        opts_headless = get_context_options(headless=True)
        opts_headed = get_context_options(headless=False)
        assert opts_headless["headless"] is True
        assert opts_headed["headless"] is False

    def test_locale_and_timezone(self):
        opts = get_context_options()
        assert opts["locale"] == "zh-CN"
        assert opts["timezone_id"] == "Asia/Shanghai"


class TestPersistentContextOptions:
    """Persistent context includes identity headers for consistent fingerprint."""

    def test_has_user_agent(self):
        opts = get_persistent_context_options()
        assert "user_agent" in opts
        assert "Chrome" in opts["user_agent"]

    def test_no_geolocation(self):
        opts = get_persistent_context_options()
        assert "geolocation" not in opts
        assert "permissions" not in opts

    def test_has_sec_ch_ua_headers(self):
        opts = get_persistent_context_options()
        headers = opts.get("extra_http_headers", {})
        assert "sec-ch-ua" in headers
        assert "sec-ch-ua-platform" in headers

    def test_has_anti_detection_args(self):
        opts = get_persistent_context_options()
        assert "--disable-blink-features=AutomationControlled" in opts["args"]

    def test_has_locale_and_timezone(self):
        opts = get_persistent_context_options()
        assert opts["locale"] == "zh-CN"
        assert opts["timezone_id"] == "Asia/Shanghai"

    def test_no_sandbox_removed(self):
        """--no-sandbox can affect cookie storage on Windows."""
        opts = get_persistent_context_options()
        assert "--no-sandbox" not in opts["args"]


class TestEphemeralContextOptions:
    """Ephemeral context can have full fingerprint settings."""

    def test_has_extra_headers(self):
        opts = get_context_options()
        assert "extra_http_headers" in opts
        assert opts["extra_http_headers"]["sec-ch-ua"] == SEC_CH_UA

    def test_has_user_agent(self):
        opts = get_context_options()
        assert opts["user_agent"] == USER_AGENT


class TestLaunchArgs:
    def test_contains_anti_detection_flag(self):
        args = get_launch_args()
        assert "--disable-blink-features=AutomationControlled" in args

    def test_no_sandbox_removed(self):
        args = get_launch_args()
        assert "--no-sandbox" not in args


class TestStealthJs:
    def test_stealth_js_not_empty(self):
        js = get_stealth_js()
        assert len(js) > 100  # Should have stealth.min.js + patches

    def test_stealth_js_contains_webdriver_patch(self):
        js = get_stealth_js()
        assert "navigator" in js
        assert "webdriver" in js
