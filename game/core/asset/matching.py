"""材料最省匹配：把「哪份材料进哪个槽位」解成一次最小费用最大流。

炼丹与炼器的这份实现原先逐字节相同，靠一句「两处必须同步修改」的注释维持。
收在这里之后，改一次就是两边一起改。身份类型只用到 identity.item_id，所以用 Any 收口。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .contracts import AssetEntry

if TYPE_CHECKING:
    from .service import AssetService


@dataclass
class Edge:
    target: int
    reverse: int
    capacity: int
    cost: int


@dataclass
class Choice:
    identity: Any
    entry: AssetEntry
    slot: int
    trait: str
    relation: str
    quantity: int


def minimum_cost_matching(
    item_ids: tuple[str, ...],
    slot_count: int,
    choices: Sequence[Choice],
    asset: "AssetService",
    *,
    secondary_cost: int = 1_000_000_000,
    grade_cost: int = 100_000,
    secondary_relation: str = "旁脉",
) -> dict[int, Choice]:
    """挑一组「每份材料各进一个槽位」的最小代价匹配。"""

    if not item_ids or not slot_count:
        return {}
    item_index = {item_id: index for index, item_id in enumerate(item_ids)}
    source = 0
    item_start = 1
    slot_start = item_start + len(item_ids)
    sink = slot_start + slot_count
    graph: list[list[Edge]] = [[] for _ in range(sink + 1)]

    def add_edge(origin: int, target: int, capacity: int, cost: int) -> Edge:
        forward = Edge(target, len(graph[target]), capacity, cost)
        backward = Edge(origin, len(graph[origin]), 0, -cost)
        graph[origin].append(forward)
        graph[target].append(backward)
        return forward

    for index in range(len(item_ids)):
        add_edge(source, item_start + index, 1, 0)
    for slot in range(slot_count):
        add_edge(slot_start + slot, sink, 1, 0)
    tracked: list[tuple[Choice, Edge]] = []
    for choice in sorted(
        choices,
        key=lambda value: (
            value.identity.item_id,
            value.slot,
            value.relation,
            value.entry.grade_id,
        ),
    ):
        grade_order = asset.grade(choice.entry.grade_id).order
        rank = item_index[choice.identity.item_id]
        cost = (
            (secondary_cost if choice.relation == secondary_relation else 0)
            + grade_order * grade_cost
            + rank
        )
        tracked.append(
            (
                choice,
                add_edge(
                    item_start + item_index[choice.identity.item_id],
                    slot_start + choice.slot,
                    1,
                    cost,
                ),
            )
        )
    while True:
        distances = [10**30] * len(graph)
        previous: list[tuple[int, int] | None] = [None] * len(graph)
        distances[source] = 0
        for _ in range(len(graph) - 1):
            changed = False
            for origin, edges in enumerate(graph):
                if distances[origin] == 10**30:
                    continue
                for edge_index, edge in enumerate(edges):
                    if edge.capacity and distances[origin] + edge.cost < distances[edge.target]:
                        distances[edge.target] = distances[origin] + edge.cost
                        previous[edge.target] = (origin, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            origin, edge_index = previous[node]  # type: ignore[misc]
            edge = graph[origin][edge_index]
            edge.capacity -= 1
            graph[node][edge.reverse].capacity += 1
            node = origin
    return {choice.slot: choice for choice, edge in tracked if edge.capacity == 0}


__all__ = ["Choice", "Edge", "minimum_cost_matching"]
