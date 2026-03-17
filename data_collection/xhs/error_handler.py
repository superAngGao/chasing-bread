from __future__ import annotations

import asyncio
import logging
from enum import Enum, auto

from data_collection.xhs.mc_api import XhsApiError, is_account_state_error

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    RATE_LIMIT = auto()
    AUTH_INVALID = auto()
    IP_BLOCK = auto()
    NOTE_ABNORMAL = auto()
    NETWORK_ERROR = auto()
    DATA_EMPTY = auto()
    UNKNOWN = auto()


class RecoveryAction(Enum):
    RETRY_IMMEDIATELY = auto()
    RETRY_WITH_BACKOFF = auto()
    LONG_SLEEP = auto()
    RELOGIN = auto()
    ROTATE_PROXY = auto()
    SKIP = auto()
    ABORT = auto()


class XhsErrorHandler:
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(__name__)

    def classify(self, exc: Exception | str | int) -> ErrorType:
        code: int | None = None
        msg: str = ""

        if isinstance(exc, XhsApiError):
            code = exc.code
            msg = exc.msg or ""
        elif isinstance(exc, (int, float)):
            code = int(exc)
        else:
            msg = str(exc)

        if is_account_state_error(code, msg):
            if code in {-100, -101, -104} or "登录" in msg:
                return ErrorType.AUTH_INVALID
            return ErrorType.RATE_LIMIT

        if code == 300012 or "network connection" in msg.lower():
            return ErrorType.IP_BLOCK

        if code == -510001 or "note status abnormal" in msg.lower():
            return ErrorType.NOTE_ABNORMAL

        if "timeout" in msg.lower() or "connection" in msg.lower():
            return ErrorType.NETWORK_ERROR

        return ErrorType.UNKNOWN

    def determine_action(
        self, error_type: ErrorType, attempt: int = 1
    ) -> tuple[RecoveryAction, float]:
        if error_type == ErrorType.RATE_LIMIT:
            wait_time = min(120 * (2 ** (attempt - 1)), 600)
            return RecoveryAction.LONG_SLEEP, wait_time

        if error_type == ErrorType.AUTH_INVALID:
            return RecoveryAction.RELOGIN, 0.0

        if error_type == ErrorType.IP_BLOCK:
            return RecoveryAction.RETRY_WITH_BACKOFF, 10.0

        if error_type == ErrorType.NETWORK_ERROR:
            return RecoveryAction.RETRY_WITH_BACKOFF, 2.0 * attempt

        if error_type == ErrorType.NOTE_ABNORMAL:
            return RecoveryAction.SKIP, 0.0

        return RecoveryAction.ABORT, 0.0

    async def execute_recovery(
        self, action: RecoveryAction, wait_time: float, context_msg: str = ""
    ):
        if action == RecoveryAction.LONG_SLEEP:
            self.logger.warning(f"{context_msg} -> Hit Rate Limit. Sleeping for {wait_time}s...")
            await asyncio.sleep(wait_time)
        elif action == RecoveryAction.RETRY_WITH_BACKOFF:
            self.logger.info(f"{context_msg} -> Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
        elif action == RecoveryAction.RETRY_IMMEDIATELY:
            pass
        elif action == RecoveryAction.RELOGIN:
            self.logger.error(f"{context_msg} -> Session expired. Requires Re-Login.")
            raise ReLoginRequiredError(context_msg)
        elif action == RecoveryAction.SKIP:
            self.logger.warning(f"{context_msg} -> Skipping item (unrecoverable).")
        elif action == RecoveryAction.ABORT:
            self.logger.critical(f"{context_msg} -> Critical error. Aborting.")
            raise AbortError(context_msg)


class ReLoginRequiredError(Exception):
    pass


class AbortError(Exception):
    pass
