"""HTTP header and cookie utilities for XHS API requests."""

from __future__ import annotations

from data_collection.xhs.browser_fingerprint import get_http_headers


def cookie_header_to_dict(cookie_header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def build_headers(cookie_header: str) -> dict[str, str]:
    return get_http_headers(cookie_header)
