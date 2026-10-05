"""核心数据库的 SQLite 内部实现；不属于跨服务公共接口。"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from uuid import uuid4

from .contracts import (
    CommittedTransaction,
    DatabaseError,
    IdempotencyConflictError,
    LocationMutation,
    LocationRecord,
    MutationChange,
    NearbyLocationRecord,
    SharedConstraintError,
    SharedEntityMutation,
    SharedEntityRecord,
    SharedLocationMutation,
    SharedLocationRecord,
    SharedMemberMutation,
    SharedMemberRecord,
    StateAddress,
    StateConflictError,
    StateMutation,
    StateSnapshot,
    TransactionCommand,
    TransactionReceipt,
)

_SHARED_ENTITY_ID_FIELDS = {
    "宗门": "编号",
    "宗门同行": "宗门编号",
    "宗门灵藏": "宗门编号",
    "宗门万珍殿": "宗门编号",
    "宗门灵脉": "宗门编号",
    "宗门灵田": "宗门编号",
    "托管计划": "托管编号",
    "宗门战": "宗门战编号",
}

#: 一次请求（一条命令）范围内的只读连接缓存。请求之外恒为 None —— 句柄不跨请求存活。
_REQUEST_CONNECTIONS: ContextVar["_RequestConnections | None"] = ContextVar(
    "core_database_request_connections", default=None
)


class _ReusableConnection:
    """请求范围内复用的一条连接。

    它只由**创建它的那个线程**取用（缓存键里带线程身份），所以不会有两条线程同时
    用它；而收尾常常发生在另一条线程上（命令跑完的那条），因此以
    `check_same_thread=False` 建，并用一把小锁保证「关闭」不与「使用」交叉：正在被
    使用时先记作待退休，由释放它的那条线程顺手关闭。
    """

    __slots__ = ("_connection", "_lock", "_using", "_retire", "_closed")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = RLock()
        self._using = 0
        self._retire = False
        self._closed = False

    @contextmanager
    def hold(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._using += 1
        try:
            yield self._connection
        finally:
            with self._lock:
                self._using -= 1
                if self._retire and not self._using:
                    self._close_locked()

    def retire(self) -> None:
        """请求收尾：没人用就立刻关，有人用就等它释放时关。"""

        with self._lock:
            if self._using:
                self._retire = True
            else:
                self._close_locked()

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connection.close()


class _RequestConnections:
    """一次请求内的连接缓存：按「库路径 + 连接参数 + 线程」各留一条。"""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, int, int], _ReusableConnection] = {}
        self._lock = RLock()
        self._closed = False

    def acquire(
        self,
        key: tuple[str, int, int],
        factory: Callable[[], sqlite3.Connection],
    ) -> _ReusableConnection | None:
        """取本线程在这条库路径上的连接；请求已收尾时给 None（退回新建连接）。"""

        with self._lock:
            if self._closed:
                return None
            entry = self._entries.get(key)
            if entry is None:
                entry = _ReusableConnection(factory())
                self._entries[key] = entry
            return entry

    def close_all(self) -> None:
        """收尾：先关掉「还能进缓存」这条路，再逐条退休。"""

        with self._lock:
            self._closed = True
            entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.retire()


def open_request_connections() -> Callable[[], None]:
    """开启一次请求范围内的连接复用，返回收尾函数。

    驱动器在一条消息开始时调用；返回的收尾函数在**这条消息处理完**时调用（守卫拦下、
    业务抛错、提前 return 三条路径都会走到）：它先让缓存不再接受新的取用，再关闭其中
    每一条连接。取用一律按**当时的库路径**作键，两次请求之间换库（快照回档、测试换库）
    自然拿到新连接，不会把旧句柄借出去；请求之外没有缓存，读取照旧每次新建连接。
    """

    cache = _RequestConnections()
    token = _REQUEST_CONNECTIONS.set(cache)

    def close() -> None:
        cache.close_all()
        with suppress(ValueError):
            _REQUEST_CONNECTIONS.reset(token)

    return close


# 玩家存档折叠：每玩家一行（state_type='player', state_key='main'），行内为
# { "类型/键": {"值": …, "版本": n, "时间": …} }；老形态（一个状态键一行）读写时现场合并。
_BLOB_TYPE = "player"
_BLOB_KEY = "main"


def _逻辑键(state_type: str, state_key: str) -> str:
    return f"{state_type}/{state_key}"


def _读逻辑状态(connection: sqlite3.Connection, user_id: str) -> dict[str, dict[str, object]]:
    """读出某玩家全部逻辑状态（自动合并老形态的行）。"""
    条目: dict[str, dict[str, object]] = {}
    for 行 in connection.execute(
        "SELECT state_type, state_key, state_json, version, updated_at "
        "FROM state_snapshot WHERE user_id = ?",
        (user_id,),
    ).fetchall():
        state_type, state_key, state_json, version, updated_at = 行
        if str(state_type) == _BLOB_TYPE and str(state_key) == _BLOB_KEY:
            continue
        条目[_逻辑键(str(state_type), str(state_key))] = {
            "值": json.loads(str(state_json)),
            "版本": int(version),
            "时间": str(updated_at),
        }
    行 = connection.execute(
        "SELECT state_json FROM state_snapshot "
        "WHERE user_id = ? AND state_type = ? AND state_key = ?",
        (user_id, _BLOB_TYPE, _BLOB_KEY),
    ).fetchone()
    if 行 is not None:
        for 键, 项 in json.loads(str(行[0])).items():
            条目[str(键)] = 项
    return 条目


def _写逻辑状态(
    connection: sqlite3.Connection,
    user_id: str,
    payload: dict[str, dict[str, object]],
    committed_at: str,
) -> None:
    """整体写回单行，并清掉该玩家残留的老形态行。"""
    现有 = connection.execute(
        "SELECT version FROM state_snapshot "
        "WHERE user_id = ? AND state_type = ? AND state_key = ?",
        (user_id, _BLOB_TYPE, _BLOB_KEY),
    ).fetchone()
    新版本 = (int(现有[0]) + 1) if 现有 is not None else 1
    connection.execute(
        "DELETE FROM state_snapshot WHERE user_id = ? AND NOT (state_type = ? AND state_key = ?)",
        (user_id, _BLOB_TYPE, _BLOB_KEY),
    )
    connection.execute(
        "DELETE FROM state_snapshot WHERE user_id = ? AND state_type = ? AND state_key = ?",
        (user_id, _BLOB_TYPE, _BLOB_KEY),
    )
    connection.execute(
        "INSERT INTO state_snapshot (user_id, state_type, state_key, state_json, version, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, _BLOB_TYPE, _BLOB_KEY,
         json.dumps(payload, ensure_ascii=False, sort_keys=True), 新版本, committed_at),
    )


class SQLiteStateStore:
    """玩家状态、位置与幂等事务的 SQLite 仓储。"""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._write_lock = RLock()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("核心数据库已经初始化")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS state_snapshot (
                    user_id TEXT NOT NULL,
                    state_type TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, state_type, state_key)
                );
                CREATE TABLE IF NOT EXISTS committed_transaction (
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    business_type TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL,
                    UNIQUE (user_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS player_location (
                    user_id TEXT PRIMARY KEY,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS player_space (
                    user_id TEXT PRIMARY KEY,
                    space_type TEXT NOT NULL,
                    space_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_state_snapshot_user
                ON state_snapshot(user_id, state_type);
                CREATE INDEX IF NOT EXISTS ix_committed_transaction_user
                ON committed_transaction(user_id, committed_at);
                CREATE INDEX IF NOT EXISTS ix_player_location_xy
                ON player_location(x, y, user_id);
                CREATE TABLE IF NOT EXISTS shared_entity (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id),
                    UNIQUE (entity_type, entity_name)
                );
                CREATE TABLE IF NOT EXISTS shared_member (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    join_order INTEGER NOT NULL CHECK (join_order > 0),
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id, user_id),
                    UNIQUE (entity_type, user_id)
                );
                CREATE TABLE IF NOT EXISTS shared_location (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id),
                    UNIQUE (entity_type, x, y)
                );
                CREATE INDEX IF NOT EXISTS ix_shared_member_entity
                ON shared_member(entity_type, entity_id, join_order, user_id);
                CREATE INDEX IF NOT EXISTS ix_shared_location_xy
                ON shared_location(entity_type, x, y);
                """
            )
        self._initialized = True

    def counts(self) -> tuple[int, int, int, int, int, int]:
        self._require_initialized()
        with self._connect(reusable=True) as connection:
            state_count = int(
                connection.execute("SELECT COUNT(*) FROM state_snapshot").fetchone()[0]
            )
            location_count = int(
                connection.execute("SELECT COUNT(*) FROM player_location").fetchone()[0]
            )
            transaction_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM committed_transaction"
                ).fetchone()[0]
            )
            shared_entity_count = int(
                connection.execute("SELECT COUNT(*) FROM shared_entity").fetchone()[0]
            )
            shared_member_count = int(
                connection.execute("SELECT COUNT(*) FROM shared_member").fetchone()[0]
            )
            shared_location_count = int(
                connection.execute("SELECT COUNT(*) FROM shared_location").fetchone()[0]
            )
        return (
            state_count,
            location_count,
            transaction_count,
            shared_entity_count,
            shared_member_count,
            shared_location_count,
        )

    def get_shared_entity(
        self, entity_type: str, entity_id: str
    ) -> SharedEntityRecord | None:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        _validate_text(entity_id, "entity_id")
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT entity_name, value_json, version, updated_at
                FROM shared_entity
                WHERE entity_type = ? AND entity_id = ?
                """,
                (entity_type, entity_id),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row[1]))
        if not isinstance(value, dict):
            raise DatabaseError("共享实体 JSON 根值必须是对象")
        value = _shared_entity_view(value, entity_type, entity_id, str(row[0]))
        return SharedEntityRecord(
            entity_type,
            entity_id,
            _freeze_json(value),
            int(row[2]),
            str(row[3]),
        )

    def get_shared_entity_by_name(
        self, entity_type: str, entity_name: str
    ) -> SharedEntityRecord | None:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        _validate_text(entity_name, "entity_name")
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT entity_id, entity_name, value_json, version, updated_at
                FROM shared_entity
                WHERE entity_type = ? AND entity_name = ?
                """,
                (entity_type, entity_name),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row[2]))
        if not isinstance(value, dict):
            raise DatabaseError("共享实体 JSON 根值必须是对象")
        value = _shared_entity_view(
            value, entity_type, str(row[0]), str(row[1])
        )
        return SharedEntityRecord(
            entity_type,
            str(row[0]),
            _freeze_json(value),
            int(row[3]),
            str(row[4]),
        )

    def list_shared_entities(
        self, entity_type: str
    ) -> tuple[SharedEntityRecord, ...]:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        with self._connect(reusable=True) as connection:
            rows = connection.execute(
                """
                SELECT entity_id, entity_name, value_json, version, updated_at
                FROM shared_entity
                WHERE entity_type = ?
                ORDER BY entity_id
                """,
                (entity_type,),
            ).fetchall()
        result = []
        for row in rows:
            value = json.loads(str(row[2]))
            if not isinstance(value, dict):
                raise DatabaseError("共享实体 JSON 根值必须是对象")
            value = _shared_entity_view(
                value, entity_type, str(row[0]), str(row[1])
            )
            result.append(
                SharedEntityRecord(
                    entity_type, str(row[0]), _freeze_json(value), int(row[3]), str(row[4])
                )
            )
        return tuple(result)

    def get_shared_member(
        self, entity_type: str, user_id: str
    ) -> SharedMemberRecord | None:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        _validate_text(user_id, "user_id")
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT entity_id, role, join_order, version, updated_at
                FROM shared_member
                WHERE entity_type = ? AND user_id = ?
                """,
                (entity_type, user_id),
            ).fetchone()
        return (
            SharedMemberRecord(
                entity_type,
                str(row[0]),
                user_id,
                str(row[1]),
                int(row[2]),
                int(row[3]),
                str(row[4]),
            )
            if row is not None
            else None
        )

    def get_shared_members(
        self, entity_type: str, user_ids: tuple[str, ...]
    ) -> tuple[SharedMemberRecord, ...]:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        if not user_ids:
            return ()
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("user_ids不能重复")
        for user_id in user_ids:
            _validate_text(user_id, "user_id")
        placeholders = ", ".join("?" for _ in user_ids)
        with self._connect(reusable=True) as connection:
            rows = connection.execute(
                f"""
                SELECT entity_id, user_id, role, join_order, version, updated_at
                FROM shared_member
                WHERE entity_type = ? AND user_id IN ({placeholders})
                """,
                (entity_type, *user_ids),
            ).fetchall()
        return tuple(
            SharedMemberRecord(
                entity_type,
                str(row[0]),
                str(row[1]),
                str(row[2]),
                int(row[3]),
                int(row[4]),
                str(row[5]),
            )
            for row in rows
        )

    def list_shared_members(
        self, entity_type: str, entity_id: str
    ) -> tuple[SharedMemberRecord, ...]:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        _validate_text(entity_id, "entity_id")
        with self._connect(reusable=True) as connection:
            rows = connection.execute(
                """
                SELECT user_id, role, join_order, version, updated_at
                FROM shared_member
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY join_order, user_id
                """,
                (entity_type, entity_id),
            ).fetchall()
        return tuple(
            SharedMemberRecord(
                entity_type,
                entity_id,
                str(row[0]),
                str(row[1]),
                int(row[2]),
                int(row[3]),
                str(row[4]),
            )
            for row in rows
        )

    def get_shared_location(
        self, entity_type: str, entity_id: str
    ) -> SharedLocationRecord | None:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        _validate_text(entity_id, "entity_id")
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT x, y, version, updated_at
                FROM shared_location
                WHERE entity_type = ? AND entity_id = ?
                """,
                (entity_type, entity_id),
            ).fetchone()
        return (
            SharedLocationRecord(
                entity_type,
                entity_id,
                (int(row[0]), int(row[1])),
                int(row[2]),
                str(row[3]),
            )
            if row is not None
            else None
        )

    def shared_location_at(
        self, entity_type: str, xy: tuple[int, int]
    ) -> SharedLocationRecord | None:
        self._require_initialized()
        _validate_text(entity_type, "entity_type")
        x, y = _validate_xy(xy)
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT entity_id, x, y, version, updated_at
                FROM shared_location
                WHERE entity_type = ? AND x = ? AND y = ?
                """,
                (entity_type, x, y),
            ).fetchone()
        return (
            SharedLocationRecord(
                entity_type,
                str(row[0]),
                (int(row[1]), int(row[2])),
                int(row[3]),
                str(row[4]),
            )
            if row is not None
            else None
        )

    def get(self, address: StateAddress) -> StateSnapshot | None:
        self._require_initialized()
        _validate_address(address)
        with self._connect(reusable=True) as connection:
            条目 = _读逻辑状态(connection, address.user_id)
        项 = 条目.get(_逻辑键(address.state_type, address.state_key))
        if 项 is None:
            return None
        return StateSnapshot(address, _freeze_json(项["值"]), int(项["版本"]), str(项["时间"]))

    def list_for_user(
        self, user_id: str, state_type: str | None = None
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        _validate_text(user_id, "user_id")
        if state_type is not None:
            _validate_text(state_type, "state_type")
        with self._connect(reusable=True) as connection:
            条目 = _读逻辑状态(connection, user_id)
        出: list[StateSnapshot] = []
        for 键 in sorted(条目, key=lambda 名: tuple(名.split("/", 1))):
            类型, 键名 = 键.split("/", 1)
            if state_type is not None and 类型 != state_type:
                continue
            项 = 条目[键]
            出.append(StateSnapshot(StateAddress(user_id, 类型, 键名), _freeze_json(项["值"]), int(项["版本"]), str(项["时间"])))
        return tuple(出)

    def get_many(
        self, addresses: tuple[StateAddress, ...]
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        if not addresses:
            return ()
        for address in addresses:
            _validate_address(address)
        if len(addresses) != len(
            {(item.user_id, item.state_type, item.state_key) for item in addresses}
        ):
            raise ValueError("批量状态地址不能重复")
        快照: dict[tuple[str, str, str], StateSnapshot] = {}
        with self._connect(reusable=True) as connection:
            for 用户 in sorted({item.user_id for item in addresses}):
                for 键, 项 in _读逻辑状态(connection, 用户).items():
                    类型, 键名 = 键.split("/", 1)
                    快照[(用户, 类型, 键名)] = StateSnapshot(
                        StateAddress(用户, 类型, 键名), _freeze_json(项["值"]), int(项["版本"]), str(项["时间"])
                    )
        return tuple(
            快照[(address.user_id, address.state_type, address.state_key)]
            for address in addresses
            if (address.user_id, address.state_type, address.state_key) in 快照
        )

    def get_location(self, user_id: str) -> LocationRecord | None:
        self._require_initialized()
        _validate_text(user_id, "user_id")
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT p.x, p.y, p.version, p.updated_at,
                       COALESCE(s.space_type, '地表'), COALESCE(s.space_id, '')
                FROM player_location AS p
                LEFT JOIN player_space AS s ON s.user_id = p.user_id
                WHERE p.user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return LocationRecord(
            user_id,
            (int(row[0]), int(row[1])),
            int(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
        )

    def get_locations(self, user_ids: tuple[str, ...]) -> tuple[LocationRecord, ...]:
        """批量读一批人的地表位置：一条连接读完，缺行的人不出现（顺序同输入）。"""

        self._require_initialized()
        if not user_ids:
            return ()
        for user_id in user_ids:
            _validate_text(user_id, "user_id")
        unique = tuple(dict.fromkeys(user_ids))
        found: dict[str, LocationRecord] = {}
        with self._connect(reusable=True) as connection:
            for chunk in _chunks(unique, 300):
                placeholders = ", ".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT p.user_id, p.x, p.y, p.version, p.updated_at,
                           COALESCE(s.space_type, '地表'), COALESCE(s.space_id, '')
                    FROM player_location AS p
                    LEFT JOIN player_space AS s ON s.user_id = p.user_id
                    WHERE p.user_id IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    found[str(row[0])] = LocationRecord(
                        str(row[0]),
                        (int(row[1]), int(row[2])),
                        int(row[3]),
                        str(row[4]),
                        str(row[5]),
                        str(row[6]),
                    )
        return tuple(found[user_id] for user_id in unique if user_id in found)

    def nearby_locations(
        self,
        *,
        origin_xy: tuple[int, int],
        space_type: str,
        space_id: str,
        radius_meters: int,
        cell_size_meters: int,
        limit: int,
        exclude_user_id: str,
    ) -> tuple[NearbyLocationRecord, ...]:
        self._require_initialized()
        origin_x, origin_y = _validate_xy(origin_xy)
        _validate_space(space_type, space_id)
        _validate_text(exclude_user_id, "exclude_user_id")
        for value, label in (
            (radius_meters, "radius_meters"),
            (cell_size_meters, "cell_size_meters"),
            (limit, "limit"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} 必须是正整数")
        cell_radius = (radius_meters + cell_size_meters - 1) // cell_size_meters
        radius_squared = radius_meters * radius_meters
        cells = sorted(
            (
                (
                    (dx * dx + dy * dy) * cell_size_meters * cell_size_meters,
                    origin_x + dx,
                    origin_y + dy,
                )
                for dx in range(-cell_radius, cell_radius + 1)
                for dy in range(-cell_radius, cell_radius + 1)
                if (dx * dx + dy * dy) * cell_size_meters * cell_size_meters
                <= radius_squared
            ),
            key=lambda value: (value[0], value[1], value[2]),
        )
        result: list[NearbyLocationRecord] = []
        with self._connect(reusable=True) as connection:
            for distance_squared, x, y in cells:
                remaining = limit - len(result)
                if remaining == 0:
                    break
                rows = connection.execute(
                    """
                    SELECT p.user_id,
                           COALESCE(s.space_type, '地表'), COALESCE(s.space_id, '')
                    FROM player_location AS p
                    LEFT JOIN player_space AS s ON s.user_id = p.user_id
                    WHERE p.x = ? AND p.y = ? AND p.user_id <> ?
                      AND COALESCE(s.space_type, '地表') = ?
                      AND COALESCE(s.space_id, '') = ?
                    ORDER BY p.user_id
                    LIMIT ?
                    """,
                    (x, y, exclude_user_id, space_type, space_id, remaining),
                ).fetchall()
                result.extend(
                    NearbyLocationRecord(
                        user_id=str(row[0]),
                        xy=(x, y),
                        horizontal_distance_squared_meters=distance_squared,
                        space_type=str(row[1]),
                        space_id=str(row[2]),
                    )
                    for row in rows
                )
        return tuple(result)

    def committed_transaction(
        self, user_id: str, request_id: str
    ) -> CommittedTransaction | None:
        """只读取得一次已经提交的幂等事务。"""

        self._require_initialized()
        with self._connect(reusable=True) as connection:
            row = connection.execute(
                """
                SELECT transaction_id, business_type, changes_json, committed_at
                FROM committed_transaction
                WHERE user_id = ? AND request_id = ?
                """,
                (user_id, request_id),
            ).fetchone()
        if row is None:
            return None
        stored = json.loads(str(row[2]))
        payload = stored.get("payload")
        if not isinstance(payload, dict):
            raise DatabaseError("已提交事务缺少对象载荷")
        command = TransactionCommand(user_id, request_id, str(row[1]), (), {})
        return CommittedTransaction(
            _receipt_from_row(command, row, replayed=True),
            _freeze_json(payload),
        )

    def commit(self, command: TransactionCommand) -> TransactionReceipt:
        self._require_initialized()
        _validate_command(command)
        # 指纹与落库共用同一份「共享实体规范化正文」，见 `_command_json`。
        entity_storages: dict[tuple[str, str], Mapping[str, object]] = {}
        fingerprint = _command_json(command, entity_storages)
        transaction_id = uuid4().hex
        committed_at = _now()
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT transaction_id, business_type, changes_json, committed_at
                    FROM committed_transaction
                    WHERE user_id = ? AND request_id = ?
                    """,
                    (command.user_id, command.request_id),
                ).fetchone()
                if existing is not None:
                    stored = json.loads(str(existing[2]))
                    if stored.get("command") != fingerprint:
                        raise IdempotencyConflictError("request_id 已提交过不同事务")
                    connection.execute("COMMIT")
                    return _receipt_from_row(command, existing, replayed=True)

                changes: list[MutationChange] = []
                for operation in command.operations:
                    if isinstance(operation, StateMutation):
                        changes.append(
                            _apply_mutation(connection, operation, committed_at)
                        )
                    elif isinstance(operation, LocationMutation):
                        changes.append(
                            _apply_location_mutation(
                                connection, operation, committed_at
                            )
                        )
                    elif isinstance(operation, SharedEntityMutation):
                        changes.append(
                            _apply_shared_entity_mutation(
                                connection,
                                operation,
                                committed_at,
                                entity_storages.get(
                                    (operation.entity_type, operation.entity_id)
                                ),
                            )
                        )
                    elif isinstance(operation, SharedMemberMutation):
                        changes.append(
                            _apply_shared_member_mutation(
                                connection, operation, committed_at
                            )
                        )
                    else:
                        changes.append(
                            _apply_shared_location_mutation(
                                connection, operation, committed_at
                            )
                        )
                changes_json = {
                    "command": fingerprint,
                    "payload": _json_value(command.payload),
                    "changes": [_change_json(change) for change in changes],
                }
                # 这三部分都已经过 `_json_value`（`_command_json` / `_shared_entity_storage`
                # 内含），`changes` 全是标量，所以直接编码；再走一趟规范化只是把同一棵
                # 58 万字符的树又爬一遍。
                connection.execute(
                    """
                    INSERT INTO committed_transaction (
                        transaction_id, user_id, request_id, business_type,
                        changes_json, committed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        command.user_id,
                        command.request_id,
                        command.business_type,
                        _encode_ready(changes_json),
                        committed_at,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return TransactionReceipt(
            transaction_id=transaction_id,
            user_id=command.user_id,
            request_id=command.request_id,
            business_type=command.business_type,
            committed_at=committed_at,
            replayed=False,
            changes=tuple(changes),
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("核心数据库尚未初始化")

    @contextmanager
    def _connect(self, *, reusable: bool = False) -> Iterator[sqlite3.Connection]:
        """取一条连接。

        `reusable=True` 的读取优先用**本次请求**的连接缓存：同一条命令里同一线程的多次
        读取共用一条连接（省掉每次重开文件、重读分页器的固定开销，见
        `open_request_connections`），请求一结束就关闭。写入与建表恒走新建连接，
        事务语义与原先一致。
        """

        cache = _REQUEST_CONNECTIONS.get() if reusable else None
        if cache is not None:
            entry = cache.acquire(
                (str(self.path), self.busy_timeout_ms, threading.get_ident()),
                lambda: self._new_connection(shared=True),
            )
            if entry is not None:
                with entry.hold() as connection:
                    yield connection
                return
        connection = self._new_connection()
        try:
            yield connection
        finally:
            connection.close()

    def _new_connection(self, *, shared: bool = False) -> sqlite3.Connection:
        """建一条连接并设好本服务的固定参数。

        `shared=True` 只给请求范围内的复用连接用：它由线程甲建、可能由线程乙收尾关闭，
        因此放开 `check_same_thread`；「同一时刻只有一条线程用它」由缓存键保证。
        """

        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            check_same_thread=not shared,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection


def _apply_mutation(
    connection: sqlite3.Connection,
    mutation: StateMutation,
    committed_at: str,
) -> MutationChange:
    条目 = _读逻辑状态(connection, mutation.user_id)
    键 = _逻辑键(mutation.state_type, mutation.state_key)
    现有 = 条目.get(键)
    current_version = int(现有["版本"]) if 现有 is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError(
            f"状态版本冲突：{mutation.state_type}/{mutation.state_key} "
            f"期望 {mutation.expected_version}，实际 {current_version}"
        )
    if mutation.value is None:
        if 现有 is None:
            raise StateConflictError("不能删除不存在的状态")
        条目.pop(键)
        _写逻辑状态(connection, mutation.user_id, 条目, committed_at)
        return MutationChange(
            "player_state", mutation.user_id, mutation.state_type, mutation.state_key,
            "delete", current_version, None,
        )
    next_version = current_version + 1
    条目[键] = {"值": json.loads(_encode(mutation.value)), "版本": next_version, "时间": committed_at}
    _写逻辑状态(connection, mutation.user_id, 条目, committed_at)
    return MutationChange(
        "player_state", mutation.user_id, mutation.state_type, mutation.state_key,
        "insert" if 现有 is None else "update", current_version or None, next_version,
    )


def _apply_location_mutation(
    connection: sqlite3.Connection,
    mutation: LocationMutation,
    committed_at: str,
) -> MutationChange:
    row = connection.execute(
        "SELECT version FROM player_location WHERE user_id = ?",
        (mutation.user_id,),
    ).fetchone()
    current_version = int(row[0]) if row is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError(
            f"位置版本冲突：期望 {mutation.expected_version}，实际 {current_version}"
        )
    if mutation.xy is None:
        if row is None:
            raise StateConflictError("不能删除不存在的位置")
        connection.execute(
            "DELETE FROM player_location WHERE user_id = ?",
            (mutation.user_id,),
        )
        connection.execute(
            "DELETE FROM player_space WHERE user_id = ?", (mutation.user_id,)
        )
        return MutationChange(
            "player_location",
            mutation.user_id,
            "location",
            "main",
            "delete",
            current_version,
            None,
        )

    x, y = _validate_xy(mutation.xy)
    next_version = current_version + 1
    if row is None:
        connection.execute(
            """
            INSERT INTO player_location (user_id, x, y, version, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mutation.user_id, x, y, next_version, committed_at),
        )
        operation = "insert"
    else:
        connection.execute(
            """
            UPDATE player_location
            SET x = ?, y = ?, version = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (x, y, next_version, committed_at, mutation.user_id),
        )
        operation = "update"
    space_type = str(mutation.space_type or "").strip()
    space_id = str(mutation.space_id or "").strip()
    _validate_space(space_type, space_id)
    connection.execute(
        """
        INSERT INTO player_space (user_id, space_type, space_id)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            space_type = excluded.space_type,
            space_id = excluded.space_id
        """,
        (mutation.user_id, space_type, space_id),
    )
    return MutationChange(
        "player_location",
        mutation.user_id,
        "location",
        "main",
        operation,
        current_version or None,
        next_version,
    )


def _apply_shared_entity_mutation(
    connection: sqlite3.Connection,
    mutation: SharedEntityMutation,
    committed_at: str,
    storage: Mapping[str, object] | None = None,
) -> MutationChange:
    """`storage` 是已经规范化过的正文（由 `_command_json` 顺带算出），给了就不重算。"""
    _validate_text(mutation.entity_type, "entity_type")
    _validate_text(mutation.entity_id, "entity_id")
    row = connection.execute(
        """
        SELECT version
        FROM shared_entity
        WHERE entity_type = ? AND entity_id = ?
        """,
        (mutation.entity_type, mutation.entity_id),
    ).fetchone()
    current_version = int(row[0]) if row is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError("共享实体版本冲突")
    if mutation.value is None:
        if row is None:
            raise StateConflictError("不能删除不存在的共享实体")
        connection.execute(
            "DELETE FROM shared_entity WHERE entity_type = ? AND entity_id = ?",
            (mutation.entity_type, mutation.entity_id),
        )
        return MutationChange(
            "shared_entity",
            mutation.entity_id,
            mutation.entity_type,
            "main",
            "delete",
            current_version,
            None,
        )
    name = str(mutation.value.get("名称") or "").strip()
    if not name:
        raise ValueError("共享实体必须包含非空名称")
    encoded = _encode_ready(
        storage
        if storage is not None
        else _shared_entity_storage(
            mutation.entity_type, mutation.entity_id, mutation.value
        )
    )
    next_version = current_version + 1
    try:
        if row is None:
            connection.execute(
                """
                INSERT INTO shared_entity (
                    entity_type, entity_id, entity_name, value_json, version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mutation.entity_type,
                    mutation.entity_id,
                    name,
                    encoded,
                    next_version,
                    committed_at,
                ),
            )
            operation = "insert"
        else:
            connection.execute(
                """
                UPDATE shared_entity
                SET entity_name = ?, value_json = ?, version = ?, updated_at = ?
                WHERE entity_type = ? AND entity_id = ?
                """,
                (
                    name,
                    encoded,
                    next_version,
                    committed_at,
                    mutation.entity_type,
                    mutation.entity_id,
                ),
            )
            operation = "update"
    except sqlite3.IntegrityError as exc:
        raise SharedConstraintError("共享实体名称已经存在") from exc
    return MutationChange(
        "shared_entity",
        mutation.entity_id,
        mutation.entity_type,
        "main",
        operation,
        current_version or None,
        next_version,
    )


def _apply_shared_member_mutation(
    connection: sqlite3.Connection,
    mutation: SharedMemberMutation,
    committed_at: str,
) -> MutationChange:
    _validate_text(mutation.entity_type, "entity_type")
    _validate_text(mutation.user_id, "user_id")
    existing = connection.execute(
        """
        SELECT entity_id, version
        FROM shared_member
        WHERE entity_type = ? AND user_id = ?
        """,
        (mutation.entity_type, mutation.user_id),
    ).fetchone()
    current_version = int(existing[1]) if existing is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError("共享成员版本冲突")
    if mutation.entity_id is None:
        if existing is None:
            raise StateConflictError("不能删除不存在的共享成员")
        connection.execute(
            "DELETE FROM shared_member WHERE entity_type = ? AND user_id = ?",
            (mutation.entity_type, mutation.user_id),
        )
        return MutationChange(
            "shared_member",
            mutation.user_id,
            mutation.entity_type,
            str(existing[0]),
            "delete",
            current_version,
            None,
        )
    _validate_text(mutation.entity_id, "entity_id")
    _validate_text(mutation.role, "role")
    if isinstance(mutation.join_order, bool) or mutation.join_order < 1:
        raise ValueError("join_order必须是正整数")
    next_version = current_version + 1
    try:
        if existing is None:
            connection.execute(
                """
                INSERT INTO shared_member (
                    entity_type, entity_id, user_id, role, join_order, version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mutation.entity_type,
                    mutation.entity_id,
                    mutation.user_id,
                    mutation.role,
                    mutation.join_order,
                    next_version,
                    committed_at,
                ),
            )
            operation = "insert"
        else:
            connection.execute(
                """
                UPDATE shared_member
                SET entity_id = ?, role = ?, join_order = ?, version = ?, updated_at = ?
                WHERE entity_type = ? AND user_id = ?
                """,
                (
                    mutation.entity_id,
                    mutation.role,
                    mutation.join_order,
                    next_version,
                    committed_at,
                    mutation.entity_type,
                    mutation.user_id,
                ),
            )
            operation = "update"
    except sqlite3.IntegrityError as exc:
        raise SharedConstraintError("共享成员归属或顺序违反唯一约束") from exc
    return MutationChange(
        "shared_member",
        mutation.user_id,
        mutation.entity_type,
        mutation.entity_id,
        operation,
        current_version or None,
        next_version,
    )


def _apply_shared_location_mutation(
    connection: sqlite3.Connection,
    mutation: SharedLocationMutation,
    committed_at: str,
) -> MutationChange:
    _validate_text(mutation.entity_type, "entity_type")
    _validate_text(mutation.entity_id, "entity_id")
    row = connection.execute(
        """
        SELECT x, y, version
        FROM shared_location
        WHERE entity_type = ? AND entity_id = ?
        """,
        (mutation.entity_type, mutation.entity_id),
    ).fetchone()
    current_version = int(row[2]) if row is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError("共享位置版本冲突")
    if mutation.xy is None:
        if row is None:
            raise StateConflictError("不能删除不存在的共享位置")
        connection.execute(
            "DELETE FROM shared_location WHERE entity_type = ? AND entity_id = ?",
            (mutation.entity_type, mutation.entity_id),
        )
        return MutationChange(
            "shared_location",
            mutation.entity_id,
            mutation.entity_type,
            "main",
            "delete",
            current_version,
            None,
        )
    x, y = _validate_xy(mutation.xy)
    next_version = current_version + 1
    try:
        if row is None:
            connection.execute(
                """
                INSERT INTO shared_location (
                    entity_type, entity_id, x, y, version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mutation.entity_type, mutation.entity_id, x, y, next_version, committed_at),
            )
            operation = "insert"
        else:
            connection.execute(
                """
                UPDATE shared_location
                SET x = ?, y = ?, version = ?, updated_at = ?
                WHERE entity_type = ? AND entity_id = ?
                """,
                (
                    x,
                    y,
                    next_version,
                    committed_at,
                    mutation.entity_type,
                    mutation.entity_id,
                ),
            )
            operation = "update"
    except sqlite3.IntegrityError as exc:
        raise SharedConstraintError("共享位置已经被其他实体占用") from exc
    return MutationChange(
        "shared_location",
        mutation.entity_id,
        mutation.entity_type,
        "main",
        operation,
        current_version or None,
        next_version,
    )


def _snapshot(
    address: StateAddress, row: sqlite3.Row | tuple[object, ...]
) -> StateSnapshot:
    state_json, version, updated_at = row
    value = json.loads(str(state_json))
    if not isinstance(value, dict):
        raise DatabaseError("状态 JSON 根值必须是对象")
    return StateSnapshot(address, _freeze_json(value), int(version), str(updated_at))


def _receipt_from_row(
    command: TransactionCommand,
    row: sqlite3.Row | tuple[object, ...],
    *,
    replayed: bool,
) -> TransactionReceipt:
    stored = json.loads(str(row[2]))
    changes = tuple(
        MutationChange(
            str(change.get("scope", "player_state")),
            str(change["user_id"]),
            str(change["state_type"]),
            str(change["state_key"]),
            str(change["operation"]),
            _optional_int(change.get("before_version")),
            _optional_int(change.get("after_version")),
        )
        for change in stored.get("changes", [])
    )
    return TransactionReceipt(
        transaction_id=str(row[0]),
        user_id=command.user_id,
        request_id=command.request_id,
        business_type=str(row[1]),
        committed_at=str(row[3]),
        replayed=replayed,
        changes=changes,
    )


def _validate_command(command: TransactionCommand) -> None:
    for value, label in (
        (command.user_id, "user_id"),
        (command.request_id, "request_id"),
        (command.business_type, "business_type"),
    ):
        _validate_text(value, label)
    if not command.operations:
        raise ValueError("事务至少需要一项状态变更")
    addresses = set()
    for operation in command.operations:
        if hasattr(operation, "expected_version") and (
            isinstance(operation.expected_version, bool)
            or operation.expected_version < 0
        ):
            raise ValueError("expected_version 不能小于 0")
        if isinstance(operation, StateMutation):
            _validate_text(operation.user_id, "operation.user_id")
            _validate_text(operation.state_type, "state_type")
            _validate_text(operation.state_key, "state_key")
            address = (operation.user_id, operation.state_type, operation.state_key)
        elif isinstance(operation, LocationMutation):
            _validate_text(operation.user_id, "operation.user_id")
            _validate_space(operation.space_type, operation.space_id)
            address = (operation.user_id, "location", "main")
        elif isinstance(operation, SharedEntityMutation):
            _validate_text(operation.entity_type, "entity_type")
            _validate_text(operation.entity_id, "entity_id")
            address = ("shared_entity", operation.entity_type, operation.entity_id)
        elif isinstance(operation, SharedMemberMutation):
            _validate_text(operation.entity_type, "entity_type")
            _validate_text(operation.user_id, "operation.user_id")
            address = ("shared_member", operation.entity_type, operation.user_id)
            if operation.entity_id is not None:
                _validate_text(operation.entity_id, "entity_id")
        else:
            _validate_text(operation.entity_type, "entity_type")
            _validate_text(operation.entity_id, "entity_id")
            address = ("shared_location", operation.entity_type, operation.entity_id)
        if address in addresses:
            raise ValueError("同一事务不能重复修改同一状态")
        addresses.add(address)
        if isinstance(operation, StateMutation) and operation.value is not None:
            if not isinstance(operation.value, Mapping):
                raise TypeError("状态 JSON 根值必须是对象")
            _encode(operation.value)
        if isinstance(operation, LocationMutation) and operation.xy is not None:
            _validate_xy(operation.xy)
        if isinstance(operation, SharedEntityMutation) and operation.value is not None:
            if not isinstance(operation.value, Mapping):
                raise TypeError("共享实体 JSON 根值必须是对象")
            _encode(operation.value)
        if isinstance(operation, SharedLocationMutation) and operation.xy is not None:
            _validate_xy(operation.xy)
    if not isinstance(command.payload, Mapping):
        raise TypeError("事务 payload 根值必须是对象")
    _encode(command.payload)


def _validate_address(address: StateAddress) -> None:
    _validate_text(address.user_id, "user_id")
    _validate_text(address.state_type, "state_type")
    _validate_text(address.state_key, "state_key")


def _validate_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} 必须是无首尾空白的非空字符串")


def _validate_space(space_type: object, space_id: object) -> None:
    normalized_type = str(space_type or "").strip()
    normalized_id = str(space_id or "").strip()
    if not normalized_type:
        raise ValueError("space_type 必须是非空字符串")
    if normalized_type == "地表" and normalized_id:
        raise ValueError("地表空间不能包含 space_id")
    if normalized_type != "地表" and not normalized_id:
        raise ValueError("非地表空间必须包含 space_id")


def _command_json(
    command: TransactionCommand,
    storages: dict[tuple[str, str], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """事务指纹。`storages` 非空时顺带交出每个共享实体**规范化后的正文**。

    交给调用方是为了**同一份正文只规范化一次**：指纹里要它，真正落库时也要它，
    而规范化一趟要走完整棵树（实测 15 对 15 的战报 58 万字符），走两趟纯属白做。
    """

    return {
        "business_type": command.business_type,
        "operations": [
            _operation_json(operation, storages) for operation in command.operations
        ],
        "payload": _json_value(command.payload),
    }


def _change_json(change: MutationChange) -> dict[str, object]:
    return {
        "scope": change.scope,
        "user_id": change.user_id,
        "state_type": change.state_type,
        "state_key": change.state_key,
        "operation": change.operation,
        "before_version": change.before_version,
        "after_version": change.after_version,
    }


def _operation_json(
    operation: StateMutation
    | LocationMutation
    | SharedEntityMutation
    | SharedMemberMutation
    | SharedLocationMutation,
    storages: dict[tuple[str, str], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    if isinstance(operation, StateMutation):
        return {
            "kind": "state",
            "user_id": operation.user_id,
            "state_type": operation.state_type,
            "state_key": operation.state_key,
            "value": _json_value(operation.value),
            "expected_version": operation.expected_version,
        }
    if isinstance(operation, LocationMutation):
        return {
            "kind": "location",
            "user_id": operation.user_id,
            "xy": list(operation.xy) if operation.xy is not None else None,
            "expected_version": operation.expected_version,
            "space_type": operation.space_type,
            "space_id": operation.space_id,
        }
    if isinstance(operation, SharedEntityMutation):
        storage = (
            None
            if operation.value is None
            else _shared_entity_storage(
                operation.entity_type, operation.entity_id, operation.value
            )
        )
        if storage is not None and storages is not None:
            # 同一事务不许重复改同一状态（`_validate_command` 已查死），所以地址做键唯一。
            storages[(operation.entity_type, operation.entity_id)] = storage
        return {
            "kind": "shared_entity",
            "entity_type": operation.entity_type,
            "entity_id": operation.entity_id,
            "entity_name": (
                None
                if operation.value is None
                else str(operation.value.get("名称") or "").strip()
            ),
            "value": storage,
            "expected_version": operation.expected_version,
        }
    if isinstance(operation, SharedMemberMutation):
        return {
            "kind": "shared_member",
            "entity_type": operation.entity_type,
            "user_id": operation.user_id,
            "entity_id": operation.entity_id,
            "role": operation.role,
            "join_order": operation.join_order,
            "expected_version": operation.expected_version,
        }
    return {
        "kind": "shared_location",
        "entity_type": operation.entity_type,
        "entity_id": operation.entity_id,
        "xy": list(operation.xy) if operation.xy is not None else None,
        "expected_version": operation.expected_version,
    }


def _validate_xy(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError("xy 必须是两个整数")
    return int(value[0]), int(value[1])


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, raw in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("JSON 对象键必须是非空字符串")
            if key in result:
                raise ValueError(f"JSON 对象存在重复键：{key}")
            result[key] = _json_value(raw)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_json(raw) for key, raw in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _encode(value: object) -> str:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except TypeError as exc:
        raise ValueError("状态数据必须是可序列化 JSON") from exc


def _encode_ready(value: object) -> str:
    """`_encode` 的「值**已经过** `_json_value`」版本：不再走一遍转换。

    只给「刚刚由 `_json_value` 造出来的对象」用。`_json_value` 是幂等的，所以省掉的
    那一遍只影响耗时，不影响落盘字符串或报错——键非字符串、键重复这些判据在造这份对象时
    已经查过，`json.dumps` 的 `TypeError` 分支照旧。
    """

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except TypeError as exc:
        raise ValueError("状态数据必须是可序列化 JSON") from exc


def _shared_entity_storage(
    entity_type: str, entity_id: str, value: Mapping[str, object]
) -> dict[str, object]:
    """共享实体只保存可变正文；身份字段由实体列唯一承载。"""

    identity_fields = {"名称"}
    identity_field = _SHARED_ENTITY_ID_FIELDS.get(entity_type)
    if identity_field is not None:
        declared_id = str(value.get(identity_field) or "").strip()
        if declared_id and declared_id != entity_id:
            raise ValueError(f"共享实体{identity_field}必须与实体地址一致")
        identity_fields.add(identity_field)
    return _json_value(
        {
            key: raw
            for key, raw in value.items()
            if key not in identity_fields
        }
    )


def _shared_entity_view(
    value: Mapping[str, object],
    entity_type: str,
    entity_id: str,
    entity_name: str,
) -> dict[str, object]:
    """读取时补回公共契约需要的身份字段，但不重复落盘。"""

    result = dict(value)
    result["名称"] = entity_name
    identity_field = _SHARED_ENTITY_ID_FIELDS.get(entity_type)
    if identity_field is not None:
        result[identity_field] = entity_id
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _chunks[T](values: tuple[T, ...], size: int) -> Iterator[tuple[T, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


__all__ = ["SQLiteStateStore"]
