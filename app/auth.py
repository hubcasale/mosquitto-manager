"""UI authentication: a single shared password, signed session cookie, login throttle."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque

COOKIE_NAME = "mm_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "mosquitto-manager"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(secret: str, hours: int, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = _b64(json.dumps({"iat": int(now), "exp": int(now + hours * 3600)}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(_unb64(payload))
        exp = int(data["exp"])
    except (ValueError, KeyError, TypeError):
        return False
    return (time.time() if now is None else now) < exp


def check_password(expected: str, supplied: str) -> bool:
    """Constant-time comparison (hashing first hides the length)."""
    a = hashlib.sha256(expected.encode()).digest()
    b = hashlib.sha256(supplied.encode()).digest()
    return hmac.compare_digest(a, b)


class LoginThrottle:
    """Allow `limit` failed logins per `window` seconds for each client address."""

    def __init__(self, limit: int = 5, window: float = 300.0):
        self.limit = limit
        self.window = window
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:
            self._fails.pop(key, None)
            return self._fails[key]
        return q

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds the client must wait, 0 if it may try now."""
        now = time.time() if now is None else now
        q = self._prune(key, now)
        if len(q) < self.limit:
            return 0
        return max(1, int(q[0] + self.window - now) + 1)

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)
