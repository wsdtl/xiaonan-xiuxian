"""按当前领域读取存档，补上「键名/结构」查不到的语义漂移。

这不是兼容层：任何状态只要当前服务读不出来，就让闸门红，逼着先迁移。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path


def audit_saves(path: Path) -> tuple[int, list[str]]:
    from game.app import build_game_services

    errors: list[str] = []
    checks = 0
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    try:
        raw = {
            str(row[0]): json.loads(row[1])
            for row in connection.execute("SELECT user_id, state_json FROM player_state")
        }
    finally:
        connection.close()

    async def run() -> None:
        nonlocal checks

        services = build_game_services()
        try:
            for user_id, data in raw.items():
                async def attempt(label: str, call) -> None:
                    nonlocal checks
                    try:
                        await call()
                        checks += 1
                    except Exception as error:  # noqa: BLE001 - 审计要收全
                        errors.append(
                            f"{user_id} {label}: {type(error).__name__}: {error}"
                        )

                await attempt("player_state.current", lambda: services.core.player_state.current(user_id))
                await attempt("character.profile", lambda: services.core.character.profile(user_id))
                await attempt("asset.snapshot", lambda: services.core.asset.snapshot(user_id))
                await attempt("location.current", lambda: services.core.location.current(user_id))
                await attempt("team.membership", lambda: services.core.team.membership(user_id))
                await attempt("team.pending", lambda: services.core.team.pending_invitation(user_id))
                await attempt("sect.membership", lambda: services.core.sect.membership(user_id))
                await attempt("sect.follow", lambda: services.core.sect.follow_membership(user_id))
                await attempt("innate_treasure", lambda: services.core.innate_treasure.collection(user_id))
                await attempt("companion.active", lambda: services.core.companion.active(user_id))
                for key in data:
                    if key.startswith("companion_instance/"):
                        cid = key.split("/", 1)[1]
                        await attempt(
                            f"companion.instance {cid}",
                            lambda cid=cid: services.core.companion.instance(user_id, cid),
                        )
                    if key.startswith("companion_relation/"):
                        cid = key.split("/", 1)[1]
                        await attempt(
                            f"companion.relation {cid}",
                            lambda cid=cid: services.core.companion.relation(user_id, cid),
                        )
                    if key.startswith("injury/"):
                        subject = key.split("/", 1)[1]
                        await attempt(
                            f"injury {subject}",
                            lambda subject=subject: services.core.injury.state(user_id, subject),
                        )
                if "exploration_latest/main" in data:
                    await attempt(
                        "exploration.latest",
                        lambda: services.core.exploration.latest_settlement(user_id),
                    )
                # 历史结算也按当前展示/回放口径解析，避免“当前能看、历史一翻就炸”。
                for key, entry in data.items():
                    try:
                        if key.startswith("retreat_settlement/"):
                            services.core.retreat._settlement(
                                key.split("/", 1)[1], entry["value"], replayed=True
                            )
                        elif key.startswith("exploration_settlement/"):
                            services.core.exploration._settlement(
                                key.split("/", 1)[1], entry["value"], replayed=True
                            )
                        elif key.startswith("gathering_settlement/"):
                            services.core.gathering._settlement(
                                key.split("/", 1)[1], entry["value"], replayed=True
                            )
                        else:
                            continue
                        checks += 1
                    except Exception as error:  # noqa: BLE001 - 审计要收全
                        errors.append(
                            f"{user_id} {key}: {type(error).__name__}: {error}"
                        )

            for user_id, data in raw.items():
                behavior = (
                    (data.get("player_state/main", {}).get("value", {}).get("行为") or {})
                    .get("状态编号")
                )
                for prefix, id_field, active_state in (
                    ("exploration_latest/main", "探险编号", "520004"),
                    ("retreat_latest/main", "闭关编号", "520003"),
                ):
                    entry = data.get(prefix)
                    if not entry:
                        continue
                    sid = entry["value"].get(id_field)
                    session_prefix = prefix.split("_", 1)[0] + "_session/"
                    settlement_prefix = prefix.split("_", 1)[0] + "_settlement/"
                    if f"{session_prefix}{sid}" not in data:
                        errors.append(f"{user_id} {prefix} 指向不存在的会话 {sid}")
                    elif f"{settlement_prefix}{sid}" not in data and behavior != active_state:
                        errors.append(f"{user_id} {prefix} 指向未结算会话 {sid}")
                for key, entry in data.items():
                    if not key.startswith("gathering_latest/"):
                        continue
                    sid = entry["value"].get("采集编号")
                    if f"gathering_session/{sid}" not in data or f"gathering_settlement/{sid}" not in data:
                        mode = key.split("/", 1)[1]
                        active = "520010" if mode == "采药" else "520011"
                        if behavior != active:
                            errors.append(f"{user_id} {key} 指向不完整采集 {sid}")
        finally:
            services.core.database.close()

    asyncio.run(run())

    # 共享实体与成员不能是孤儿，宗门成员数要跟成员表一致。
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    try:
        connection.row_factory = sqlite3.Row
        entities = {
            (row["entity_type"], row["entity_id"])
            for row in connection.execute("SELECT entity_type, entity_id FROM shared_entity")
        }
        for row in connection.execute("SELECT entity_type, entity_id, user_id FROM shared_member"):
            if (row["entity_type"], row["entity_id"]) not in entities:
                errors.append(
                    f"shared_member 孤儿：{row['entity_type']}/{row['entity_id']} {row['user_id']}"
                )
        for row in connection.execute(
            "SELECT entity_id, value_json FROM shared_entity WHERE entity_type='宗门'"
        ):
            value = json.loads(row["value_json"])
            members = connection.execute(
                "SELECT count(*) FROM shared_member WHERE entity_type='宗门' AND entity_id=?",
                (row["entity_id"],),
            ).fetchone()[0]
            if int(value.get("成员数量", -1)) != members:
                errors.append(
                    f"宗门成员数不一致：{row['entity_id']} {value.get('成员数量')} != {members}"
                )
    finally:
        connection.close()

    return checks, errors
