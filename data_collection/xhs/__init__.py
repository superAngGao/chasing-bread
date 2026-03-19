"""XHS (Xiaohongshu) platform SDK — session management, API client, search, and tracking.

Public API for session/login management:

    from data_collection.xhs import open_session, run_with_session, XhsApiClient

These are the canonical entry points for all modules that need an
authenticated XHS browser session.  Do NOT import qrcode_auth or
session internals directly.
"""

from data_collection.xhs.api_client import XhsApiClient
from data_collection.xhs.qrcode_auth import QrcodeAuthSession
from data_collection.xhs.session import open_xhs_api_session as open_session
from data_collection.xhs.session import run_with_xhs_session as run_with_session

__all__ = [
    "QrcodeAuthSession",
    "XhsApiClient",
    "open_session",
    "run_with_session",
]
