# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/errors.py
"""Failure classes shared by the api runner; the adapter turns them into per-page errors."""

from __future__ import annotations


class XhsApiError(Exception):
    """The platform failed a request; `code` is its body code, `status` the HTTP status."""

    def __init__(self, message: str, code: int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class XhsLoginRequired(XhsApiError):
    """No usable web session: cookies missing, login expired, or a verification challenge."""


class XhsRateLimited(XhsApiError):
    """The platform throttled us (访问频次异常); retried with backoff before this was raised."""
