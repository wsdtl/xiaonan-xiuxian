"""核心数据库微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DatabaseError(RuntimeError):
    """数据库服务无法完成请求。"""


class StateConflictError(DatabaseError):
    """状态版本与调用方预期不一致。"""


class IdempotencyConflictError(DatabaseError):
    """同一请求编号被重复用于不同事务。"""


class SharedConstraintError(DatabaseError):
    """共享实体、成员或位置违反唯一约束。"""


JsonObject = Mapping[str, Any]


@dataclass(frozen=True)
class DatabaseStatus:
    initialized: bool
    path: Path
    state_count: int
    location_count: int
    transaction_count: int
    shared_entity_count: int
    shared_member_count: int


@dataclass(frozen=True)
class StateAddress:
    user_id: str
    state_type: str
    state_key: str


@dataclass(frozen=True)
class StateSnapshot:
    address: StateAddress
    value: JsonObject
    version: int
    updated_at: str


@dataclass(frozen=True)
class StateMutation:
    user_id: str
    state_type: str
    state_key: str
    value: JsonObject | None
    expected_version: int


@dataclass(frozen=True)
class LocationMutation:
    user_id: str
    xy: tuple[int, int] | None
    expected_version: int
    space_type: str = "地表"
    space_id: str = ""


@dataclass(frozen=True)
class SharedEntityMutation:
    entity_type: str
    entity_id: str
    value: JsonObject | None
    expected_version: int


@dataclass(frozen=True)
class SharedMemberMutation:
    entity_type: str
    user_id: str
    entity_id: str | None
    role: str
    join_order: int
    expected_version: int


DatabaseMutation = (
    StateMutation
    | LocationMutation
    | SharedEntityMutation
    | SharedMemberMutation
)


@dataclass(frozen=True)
class MutationChange:
    scope: str
    user_id: str
    state_type: str
    state_key: str
    operation: str
    before_version: int | None
    after_version: int | None


@dataclass(frozen=True)
class TransactionCommand:
    user_id: str
    request_id: str
    business_type: str
    operations: tuple[DatabaseMutation, ...]
    payload: JsonObject


@dataclass(frozen=True)
class SettlementTransactionPlan:
    """把结算结果、奖励、状态释放和结算事实收进同一事务。"""

    result_operations: tuple[DatabaseMutation, ...]
    reward_operations: tuple[DatabaseMutation, ...]
    release_operations: tuple[DatabaseMutation, ...]
    record_operations: tuple[DatabaseMutation, ...]

    def command(
        self,
        *,
        user_id: str,
        request_id: str,
        business_type: str,
        payload: JsonObject,
    ) -> TransactionCommand:
        if not self.result_operations:
            raise ValueError("玩法结算必须包含角色或公共结果写入")
        if not self.release_operations:
            raise ValueError("玩法结算必须释放参与者行为状态")
        if not self.record_operations:
            raise ValueError("玩法结算必须保存不可变结算事实")
        return TransactionCommand(
            user_id=user_id,
            request_id=request_id,
            business_type=business_type,
            operations=(
                *self.result_operations,
                *self.reward_operations,
                *self.release_operations,
                *self.record_operations,
            ),
            payload=payload,
        )


@dataclass(frozen=True)
class TransactionReceipt:
    transaction_id: str
    user_id: str
    request_id: str
    business_type: str
    committed_at: str
    replayed: bool
    changes: tuple[MutationChange, ...]


@dataclass(frozen=True)
class CommittedTransaction:
    receipt: TransactionReceipt
    payload: JsonObject


@dataclass(frozen=True)
class LocationRecord:
    user_id: str
    xy: tuple[int, int]
    version: int
    updated_at: str
    space_type: str = "地表"
    space_id: str = ""


@dataclass(frozen=True)
class NearbyLocationRecord:
    user_id: str
    xy: tuple[int, int]
    horizontal_distance_squared_meters: int
    space_type: str = "地表"
    space_id: str = ""


@dataclass(frozen=True)
class SharedEntityRecord:
    entity_type: str
    entity_id: str
    value: JsonObject
    version: int
    updated_at: str


@dataclass(frozen=True)
class SharedMemberRecord:
    entity_type: str
    entity_id: str
    user_id: str
    role: str
    join_order: int
    version: int
    updated_at: str


__all__ = [
    "CommittedTransaction",
    "DatabaseError",
    "DatabaseMutation",
    "DatabaseStatus",
    "IdempotencyConflictError",
    "LocationMutation",
    "LocationRecord",
    "MutationChange",
    "NearbyLocationRecord",
    "SettlementTransactionPlan",
    "SharedConstraintError",
    "SharedEntityMutation",
    "SharedEntityRecord",
    "SharedMemberMutation",
    "SharedMemberRecord",
    "StateAddress",
    "StateConflictError",
    "StateMutation",
    "StateSnapshot",
    "TransactionCommand",
    "TransactionReceipt",
]
