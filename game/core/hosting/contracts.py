"""托管核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


class HostingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HostingActivity:
    name: str
    state_id: str
    end_state_id: str
    start_command: str
    end_command: str


@dataclass(frozen=True)
class HostingServiceStatus:
    initialized: bool
    control_states: Mapping[str, str]
    activity_names: tuple[str, ...] = ()
    activity_seconds: int = 0
    maximum_seconds: int = 0
    maximum_activities: int = 0


@dataclass(frozen=True)
class HostingSession:
    session_id: str
    mode: str
    leader_user_id: str
    participant_user_ids: tuple[str, ...]
    activities: tuple[str, ...] = ()
    current_index: int = 0
    phase: str = "待开始"
    next_trigger_at: datetime | None = None
    expires_at: datetime | None = None
    cycle_count: int = 0
    execution_count: int = 0
    status: str = "运行中"
    last_error: str = ""
    last_message: str = ""

    @property
    def current_activity(self) -> str:
        if not self.activities:
            return ""
        return self.activities[self.current_index % len(self.activities)]


@dataclass(frozen=True)
class HostingExecution:
    session_id: str
    leader_user_id: str
    participant_user_ids: tuple[str, ...]
    activity: str
    phase: str
    command: str
    request_id: str
    triggered_at: datetime


__all__ = [
    "HostingActivity",
    "HostingError",
    "HostingExecution",
    "HostingServiceStatus",
    "HostingSession",
]
