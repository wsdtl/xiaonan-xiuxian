"""根链生命周期；调度规则不包含具体功法名称。"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from typing import Any

from .models import BattleContext


def response_level(node: Mapping[str, Any]) -> int:
    value = node.get("响应等级", "随时点")
    if value == "随时点":
        event = str(node.get("事件", ""))
        return 3 if event.endswith("前") else 2
    return {"应式": 2, "裁断": 3}[value]


class ChainRuntime:
    @contextmanager
    def root_chain(self, context: BattleContext) -> Iterator[None]:
        if context.chain_active:
            yield
            return
        context.chain_serial += 1
        context.chain_active = True
        context.chain_level = 1
        context.chain_counts.clear()
        context.chain_exhausted.clear()
        context.chain_source_counts.clear()
        context.chain_pending.clear()
        context.chain_queued.clear()
        try:
            yield
            index = 0
            while index < len(context.chain_pending):
                entry, kind, source_id, target_id, amount, facts, tags = context.chain_pending[index]
                index += 1
                # 队列不延长已退场载体的生命；重建后用稳定预算键寻找当前声明。
                owner = context.fighter_by_id(entry[1].id)
                if owner is None or not owner.alive:
                    continue
                current = next((item for item in self._compiled_listeners(context).get(kind, ())
                                if item[13] == entry[13] and item[6] == entry[6]), None)
                source = context.fighter_by_id(source_id)
                target = context.fighter_by_id(target_id)
                if current is None or source is None or target is None:
                    continue
                self._dispatch_event_body(context, kind=kind, source=source, target=target,
                                          amount=amount, values=facts, tags=tags, record=False,
                                          capture=False, chain_entry=current)
        finally:
            context.chain_active = False
            context.chain_level = 1
            context.chain_pending.clear()
            context.chain_queued.clear()
