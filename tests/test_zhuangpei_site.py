"""装配台命令层与网页接口的失败路径：格式提示、干净错误、匿名只读。"""
import asyncio
import importlib
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI

from game.features.zhuangpei import ZhuangpeiFeatureError, encode
from tests.test_zhuangpei import HttpClient, acquire, blank, item, player, services  # noqa: F401


def _app(services, monkeypatch):
    site = importlib.import_module("game.cmd.通用.装配台.site")
    monkeypatch.setattr(site, "current_game_services", lambda: services)
    app = FastAPI()
    app.include_router(site.router)
    return app


def test_scope_for_unknown_user_is_clean_error(services, monkeypatch):
    """查一个不存在或没公开的用户名 ⇒ 400 + 人话，而不是 500 堆栈。"""
    with HttpClient(_app(services, monkeypatch)) as client:
        response = client.get("/assembly/data?scope=user:no-such-user")
        assert response.status_code == 400
        assert "公开" in response.json()["error"]


def test_content_endpoint_contract(services, monkeypatch):
    with HttpClient(_app(services, monkeypatch)) as client:
        good = client.get(f"/assembly/content?section={quote('功法')}&content_id=400001")
        assert good.status_code == 200
        assert good.json()["name"] and isinstance(good.json()["lines"], list)
        bad_section = client.get(f"/assembly/content?section={quote('不存在的类')}&content_id=400001")
        assert bad_section.status_code == 400
        assert "功法" in bad_section.json()["error"]
        assert client.get(f"/assembly/content?section={quote('功法')}&content_id=999999").status_code == 400
        assert client.get(f"/assembly/content?section={quote('功法')}").status_code == 422


def test_scheme_endpoint_payload_edges(services, monkeypatch):
    with HttpClient(_app(services, monkeypatch)) as client:
        for payload in ({"build": None}, {"code": ""}, {"code": 12}, {}, {"build": blank(), "code": "x"}):
            assert client.post("/assembly/scheme", json=payload).status_code == 400, payload


def test_import_command_format_hint_does_not_write(services, monkeypatch):
    """空参、多参只给格式提示，不产生任何事务。"""
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent: list = []

    async def send(value):
        sent.append(value)

    manager = SimpleNamespace(send=send)

    async def run():
        uid = await player(services)
        before = services.core.database.status().transaction_count
        for index, message in enumerate(("", "   ", "ZP1.abc extra")):
            await module.import_assembly(
                user_id=uid, message=message,
                message_context=SimpleNamespace(request_id=f"format-{index}"), manager=manager,
            )
            assert "格式：导入装配 装配码" in str(sent[-1])
        assert services.core.database.status().transaction_count == before

    asyncio.run(run())


def test_public_toggle_command_cards(services, monkeypatch):
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent: list = []

    async def send(value):
        sent.append(value)

    manager = SimpleNamespace(send=send)

    async def run():
        uid = await player(services)
        await module.toggle_public(user_id=uid, message_context=SimpleNamespace(request_id="pub-1"), manager=manager)
        assert "已公开" in str(sent[-1])
        await module.toggle_public(user_id=uid, message_context=SimpleNamespace(request_id="pub-2"), manager=manager)
        assert "已关闭" in str(sent[-1])

    asyncio.run(run())


@pytest.mark.parametrize("text", ["ZP1.abc", "　", "ZP1.abc extra"])
def test_import_command_error_card_names_the_code(services, monkeypatch, text):
    """非法码一律落错误卡片，且提示里要认得出是"装配码"问题。"""
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent: list = []

    async def send(value):
        sent.append(value)

    async def run():
        uid = await player(services)
        await module.import_assembly(
            user_id=uid, message=text,
            message_context=SimpleNamespace(request_id=f"parse-{abs(hash(text))}"),
            manager=SimpleNamespace(send=send),
        )
        assert "装配码" in str(sent[-1])

    asyncio.run(run())


def test_public_scope_lists_that_users_holdings(services, monkeypatch):
    """公开后按用户名能选到对方的池；关闭后立刻从列表与范围内消失。"""

    async def run():
        uid = await player(services)
        await acquire(services, uid, "功法", "400001")
        await services.features.zhuangpei.toggle_public(uid, "scope-open")
        with HttpClient(_app(services, monkeypatch)) as client:
            data = client.get(f"/assembly/data?scope=user:{uid}").json()
            assert data["scope"] == f"user:{uid}"
            entry = next(e for e in data["entries"] if e["section"] == "功法" and e["id"] == "400001")
            assert entry["quantity"] == 1 and entry["equipped"] == []
            assert f"user:{uid}" in {value["id"] for value in client.get("/assembly/data").json()["scopes"]}
            await services.features.zhuangpei.toggle_public(uid, "scope-close")
            closed = client.get(f"/assembly/data?scope=user:{uid}")
            assert closed.status_code == 400 and "公开" in closed.json()["error"]
            assert f"user:{uid}" not in {value["id"] for value in client.get("/assembly/data").json()["scopes"]}

    asyncio.run(run())


def test_public_scope_keeps_equipped_entry_without_stock(services, monkeypatch):
    """真意按规则会被消耗：装进槽位后库存归零，但条目仍要留在本人清单里。"""

    async def run():
        uid = await player(services)
        content_id = next(iter(services.core.data.entities("真意")))
        await acquire(services, uid, "真意", content_id)
        code = encode({**blank(), "真意": [item(content_id)]})
        await services.features.zhuangpei.import_code(uid, "stock-import", code)
        await services.features.zhuangpei.toggle_public(uid, "stock-open")
        with HttpClient(_app(services, monkeypatch)) as client:
            entries = client.get(f"/assembly/data?scope=user:{uid}").json()["entries"]
            entry = next(e for e in entries if e["section"] == "真意" and e["id"] == content_id)
            assert entry["quantity"] == 0
            assert entry["equipped"] == [1]

    asyncio.run(run())


def test_same_request_id_with_other_code_is_refused(services):
    """同请求编号复用到不同码 ⇒ 明确拒绝，而不是当成重放。"""

    async def run():
        uid = await player(services)
        ids = tuple(services.core.data.entities("功法"))[:2]
        for content_id in ids:
            await acquire(services, uid, "功法", content_id)
        feature = services.features.zhuangpei
        await feature.import_code(uid, "same-request", encode({**blank(), "功法": [item(ids[0])]}))
        with pytest.raises(ZhuangpeiFeatureError, match="同一请求编号"):
            await feature.import_code(uid, "same-request", encode({**blank(), "功法": [item(ids[1])]}))
        # 同一个码重放 ⇒ 幂等回执，不报错
        replay = await feature.import_code(uid, "same-request", encode({**blank(), "功法": [item(ids[0])]}))
        assert replay.replayed is True

    asyncio.run(run())


def test_scheme_rejects_duplicate_and_over_limit(services):
    """整套校验的两条硬边界：超过人物槽位上限、同类里重复装同一内容。"""
    feature = services.features.zhuangpei
    ids = tuple(services.core.data.entities("功法"))
    limits = services.core.character.assembly_limits()
    with pytest.raises(ZhuangpeiFeatureError, match="槽位上限"):
        feature.scheme({**blank(), "功法": [item(ids[0])] * (limits["功法"] + 1)})
    assert limits["功法"] >= 2
    with pytest.raises(ZhuangpeiFeatureError, match="不能重复装配"):
        feature.scheme({**blank(), "功法": [item(ids[0]), item(ids[0])]})
