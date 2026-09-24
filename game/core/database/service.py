"""异步核心数据库微服务门面。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .contracts import (
    CommittedTransaction,
    DatabaseStatus,
    LocationRecord,
    NearbyLocationRecord,
    SharedEntityRecord,
    SharedLocationRecord,
    SharedMemberRecord,
    StateAddress,
    StateSnapshot,
    TransactionCommand,
    TransactionReceipt,
)
from .storage import SQLiteStateStore


class DatabaseService:
    """为所有玩法提供异步状态读取和原子事务提交。"""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self._store = SQLiteStateStore(path, busy_timeout_ms=busy_timeout_ms)
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._store.path

    def initialize(self) -> DatabaseStatus:
        """启动时建表；服务运行期间不做结构迁移。"""

        if self._initialized:
            raise RuntimeError("核心数据库已经初始化")
        self._store.initialize()
        self._initialized = True
        return self.status()

    def status(self) -> DatabaseStatus:
        (
            state_count,
            location_count,
            transaction_count,
            shared_entity_count,
            shared_member_count,
            shared_location_count,
        ) = (
            self._store.counts() if self._initialized else (0, 0, 0, 0, 0, 0)
        )
        return DatabaseStatus(
            initialized=self._initialized,
            path=self.path,
            state_count=state_count,
            location_count=location_count,
            transaction_count=transaction_count,
            shared_entity_count=shared_entity_count,
            shared_member_count=shared_member_count,
            shared_location_count=shared_location_count,
        )

    async def get(self, address: StateAddress) -> StateSnapshot | None:
        self._require_initialized()
        return await asyncio.to_thread(self._store.get, address)

    async def list_for_user(
        self, user_id: str, *, state_type: str | None = None
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        return await asyncio.to_thread(self._store.list_for_user, user_id, state_type)

    async def get_many(
        self, addresses: tuple[StateAddress, ...]
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        return await asyncio.to_thread(self._store.get_many, addresses)

    async def get_location(self, user_id: str) -> LocationRecord | None:
        self._require_initialized()
        return await asyncio.to_thread(self._store.get_location, user_id)

    async def get_locations(
        self, user_ids: tuple[str, ...]
    ) -> tuple[LocationRecord, ...]:
        self._require_initialized()
        return await asyncio.to_thread(self._store.get_locations, user_ids)

    async def get_shared_entity(
        self, entity_type: str, entity_id: str
    ) -> SharedEntityRecord | None:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.get_shared_entity, entity_type, entity_id
        )

    async def get_shared_entity_by_name(
        self, entity_type: str, entity_name: str
    ) -> SharedEntityRecord | None:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.get_shared_entity_by_name, entity_type, entity_name
        )

    async def list_shared_entities(
        self, entity_type: str
    ) -> tuple[SharedEntityRecord, ...]:
        self._require_initialized()
        return await asyncio.to_thread(self._store.list_shared_entities, entity_type)

    async def get_shared_member(
        self, entity_type: str, user_id: str
    ) -> SharedMemberRecord | None:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.get_shared_member, entity_type, user_id
        )

    async def get_shared_members(
        self, entity_type: str, user_ids: tuple[str, ...]
    ) -> tuple[SharedMemberRecord, ...]:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.get_shared_members, entity_type, user_ids
        )

    async def list_shared_members(
        self, entity_type: str, entity_id: str
    ) -> tuple[SharedMemberRecord, ...]:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.list_shared_members, entity_type, entity_id
        )

    async def get_shared_location(
        self, entity_type: str, entity_id: str
    ) -> SharedLocationRecord | None:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.get_shared_location, entity_type, entity_id
        )

    async def shared_location_at(
        self, entity_type: str, xy: tuple[int, int]
    ) -> SharedLocationRecord | None:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.shared_location_at, entity_type, xy
        )

    async def nearby_locations(
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
        return await asyncio.to_thread(
            self._store.nearby_locations,
            origin_xy=origin_xy,
            space_type=space_type,
            space_id=space_id,
            radius_meters=radius_meters,
            cell_size_meters=cell_size_meters,
            limit=limit,
            exclude_user_id=exclude_user_id,
        )

    async def commit(self, command: TransactionCommand) -> TransactionReceipt:
        self._require_initialized()
        return await asyncio.to_thread(self._store.commit, command)

    async def committed_transaction(
        self, user_id: str, request_id: str
    ) -> CommittedTransaction | None:
        self._require_initialized()
        return await asyncio.to_thread(
            self._store.committed_transaction,
            user_id,
            request_id,
        )

    def close(self) -> None:
        self._initialized = False

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("核心数据库尚未初始化")


__all__ = ["DatabaseService"]
