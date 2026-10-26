"""天道后台密码与进程内会话。"""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque

from game.config import game_config

from .models import ConsoleSession

SESSION_TTL_SECONDS = 12 * 60 * 60
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_MAX_FAILURES = 8
CONSOLE_USERNAME = "天道"


class ConsoleAuthService:
    """用 .env 凭据签发不落库的短期登录会话。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ConsoleSession] = {}
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    @property
    def configured(self) -> bool:
        return bool(self.password)

    @property
    def username(self) -> str:
        return CONSOLE_USERNAME

    @property
    def password(self) -> str:
        return game_config.console.password

    def login(
        self, username: str, password: str, *, source: str = "unknown"
    ) -> ConsoleSession | None:
        self._remove_expired()
        if not self.configured:
            return None
        source_key = str(source or "unknown")[:128]
        if self.is_rate_limited(source_key):
            return None
        username_matches = hmac.compare_digest(
            str(username).encode("utf-8"),
            self.username.encode("utf-8"),
        )
        password_matches = hmac.compare_digest(
            str(password).encode("utf-8"),
            self.password.encode("utf-8"),
        )
        if not username_matches or not password_matches:
            self._failures[source_key].append(time.time())
            return None
        self._failures.pop(source_key, None)
        session = ConsoleSession(
            session_id=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            username=self.username,
            expires_at=time.time() + SESSION_TTL_SECONDS,
        )
        self._sessions[session.session_id] = session
        return session

    def is_rate_limited(self, source: str) -> bool:
        key = str(source or "unknown")[:128]
        failures = self._failures[key]
        cutoff = time.time() - LOGIN_WINDOW_SECONDS
        while failures and failures[0] < cutoff:
            failures.popleft()
        return len(failures) >= LOGIN_MAX_FAILURES

    def require(self, session_id: str) -> ConsoleSession | None:
        self._remove_expired()
        return self._sessions.get(str(session_id or ""))

    def verify_csrf(self, session: ConsoleSession, token: str) -> bool:
        return hmac.compare_digest(session.csrf_token, str(token or ""))

    def logout(self, session_id: str) -> None:
        self._sessions.pop(str(session_id or ""), None)

    def _remove_expired(self) -> None:
        now_value = time.time()
        for session_id, session in tuple(self._sessions.items()):
            if session.expires_at <= now_value:
                self._sessions.pop(session_id, None)


__all__ = ["CONSOLE_USERNAME", "SESSION_TTL_SECONDS", "ConsoleAuthService"]
